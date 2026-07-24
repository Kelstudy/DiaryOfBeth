# DiaryOfBeth

A self-updating Instagram media kit for [@thediaryofbeth](https://instagram.com/thediaryofbeth).

Live site: **https://kelstudy.github.io/DiaryOfBeth/**

Every day, a GitHub Actions workflow pulls fresh stats from the Instagram Graph API — follower growth,
engagement rate, top posts, audience demographics — and appends them to a JSON history file. The site
reads that file and renders it client-side. No manual copying numbers into a deck, no server to
maintain, no cost.

## How it fits together

```
scripts/            Python data-collection pipeline (see below)
data/statsHistory.json   Append-only history of daily snapshots — what the site actually reads
index.html           The dashboard page (must stay at repo root — see note below)
assets/              Dashboard CSS/JS + the profile photo
.github/workflows/   The daily automation
```

**`scripts/`** — run from the repo root (`python scripts/<name>.py`), not from inside the folder,
since they read/write `token.json` and `data/` relative to the working directory:

| Script | What it does |
|---|---|
| `getAccessToken.py` | One-time interactive login — produces `token.json`. Run this first. |
| `refreshToken.py` | Non-interactive token refresh, run automatically by the daily workflow. |
| `igApi.py` | All the Instagram Graph API calls, imported by the others. |
| `pullData.py` | The actual collector — pulls stats and appends a snapshot to `data/statsHistory.json`. |
| `inspectMedia.py` | One-off diagnostic, not part of the automated pipeline. |

**Why `index.html` lives at the repo root, not in a subfolder:** GitHub Pages serves one folder as
the site root, and the dashboard fetches `data/statsHistory.json` via a relative path at runtime. Both
have to be reachable from the same origin, so moving the page into a subfolder would break that fetch
unless the data were duplicated into it too.

## Setup

```
pip install -r requirements.txt
```

Requires a `.env` file (gitignored, never commit) with your Instagram app credentials:
```
INSTAGRAM_APP_ID=your_app_id
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_REDIRECT_URI=https://localhost/
```

Then:
```
python scripts/getAccessToken.py    # one-time login, produces token.json
python scripts/pullData.py          # pull stats, interactive prompts for the pull window
```

Full architecture, API quirks discovered along the way, and the reasoning behind various decisions are
documented in [CLAUDE.md](CLAUDE.md) — worth reading before making changes.

## Automation

`.github/workflows/pull-stats.yml` runs daily: refreshes the access token, pulls the latest stats,
commits `data/statsHistory.json` if anything changed. Requires two repo secrets
(`INSTAGRAM_TOKEN_JSON`, `GH_PAT`) — see CLAUDE.md's "Storage & automation" section for what they're
for and how to set them up.
