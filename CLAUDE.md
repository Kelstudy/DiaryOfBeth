# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
# Instagram Media Kit Dashboard — DiaryOfBeth

## Purpose
Automated pipeline that pulls live Instagram stats for the account
`thediaryofbeth` (Instagram user ID `28342906085327802`) and displays
them on a public dashboard used as a media kit when negotiating paid
brand collabs. Goal: a self-updating, shareable page — no manual stat
pulling ever again.

## Tech & Conventions
- Python for all scripting.
- **camelCase** for variable/function names — deliberate deviation from
  PEP8, keep it consistent everywhere. This is a hard style rule, not a
  suggestion.
- Prefer explicit, readable code over clever one-liners.
- No code duplication — new scripts import from existing proven scripts
  rather than re-implementing logic (e.g. `pullData.py` imports from
  `testPull.py`).
- Frontend: plain HTML/CSS/JS or a lightweight framework. No paid
  services anywhere in the stack — everything must stay free to host.
- Design: dark-themed, data-report aesthetic, visually consistent with
  an existing portfolio site also hosted on GitHub Pages.

## Architecture
- **Data pull**: Python scripts call the Instagram API (Instagram API
  with Instagram Login, Standard Access — single-user, own-account-only,
  no Meta App Review needed).
- **Storage**: no database. Pulled data appends as timestamped snapshots
  to `data/statsHistory.json` (append-only, powers time-series charts).
- **Automation**: GitHub Actions scheduled workflow runs the pull script
  and commits the updated JSON. Daily cadence (not more frequent) — this
  was a deliberate default given ~169 API calls per 30-day pull, to stay
  within rate limits.
- **Frontend**: static site on GitHub Pages, reads the JSON, renders
  charts/cards — follower growth line, engagement rate trend, audience
  demographics, top posts gallery.

## Current State (as of last session)
- Core scripts exist: `getAccessToken.py` (one-time OAuth → long-lived
  60-day token), `testPull.py` (sanity pull of profile + insights),
  `refreshToken.py`, `pullData.py`, `inspectMedia.py` (diagnostic).
- `pullData.py` imports from `testPull.py`, appends snapshots to
  `data/statsHistory.json`.
- GitHub repo `DiaryOfBeth` is set up. `INSTAGRAM_ACCESS_TOKEN` stored as
  a repo secret. `.env` and `token.json` correctly gitignored.
- Long-lived token generated (expires ~September 2026) — **was briefly
  exposed in chat and needs rotation before going live.**
- Two bugs fixed: silent-hang appearance during large API batches (fixed
  with progress logging); `JSONDecodeError` on empty `statsHistory.json`
  (fixed with resilient file loading).
- Trial reels show up in the `/media` API response despite being
  Instagram-internal. `inspectMedia.py` exists to find a distinguishing
  field to filter them out — **this investigation is still pending**,
  next step is running it against a known trial reel ID vs. a normal
  post ID and comparing output.

## On the Horizon
1. Use `inspectMedia.py` output to find the trial-reel-distinguishing
   field, then add filtering logic to `testPull.py`/`pullData.py`.
2. Confirm `impressions` works for photos/carousels (only tested live
   for Reels so far).
3. Set up GitHub Actions for scheduled automation (daily).
4. Set up a GitHub PAT for streamlined pushes (not yet configured).
5. Build the frontend dashboard on GitHub Pages.
6. Rotate the exposed access token before going live.

## Key Learnings (don't relitigate these)
- Reels support `reach`, `views`, `saved`, `shares`, `total_interactions`
  — **not** `impressions`. Photos/carousels are expected to use
  `impressions` instead of `views` (unconfirmed live as of last session).
- `total_interactions` is the correct 2026 metric name — `engagement` is
  not a valid field, don't use it.
- The 30-day post window needs cursor-based pagination that stops at a
  date boundary — a fixed page-count approach misses posts on
  high-volume accounts.
- Per-post engagement rate = `(likes + comments) / followers × 100`.
- Meta's developer dashboard reorganizes often — if a metric call fails,
  check current field names before assuming the script is broken. The
  "Tester Invites" tab tied to the old Basic Display API no longer
  appears for the current Instagram Login flow.

## Infra Reference
- Meta developer app ID: `1577775653712830`
- OAuth redirect URI: `https://localhost/`
- Permissions: `instagram_business_basic`, `instagram_business_manage_insights`
- Local path: `C:\Users\Kelvi\OneDrive\Desktop\diaryofbeth`
- Repo: GitHub `DiaryOfBeth`, GitHub Actions (planned), GitHub Pages (planned)

## Working Style
- Treat this as an ongoing multi-session build — check what's built vs.
  still needed, don't restart planning from scratch.
- When a decision is needed (e.g. "auto-refresh vs manual trigger"),
  state a sensible default and proceed — flag the choice so it can be
  revisited later, don't stall on it.
- Flag anything that will require re-authentication or token refresh so
  it doesn't silently break.
- If a Meta Insights API metric call fails, check current field names
  first — fields change periodically, it's usually not a code bug.