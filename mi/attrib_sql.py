"""Which Meta ad, ad set and campaign a visit came from.

The link a visitor arrives with carries the ad in `utm_content` and the ad set in `utm_term`. Some ads send Meta's own ids ({{ad.id}}), others carry a
hand-typed name ("New Sales Ad"). Only the ids used to be understood, so about half of the Paid Meta visits had no ad. This step reads both:

  id        the value is a Meta ad id (from the synced list, or from the spend report, which also knows archived / deleted ads)
  name      the value is the name of exactly one Meta ad
  probable  several ads share that name; the ad that fits the visit best is chosen (same ad set, same campaign, spent money on that day, spent most)
  (a value cut short by the tracker is matched by its start, only when nothing matches exactly, and counts as probable)
  unmatched nothing in Meta fits: the raw value is kept so the visit can still be listed

`ad_raw` / `adset_raw` always hold what the link said. Visits whose campaign tag did not match a campaign but whose ad did are added to `session_meta`,
so the campaign table, ROAS and the health checks see them too.
"""

def _key(x: str) -> str:
    """SQL that makes a name comparable: URL-decoded (+ and %7C), '|' written as the letter I the way people type it, spaces collapsed, lower case."""
    return f"lower(trim(regexp_replace(replace(coalesce(try(url_decode(replace(regexp_replace({x}, '%[0-9A-Fa-f]?$', ''), '+', ' '))), {x}), '|', 'I'), ' {2,}', ' ', 'g')))"


ATTRIB_SQL = """
-- every Meta ad we can name: the synced list plus any ad that spent money (archived and deleted ads are only in the spend report)
CREATE OR REPLACE TABLE meta_ad_dim AS
WITH i AS (SELECT ad_id, max(ad_name) AS name, max(adset_id) AS adset_id, max(campaign_id) AS campaign_id, sum(spend) AS spend FROM raw_meta_insights WHERE ad_id IS NOT NULL GROUP BY 1),
e AS (SELECT entity_id AS ad_id, any_value(name) AS name, any_value(adset_id) AS adset_id, any_value(campaign_id) AS campaign_id, any_value(effective_status) AS status
      FROM raw_meta_entities WHERE entity_type = 'ad' GROUP BY 1)
SELECT coalesce(e.ad_id, i.ad_id) AS ad_id, coalesce(e.name, i.name) AS name, coalesce(e.adset_id, i.adset_id) AS adset_id,
       coalesce(e.campaign_id, i.campaign_id) AS campaign_id, e.status AS status, coalesce(i.spend, 0) AS spend
FROM e FULL JOIN i ON e.ad_id = i.ad_id;

CREATE OR REPLACE TABLE meta_adset_dim AS
WITH i AS (SELECT adset_id, max(adset_name) AS name, max(campaign_id) AS campaign_id FROM raw_meta_insights WHERE adset_id IS NOT NULL GROUP BY 1),
e AS (SELECT entity_id AS adset_id, any_value(name) AS name, any_value(campaign_id) AS campaign_id FROM raw_meta_entities WHERE entity_type = 'adset' GROUP BY 1)
SELECT coalesce(e.adset_id, i.adset_id) AS adset_id, coalesce(e.name, i.name) AS name, coalesce(e.campaign_id, i.campaign_id) AS campaign_id
FROM e FULL JOIN i ON e.adset_id = i.adset_id;

CREATE OR REPLACE TABLE session_attrib AS
WITH r AS (
  SELECT b.session_id, s.date_ist AS d, b.v, b.t, s.campaign AS camp FROM (
    SELECT session_id, first(utm_content ORDER BY ts) FILTER (WHERE utm_content IS NOT NULL) AS v, first(utm_term ORDER BY ts) FILTER (WHERE utm_term IS NOT NULL) AS t
    FROM events_base GROUP BY 1 HAVING count(utm_content) > 0) b
  LEFT JOIN sessions s ON s.session_id = b.session_id),
an AS (SELECT {K_NAME} AS k, min(adset_id) AS adset_id FROM meta_adset_dim WHERE name IS NOT NULL GROUP BY 1 HAVING count(*) = 1),
r2 AS (
  SELECT r.*, coalesce(ai.adset_id, an.adset_id) AS t_adset,
         coalesce((SELECT campaign_id FROM meta_ids WHERE key = r.camp), (SELECT campaign_id FROM meta_ids WHERE key = lower(trim(r.camp)))) AS camp_id
  FROM r LEFT JOIN meta_adset_dim ai ON ai.adset_id = r.t LEFT JOIN an ON an.k = {K_T}),
cn AS (SELECT {K_CN} AS k, min(campaign_id) AS campaign_id FROM (
         SELECT campaign_id, campaign_name AS name FROM raw_meta_insights WHERE campaign_name IS NOT NULL
         UNION ALL SELECT entity_id, name FROM raw_meta_entities WHERE entity_type = 'campaign' AND name IS NOT NULL) GROUP BY 1 HAVING count(DISTINCT campaign_id) = 1),
ds AS (SELECT ad_id, date, sum(spend) AS spend FROM raw_meta_insights GROUP BY 1, 2),
hit AS (
  SELECT r2.session_id, r2.v, r2.t_adset, r2.camp_id, r2.d, a.ad_id, a.adset_id, a.campaign_id, a.spend AS total_spend, (a.ad_id = r2.v) AS by_id, false AS by_prefix
  FROM r2 JOIN meta_ad_dim a ON a.ad_id = r2.v OR {K_A} = {K_V}),
-- a value the tracker cut short (an id missing its last digit, a name cut off): only when nothing matched exactly, and never better than "probable"
hit_prefix AS (
  SELECT r2.session_id, r2.v, r2.t_adset, r2.camp_id, r2.d, a.ad_id, a.adset_id, a.campaign_id, a.spend AS total_spend, false AS by_id, true AS by_prefix
  FROM r2 JOIN meta_ad_dim a ON length(r2.v) >= 12 AND (starts_with(a.ad_id, r2.v) OR starts_with({K_A}, {K_V}))
  WHERE r2.session_id NOT IN (SELECT session_id FROM hit)),
cand AS (
  SELECT h.*, count(*) OVER w AS n_cand, (min(h.campaign_id) OVER w = max(h.campaign_id) OVER w) AS one_campaign,
         row_number() OVER (PARTITION BY h.session_id ORDER BY h.by_id DESC, (h.adset_id = h.t_adset) DESC NULLS LAST,
                            (h.campaign_id = h.camp_id) DESC NULLS LAST, coalesce(ds.spend, 0) DESC, h.total_spend DESC, h.ad_id) AS rn
  FROM (SELECT * FROM hit UNION ALL SELECT * FROM hit_prefix) h
  LEFT JOIN ds ON ds.ad_id = h.ad_id AND ds.date = h.d
  WINDOW w AS (PARTITION BY h.session_id)),
best AS (SELECT * FROM cand WHERE rn = 1)
SELECT r2.session_id,
  coalesce(best.ad_id, r2.v) AS ad_id,
  coalesce(best.adset_id, r2.t_adset, r2.t) AS adset_id,
  -- only when the ad is certain, or every ad that could be meant sits in the same campaign
  CASE WHEN best.ad_id IS NOT NULL THEN
         CASE WHEN best.by_id OR (best.n_cand = 1 AND NOT best.by_prefix) OR best.one_campaign THEN coalesce(best.campaign_id, ad2.campaign_id) END
       ELSE coalesce(cn.campaign_id, ad2.campaign_id) END AS campaign_id,
  CASE WHEN best.ad_id IS NULL THEN 'unmatched' WHEN best.by_id THEN 'id' WHEN best.n_cand = 1 AND NOT best.by_prefix THEN 'name' ELSE 'probable' END AS ad_match,
  r2.v AS ad_raw, r2.t AS adset_raw
FROM r2 LEFT JOIN best USING (session_id)
LEFT JOIN meta_adset_dim ad2 ON ad2.adset_id = coalesce(best.adset_id, r2.t_adset)
LEFT JOIN cn ON cn.k = {K_V};

-- Meta visits whose campaign tag matched nothing, but whose ad did
INSERT INTO session_meta
SELECT sa.session_id, sa.campaign_id FROM session_attrib sa JOIN sessions s ON s.session_id = sa.session_id
WHERE sa.campaign_id IS NOT NULL AND s.source IN ('facebook', 'instagram') AND sa.session_id NOT IN (SELECT session_id FROM session_meta);
"""

ATTRIB_SQL = ATTRIB_SQL.replace("{K_NAME}", _key("name")).replace("{K_T}", _key("r.t")).replace("{K_A}", _key("a.name")).replace("{K_V}", _key("r2.v")).replace("{K_CN}", _key("name"))
