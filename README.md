# WYXR Memphis Concert Calendar

A daily-updating live music calendar for Memphis, Tennessee. Built for [WYXR 91.7 FM](https://wyxr.org) DJs to reference on-air.

**Live page:** [concert-calendar.vercel.app](https://concert-calendar.vercel.app) (or wherever your Vercel deployment lives)

## How It Works

A Python script runs every morning at 5 AM Central via GitHub Actions. It pulls event data from multiple sources, filters to music/DJ events only, removes duplicates, and publishes a clean static HTML page. Hosted on Vercel with a serverless upload API.

### Sources (checked daily)

| Source | Method | Notes |
|--------|--------|-------|
| Ticketmaster | API | Best coverage for major venues |
| DICE | Web scrape | Good for indie/electronic shows |
| Memphis Flyer | Web scrape | Local event listings |
| Venue websites | Custom scrapers | Hi Tone, Minglewood, Hernando's, Crosstown, GPAC |
| Artifacts (images/pages) | Claude Vision API + HTML parsing | Upload flyers or saved web pages |
| Google Sheet | Published CSV | Manual entries for Instagram-only venues |

### Venues tracked

**Scraped automatically:** Hi Tone, Minglewood Hall, Hernando's Hideaway, Crosstown Arts/Green Room, Germantown PAC, B.B. King's, FedExForum, Graceland Soundstage

**Manual entry via Google Sheet or artifact upload:** Bar DKDC, B-Side Memphis, Orpheum Theatre, Lafayette's Music Room, Overton Park Shell

## Architecture

```
GitHub Actions (daily 5 AM UTC)
  → Python fetches from all sources
  → Deduplicates events
  → Generates docs/index.html
  → Commits & pushes
  → Triggers Vercel redeploy

Vercel
  → Serves docs/index.html (calendar)
  → Serves docs/upload.html (upload form)
  → api/upload.py (serverless: commits artifacts to GitHub)
  → api/rebuild.py (serverless: triggers GitHub Actions rebuild)
```

## Setup

### 1. Deploy to Vercel

```bash
cd concert-calendar
vercel          # Link to the repo
vercel --prod   # Deploy
```

Set these environment variables in the Vercel dashboard:
- `UPLOAD_PASSWORD` — password for the upload form
- `GITHUB_PAT` — fine-grained PAT with `contents:write` scope for this repo

### 2. API Keys

Add these as GitHub Secrets (Settings → Secrets → Actions):

| Secret Name | Value | Required? |
|------------|-------|-----------|
| `TICKETMASTER_API_KEY` | Ticketmaster consumer key ([developer.ticketmaster.com](https://developer.ticketmaster.com)) | Yes |
| `GOOGLE_SHEET_CSV_URL` | Published CSV URL from your Google Sheet | Recommended |
| `ANTHROPIC_API_KEY` | Anthropic API key (for image artifact processing) | For image uploads |
| `VERCEL_DEPLOY_HOOK` | Vercel deploy hook URL (for auto-redeploy after builds) | Recommended |

### 3. Google Sheet (for manual events)

1. Create a Google Sheet with columns: `date`, `artist`, `venue`, `time`, `source_note`
2. Go to **File → Share → Publish to web** → select CSV → Publish
3. Add the published CSV URL as the `GOOGLE_SHEET_CSV_URL` GitHub secret

### 4. Test It

Trigger a manual run from the **Actions** tab → **Daily Concert Calendar Update** → **Run workflow**.

## Uploading Artifacts

Visit `/upload.html` on your Vercel deployment to upload event sources from any device (phone, laptop, etc.):

- **Images** (PNG, JPG, WebP, GIF) — flyers, screenshots of event listings. Processed by Claude Vision API.
- **Web pages** (MHTML, HTML) — saved venue calendars. Parsed directly with BeautifulSoup.

Uploaded files are committed to the `artifacts/` folder in the repo. Hit "Rebuild Calendar" to process them immediately, or wait for the next daily run. Artifacts older than 24 hours are automatically cleaned up.

## Adding a New Venue

1. Add the venue to `VENUES` in `src/config.py` with `name`, `aliases`, `calendar_url`, and `scraper` type
2. The generic scraper handles JSON-LD and common CMS patterns (Squarespace, WordPress Events Calendar, etc.)
3. If needed, add a custom parser in `src/sources/venue_scrapers.py`
4. For Instagram-only venues, set `scraper: "manual_only"` and use the Google Sheet or artifact upload

## Project Structure

```
concert-calendar/
├── .github/workflows/
│   └── daily.yml              # GitHub Actions daily schedule
├── api/
│   ├── upload.py              # Vercel serverless: artifact upload
│   ├── rebuild.py             # Vercel serverless: trigger rebuild
│   └── requirements.txt
├── src/
│   ├── main.py                # Orchestrator
│   ├── config.py              # Venues, keywords, settings
│   ├── models.py              # Event and SourceResult data models
│   ├── date_utils.py          # Shared date parsing
│   ├── normalize.py           # Deduplication logic
│   ├── generate_html.py       # Static page generator
│   └── sources/
│       ├── ticketmaster.py    # Ticketmaster Discovery API
│       ├── dice.py            # DICE browse page scraper
│       ├── memphis_flyer.py   # Memphis Flyer calendar scraper
│       ├── venue_scrapers.py  # Individual venue website scrapers
│       ├── google_sheet.py    # Manual events from Google Sheet CSV
│       └── artifacts.py       # Image + web page artifact processing
├── artifacts/                 # Uploaded files (auto-cleaned after 24h)
├── docs/
│   ├── index.html             # Published calendar (auto-generated)
│   ├── upload.html            # Upload form
│   └── log.json               # Latest run log
├── vercel.json                # Vercel config
├── requirements.txt
└── README.md
```

## Run Locally

```bash
git clone https://github.com/wyxr-memphis/concert-calendar.git
cd concert-calendar
pip install -r requirements.txt

export TICKETMASTER_API_KEY="your_key"

# Dry run — prints results without writing files
python -m src.main --dry-run

# Full run — generates docs/index.html
python -m src.main
```

## Cost

**$0/month** for hosting and APIs. GitHub Actions, Vercel free tier, and Ticketmaster API are all free. Only cost is Anthropic API usage for image artifact processing (pennies per image).

## License

Internal tool for WYXR 91.7 FM. Built in Memphis.
