# Artifact Image Tips

## What Works Well ✅

**Single event or small venue listings** (bar-dkdc.png style):
- Screenshots of Instagram posts with 1-3 events
- Website sections showing a few upcoming events
- Focused venue event pages

**Result**: Clear text extraction, accurate dates/times

## What Doesn't Work Well ❌

**Full-page scrolled screenshots** (bands-in-town.png style):
- Complete Bandsintown page with hundreds of events
- Massive scrolled screenshots with tiny text
- Mixed months/dates

**Result**: Incomplete/unreliable extraction, text too small after resizing

## Why?

When we resize large images to fit Claude's API limits (1024px width), text becomes too small to read reliably. A 2798x10734px image compressed to 533x2048px loses detail.

## Better Approach

Instead of one giant screenshot:
1. **Take separate screenshots for each week** (Feb 11-17, Feb 18-24, etc.)
2. **Or focus on specific venues** (B-Side events, Minglewood events, etc.)
3. **Crop to just the relevant section** before saving

Example:
- `bandsintown-week-feb11.png` — Just 1 week, better quality
- `minglewood-events.png` — Just one venue's listings
- `bandsintown-week-feb18.png` — Next week

## Recommendation

For ongoing use:
- Keep using **manual Google Sheet** for reliable, easy-to-update listings (currently finding 7 events)
- Use **artifact images for exceptional finds** (special events, last-minute additions)
- Screenshot focused sections, not entire pages
