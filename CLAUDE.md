# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose
Automated pipeline that pulls live Instagram stats for the account `thediaryofbeth` and displays them
on a public dashboard (`https://kelstudy.github.io/DiaryOfBeth/`) used as a media kit when negotiating
paid brand collabs. A self-updating, shareable page — no manual stat pulling ever again.

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

All Python scripts live in `scripts/` and are run from the repo root (they use paths relative to the
working directory, e.g. `data/statsHistory.json` and `token.json`, not to the script's own location).

- `python scripts/getAccessToken.py` — one-time (or re-auth) interactive flow: builds an authorization
  URL, takes a pasted redirect URL back, and exchanges it for a long-lived (~60 day) token saved to
  `token.json` (gitignored, repo root). Run this first, and again whenever the token has fully expired.
- `python scripts/pullData.py` — the real collector. Prompts for exactly one pull mode: every post from
  the last N days, exactly N most recent posts, or every post since a given date (midnight UTC on that
  date onward) — never combined, so requesting "30 days" can't silently get capped at "10 posts".
  Enter accepts the day/post-count defaults (30 days / 10 posts); the date mode always requires
  explicit input. Then builds one JSON snapshot and appends it to `data/statsHistory.json`, skipping
  the save if nothing changed since the last run.
- `python scripts/pullData.py --mode {days,posts,date} --value VALUE` — same collector, non-interactive.
  Skips the prompts entirely; used by the GitHub Actions workflow. `--mode` and `--value` must be
  given together. Example: `python scripts/pullData.py --mode days --value 30`.
- `python scripts/refreshToken.py` — non-interactive. Exchanges the current long-lived token in
  `token.json` for a fresh one with a new ~60-day expiry (no browser login needed, unlike
  `getAccessToken.py`). Instagram only allows this once the token is at least 24h old and still
  unexpired. Run automatically by the GitHub Actions workflow before every scheduled pull.

There is no test suite, linter, or build step configured.

## Tech & conventions

- Python for all scripting.
- **camelCase** for variable/function names — deliberate deviation from PEP8, keep it consistent
  everywhere. This is a hard style rule, not a suggestion.
- Prefer explicit, readable code over clever one-liners.
- No code duplication — new scripts import shared logic rather than re-implementing it (see
  `igApi.py` below).
- Frontend: plain HTML/CSS/JS, no build step, no framework. No paid services anywhere in the stack —
  everything must stay free to host. Light, pink-based brand aesthetic (page background pink, cards
  off-white, text near-black) — modeled after a reference media-kit screenshot the account owner
  supplied; changed from an earlier dark theme, see Frontend section below.

## Architecture

All paths below are relative to `scripts/` unless stated otherwise.

1. **`getAccessToken.py`** — auth only. Produces `token.json` (repo root; `accessToken`, `userId`,
   `obtainedAt`, `expiresAt`). Not imported by the other scripts. Instagram API with Instagram Login,
   Standard Access — single-user, own-account-only, no Meta App Review needed.
2. **`refreshToken.py`** — standalone, not imported by other scripts. Calls
   `https://graph.instagram.com/refresh_access_token` with the current token to get a new one with a
   fresh ~60-day expiry, overwriting `token.json` in place (keeps the same `userId`). On failure
   (network error, token past its refresh window), it leaves `token.json` untouched and exits cleanly
   rather than raising — a refresh hiccup shouldn't abort the workflow's actual data pull.
3. **`igApi.py`** — owns all the Instagram Graph API pull logic, imported by `pullData.py`:
   - `loadToken()` reads `token.json`.
   - `pullProfile`, `pullMostRecentPosts`, `pullMediaSinceDate`, `pullMediaWithinLastNDays`,
     `pullMediaInsights`, `pullAccountReachLastNDays`, `pullAccountProfileViewsLastNDays`,
     `pullAccountViewsLastNDays`, `pullNetFollowersLastNDays`, `pullFollowerDemographics` — the API
     calls.
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
   - `pullAccountProfileViewsLastNDays` pulls `profile_views` — confirmed live that this metric is
     "total value" only on this API: a plain `period=day` request returns an empty data array with no
     error, so it requires `metric_type=total_value` and returns one pre-summed number rather than a
     daily list to add up, unlike `reach`.
   - `pullAccountViewsLastNDays` pulls `views` — **not the same metric as `profile_views`**, despite the
     similar name. `views` is total content plays (reels/posts/stories combined) and is what the
     Instagram app's own account-insights "Views" figure refers to; `profile_views` is specifically
     profile-page visits, a much smaller number. Confirmed live both are real, distinct metrics on this
     account (profile views ~16K vs. content views ~1.36M over the same 30-day window) — a user
     comparing the app's "Views" against this site's old profile-views-only tile is why this metric got
     added. Same `metric_type=total_value` shape as `profile_views`.
   - `pullNetFollowersLastNDays` pulls `follows_and_unfollows` with `breakdown=follow_type` and returns
     `FOLLOWER - NON_FOLLOWER` (new follows minus unfollows/account deletions) — matching the "Net
     followers" figure Instagram's own app shows on its Insights overview screen. (An earlier version of
     this returned just the `FOLLOWER` count as "new followers," which a user caught by comparing
     against a screenshot of the app: the app's own number is explicitly net, not gross new follows —
     confirmed live that `FOLLOWER - NON_FOLLOWER` lines up closely with the app's reported figure for
     the same window, small gaps expected purely from pull-timing.) This is a real API window total,
     unlike comparing the point-in-time follower count between two pulls (close to meaningless when
     pulls are only hours apart rather than a full window).
   - `pullFollowerDemographics(accessToken, userId, breakdown)` pulls the `follower_demographics`
     metric — also `metric_type=total_value`, `period=lifetime` (a current-snapshot value, not a
     day-window one). `breakdown` accepts `"age,gender"` (combined), `"country"`, or `"city"`; confirmed
     live that all three work on this account. Returns a list of `{"dimensionValues": [...], "value"}`
     — `dimensionValues` order matches the requested breakdown fields (e.g. `["25-34", "F"]` for
     `"age,gender"`).
   - `calculateEngagementRate` = (likes + comments) / followers, as a percentage.
   - Note: `total_interactions` is the correct current metric name — `engagement` is not a valid
     field.
   - `mediaFields` (used by both `pullMostRecentPosts` and `pullMediaSinceDate`) includes
     `media_url,thumbnail_url` so the frontend can render real post thumbnails — see
     `buildPostRecord`'s `thumbnailUrl` below.
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
   - `buildPostRecord`'s `thumbnailUrl` is `mediaItem.get("thumbnail_url") or mediaItem.get("media_url")`
     — Reels/videos only populate `thumbnail_url`, photos/carousels populate `media_url` directly, so
     the fallback picks whichever the media type actually returns. **Known risk, confirmed
     acceptable**: these Graph API URLs are signed and expire — verified live that current-pull URLs
     load fine, but older snapshots' stored URLs will eventually 404. The frontend handles this (see
     Frontend section) by dropping the broken image rather than showing a broken-image icon; the grid
     only ever renders the *latest* snapshot's posts anyway, so this only bites if the site goes
     unpulled for a long stretch.
   - For the account-level reach / profile-views / content-views / new-followers calls (which each need
     a since/until range, not a post count or date), `"days"` mode uses `pullValue` directly; `"date"`
     mode computes days between `cutoffDate` and now; `"posts"` mode estimates the span via
     `daysSpannedByPosts` (days between the oldest pulled post and now). The same window is used for all
     four calls; the actual value is stored per-metric as `accountReachWindowDays` /
     `profileViewsWindowDays` / `viewsWindowDays` / `netFollowersWindowDays` so it's always traceable per
     snapshot.
   - `buildPulledSetSummary` aggregates totals across the pulled set, tagged with `pullMode` and
     `pullValue` so each snapshot is self-describing. Stored under the `pulledSetSummary` key. (Older
     entries predating this change use `recentWindow` or `last30Days` instead — the dedup check in
     `isDuplicateOfLastSnapshot` treats these as distinct from current-schema snapshots, which is
     correct since the schema differs.)
   - `buildAudienceDemographics` pulls all three `pullFollowerDemographics` breakdowns and reshapes
     each into a clean list (`ageGender`, `country`, `city`), stored under the snapshot's
     `audienceDemographics` key — separate from `pulledSetSummary` since it's account-lifetime data,
     not scoped to the pull's day window/post count.
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
  `pulledSetSummary` / `recentWindow` / `last30Days` is present, so old-schema entries still render;
  `audienceDemographics` passes through as-is, `null` for older entries that predate it), then renders
  a masthead (avatar photo, username, `formatAccountType()`-title-cased account type, following/posts/
  followers counts) plus two tabs — see Filters and Tabs below.
- **Three tabs** (`#tabBtnOverview` / `#tabBtnAudience` / `#tabBtnCollabs`, plain `hidden`-attribute
  show/hide via `setupTabs()`, no routing): **Overview** is everything described below under Filters;
  **Audience** renders the latest pull's `audienceDemographics` once at boot (not re-scoped by the time
  range filter, which only governs the Overview tab, since demographics are a lifetime/current-snapshot
  value, not a day-window one) — a hand-rolled SVG grouped bar chart (`renderAgeGenderChart`, age
  bracket × gender, 3-series categorical with legend + per-bar hover tooltip) plus two `renderRankList`
  calls (top 8 countries via `formatCountryName()`'s ISO code lookup, top 8 cities) sharing one ranked
  list-with-proportional-bar component rather than a second chart type; **Collabs** is entirely static
  placeholder content in `index.html` (rate card, "what's included," contact details) — not
  data-driven, not touched by `dashboard.js` at all beyond the tab show/hide. Every value that needs
  replacing before sharing the page externally is marked `PLACEHOLDER` (rates, email, turnaround times)
  — search `index.html` for that string to find them all.
- The masthead avatar is a static file at `assets/profile.jpg` (not pulled from the API — Instagram's
  Graph API doesn't expose a fetchable profile picture URL for this product), referenced directly in
  `index.html`. Replace that file to change the photo; no code change needed. It renders inside
  `.avatar-ring` (padding trick: gradient background peeking out as a ring) rather than having a
  gradient border directly, since `border` can't take a gradient value without `border-image` hacks.
  Carries its own `box-shadow` (a soft `--brand-glow` bloom plus a tight dark contact shadow) so it
  reads as the masthead's visual anchor rather than sitting flush with the page.
- **Manrope** (self-hosted, weights 700/800 only) is used for headings/display text (`.masthead h1`,
  `.section-heading h2`, `.card-head h2`, `.print-only-heading`, `.stat-value`) — body text stays on
  the default system font stack. `.card-head h2`/`.stat-value` were bumped from their original 600
  weight to 700 to actually land inside Manrope's declared 700–800 range (a weight outside a
  `@font-face`'s declared range falls through to the next font in the stack instead of synthesizing
  bold). Two woff2 files live at `assets/fonts/` (`manrope-latin.woff2`, `manrope-latin-ext.woff2`) —
  downloaded once from Google Fonts' CSS2 API rather than linked live, keeping the "no CDN dependency"
  rule intact; confirmed live that Google serves the *same* variable-font file for both the 700 and
  800 static weights per subset, so `font-weight: 700 800` on one `@font-face` per subset covers both
  without needing four separate files.
- Three surface tiers, not two: `--page-plane` (saturated pink, the body background), `--surface-1`
  (off-white, top-level cards), `--surface-2` (pale pink, nested chips *inside* an off-white card —
  post cards in the Top Posts grid, rate-card items in Collabs). Using page-plane pink again for those
  nested chips would have made them blend into the page instead of reading as "inside" the card.
- An explainer card (`.explainer` in `index.html`, right below the masthead, above the tab nav so it's
  visible on all three tabs) holds Beth's own bio — who she is, what she posts about, what brands she
  will/won't collab with — supplied by the account owner, not generic dashboard-usage copy. Static
  content, not data-driven. (An earlier version of this card explained how to read the dashboard
  instead; that copy was tried, then explicitly reverted in favor of the bio.)
- **Layout is split by what's actually filterable**, so a filter control always sits directly above the
  content it scopes rather than floating above the whole page implying it controls everything:
  - `#kpiRowFixed` (Followers, Net followers, Views, Account reach, Profile views) renders once at boot
    via `renderFixedKpiRow()` and never changes with the filter — these are point-in-time/fixed-window
    API values a client-side date filter can't meaningfully reslice. It sits directly under the
    masthead, with no filter control anywhere near it. The four window-based tiles (everything except
    Followers itself) share one `buildWindowedStatTile()` helper for the "As pulled, last N days" label
    + delta pattern, rather than repeating it per tile; its `signed` param prefixes a `+` on positive
    values for net-change metrics (used for Net followers only — the other three are magnitudes, not
    deltas).
  - The `#rangeSelect` (`Time range`: 1/5/7/30 days — no "all time" option, since it would just show
    the same 30 days every time; capped at 30 to match the workflow's default pull window, see Storage
    & automation) lives in a `.section-heading` labeled "Performance trends", positioned immediately
    above the one block of content it actually scopes:
    `#kpiRowFiltered` (Engagement rate, Total interactions, via `renderFilteredKpiRow()`) and both trend
    charts. It filters which *history snapshots* feed the charts, and which of the latest snapshot's own
    posts (by each post's own `timestamp`) feed the filtered KPI tiles and the top-posts grid. It can
    never surface posts older than what the last pull actually collected — a wide range just means
    "show everything that was pulled."
  - `computeAggregateFromPosts()` recomputes engagement rate / interactions client-side from the
    range-filtered raw post records, rather than trusting a snapshot's pre-computed `pulledSetSummary`
    (which reflects whatever pull mode was used at collection time, not the viewer's selected range).
  - `#topNSelect` (`Show top`: 5/10/15/25/all posts) lives inside the Top Posts card's own header
    (`.posts-card-head`), next to that card's title, since it only ever affects that one grid — how
    many cards render, not a data scope.
  - `renderDashboard(fullHistory, rangeValue, topN)` is the single function both selects' `change`
    listeners call; it re-renders the filtered KPI row, both charts, and the posts grid together so
    they can never disagree with each other.
- The charts and posts grid are hand-rolled SVG/DOM, not a library: two line charts (follower growth,
  engagement rate over time — with a hover crosshair + tooltip, and a direct end-label on the latest
  point, clamped so it can never render above the chart card), and a top-posts grid (range-filtered
  posts, sorted by `engagementRate` descending, capped at the selected top-N, linking out to the real
  permalink).
- Post cards show a real thumbnail (`.post-thumb`, an `<img>` bled to the card's edges via negative
  margins matching `.post-card`'s own padding) when `post.thumbnailUrl` is present — falls back to the
  original text-only card layout for older snapshots pulled before this field existed (falsy check,
  no schema migration needed). Since Instagram's media URLs are signed and expire (see
  `buildPostRecord` above), the `<img>` has an `onerror` handler that removes itself rather than
  showing a broken-image icon — a graceful downgrade to the text-only card, not an error state.
  Hidden entirely in `@media print` (`.post-thumb { display: none; }`) rather than shrunk — four extra
  images per row risked blowing the tuned one-page-per-tab PDF layout, and a printable media kit reads
  fine as text-only.
- Charts render an empty-state message instead of a broken chart when there are fewer than 2 history
  points (true for a freshly-started history) — `renderLineChart` checks `points.length < 2` first.
- **Light-only, pink-based (no dark-mode toggle)** — deliberate, per the brand aesthetic above, not an
  oversight. This replaced an earlier dark theme; the account owner supplied a reference media-kit
  screenshot (pink background, off-white boxes, black text) and asked to match it. Chart/data colors
  are the dataviz skill's validated **light-mode** palette (not a straight recolor of the old dark-mode
  set — light backgrounds need different lightness/contrast): series blue `#2a78d6`, orange `#eb6834`,
  aqua `#1baf7a`, good/bad deltas `#006300`/`#c0392b`, chart surface `#fdf6f3` on page plane `#f6c9d8`.
- **`--brand-gradient`** (a CSS var approximating a pink/rose brand gradient, light pink → deep rose)
  is reserved for decorative chrome only — the avatar ring, the primary CTA buttons (`.btn-gradient`),
  the tab underline, and the explainer card's accent border. It is never used on anything that encodes
  data (chart marks, KPI values, rank-list bars all stay on the validated dataviz palette above) —
  mixing a decorative gradient into data encoding would break the "never a rainbow" categorical-color
  rule the dataviz skill enforces elsewhere on this page. Rate-card prices (`.rate-price`) use a
  **separate**, more saturated two-stop gradient (`linear-gradient(90deg, #ec6a9c, #a83368)`) rather
  than `--brand-gradient` directly — `--brand-gradient`'s pale starting stop reads too low-contrast as
  small `background-clip: text`, which matters more for actual pricing text than for a large button.
  `.post-type` used the same gradient as clipped text originally, but was switched to a solid filled
  pill badge in that gradient (background, not `background-clip: text`) — a repeated small metadata
  tag read a little soft/"influencer aesthetic" as transparent-fill gradient text at 10-11px, and a
  filled badge is the more standard professional-dashboard affordance for that role; the gradient stays
  reserved for hero content like the price.
- **Elevation**: every card-like surface (`.card`, `.stat-tile`, `.post-card`, `.rate-item`,
  `.explainer`) carries `--shadow-resting` normally and lifts to `--shadow-hover` (`translateY(-2px)`
  + a stronger shadow) on hover — added after the original flat-bordered-box treatment read as
  underdesigned/wireframe-y rather than a finished dashboard; a soft ink-tinted shadow (not black, to
  stay warm on the pink page) gives the page actual depth. Explicitly `box-shadow: none !important` in
  `@media print` — shadows print as muddy smudges rather than rendering as light, so the border alone
  carries surface definition on paper.
- The two masthead timestamp lines (`#asOf`, `#pageUpdatedAt`) are a related pair ("data pulled at X,
  page deployed at Y"), so they sit close together with the larger gap reserved for after the pair,
  before the unrelated explainer card — `#asOf:has(+ #pageUpdatedAt:not([hidden]))` tightens `#asOf`'s
  own bottom margin only when the second line will actually render, so a failed `renderPageDeploymentTime()`
  lookup (which leaves `#pageUpdatedAt` `hidden`) doesn't leave too little space before the explainer.
- Tab switches trigger a short fade/slide-in (`.tab-panel-enter`, re-triggered on every click via a
  remove-reflow-readd cycle in `setupTabs()`) rather than an instant `hidden` toggle — purely cosmetic
  polish, doesn't change what's shown.
- Tab buttons (`.tab-btn`) are bordered pills, not an underline-only style — bigger hit target and more
  visually obvious than a thin underline, per explicit feedback that the original underline tabs were
  too easy to miss. The active tab fills solid with `--brand-gradient` and white text rather than just
  changing an indicator line.
- **PDF export** (`#downloadPdfBtn` in the masthead, `.no-print`) calls `window.print()` — no PDF
  library, no server, just the browser's native print-to-PDF via a dedicated `@media print` block in
  `dashboard.css`. That block: forces all three tab panels visible (`display: block !important`,
  overriding the `hidden` attribute `setupTabs()` uses on screen) with `break-before: page` between
  them, so the export is one complete document covering Overview/Audience/Collabs regardless of which
  tab was open when the button was clicked, not just a snapshot of the current view; adds a
  `.print-only-heading` per panel (hidden on screen, since the tab nav already labels each panel there)
  so each section is still identifiable once the tab nav itself is hidden for print; and
  `break-inside: avoid` on cards/tiles so a stat tile or post card doesn't split across a page
  boundary.
  - **Print gets its own visual treatment, not the screen theme with color-adjust forced on.** An
    early version just forced the screen's saturated pink page-plane to print — technically on-brand,
    but the empty leftover space below shorter sections rendered as large flat pink voids that read as
    unfinished rather than professional (explicit user feedback). Fixed by overriding
    `--page-plane`/`--surface-1`/`--surface-2`/`--border` to white/near-white **inside** the
    `@media print` block (cascades through every component automatically, since they're all written
    against those custom properties rather than hardcoded colors) — pink is kept only as small accents
    (explainer left-bar, rate-price/post-type text, the print-only headings), plus
    `print-color-adjust: exact` so those accents and the chart colors still actually print (browsers
    strip background colors/gradients by default).
  - **Landscape + aggressive compaction**, aiming to fit each tab in as few pages as its content
    allows rather than the screen's touch-friendly sizing: `@page { size: A4 landscape; }`, and a large
    block of print-only overrides shrinking font sizes, padding, and gaps across every component
    (`.stat-tile`, `.card`, `.post-card`, `.rate-item`, `.rank-item`, etc.) well below their on-screen
    values. The Time range `<select>` is hidden in print (a live dropdown looks out of place in a
    static document) and replaced by a `.print-only-value` paragraph populated from the select's
    current selection via a `beforeprint` listener in `dashboard.js` (`setupPdfDownload()`) — plain
    text of the actual value, not a non-functional control. The age/gender bar chart (`#ageGenderChart
    svg`) gets an explicit `max-width` in print specifically — as the one full-width standalone chart
    (not a 2-up grid like the trend charts), its fixed aspect ratio otherwise renders it tall enough at
    full landscape width to push the two rank-list cards below it onto a second page.
  - Verified end-to-end with headless Chromium's `page.pdf()` across iterations: 7 pages → 5 (surface
    color + compaction) → 4 (age/gender chart cap) — Overview 2pp (by far the most content: 7 KPI
    tiles, 2 charts, 10 post cards), Audience 1pp, Collabs 1pp.
- **Two separate timestamps under the masthead**, deliberately not merged into one - they answer
  different questions and are always somewhat apart in practice:
  - `#asOf` ("Data last pulled on…") is `latest.pulledAt` from the fetched history - when
    `pullData.py` actually ran.
  - `#pageUpdatedAt` ("Page last updated on…") is when GitHub Pages *finished redeploying* that data,
    fetched client-side from GitHub's public Actions API (`renderPageDeploymentTime()`): a data pull
    commits `statsHistory.json`, which *triggers* the `pages-build-deployment` workflow, but that
    deployment then takes its own ~30–90s (observed up to ~30min under queue load) to actually finish
    and go live - conflating the two read as flatly wrong the one time a user actually checked (the
    page said "updated" at the pull time, while the visible data had in fact gone live half an hour
    later). Two API calls, chained: `pages-build-deployment`'s numeric workflow id isn't something to
    hardcode, so it's resolved by name via `/actions/workflows` first, then its latest successful run
    is fetched via `/actions/workflows/{id}/runs?status=success`. Public unauthenticated GitHub REST
    calls are CORS-enabled and need no token, but are rate-limited to 60/hour per IP - acceptable for a
    low-traffic media kit; on any failure (rate limit, network) `#pageUpdatedAt` just stays `hidden`
    rather than showing an error, since this is read-only decoration, not core content.
- Live at `https://kelstudy.github.io/DiaryOfBeth/` via GitHub Pages (Settings → Pages → Deploy from
  branch → `main` / `(root)`).

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
    `token.json`. Written out on the runner before calling `scripts/refreshToken.py`/`scripts/pullData.py`;
    nothing token-related ever gets committed (`git add` in the workflow only stages
    `data/statsHistory.json`).
  - **Requires a second repo secret named `GH_PAT`** — a GitHub Personal Access Token with permission
    to write Actions secrets on this repo, used by the `gh secret set` step to persist the refreshed
    token back into `INSTAGRAM_TOKEN_JSON`. This is the one piece of setup that can't be automated away
    (a workflow can't grant itself permission to modify repo secrets) — a one-time manual step, not an
    ongoing one.
  - If both secrets are set correctly and the daily cron keeps running, no manual token maintenance
    should ever be needed again. If the workflow ever stops running for longer than the refresh window
    (~60 days) — repo archived, Actions disabled, etc. — the token will lapse and
    `scripts/getAccessToken.py` will need to be run by hand to re-establish it from scratch.

## Open items / known gaps

- **Security**: an earlier access token was exposed in a chat session and has since been rotated via
  `scripts/getAccessToken.py`.
- Trial reels (Instagram creates several distinct REELS media IDs per trial reel upload, seconds
  apart) show up as separate posts in pulls, inflating post counts and stats. A timing-based filter
  (collapsing REELS posted within 60s of each other) was tried and reverted — it risked dropping
  legitimate posts made in quick succession, since no API field reliably distinguishes trial reels
  from real ones (`is_shared_to_feed` was tested and ruled out). `scripts/inspectMedia.py` remains in
  the repo
  as a diagnostic. Planned approach instead: tag trial-reel captions manually going forward and filter
  on that tag, once there's a labeled example to build against.
