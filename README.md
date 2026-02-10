# WYXR Memphis Concert Calendar 🎵

A daily-updating live music calendar for Memphis, Tennessee. Built for [WYXR 91.7 FM](https://wyxr.org) DJs to reference on-air.

**Live page:** [wyxr-memphis.github.io/concert-calendar](https://wyxr-memphis.github.io/concert-calendar)      

## How It Works

A Python script runs every morning at 5 AM Central via GitHub Actions. It pulls event data from multiple sources, filters to music/DJ events only, removes duplicates, and publishes a clean static HTML page to GitHub Pages.

### Sources (checked daily)

| Source | Method | Reliability |
|--------|--------|-------------|
| Ticketmaster | API | ⭐⭐⭐ High |
| Eventbrite | API | ⭐⭐⭐ High |
| Bandsintown | Web scrape | ⭐⭐ Medium |
| DICE | Web scrape | ⭐⭐ Medium |
| Memphis Flyer | Web scrape | ⭐⭐ Medium |
| Venue websites | Web scrape | ⭐ Varies |
| Google Sheet (manual) | Published CSV | ⭐⭐⭐ High |

### Venues tracked

Hi Tone, Minglewood Hall, Growlers, Hernando's Hideaway, Crosstown Arts/Green Room, Lafayette's Music Room, Overton Park Shell, B.B. King's, Graceland Soundstage, FedExForum, and more.

Instagram-only venues (Bar DKDC, B-Side Memphis, etc.) are added manually via the shared Google Sheet.

## Setup

### 1. Enable GitHub Pages

1. Go to repo **Settings → Pages**
2. Set Source to **Deploy from a branch**
3. Set Branch to **main**, folder to **/docs**
4. Save — your site will be live at `wyxr-memphis.github.io/concert-calendar`

### 2. Get API Keys (free)

**Ticketmaster (highest priority — best Memphis coverage):**
1. Go to [developer.ticketmaster.com](https://developer.ticketmaster.com)
2. Create an account and get a Consumer Key
3. Add as GitHub secret: `TICKETMASTER_API_KEY`

**Eventbrite:**
1. Go to [eventbrite.com/platform/api-keys](https://www.eventbrite.com/platform/api-keys)
2. Create a private API token
3. Add as GitHub secret: `EVENTBRITE_API_TOKEN`

**Bandsintown (optional):**
1. Go to [artists.bandsintown.com](https://artists.bandsintown.com) and sign up
2. Request an API app ID
3. Add as GitHub secret: `BANDSINTOWN_APP_ID`

### 3. Set Up Google Sheet (for manual events)

This is the simplest approach — no API keys needed for the sheet itself.

1. Create a Google Sheet with these columns in Row 1:
   ```
   date | artist | venue | time | source_note
   ```
2. Use any date format (MM/DD/YYYY, YYYY-MM-DD, Feb 15, etc.)
3. The `time` and `source_note` columns are optional
4. Go to **File → Share → Publish to web**
5. Select the sheet tab → choose **CSV** format → click **Publish**
6. Copy the published CSV URL
7. Add as GitHub secret: `GOOGLE_SHEET_CSV_URL`

**Example sheet rows:**
| date | artist | venue | time | source_note |
|------|--------|-------|------|-------------|
| 2/14/2026 | DJ Night | Bar DKDC | 10 PM | Instagram post 2/10 |
| 2/15/2026 | Local Band | B-Side Memphis | | spotted on IG |
| 2/16/2026 | House Show | Midtown TBA | 7 PM | flyer on telephone pole |

### 4. Add GitHub Secrets

Go to repo **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Value | Required? |
|------------|-------|-----------|
| `TICKETMASTER_API_KEY` | Your Ticketmaster consumer key | **Yes** (start here) |
| `EVENTBRITE_API_TOKEN` | Your Eventbrite private token | Recommended |
| `BANDSINTOWN_APP_ID` | Your Bandsintown app ID | Optional |
| `GOOGLE_SHEET_CSV_URL` | Published CSV URL from your sheet | Recommended |

### 5. Test It

Trigger a manual run:
1. Go to **Actions** tab in the repo
2. Click **Daily Concert Calendar Update**
3. Click **Run workflow**
4. Check the run logs and then visit your GitHub Pages URL

## Manual Events

For venues that only post shows on Instagram (Bar DKDC, B-Side, etc.):

1. Open the shared Google Sheet
2. Add a row with: `date`, `artist`, `venue`, `time`, `source_note`
3. The next daily run will include these events automatically

You can also use `manual_events.csv` in the repo as a fallback.

## Troubleshooting

### Check the error log

After each run, check:
- **GitHub Actions** tab → latest run → see console output
- `docs/log.json` — machine-readable source status with per-source details
- The **SOURCE NOTES** section at the bottom of the live page

### Common issues

| Problem | Cause | Fix |
|---------|-------|-----|
| "0 events found" from a venue | Site changed its HTML structure | Open the venue URL, inspect HTML, update the scraper in `src/sources/venue_scrapers.py` |
| "No API key configured" | Missing GitHub secret | Add the secret in Settings → Secrets |
| Page not updating | GitHub Action failed | Check Actions tab for error details |
| Duplicate events showing | Different name formatting across sources | Add aliases to `VENUES` dict in `src/config.py` |

## Adding a New Venue

1. Add the venue to the `VENUES` dict in `src/config.py` — include `name`, `aliases`, `calendar_url`, and `scraper` type
2. The generic scraper will try JSON-LD and common DOM patterns automatically
3. If the generic scraper doesn't work, you can add a custom parser in `src/sources/venue_scrapers.py`
4. For Instagram-only venues, set `scraper: "manual_only"` and add events via the Google Sheet

## Project Structure

```
concert-calendar/
├── .github/workflows/
│   └── daily.yml              # GitHub Actions daily schedule
├── src/
│   ├── main.py                # Orchestrator — runs everything
│   ├── config.py              # Venues, keywords, settings
│   ├── models.py              # Event and SourceResult data models
│   ├── normalize.py           # Deduplication logic
│   ├── generate_html.py       # Static page generator
│   └── sources/
│       ├── ticketmaster.py    # Ticketmaster Discovery API
│       ├── eventbrite.py      # Eventbrite API
│       ├── bandsintown.py     # Bandsintown city page scraper
│       ├── dice.py            # DICE browse page scraper
│       ├── memphis_flyer.py   # Memphis Flyer calendar scraper
│       ├── venue_scrapers.py  # Individual venue website scrapers
│       └── google_sheet.py    # Manual events from Google Sheet CSV
├── docs/
│   ├── index.html             # Published page (auto-generated)
│   └── log.json               # Latest run log (auto-generated)
├── manual_events.csv          # CSV fallback for manual events
├── requirements.txt
└── README.md
```

## Future Plans

- **User submission form** — a public form where anyone can submit events for approval before they appear on the calendar
- **Email/Slack digest** — option to push the daily list to a Slack channel or email list
- **Better dedup** — fuzzy matching improvements for artist name variations
- **More venues** — continuously expanding the venue list

## Cost

**$0/month.** GitHub Actions, GitHub Pages, and all APIs used are free tier.

## Run Locally

```bash
# Clone and install
git clone https://github.com/wyxr-memphis/concert-calendar.git
cd concert-calendar
pip install -r requirements.txt

# Set API keys (get at least Ticketmaster)
export TICKETMASTER_API_KEY="your_key_here"

# Dry run — prints results without writing files
python -m src.main --dry-run

# Full run — generates docs/index.html
python -m src.main
```

## License

Internal tool for WYXR 91.7 FM. Built with 🎶 in Memphis.
