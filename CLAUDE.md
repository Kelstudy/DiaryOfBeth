# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose
Automated pipeline that pulls live Instagram stats for the account `thediaryofbeth` and (eventually)
displays them on a public dashboard used as a media kit when negotiating paid brand collabs. Goal: a
self-updating, shareable page — no manual stat pulling ever again.

## Setup

```
pip install -r requirements.txt
```

Requires a `.env` file (gitignored, never commit) with:
```
INSTAGRAM_APP_ID=your_app_id
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_REDIRECT_URI=https://localhost/
```

## Commands

- `python getAccessToken.py` — one-time (or re-auth) interactive flow: builds an authorization URL,
  takes a pasted redirect URL back, and exchanges it for a long-lived (~60 day) token saved to
  `token.json` (gitignored). Run this first, and again whenever the token has fully expired.
- `python pullData.py` — the real collector. Prompts for exactly one pull mode: every post from the
  last N days, exactly N most recent posts, or every post since a given date (midnight UTC on that
  date onward) — never combined, so requesting "30 days" can't silently get capped at "10 posts".
  Enter accepts the day/post-count defaults (30 days / 10 posts); the date mode always requires
  explicit input. Then builds one JSON snapshot and appends it to `data/statsHistory.json`, skipping
  the save if nothing changed since the last run.
- `python pullData.py --mode {days,posts,date} --value VALUE` — same collector, non-interactive.
  Skips the prompts entirely; used by the GitHub Actions workflow. `--mode` and `--value` must be
  given together. Example: `python pullData.py --mode days --value 30`.
- `python refreshToken.py` — non-interactive. Exchanges the current long-lived token in `token.json`
  for a fresh one with a new ~60-day expiry (no browser login needed, unlike `getAccessToken.py`).
  Instagram only allows this once the token is at least 24h old and still unexpired. Run automatically
  by the GitHub Actions workflow before every scheduled pull.

There is no test suite, linter, or build step configured.

## Tech & conventions

- Python for all scripting.
- **camelCase** for variable/function names — deliberate deviation from PEP8, keep it consistent
  everywhere. This is a hard style rule, not a suggestion.
- Prefer explicit, readable code over clever one-liners.
- No code duplication — new scripts import shared logic rather than re-implementing it (see
  `igApi.py` below).
- Frontend: plain HTML/CSS/JS, no build step, no framework. No paid services anywhere in the stack —
  everything must stay free to host. Dark-themed, data-report aesthetic.

## Architecture

1. **`getAccessToken.py`** — auth only. Produces `token.json` (`accessToken`, `userId`, `obtainedAt`,
   `expiresAt`). Not imported by the other scripts. Instagram API with Instagram Login, Standard
   Access — single-user, own-account-only, no Meta App Review needed.
2. **`refreshToken.py`** — standalone, not imported by other scripts. Calls
   `https://graph.instagram.com/refresh_access_token` with the current token to get a new one with a
   fresh ~60-day expiry, overwriting `token.json` in place (keeps the same `userId`). On failure
   (network error, token past its refresh window), it leaves `token.json` untouched and exits cleanly
   rather than raising — a refresh hiccup shouldn't abort the workflow's actual data pull.
3. **`igApi.py`** — owns all the Instagram Graph API pull logic, imported by `pullData.py`:
   - `loadToken()` reads `token.json`.
   - `pullProfile`, `pullMostRecentPosts`, `pullMediaSinceDate`, `pullMediaWithinLastNDays`,
     `pullMediaInsights`, `pullAccountReachLastNDays` — the API calls.
   - `pullMostRecentPosts(accessToken, userId, postCount)` paginates through `paging.next` URLs until
     it has collected exactly `postCount` posts (or the account runs out), rather than issuing a
     single request capped at whatever the API's default page size allows.
   - `pullMediaSinceDate(accessToken, userId, cutoffDate)` paginates until it hits a post older than
     `cutoffDate` (posts come back newest-first), so the post set is exact, not capped by page size.
     `pullMediaWithinLastNDays(accessToken, userId, days)` is a thin wrapper over this — it just
     computes `cutoffDate = now - timedelta(days=days)`.
   - `getMetricListForProductType` — Reels support `reach`, `views`, `saved`, `shares`,
     `total_interactions` but **not** `impressions`; photos/carousels are expected to use
     `impressions` instead of `views` (confirmed live for Reels; not yet confirmed live for
     photos/carousels).
   - `pullMediaInsights` tries all metrics for a post in one combined call first, and falls back to
     per-metric calls (dropping any that error) if the combined call fails — a single unsupported
     metric for a post should not lose the rest of that post's insights.
   - `calculateEngagementRate` = (likes + comments) / followers, as a percentage.
   - Note: `total_interactions` is the correct current metric name — `engagement` is not a valid
     field.
4. **`pullData.py`** — imports the pull functions from `igApi.py` and assembles them into a snapshot:
   - `promptForPullMode()` asks the user to choose exactly one of `"days"`, `"posts"`, or `"date"` mode
     and a value (`pullValue` is an int for `"days"`/`"posts"`, a `"YYYY-MM-DD"` string for `"date"`),
     returning `(pullMode, pullValue)`. These feed into a single pulled post set — there's no separate
     "detailed posts" list capped independently of the day window.
   - `buildSnapshot(accessToken, userId, pullMode, pullValue)` pulls that one post set
     (`pullMediaWithinLastNDays` for `"days"`, `pullMostRecentPosts` for `"posts"`, `pullMediaSinceDate`
     for `"date"` — parsing `pullValue` into a midnight-UTC `cutoffDate`), then pulls insights and
     builds a full `buildPostRecord` for every post in it — all pulled posts get full detail, not just
     the first 10.
   - For the account-level reach call (which needs a since/until range, not a post count or date),
     `"days"` mode uses `pullValue` directly; `"date"` mode computes days between `cutoffDate` and now;
     `"posts"` mode estimates the span via `daysSpannedByPosts` (days between the oldest pulled post
     and now). The actual value used is stored as `accountReachWindowDays` so it's always traceable
     per snapshot.
   - `buildPulledSetSummary` aggregates totals across the pulled set, tagged with `pullMode` and
     `pullValue` so each snapshot is self-describing. Stored under the `pulledSetSummary` key. (Older
     entries predating this change use `recentWindow` or `last30Days` instead — the dedup check in
     `isDuplicateOfLastSnapshot` treats these as distinct from current-schema snapshots, which is
     correct since the schema differs.)
   - `loadExistingHistory` / `saveHistory` read and rewrite `data/statsHistory.json` as a JSON array
     (append-only, powers time-series charts on the eventual frontend).
   - `isDuplicateOfLastSnapshot` compares a freshly built snapshot to the last saved one (ignoring the
     `pulledAt` timestamp); if nothing changed, `main()` skips the save instead of appending a no-op
     duplicate entry. A real change in followers, likes, or insights always gets saved.

## Frontend

- **`index.html`** (repo root — required so GitHub Pages can serve both the page and
  `data/statsHistory.json` from the same origin via a relative `fetch("data/statsHistory.json")`;
  moving the page into a subfolder would break that fetch unless the data were duplicated into it) +
  **`assets/dashboard.css`** + **`assets/dashboard.js`**. No build step, no framework, no CDN
  dependency — everything is hand-written vanilla JS/CSS, self-contained.
- `dashboard.js` fetches the full history, normalizes each entry (`getSummary()` reads whichever of
  `pulledSetSummary` / `recentWindow` / `last30Days` is present, so old-schema entries still render),
  then renders a masthead (latest username/account type/following/media count) plus a
  filter-driven dashboard body — see Filters below.
- Two filter `<select>`s (`#rangeSelect`: 7/30 days or all time — capped at 30 to match the workflow's
  default pull window, see Storage & automation; `#topNSelect`: 5/10/15/25/all posts)
  sit above the KPI row and drive `renderDashboard()` on `change`. **Scoping rules** (deliberately
  different per element, since some KPIs are point-in-time and can't be "filtered"):
  - **Time range** filters which *history snapshots* feed the two line charts, and which of the
    latest snapshot's own posts (by each post's own `timestamp`) feed the Engagement rate / Total
    interactions tiles and the top-posts grid. It can never surface posts older than what the last
    pull actually collected — a wide range just means "show everything that was pulled."
  - `computeAggregateFromPosts()` recomputes engagement rate / interactions / reach client-side from
    the range-filtered raw post records, rather than trusting a snapshot's pre-computed
    `pulledSetSummary` (which reflects whatever pull mode was used at collection time, not the
    viewer's selected range).
  - **Followers** and **Account reach** KPI tiles stay anchored to the true latest pull regardless of
    the range selector — both are point-in-time/fixed-window values from the API, not something a
    client-side date filter can meaningfully reslice. Account reach shows its own actual
    `accountReachWindowDays` as a label so it's never ambiguous which window it covers.
  - **Show top** only controls how many post cards render in the grid (post-count display, not a
    scope) — independent of the time range.
- The charts and posts grid are hand-rolled SVG/DOM, not a library: two line charts (follower growth,
  engagement rate over time — with a hover crosshair + tooltip, and a direct end-label on the latest
  point, clamped so it can never render above the chart card), and a top-posts grid (range-filtered
  posts, sorted by `engagementRate` descending, capped at the selected top-N, linking out to the real
  permalink).
- Charts render an empty-state message instead of a broken chart when there are fewer than 2 history
  points (true for a freshly-started history) — `renderLineChart` checks `points.length < 2` first.
- Dark-only (no light-mode toggle) — deliberate, per the dark-themed aesthetic above, not an
  oversight. Colors are the dataviz skill's default validated palette (dark column): series blue
  `#3987e5`, good/bad deltas `#0ca30c`/`#e66767`, chart surface `#1a1a19` on page plane `#0d0d0d`.
- **GitHub Pages must be enabled manually** in repo Settings → Pages → Source: Deploy from branch →
  `main` / `(root)`. Not yet done as of this writing — needed before the site is actually reachable.

## Storage & automation

- No database. Pulled data appends as timestamped snapshots to `data/statsHistory.json`.
- `.github/workflows/pull-stats.yml` runs on a daily cron (07:00 UTC) — daily, not more frequent, given
  the API call volume of a full N-day pull (one insights call per post), to stay within rate limits.
  Also runnable manually via `workflow_dispatch` with `mode`/`value` inputs (defaults: `days` / `30`).
  Each run: writes `token.json` from a secret → refreshes it → writes the refreshed token back to that
  same secret → pulls stats with the refreshed token → commits `data/statsHistory.json` if it changed.
  This makes the token effectively self-sustaining: it gets refreshed to a fresh ~60-day expiry every
  single day, so it never has a chance to actually expire as long as the workflow keeps running.
  - **Requires a repo secret named `INSTAGRAM_TOKEN_JSON`** containing the exact contents of a valid
    `token.json`. Written out on the runner before calling `refreshToken.py`/`pullData.py`; nothing
    token-related ever gets committed (`git add` in the workflow only stages `data/statsHistory.json`).
  - **Requires a second repo secret named `GH_PAT`** — a GitHub Personal Access Token with permission
    to write Actions secrets on this repo, used by the `gh secret set` step to persist the refreshed
    token back into `INSTAGRAM_TOKEN_JSON`. This is the one piece of setup that can't be automated away
    (a workflow can't grant itself permission to modify repo secrets) — a one-time manual step, not an
    ongoing one.
  - If both secrets are set correctly and the daily cron keeps running, no manual token maintenance
    should ever be needed again. If the workflow ever stops running for longer than the refresh window
    (~60 days) — repo archived, Actions disabled, etc. — the token will lapse and `getAccessToken.py`
    will need to be run by hand to re-establish it from scratch.

## Open items / known gaps

- GitHub Pages isn't enabled yet (see Frontend section above) — the site exists in the repo but isn't
  live until that's turned on in repo settings.
- **Security**: an earlier access token was exposed in a chat session and has since been rotated via
  `getAccessToken.py`.
- Trial reels (Instagram creates several distinct REELS media IDs per trial reel upload, seconds
  apart) show up as separate posts in pulls, inflating post counts and stats. A timing-based filter
  (collapsing REELS posted within 60s of each other) was tried and reverted — it risked dropping
  legitimate posts made in quick succession, since no API field reliably distinguishes trial reels
  from real ones (`is_shared_to_feed` was tested and ruled out). `inspectMedia.py` remains in the repo
  as a diagnostic. Planned approach instead: tag trial-reel captions manually going forward and filter
  on that tag, once there's a labeled example to build against.
