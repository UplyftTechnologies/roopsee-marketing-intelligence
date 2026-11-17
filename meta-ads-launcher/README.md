# Roopsee Meta Ads Launcher

A command-line tool that turns **local images + JSON files** into Meta (Facebook / Instagram) ads through the Marketing API.

- You design the images and write the copy. Python validates, uploads and creates everything on Meta.
- **Everything is created PAUSED.** Only `publish` activates anything, and only after you type `PUBLISH`.
- The default environment is the **sandbox** (no delivery, no spend). Production is locked behind an explicit flag.
- Spend and orders per creative show up in the marketing dashboard (see [Tracking](#tracking-and-the-dashboard)).

> Status: tested against a real Meta **sandbox** account. Image upload, campaign and ad set creation work; creative creation is blocked by a Page permission on the sandbox token. Full report: [SANDBOX_TEST.md](SANDBOX_TEST.md). See also [Known limits](#12-known-limits-and-unverified-points).

The original design is kept in [plan.md](plan.md). This README describes what is actually built, which differs from the plan in a few places (listed at the end).

---

## 1. The flow

```
 YOU (manual)                              LAUNCHER (python run.py ...)            META
 ────────────                              ────────────────────────────            ────
 1. Design image  -> creatives/<angle>/
 2. Write ads/batch_00X.json
    (copy, CTA, URL, ad set)
                                           3. validate    local checks only
                                           4. upload      ───────────────────►    image hash
                                           5. setup       ───────────────────►    campaign + ad set   (PAUSED)
                                           6. prepare     ───────────────────►    creative + ad       (PAUSED)
 7. Review previews, copy, URL,
    audience, budget, tracking
 8. Approve
                                           9. publish     ───────────────────►    campaign + ad set + ad -> ACTIVE
                                                                                  (Meta reviews, then delivers)
                                           10. performance: read in the dashboard's Meta Ads page
```

Each command can be re-run safely. Finished work is skipped, and objects that already exist on Meta under the same name are adopted instead of duplicated.

---

## 2. Folder layout

```
meta-ads-launcher/
├── run.py                  the one command you use
├── requirements.txt        requests, fastapi, uvicorn, python-multipart
├── SANDBOX_TEST.md         what was tested in the sandbox, and the result
├── .env.example            copy to .env and fill in (never commit .env)
├── plan.md                 the original plan this was built from
├── config/
│   ├── account.json        currency + UTM template
│   ├── audiences.json      named audiences (country, age, gender)
│   ├── campaigns.json      campaigns: objective, budget
│   └── adsets.json         ad sets: audience, placements, optimisation
├── creatives/              your images, one folder per angle
│   ├── acne/  pigmentation/  trust/  retargeting/
│   └── test/RS_TEST_001.png    generated test image for the sandbox
├── ads/
│   └── batch_001.json      the ads: image, copy, CTA, URL, status
├── data/
│   ├── sandbox/            Meta IDs and image hashes for the sandbox
│   └── production/         the same, kept separate for production
├── logs/launcher.log       every run, with secrets redacted
├── reports/                reserved for exports
├── ui/                     the web UI (server.py + static/ HTML, CSS, JS; no build step)
└── src/                    the implementation (see section 9)
```

`data/<env>/*.json` is created automatically and is git-ignored. It is the link between your local files and Meta's IDs. Do not delete it while ads exist on Meta, or the launcher forgets what it created (it will then fall back to finding objects by name).

---

## 3. One-time setup

**Requirements:** Python 3.10 or newer.

```
cd meta-ads-launcher
pip install -r requirements.txt          # macOS/Linux: pip3 / python3
copy .env.example .env                   # macOS/Linux: cp .env.example .env
```

Fill in the **SANDBOX** block of `.env`:

| Variable | What it is |
|---|---|
| `META_ENV` | `sandbox` (default) or `production`. Selects which block below is used |
| `META_API_VERSION` | `v25.0` |
| `META_SANDBOX_ACCESS_TOKEN` | Token with `ads_management` and `ads_read`; for creatives also the Page permissions (`pages_read_engagement`, `pages_show_list`) |
| `META_SANDBOX_APP_ID` / `_APP_SECRET` | Your Meta app. The secret is used to sign every call (`appsecret_proof`); the app id enables the token-expiry check in `doctor` |
| `META_SANDBOX_AD_ACCOUNT_ID` | The sandbox ad account, `act_...` (the `act_` prefix is added if you leave it out) |
| `META_SANDBOX_PAGE_ID` | The Facebook Page that ads are published from. Required for creatives |
| `META_SANDBOX_INSTAGRAM_ID` | Optional Instagram account id for Instagram placements |
| `META_SANDBOX_PIXEL_ID` | Optional. Only needed for conversion-optimised ad sets (Sales) |

**One token for both?** That is fine. Put it once in the shared block (`META_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET`, `META_PAGE_ID`, `META_INSTAGRAM_ID`) and leave the per-environment versions empty; they are used when a per-environment value is missing. The **ad account id and pixel id are never shared**, so the sandbox cannot touch the real account through the fallback. The environment is chosen only by `META_ENV` and its ad account.

The `META_PRODUCTION_*` block mirrors it. Leave it empty until you are ready for real money. Real environment variables starting with `META_` override the file.

Never paste tokens into chat, tickets or commits. If one was exposed, rotate it.

**Check everything (read-only, changes nothing):**
```
python run.py doctor
```
It verifies: credentials present, token accepted, token valid and its expiry, `ads_management` + `ads_read` scopes, ad account reachable (name, currency, timezone), currency matches `config/account.json`, Page reachable, and that config + a batch exist. Fix every `FAIL` line before going on.

---

## 4. How content is configured and selected

Four small files describe an ad. Each ad refers to the next level **by key**.

```
ad (ads/batch_001.json)  ->  adset_key  ->  ad set (adsets.json)  ->  campaign_key  ->  campaign (campaigns.json)
                                                      └── audience ->  audience (audiences.json)
```

### `config/campaigns.json`
| Field | Meaning |
|---|---|
| `key` | Unique name. It becomes the campaign name on Meta |
| `objective` | `OUTCOME_TRAFFIC`, `OUTCOME_SALES`, `OUTCOME_LEADS`, `OUTCOME_AWARENESS`, `OUTCOME_ENGAGEMENT` |
| `budget_strategy` | `CBO` (budget on the campaign) or `ABO` (budget on each ad set) |
| `daily_budget` | In rupees, required for CBO. `500` is sent to Meta as `50000` (minor units, `currency_offset` in `account.json`) |
| `status` | Must be `PAUSED` |
| `bid_strategy`, `special_ad_categories` | Optional. Defaults: `LOWEST_COST_WITHOUT_CAP`, `[]` |

### `config/audiences.json`
Named presets. `countries` (required, e.g. `["IN"]`), `age_min`, `age_max`, `genders` (`1` men, `2` women, empty = all). Advantage+ audience expansion is turned off so Meta stays inside what you set.

### `config/adsets.json`
| Field | Meaning |
|---|---|
| `key`, `campaign_key`, `audience` | Name, parent campaign, audience preset |
| `placements` | Any of `instagram`, `facebook`, `automatic` (automatic = let Meta choose) |
| `optimization_goal` | `LINK_CLICKS` (default), `LANDING_PAGE_VIEWS`, `OFFSITE_CONVERSIONS`, `REACH`, `IMPRESSIONS` |
| `optimization_event` | e.g. `PURCHASE`. Implies `OFFSITE_CONVERSIONS` and **needs a pixel** (`..._PIXEL_ID`) |
| `daily_budget` | Required when the campaign is ABO |
| `start_time`, `end_time`, `bid_strategy` | Optional |

### `ads/batch_001.json` (one entry per ad)
| Field | Meaning |
|---|---|
| `ad_key` | Unique, never reused, format `RS_<ANGLE>_<NNN>`, e.g. `RS_ACNE_001`. Becomes the ad and creative name |
| `adset_key` | Which ad set it belongs to |
| `image` | Path under `creatives/`. The file name must equal `ad_key` (JPG or PNG) |
| `primary_text` | The post text (about 125 characters show before "See more") |
| `headline` | Short headline (about 40 characters) |
| `description` | Optional |
| `cta` | `LEARN_MORE`, `SHOP_NOW`, `SIGN_UP`, `GET_OFFER`, `ORDER_NOW`, `CONTACT_US`, `SUBSCRIBE` |
| `destination` | Full `https://` URL. Do not put UTM tags in it; the launcher adds them |
| `status` | `DRAFT` = checked but never sent. `READY` = included when you run upload / setup / prepare / publish |

**Selecting what to launch:** a batch is "the ads for this round". Set only the ads you want out to `READY`. Everything else stays `DRAFT`.

### `config/account.json`
`currency` (checked against the real account by `doctor`), `currency_offset` (100 for INR), and `url_tags` (the UTM template, section 8).

---

## 5. Commands

```
python run.py doctor                              # read-only health check
python run.py validate [--batch batch_001]        # local checks, no network
python run.py upload   --batch batch_001          # images -> image hashes
python run.py setup    --batch batch_001          # campaigns + ad sets (PAUSED)
python run.py prepare  --batch batch_001          # creatives + ads (PAUSED)
python run.py status   [--live]                   # what exists; --live asks Meta for current state
python run.py publish  --batch batch_001          # ACTIVATE (asks you to type PUBLISH)
```

| Flag | Effect |
|---|---|
| `--dry-run` | Prints the exact payloads that would be sent. Sends nothing, saves nothing |
| `--validate-only` | Sends the request to Meta with `validate_only`, so Meta checks it and creates nothing |
| `--confirm-production` | Required for any write when `META_ENV=production` |
| `--yes` | Skips the sandbox publish prompt. Never skips the production prompt |

Every write command runs `validate` first and stops if there are errors.

### What each step sends
| Step | Meta call | Created as |
|---|---|---|
| `upload` | `POST act_X/adimages` | image hash, stored in `upload_registry.json` (identical files are uploaded once) |
| `setup` | `POST act_X/campaigns`, `act_X/adsets` | PAUSED. Targeting is built from the audience preset |
| `prepare` | `POST act_X/adcreatives`, `act_X/ads` | creative (Page, image hash, copy, CTA, URL, UTM tags), then the ad, PAUSED |
| `publish` | `POST <id>` `status=ACTIVE` for campaign, ad set and ad | An ad only runs when all three are active |

---

## 5b. Web UI (optional)

```
python run.py ui            # opens http://127.0.0.1:8765  (change with META_UI_PORT)
python run.py ui --no-browser
```
The UI wraps the same code as the CLI (`src/pipeline.py`), so both always behave identically.

| Tab | What it does |
|---|---|
| **Health** | Runs `doctor` as a checklist; shows what exists on Meta and the missing `.env` settings |
| **Library** | Drag-and-drop images into `creatives/<category>/<KEY>`; suggests the next key; shows size warnings and whether each image is on Meta; lists hashes already in the ad account |
| **Ads** | Pick a batch, add or edit ads in a form (image from the library or an image hash, character counters, CTA list) with a live feed-style preview; validates on every save; frozen batches are read-only |
| **Setup** | Forms for campaigns, ad sets, audiences and the UTM template (they edit `config/*.json`) |
| **Run** | Upload, Setup, Prepare with Dry run / Check with Meta / Run for real, live log, then review-and-publish with the typed `PUBLISH` confirmation |

UI safety: it listens on 127.0.0.1 only and rejects other host names; writes need a custom header a web page on another site cannot send; the token and secret never reach the browser; only one command runs at a time; the environment (sandbox or production) comes only from `.env`, never from the page; production shows a red banner and needs an extra tick box before any write, and publish still needs the typed word.

## 6. Running your first ad (sandbox walkthrough)

1. `python run.py doctor` -> all `OK`.
2. Put your image at `creatives/<angle>/RS_<ANGLE>_001.jpg` (1080px wide or more; 1:1 or 4:5). For a first test use the generated `creatives/test/RS_TEST_001.png`.
3. Edit the ad in `ads/batch_001.json` and set `"status": "READY"`.
4. `python run.py validate` -> `0 error(s)`.
5. Preview each step, then check it with Meta, then run it for real:
   ```
   python run.py upload  --batch batch_001 --dry-run
   python run.py upload  --batch batch_001
   python run.py setup   --batch batch_001 --validate-only
   python run.py setup   --batch batch_001
   python run.py prepare --batch batch_001 --validate-only
   python run.py prepare --batch batch_001
   ```
6. `python run.py status --live` to read the objects back from Meta. Sandbox accounts are API-only, so there is no Ads Manager to look at.
7. `python run.py publish --batch batch_001` is only meaningful on the real account. In the sandbox nothing is delivered either way.

After `prepare` succeeds, the batch is **frozen**: if you edit the file, `validate` fails. Put changes in a new batch (`batch_002.json`) with new ad keys.

---

## 7. Safety rules built in

- **Sandbox by default.** Production needs `META_ENV=production` **and** `--confirm-production` for every write, and publishing in production always needs a typed `PUBLISH`.
- **Everything is created PAUSED.** Campaign status other than `PAUSED` is rejected by `validate`.
- **No duplicates.** Registries in `data/<env>/` remember Meta IDs. Before creating a campaign, ad set or ad, the launcher also looks for the same name on Meta. Creatives cannot be looked up by name, so only the local registry protects them. Do not delete `data/` mid-way.
- **Writes are never blindly retried.** Reads and rate-limit errors are retried. A write that times out is not, because it may have gone through; re-run the command and it will adopt what exists.
- **Keys are never reused**, across batches or against the registry.
- **Batches are frozen** after their ads are created.
- **Secrets**: the token goes in a header, calls are signed with `appsecret_proof`, and tokens are redacted from errors and `logs/launcher.log`.
- **Separate environments**: separate credentials and separate registries per environment.

---

## 8. Tracking and the dashboard

The launcher sets this on every ad's URL via Meta's `url_tags`:

```
utm_source=facebook&utm_medium=paid_social
&utm_campaign={{campaign.id}}&utm_content={{ad.id}}&utm_term={{adset.id}}
&rs_creative=<ad_key>&rs_batch=<batch_id>
```

Meta replaces the `{{...}}` macros with real IDs. The marketing dashboard matches Paid Meta sessions by those IDs (or by unique names), and campaign, ad set and ad are named after their keys. Orders and revenue per creative therefore line up with the `RS_*` keys.

For the website to report it, UTMs must survive the quiz and checkout journey (`rs_creative` is the easiest to check in the event data).

Performance reading is done by the dashboard's **Meta Ads** page, not by this tool. Sandbox accounts return no performance data.

---

## 9. Code map (`src/`)

| File | Job |
|---|---|
| `common.py` | Settings, `.env`, registries, config/batch loading, production guard |
| `meta_api.py` | Graph API client: header token, `appsecret_proof`, retry rules, redacted errors, dry-run, `validate_only`, find-by-name |
| `validate.py` | All local checks: JSON, keys, images (type, size, dimensions, ratio, file name), CTA, URL, budgets, frozen batches |
| `upload_images.py` | Upload, hash registry, reuse of identical files |
| `ensure.py` | "Create only if missing": registry, then name lookup, then create |
| `create_campaigns.py`, `create_adsets.py` | Setup step |
| `create_creatives.py`, `create_ads.py` | Prepare step; freezes the batch |
| `publish.py` | The only code that activates anything |
| `doctor.py` | `doctor`, `images` and `status` |
| `pipeline.py` | The single entry point used by both `run.py` and the UI |

---

## 10. Going to production (checklist)

Do not do this until the sandbox run is clean.

1. A real ad account with a payment method, and the Page and (if used) Instagram account connected to it.
2. For Sales campaigns: a Meta pixel / dataset sending Purchase events; set `META_PRODUCTION_PIXEL_ID` and use `optimization_event`.
3. A long-lived credential: replace the user token with a **System User** token (the dashboard's current user token expires 2027-01-09).
4. Fill the `META_PRODUCTION_*` block; set `META_ENV=production`; `python run.py doctor`.
5. Run with `--dry-run`, then `--validate-only`, then for real with `--confirm-production`. Review the paused ads in Ads Manager.
6. `publish` and type `PUBLISH`. Meta reviews the ad before it delivers.

---

## 11. Troubleshooting

| Message | Likely cause |
|---|---|
| `missing in .env: ...` | Fill the block for the selected `META_ENV` |
| `Invalid OAuth access token` (code 190) | Wrong/expired token, or token and app secret are from different apps |
| `... (code 10)` / permission errors | Token lacks `ads_management`, or the user has no access to the account or Page |
| `image not found` | File name must equal `ad_key`, extension `.jpg/.jpeg/.png`, path as written in the batch |
| `batch ... edited after submission` | Restore the file, or move your changes to a new batch with new keys |
| `campaign ... has no Meta id yet` | Run `setup` before `prepare`, in order |
| `image not uploaded yet` | Run `upload` first |
| `writes are blocked` | You are on `META_ENV=production`; add `--confirm-production` only if intended |

Full detail of every call (secrets removed) is in `logs/launcher.log`.

---

## 12. Known limits and unverified points

- Sandbox-tested only up to the ad set. Creatives, ads and publish are untested (see SANDBOX_TEST.md).
- Whether a sandbox account accepts creatives and image uploads exactly like a real one is unconfirmed.
- Image limits (30 MB, 600px minimum, 1080px recommended, aspect ratios) are from memory of Meta's guidance; check current docs.
- Only static image ads with one image per ad (no video, carousel, dynamic creative, special ad categories, lookalike or custom audiences).
- Insights and reporting are intentionally left to the dashboard.

### Differences from `plan.md`
- Insights/report commands (`fetch_insights`, `generate_report`) are not built; the dashboard covers them.
- Added `doctor`, `status`, `--dry-run`, `--validate-only`, `--confirm-production`, the `entity_registry`, `batch_hashes` (batch freezing) and the DRAFT/READY gate.
- Starter campaign is **Traffic**, not Sales, because Sales needs a pixel that the sandbox cannot provide.
- UTMs use Meta's ID macros (so the dashboard can match them) plus `rs_creative`, instead of a static `utm_content=RS_ACNE_001`.
- Environment credentials are split into `META_SANDBOX_*` / `META_PRODUCTION_*` blocks in a single `.env`.
