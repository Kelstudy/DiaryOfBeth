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

There is no test suite, linter, or build step configured.

## Tech & conventions

- Python for all scripting.
- **camelCase** for variable/function names — deliberate deviation from PEP8, keep it consistent
  everywhere. This is a hard style rule, not a suggestion.
- Prefer explicit, readable code over clever one-liners.
- No code duplication — new scripts import shared logic rather than re-implementing it (see
  `igApi.py` below).
- Frontend (not yet built): plain HTML/CSS/JS or a lightweight framework. No paid services anywhere
  in the stack — everything must stay free to host. Dark-themed, data-report aesthetic, visually
  consistent with an existing portfolio site also hosted on GitHub Pages.

## Architecture

1. **`getAccessToken.py`** — auth only. Produces `token.json` (`accessToken`, `userId`, `obtainedAt`,
   `expiresAt`). Not imported by the other scripts. Instagram API with Instagram Login, Standard
   Access — single-user, own-account-only, no Meta App Review needed.
2. **`igApi.py`** — owns all the Instagram Graph API pull logic, imported by `pullData.py`:
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
3. **`pullData.py`** — imports the pull functions from `igApi.py` and assembles them into a snapshot:
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

## Storage & automation

- No database. Pulled data appends as timestamped snapshots to `data/statsHistory.json`.
- `.github/workflows/pull-stats.yml` runs `pullData.py` on a daily cron (07:00 UTC) — daily, not more
  frequent, given the API call volume of a full N-day pull (one insights call per post), to stay
  within rate limits. Also runnable manually via `workflow_dispatch` with `mode`/`value` inputs
  (defaults: `days` / `30`).
  - **Requires a repo secret named `INSTAGRAM_TOKEN_JSON`** containing the exact contents of a valid
    `token.json` (i.e. the file `getAccessToken.py` produces). The workflow writes that secret out to
    `token.json` on the runner before calling `pullData.py`; nothing token-related ever gets committed
    (`git add` in the workflow only stages `data/statsHistory.json`).
  - Because the long-lived token expires after ~60 days and there's no refresh script in this repo yet
    (see `getAccessToken.py`'s docstring re: a not-yet-present `refreshToken.py`), the secret needs
    manual re-rotation periodically — re-run `getAccessToken.py` locally and update the
    `INSTAGRAM_TOKEN_JSON` secret before the current token expires, or the scheduled runs will start
    failing.

## Open items / known gaps

- Frontend dashboard (GitHub Pages, follower growth chart, engagement trend, top posts gallery) does
  not exist yet.
- No token-refresh automation — the `INSTAGRAM_TOKEN_JSON` secret must be updated by hand every ~60
  days (see Storage & automation above).
- **Security**: an earlier access token was exposed in a chat session and has since been rotated via
  `getAccessToken.py`.
- Trial reels (Instagram creates several distinct REELS media IDs per trial reel upload, seconds
  apart) show up as separate posts in pulls, inflating post counts and stats. A timing-based filter
  (collapsing REELS posted within 60s of each other) was tried and reverted — it risked dropping
  legitimate posts made in quick succession, since no API field reliably distinguishes trial reels
  from real ones (`is_shared_to_feed` was tested and ruled out). `inspectMedia.py` remains in the repo
  as a diagnostic. Planned approach instead: tag trial-reel captions manually going forward and filter
  on that tag, once there's a labeled example to build against.
