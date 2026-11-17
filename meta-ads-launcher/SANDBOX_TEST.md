# Sandbox test report

Date: 2026-11-17 · Environment: SANDBOX · Graph API v25.0 · Ad account `act_1433477996517331` · Page `1175723048967774`
Test ad: `RS_TEST_001` (generated 1080x1080 PNG) in `ads/batch_001.json`.

## Result in one line
**Image upload, campaign and ad set work in the sandbox. Creative creation (and therefore the ad) is blocked by a Page permission, not by the launcher's payload.**

| Step | Command | Result |
|---|---|---|
| Health check | `python run.py doctor` | All OK (token valid, scope `ads_management`, account, Page reachable, can read campaigns) |
| Local validation | `python run.py validate` | 0 errors, 0 warnings |
| Upload image | `python run.py upload --batch batch_001` | **Pass.** Hash `5e8b6654357f66dc6cec9322ace00245` |
| List images | `python run.py images` | **Pass.** 1 image, 1080x1080, `RS_TEST_001.png` |
| Campaign, Meta-side check | `python run.py setup --batch batch_001 --validate-only` | **Pass.** Campaign accepted. The ad set is skipped in this mode because its campaign does not exist yet (by design) |
| Create campaign + ad set | `python run.py setup --batch batch_001` | **Pass.** Campaign `120330000135553615`, ad set `120330000135554515`, both PAUSED |
| Read back from Meta | Graph API GET on both ids | **Pass.** Values match what was sent (below) |
| Re-run safety | `python run.py setup --batch batch_001` | **Pass.** Both reported `exists`; no duplicates |
| Creative | `python run.py prepare --batch batch_001` (also with `--validate-only`) | **FAIL**, see "The blocker" |
| Ad, freeze, publish | not reached | Not tested |

## What was read back from Meta
- Campaign `ROOPSEE_TRAFFIC_001`: objective `OUTCOME_TRAFFIC`, status PAUSED, `daily_budget` `50000` (so INR 500 sent as minor units is **confirmed**), bid strategy `LOWEST_COST_WITHOUT_CAP`, no special ad categories.
- Ad set `PROSPECTING_001`: PAUSED, goal `LINK_CLICKS`, billing `IMPRESSIONS`, destination `WEBSITE`, targeting India, ages 18-45, `instagram` only, Advantage audience off. Meta added `location_types: home, recent, frequently_in` on its own.

## The blocker: creatives
```
POST act_1433477996517331/adcreatives -> Application does not have permission for this action
| No permission to access this profile (code 10, subcode 1341012)
```
Read-only diagnosis:
- The token's identity is **"Sandbox Ad Account Owner"**, a sandbox user, not you personally.
- It does appear in `me/accounts` for the Page, but `GET <page>?fields=can_post` returns **`can_post: false`**.
- `account/promote_pages` is **empty**: the sandbox account does not list the Page as promotable, even though the dashboard shows it as "Associated Page".
- The token's scopes are `ads_management, pages_manage_ads, pages_manage_metadata, pages_read_engagement, pages_read_user_content, public_profile` (no `pages_show_list`; this may or may not matter).

Conclusion: the payload is not the problem. The sandbox user cannot act as the Page, and a creative must name a Page.

### Things to try next (not yet tried)
1. **Use your own token.** In the app's *Get Access Token* box, tick `ads_read`, `ads_management`, `pages_read_engagement`, `pages_show_list`, click Get Token, put it in `META_ACCESS_TOKEN`, run `python run.py doctor` and `python run.py prepare --batch batch_001`. This token belongs to you, who administers the Page. Unknown: whether your own token is allowed to operate the sandbox account (the campaign/ad set calls will show it quickly).
2. In **Business Settings, Pages**, check that the user/system user behind the token has access to the Page with the "Create ads" task.
3. Re-do the Page association in the Sandbox Ad Account Management table (the Associate/Remove buttons) and run `doctor` again.
4. If sandbox creatives are simply not possible, the creative step can only be tested on the real account. Campaign and ad set creation are already proven.

## State left behind
- Sandbox objects (all PAUSED, no spend possible): campaign `120330000135553615`, ad set `120330000135554515`, image hash above.
- Registered locally in `data/sandbox/` (git-ignored). `RS_TEST_001` is set to `READY` in `ads/batch_001.json`; the batch is **not** frozen because `prepare` did not finish.
- The launcher finds the existing campaign and ad set again, so the test can be continued without recreating them.

## Findings that changed the launcher
- `doctor` previously demanded `ads_read`; this token has `ads_management` and reads fine without it, so the check now requires only `ads_management` and proves reading with a real request.
