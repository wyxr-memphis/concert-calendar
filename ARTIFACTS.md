# Event Artifacts System

## Overview

Instead of trying to scrape websites that change frequently, you can now collect **images/screenshots** of event listings and let Claude's vision API automatically extract the event information.

## How It Works

1. **You collect artifacts** (screenshots, photos, etc.)
2. **Drop them in the `artifacts/` folder**
3. **The script reads them** and extracts events using Claude vision
4. **Events auto-populate** into your calendar

## Artifact Types

✅ **Instagram screenshots** — Bar DKDC, B-Side posts
✅ **Website screenshots** — Venue calendar pages
✅ **Photos of posters** — Physical flyers you see around town
✅ **PDF/image exports** — Event listings from any source

## Folder Structure

```
artifacts/
├── bside/           # B-Side Memphis (Instagram screenshots)
├── bar-dkdc/        # Bar DKDC (Instagram screenshots)
├── histone/         # Hi Tone (website screenshots)
├── minglewood/      # Minglewood Hall (website screenshots)
├── lafayettes/      # Lafayette's (website screenshots)
└── other/           # Other sources
```

## Weekly Workflow (15 mins)

**Monday morning:**

1. **B-Side Memphis** → Instagram → Screenshot upcoming events → Save to `artifacts/bside/`
2. **Bar DKDC** → Instagram → Screenshot upcoming events → Save to `artifacts/bar-dkdc/`
3. **Hi Tone** → Website → Screenshot events section → Save to `artifacts/histone/`
4. **Minglewood** → Website → Screenshot events section → Save to `artifacts/minglewood/`
5. **Lafayette's** → Website → Screenshot events section → Save to `artifacts/lafayettes/`

Then when you run the script, it automatically extracts events from all images.

## File Naming (Optional)

Naming doesn't matter, but helpful names are good for your records:
```
2026-02-10-bside-instagram.png
2026-02-11-bar-dkdc-post.jpg
events-page-histone.png
```

## What Gets Extracted

Claude vision reads each image and extracts:
- **Artist/Act name** — Who's performing
- **Venue** — Where it is
- **Date** — When (any format)
- **Time** — What time (if visible)
- **Source note** — "Instagram post", "website screenshot", etc.

## Example: Instagram Screenshot

**You take a screenshot of B-Side's Instagram showing:**
```
ABERRANT
Sat Feb 15 @ 9PM
B-Side Memphis
```

**Claude extracts:**
```json
{
  "artist": "ABERRANT",
  "venue": "B-Side Memphis",
  "date": "2/15/2026",
  "time": "9 PM",
  "source_note": "Instagram screenshot"
}
```

**Result:** Event auto-added to your calendar.

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Add artifacts to artifacts/ folder
# Then run:
python -m src.main --dry-run

# Or full run:
python -m src.main
```

## GitHub Actions

When you set up GitHub Actions, add your Anthropic API key as a secret:

```
Settings → Secrets and variables → Actions → New repository secret
Name: ANTHROPIC_API_KEY
Value: [your API key from console.anthropic.com]
```

Then the daily workflow will automatically process artifacts every morning.

## Cost

- Claude's vision API costs ~$0.01 per image
- Weekly workflow (5-10 images) = ~$0.05-0.10/week
- **Total: ~$0.20-0.40/month**

## Tips

1. **Clear images work best** — Good lighting, legible text
2. **Crop to the relevant section** — Full page screenshots work too, but crops are cleaner
3. **One venue per image is fine** — Or include multiple venues if they're on the same page
4. **Old artifacts get re-processed** — Delete old images after the week passes to keep fresh
5. **Verify the results** — Check `docs/log.json` to see what was extracted

## Troubleshooting

**No events found?**
- Check that images are in the `artifacts/` folder
- Make sure file extensions are .png, .jpg, .jpeg, .gif, or .webp
- Try a clearer/bigger image

**Wrong dates/times extracted?**
- Claude does its best with handwritten or unclear text
- Clearer images = better extraction
- Manually fix in Google Sheet if needed

**Runs out of order or missing events?**
- Claude vision isn't 100% perfect — if an event looks wrong, you can manually add it to Google Sheet
- This system is meant to catch ~90% of events automatically
- You verify the final output before publishing

## Future Enhancements

- Auto-delete processed artifacts after a week
- Email you extracted events for review before publishing
- Support for OCR on handwritten posters
- Integration with Slack to ask you about unclear events
