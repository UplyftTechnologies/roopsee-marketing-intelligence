# Roopsee Meta Ads Launcher

A tool that turns **local images + JSON files** into Meta (Facebook / Instagram) ads through the Marketing API. Use it from the **command line** or from the **web UI** (`python run.py ui`), which has a guided flow for creating campaigns with several ad sets and several ads.

- You design the images and write the copy. Python validates, uploads and creates everything on Meta.
- **Everything is created PAUSED.** Only `publish` activates anything, and only after you type `PUBLISH`.
- The default environment is the **sandbox** (no delivery, no spend). Production is locked behind an explicit flag (CLI) or a typed confirmation (UI).
- Spend and orders per creative show up in the marketing dashboard (see [Tracking](#tracking-and-the-dashboard)).

> Status: tested on a real Meta **sandbox** and on the real (production) account. Sandbox: image upload, campaigns and ad sets work, including several ad sets in one campaign; creatives and ads are blocked there because the sandbox user cannot act as your Page (see [SANDBOX_TEST.md](SANDBOX_TEST.md)). Production: the full chain (image, campaign, ad set, creative, ad) was created **paused** and confirmed in Ads Manager. Going live (`publish`) has not been tested. See [Known limits](#12-known-limits-and-unverified-points).

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
├── drafts/                 saved wizard drafts (created on demand, git-ignored)
├── backups/                copies of config made before a reset (git-ignored)
├── SANDBOX_TEST.md         what was tested in the sandbox, and the result
├── .env.example            copy to .env and fill in (never commit .env)
├── plan.md                 the original plan this was built from
├── config/
│   ├── account.json        currency + UTM template
│   ├── audiences.json      named audiences (country, age, gender)
│   ├── destinations.json   web page links shown as a dropdown in the UI
│   ├── campaigns.json      campaigns: objective, budget
│   └── adsets.json         ad sets: audience, placements, optimisation
├── creatives/              your images, one folder per angle
│   ├── acne/  pigmentation/  trust/  retargeting/
│   └── test/RS_TEST_001.png    generated test image for the sandbox
├── ads/
│   └── batch_001.json      the ads: image, copy, CTA, URL, status (the UI writes batch_wiz_<date>_<time>.json for each campaign it creates)
├── data/
│   ├── sandbox/            Meta IDs and image hashes for the sandbox
│   └── production/         the same, kept separate for production
├── logs/launcher.log       every run, with secrets redacted
├── reports/                reserved for exports
├── ui/                     web UI backend (server.py, wizard.py, jobs.py); ui/dist is the built screens
├── ui-app/                 web UI source (React + Vite; styles copied from the dashboard)
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
| `META_SANDBOX_ACCESS_TOKEN` | Token with `ads_management` (`ads_read` is also fine to have); for creatives also the Page permissions (`pages_read_engagement`, `pages_show_list`) |
| `META_SANDBOX_APP_ID` / `_APP_SECRET` | Your Meta app. The secret is used to sign every call (`appsecret_proof`); the app id enables the token-expiry check in `doctor` |
| `META_SANDBOX_AD_ACCOUNT_ID` | The sandbox ad account, `act_...` (the `act_` prefix is added if you leave it out) |
| `META_SANDBOX_PAGE_ID` | The Facebook Page that ads are published from. Required for creatives |
| `META_SANDBOX_INSTAGRAM_ID` | Optional Instagram account id for Instagram placements |
| `META_SANDBOX_PIXEL_ID` | Optional. Only needed for conversion-optimised ad sets (Sales) |

**One token for both?** That is fine. Put it once in the shared block (`META_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET`, `META_PAGE_ID`, `META_INSTAGRAM_ID`) and leave the per-environment versions empty; they are used when a per-environment value is missing. The **ad account id and pixel id are never shared**, so the sandbox cannot touch the real account through the fallback. The environment starts as `META_ENV` and can be switched in the UI for that window (section 5b).

The `META_PRODUCTION_*` block mirrors it. Leave it empty until you are ready for real money. Real environment variables starting with `META_` override the file.

Never paste tokens into chat, tickets or commits. If one was exposed, rotate it.

**Check everything (read-only, changes nothing):**
```
python run.py doctor
```
It verifies: credentials present, token accepted, token valid and its expiry, the `ads_management` permission, ad account reachable (name, currency, timezone), currency matches `config/account.json`, that campaigns can be read, Page reachable, and that config + a batch exist. Fix every `FAIL` line before going on.

**Not sure which ID to use?** `python run.py discover` lists the ad accounts, Pages, Instagram accounts and pixels your token can see, each labelled with the `.env` variable it belongs in (set `META_ENV=production` for the real account, or switch for one command with `META_ENV=production python run.py discover`).

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
| `ad_key` | Unique, never reused, format `RS_<ANGLE>_<NNN>`, e.g. `RS_ACNE_001`. Becomes the ad and creative name. A second copy of the same ad in another ad set ends in `_S2`, `_S3`, e.g. `RS_ACNE_001_S2` |
| `adset_key` | Which ad set it belongs to |
| `image` | Path under `creatives/`. The file name must equal `ad_key` without any `_S2` ending (JPG or PNG). Instead of `image` you may give `image_hash`, the 32-character hash of an image already in the ad account (list them with `python run.py images`) |
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
python run.py live                                # everything in the ad account right now, straight from Meta
python run.py discover                            # list the ad accounts, Pages, Instagram accounts and pixels your token can see (to fill .env)
python run.py images                              # images already in the ad account, with hashes
python run.py ui                                  # the web UI
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

## 5b. Web UI (the easy way)

```
python run.py ui            # opens http://127.0.0.1:8765  (change with META_UI_PORT)
python run.py ui --no-browser
```
The first run builds the screens (needs Node.js once; the dashboard needs it too). The look matches the performance dashboard: same sidebar, top bar, cards, badges and light/dark theme. It runs on the same code as the command line (`src/pipeline.py`), so both always behave the same.

**New campaign (the guided way).** Five plain questions, then one button:
1. **What for**: get website visitors, or get sales (Sales needs your pixel in `.env`).
2. **Who sees it**: one or more **ad sets**. Each ad set is an audience (a ready-made one, one you saved, or your own countries, ages and gender) plus where the ads appear. Use **Add another ad set** or **Duplicate** to compare audiences or places side by side.
3. **Budget**: with several ad sets choose **one budget for the whole campaign** (Meta shares it) or **a separate budget for each ad set**. Optional start and end dates.
4. **Ads**: drop in several images (each becomes an ad), pick one from your library, or **pick an image already on Meta** (you see the real image and its hash; or paste a hash and it is checked against the ad account). Write the text once and adjust any ad, pick the web page from a list, and for each ad tick **which ad sets show it**. An ad shown in two ad sets is created once per ad set (see below).
5. **Review**: a plain summary with an ad set table, a checklist of anything to fix, then **Create on Meta (paused)**.

It uploads the images, creates the campaign and all its ad sets, then the ads, all **paused**, with a progress list. If a step fails you get a plain explanation and a **Try again** button that skips what already worked. Drafts are saved as you go (and can be opened by link), and you can start from an earlier campaign. Names on Meta are generated (for example `Roopsee | Traffic | 17 Nov`); ad IDs come from the image names. Turning a campaign on is separate: **Run > Go live**, with the typed word `PUBLISH`.

**One ad in several ad sets.** Meta needs a separate ad for each ad set. The launcher makes them for you: the first keeps the image's ID (`RS_ACNE_001`) and the others get `_S2`, `_S3` and so on (`RS_ACNE_001_S2`), using the same image. Ad IDs ending in `_S<number>` are valid; the image file name stays `RS_ACNE_001`.

**Campaigns & ad sets (the editing way).** A page of cards, one per campaign, with its ad sets inside, in plain words: what it is for ("Website visits", "Sales"), how the budget works, who sees it, where it shows, what Meta should aim for, dates. Define **audiences** once at the top and pick them anywhere. **Make a copy** duplicates an ad set or a whole campaign. Anything already created on Meta is locked and marked "on Meta" (Meta objects cannot be edited from config files); make a copy to change it. Names can only be set on new items, so existing batches are never broken.

| Page | What it does |
|---|---|
| **New campaign** | The guided flow above |
| **Overview** | Everything on Meta, read live: tiles, things that need attention, and a campaign > ad set > ad tree |
| **Creatives** | Add images by theme and see which are used or on Meta. **Already on Meta** shows the actual images in your ad account with their hash: click one to see it full size, copy the hash, or use it in a new campaign |
| **Campaigns & ad sets** | Edit campaigns, ad sets and audiences as plain cards (above) |
| **Links & tracking** (advanced) | Web page links for the dropdown, and the tracking tags added to every link |
| **Run** (advanced) | The three steps by hand with dry run / check with Meta / real, plus Go live |
| **Health** (advanced) | The connection check |

UI safety: it listens on 127.0.0.1 only and rejects other host names; changes need a header a web page on another site cannot send; the token and secret never reach the browser; one command runs at a time; the Sandbox / Production button (top right) is a simple switch for that window only (it is refused while a step is running or if that environment is not set up in `.env`); restarting the UI returns to the value in `.env` (`META_ENV`, sandbox by default); production shows a red notice and needs an extra tick box before any change, and going live still needs the typed word `PUBLISH`.

## 6. Running your first ad (sandbox walkthrough, command line)

The UI does all of this for you (section 5b); this is the same thing by hand.

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

- **Sandbox by default.** Production needs `META_ENV=production` (or the UI switch) **and** `--confirm-production` (or the UI's tick box) for every write, and publishing in production always needs a typed `PUBLISH`.
- **Everything is created PAUSED.** Campaign status other than `PAUSED` is rejected by `validate`.
- **No duplicates.** Registries in `data/<env>/` remember Meta IDs. Before creating a campaign, ad set or ad, the launcher also looks for the same name on Meta. Creatives cannot be looked up by name, so only the local registry protects them. Do not delete `data/` mid-way.
- **Writes are never blindly retried.** Reads and rate-limit errors are retried. A write that times out is not, because it may have gone through; re-run the command and it will adopt what exists.
- **Keys are never reused**, across batches or against the registry (an ad's `_S2` copies count as separate keys).
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
| `doctor.py` | `doctor`, `discover`, `live`, `images` and `status` |
| `pipeline.py` | The single entry point used by both `run.py` and the UI |

`ui/server.py` is the web backend (local only, header-protected, environment switch, creative upload, config and batch editing). `ui/wizard.py` turns the guided answers into a plan (several ad sets, shared or per-ad-set budgets, ads in several ad sets), writes the config and batch, and runs upload > setup > prepare. `ui/jobs.py` runs one background job at a time and turns common Meta errors into plain advice. `ui-app/` is the React source for the screens.

---

## 10. Going to production (checklist)

Creative and ad creation have been proven on the real account (created paused, visible in Ads Manager). Going live (`publish`) has not.

1. A real ad account with a payment method, and the Page and (if used) Instagram account connected to it.
2. For Sales campaigns: a Meta pixel / dataset sending Purchase events; set `META_PRODUCTION_PIXEL_ID` and use `optimization_event`.
3. A long-lived credential: replace the user token with a **System User** token (the dashboard's current user token expires 2027-01-09).
4. Fill the `META_PRODUCTION_*` block (`python run.py discover` finds the IDs); then either set `META_ENV=production` or use the Sandbox / Production button in the UI; run `python run.py doctor`. The token you use now expires (check `doctor` for the date); use a System User token for something long-lived.
5. In the UI: New campaign, tick the production confirmation, create. By hand: `--dry-run`, then `--validate-only`, then for real with `--confirm-production`. Either way, review the paused campaign in Ads Manager (search for its name).
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
| `writes are blocked` | You are on production; add `--confirm-production` (CLI) or tick the confirmation box (UI) only if intended |
| `No permission to access this profile` (code 10, subcode 1341012) | The token's user cannot act as your Page. In the sandbox this is expected (the sandbox user cannot post as a Page); on production give the user access to the Page in Business Settings |
| `this ad needs an Ad ID like RS_SKINCARE_001` (UI) | An ad added by image hash has no ID; type one on its card in step 4 |
| `already been used in another campaign` (UI) | Every image can be used once; upload a new image or a new version |
| `Sales campaigns need your pixel` | Set `META_<ENV>_PIXEL_ID` (find it with `python run.py discover`) |

Full detail of every call (secrets removed) is in `logs/launcher.log`.

---

## 12. Known limits and unverified points

- Sandbox: creatives and ads fail with a Page permission error, so only campaigns, ad sets and image upload can be tested there (see SANDBOX_TEST.md). I could not confirm whether Meta supports creatives in the sandbox at all.
- Production: one paused test campaign with ad set, creative and ad was created and seen in Ads Manager. Going live (`publish`) and a multi-ad-set campaign on production are untested.
- The Ads Manager link on the UI's result screen is built from the account and campaign IDs and has not been verified to open the right page.
- Image limits (30 MB, 600px minimum, 1080px recommended, aspect ratios) are from memory of Meta's guidance; check current docs.
- Only static image ads with one image per ad (no video, carousel, dynamic creative, special ad categories, lookalike or custom audiences). The guided flow offers Traffic and Sales goals only.
- Meta objects cannot be changed or deleted from the launcher; editing a campaign or ad set that is already on Meta must be done in Ads Manager (the UI locks them and offers a copy).
- Insights and reporting are intentionally left to the dashboard.

### Differences from `plan.md`
- Insights/report commands (`fetch_insights`, `generate_report`) are not built; the dashboard covers them.
- Added `doctor`, `status`, `--dry-run`, `--validate-only`, `--confirm-production`, the `entity_registry`, `batch_hashes` (batch freezing) and the DRAFT/READY gate.
- Starter campaign is **Traffic**, not Sales, because Sales needs a pixel that the sandbox cannot provide.
- Added a web UI with a guided flow, several ad sets per campaign, an environment switch, drafts, and a Campaigns & ad sets editor; ads can also be created from an existing image hash; ad IDs may end in `_S<number>` for copies of an ad in other ad sets.
- UTMs use Meta's ID macros (so the dashboard can match them) plus `rs_creative`, instead of a static `utm_content=RS_ACNE_001`.
- Environment credentials are split into `META_SANDBOX_*` / `META_PRODUCTION_*` blocks in a single `.env`.
