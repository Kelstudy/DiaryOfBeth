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
- `python pullData.py` — the real collector. Builds one JSON snapshot and appends it to
  `data/statsHistory.json`, skipping the save if nothing changed since the last run. Intended to run
  on a schedule (a GitHub Actions cron job is planned but not yet present in this repo).

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
   - `pullProfile`, `pullRecentMedia`, `pullMediaWithinLast30Days`, `pullMediaInsights`,
     `pullAccountReachLast30Days` — the API calls.
   - `pullMediaWithinLast30Days` paginates through `paging.next` URLs until it hits a post older than
     30 days (posts come back newest-first), so the 30-day set is exact, not capped by page size.
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
   - `buildSnapshot` orchestrates one full pull (profile, recent posts + their insights, 30-day post
     set + insights, account-level 30-day reach) into one dict tagged with `pulledAt`.
   - `buildPostRecord` / `buildLast30DaysSummary` shape the raw API responses into the stored record
     format.
   - `loadExistingHistory` / `saveHistory` read and rewrite `data/statsHistory.json` as a JSON array
     (append-only, powers time-series charts on the eventual frontend).
   - `isDuplicateOfLastSnapshot` compares a freshly built snapshot to the last saved one (ignoring the
     `pulledAt` timestamp); if nothing changed, `main()` skips the save instead of appending a no-op
     duplicate entry. A real change in followers, likes, or insights always gets saved.

## Storage & automation

- No database. Pulled data appends as timestamped snapshots to `data/statsHistory.json`.
- Automation is planned as a GitHub Actions scheduled workflow that runs `pullData.py` and commits the
  updated JSON — not yet set up in this repo. Daily cadence (not more frequent) is the intended
  default, given the API call volume of a full 30-day pull, to stay within rate limits.

## Open items / known gaps

- Frontend dashboard (GitHub Pages, follower growth chart, engagement trend, top posts gallery) does
  not exist yet.
- GitHub Actions scheduled workflow not yet set up.
- **Security**: an earlier access token was exposed in a chat session and has since been rotated via
  `getAccessToken.py`.
- Trial reels (Instagram creates several distinct REELS media IDs per trial reel upload, seconds
  apart) show up as separate posts in pulls, inflating post counts and stats. A timing-based filter
  (collapsing REELS posted within 60s of each other) was tried and reverted — it risked dropping
  legitimate posts made in quick succession, since no API field reliably distinguishes trial reels
  from real ones (`is_shared_to_feed` was tested and ruled out). `inspectMedia.py` remains in the repo
  as a diagnostic. Planned approach instead: tag trial-reel captions manually going forward and filter
  on that tag, once there's a labeled example to build against.
