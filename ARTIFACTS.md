# Event Artifacts System

## Overview

Upload screenshots or saved web pages of event listings and Claude's vision API automatically extracts event information. Works with any source — Instagram, venue websites, posters, Bandsintown.

## How It Works

1. **Screenshot/photo any event listing** (Instagram, website, poster, etc.)
2. **Upload via Admin UI** (Import section in Events tab)
3. **Claude vision extracts:** artist, venue, date, time
4. **Preview and confirm** — events are saved to the database

## Supported Sources

- **Instagram screenshots** — Bar DKDC, B-Side posts
- **Website screenshots** — Venue event pages
- **Bandsintown screenshots** — Regional listings
- **Photos of posters** — Flyers around town
- **Saved web pages** (HTML/MHTML) — Parsed directly with BeautifulSoup
- **Any concert listing image**

## Upload Workflow

### Via Admin UI (recommended)
1. Go to Admin -> **Events** tab -> **Import** section
2. Drop image or HTML files onto the upload area
3. Files are committed to `artifacts/` in the GitHub repo
4. Go to **Scrapers** tab -> click **"Run Scrapers"**
5. Wait ~2 minutes — Claude reads the images and adds events

### Via `/upload.html` (simpler, works from phone)
1. Visit `/upload.html` on the Vercel deployment
2. Enter the upload password
3. Select files and upload
4. Click "Rebuild Calendar" or wait for the next daily run

## What Gets Extracted

Claude vision reads each image and extracts:
- **Artist/Act name** — Who's performing
- **Venue** — Where (or source context like "Bar DKDC Instagram")
- **Date** — When (any format)
- **Time** — What time (if visible)

Multiple events per image are extracted automatically.

## Tips

1. **Clear images work best** — good lighting, readable text
2. **Crop to relevant section** — full screenshots work too, but cropping improves accuracy
3. **Multiple events per image is fine** — Claude extracts all of them
4. **Large images are auto-resized** — files over 3MB are resized before sending to Claude vision (max ~1024x2048)
5. **Artifacts auto-clean** — files in `artifacts/` older than 24 hours are deleted by the daily build
6. **Verify results** — check the admin Events tab after import, fix any errors inline

## File Naming

Any naming works, but descriptive names help your records:
```
2026-02-10-bside-instagram.png
bar-dkdc-2026-02-11-post.jpg
histone-events-page.png
poster-photo-2026-02-10.jpg
```

## Troubleshooting

**No events extracted from image?**
- Verify file is a supported format: .png, .jpg, .jpeg, .gif, .webp
- Try a clearer or larger image
- Check that `ANTHROPIC_API_KEY` is set in GitHub Secrets

**Wrong dates/venues extracted?**
- Claude does its best with unclear text
- Fix errors in the admin UI (Events tab -> click to edit)

**Missing events from a multi-event image?**
- Claude vision targets ~90% accuracy
- Add missing events manually via admin UI (+ Add Event)

## Cost

- Claude vision API: ~$0.01 per image
- Weekly workflow (5-10 images): ~$0.05-0.10/week
- **Monthly: ~$0.20-0.40**

## Running Locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your_key"

# Add images to artifacts/ folder, then:
python -m src.main --dry-run   # Preview
python -m src.main             # Full run
```
