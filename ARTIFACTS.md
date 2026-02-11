# Event Artifacts System

## Overview

Instead of scraping websites, you collect **screenshots/images** of event listings and Claude's vision API automatically extracts event information. Simple, flexible, and works with any source.

## How It Works

1. **Screenshot/photo any event listing** (Instagram, website, Bandsintown, poster, etc.)
2. **Drop image in `artifacts/` folder**
3. **Script runs** and Claude vision extracts: artist, venue, date, time
4. **Events auto-populate** into your calendar

## Super Simple Folder Structure

```
artifacts/
├── bside-2026-02-10.png
├── bar-dkdc-instagram.jpg
├── histone-events-page.png
├── bandsintown-memphis.png
└── any-other-listing.jpg
```

That's it! No subfolders. Claude figures out the venue from the image content.

## Supported Sources

✅ **Instagram screenshots** — Bar DKDC, B-Side posts
✅ **Website screenshots** — Venue event pages
✅ **Bandsintown screenshots** — Bandsintown Memphis listings
✅ **Photos of posters** — Flyers around town
✅ **Any concert listing** — Whatever format

## Weekly Workflow (10-15 mins)

**Monday morning:**

1. Instagram → B-Side upcoming events → Screenshot → Save to `artifacts/`
2. Instagram → Bar DKDC events → Screenshot → Save to `artifacts/`
3. Hi Tone website → Events page → Screenshot → Save to `artifacts/`
4. Minglewood website → Events page → Screenshot → Save to `artifacts/`
5. Lafayette's website → Music page → Screenshot → Save to `artifacts/`
6. (Optional) Bandsintown Memphis → Screenshot any regional events → Save to `artifacts/`

Then when you run the script, Claude automatically extracts events from all images.

## File Naming

Any naming works, but helpful names are good for your records:
```
2026-02-10-bside-instagram.png
bar-dkdc-2026-02-11-post.jpg
histone-events-page.png
bandsintown-memphis-week.png
poster-photo-2026-02-10.jpg
```

## What Gets Extracted

Claude vision reads each image and automatically extracts:
- **Artist/Act name** — Who's performing
- **Venue** — Where it is (or what source: "Bar DKDC Instagram", "Bandsintown", "Hi Tone website")
- **Date** — When (any format)
- **Time** — What time (if visible)

## Examples

### Example 1: Instagram Screenshot

**Image shows:**
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

### Example 2: Bandsintown Screenshot

**Image shows Bandsintown Memphis with multiple regional events**

**Claude extracts all of them** with venue as "Bandsintown" or the specific venue name if visible:
```json
[
  {
    "artist": "Some Band",
    "venue": "Minglewood Hall",
    "date": "2/14/2026",
    "time": "8 PM",
    "source_note": "Bandsintown screenshot"
  },
  ...
]
```

### Example 3: Venue Website

**Image shows Hi Tone events page with multiple listings**

**Claude extracts all events** with "Hi Tone" as venue:
```json
[
  {
    "artist": "Local Artist Name",
    "venue": "Hi Tone",
    "date": "2/16/2026",
    "time": "9 PM",
    "source_note": "Website screenshot"
  },
  ...
]
```

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Add image artifacts to artifacts/ folder
# Then run:
python -m src.main --dry-run

# Or full run:
python -m src.main
```

## GitHub Actions Setup

1. Get your API key from: https://console.anthropic.com/
2. Go to repo Settings → Secrets and variables → Actions
3. Add new secret:
   ```
   Name: ANTHROPIC_API_KEY
   Value: [your key from console.anthropic.com]
   ```
4. Done! Daily workflow will auto-process artifacts at 5 AM UTC

## Cost

- Claude's vision API: ~$0.01 per image
- Weekly workflow (5-10 images): ~$0.05-0.10/week
- **Monthly: ~$0.20-0.40**

## Tips

1. **Clear images work best** — Good lighting, readable text
2. **Crop to relevant section** — Full screenshots work too
3. **Multiple events per image is fine** — Claude extracts all of them
4. **Delete old images after the week** — Keeps folder clean
5. **Verify results** — Check `docs/log.json` after runs

## Troubleshooting

**No events found?**
- Check images are in `artifacts/` folder (top level, no subfolders)
- Verify file extensions: .png, .jpg, .jpeg, .gif, .webp
- Try clearer/larger image

**Wrong dates/venues extracted?**
- Claude does its best with unclear text
- Clearer images = better extraction
- Manually fix in Google Sheet if needed

**Missing events?**
- Claude vision isn't 100% perfect
- System aims for ~90% accuracy
- Manual additions to Google Sheet always work

## Future Enhancements

- Auto-delete processed artifacts after a week
- Email extracted events for review before publishing
- Better handwriting recognition for posters
- Slack integration for clarifications
