#!/usr/bin/env python3
"""Cut the shipped brand artwork out of the flattened Figma logo export.

    python3 dev/brand/build_brand_assets.py                       # logo cut-downs
    python3 dev/brand/build_brand_assets.py --buinton /path/to/Buinton.otf   # + script words

Source of truth: dev/brand/concert-calendar-logo.figma.svg, exported from Figma
file HEADS-UP, node 1872:3. Output: docs/brand/*.svg.

Why this is a script rather than a set of hand-saved files
----------------------------------------------------------
The designer's logo arrives as one flattened lockup. Its red linework is a
single united shape (path index 58): the mascot's outline, two letters of
CONCERT CALENDAR, the music notes, the floor shadow and "Memp" are one contour.
Nothing here redraws any of it. The mascot is the original paths with an SVG
mask hiding the neighbours it is fused to; the cut lines sit where two shapes
meet. If the designer supplies real separations, replace docs/brand/ with
those and delete this file.

The Buinton words
-----------------
Buinton is licensed for desktop use (MyFonts "Standard License"): it may be
used to make images and scalable drawings, but may not be embedded as a
webfont or redistributed. So the font file is never copied into this repo and
never served. `--buinton` reads it from wherever it is installed and writes
the outlined words as SVG paths. That needs `pip install fonttools uharfbuzz`
and is skipped cleanly without them, leaving the committed SVGs in place.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "dev" / "brand" / "concert-calendar-logo.figma.svg"
OUT = ROOT / "docs" / "brand"

RED = "#D53727"
MARIGOLD = "#FCB91A"
CREAM = "#FCE2B6"

# Path indexes in document order (0 is the cream background rectangle).
YELLOW = range(1, 25)
LETTERS = range(25, 38)          # the thirteen free-standing letters
RED_DETAIL = range(38, 58)       # face, ticket and calendar details
UNITED = 58                      # the fused red shape described above
MEMPHIS_HIS = (59, 60)
STAR, NOTE = 61, 62
BADGE_RED = (63, 64, 65, 66, 67)
MASCOT_WHITE = range(68, 96)
BADGE_WHITE = range(96, 112)

OUTLINE = 16                     # twice the logo's keyline, in logo units

# Regions of the united shape that are not the mascot. Each is a polygon in
# logo coordinates, drawn to pass between shapes rather than through them.
CUTS = [
    # the C of CONCERT that rests on the top petal
    "M470 40H640V259H470Z",
    # the first C, lying against the calendar's top-left corner
    "M60 385H262L266 462L269.5 468.5L266 476L272 500L276 512H262V522H60Z",
    # the staff and notes: under the hand, round the heel of the palm, along
    # the bottom of the calendar, then down the front of the left shoe
    "M60 596H266V642L300 640.5L316 645L320 655L328 658.5L338 658L346 654L350 651.5"
    "H398V714L390 724L372 730L360 738L352 748L349 756H60Z",
    # "Memp", fused to the left tip of the floor shadow, and everything below
    "M60 750H310L316 788L320 798L341 809.5L372 814V830H60Z",
    "M60 830H1080V1080H60Z",
]


def read_paths():
    svg = SOURCE.read_text()
    paths = []
    for m in re.finditer(r"<path\b([^>]*)/?>", svg):
        attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))
        paths.append(attrs)
    if len(paths) != 112:
        sys.exit(f"expected 112 paths in the Figma export, found {len(paths)} — "
                 "the logo changed; re-derive the indexes at the top of this file")
    return paths


def slim(d, places=0):
    """Round path coordinates.

    The export carries two decimals on a 1080-unit canvas. Whole units are a
    quarter of a CSS pixel at the largest size the page draws the art, and
    they take the mascot from 48 KB to 27 KB over the wire. The script words
    are set at a 1000-unit em and drawn small, so they keep one decimal.
    """
    def fix(m):
        v = round(float(m.group(0)), places)
        return str(int(v)) if v == int(v) else str(v)
    return re.sub(r"-?\d+\.\d+", fix, d)


def group(paths, indexes, fill, ids=False):
    def one(i):
        ident = f' id="p{i}"' if ids else ""
        return f'<path{ident} d="{slim(paths[i]["d"])}"/>'

    return f'<g fill="{fill}">{"".join(one(i) for i in indexes)}</g>'


def write(name, viewbox, body, title):
    x, y, w, h = viewbox
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" '
        f'width="{w}" height="{h}" role="img" aria-label="{title}">'
        f"<title>{title}</title>{body}</svg>\n"
    )
    print(f"  {name:28s} {(OUT / name).stat().st_size / 1024:6.1f} KB")


def build_logo(paths):
    body = (
        group(paths, YELLOW, MARIGOLD)
        + group(paths, list(LETTERS) + list(RED_DETAIL) + [UNITED, *MEMPHIS_HIS, STAR, NOTE, *BADGE_RED], RED)
        + group(paths, list(MASCOT_WHITE) + list(BADGE_WHITE), "#fff")
    )
    write("logo.svg", (56, 46, 968, 994), body, "Concert Calendar, Memphis")


def build_mascot(paths):
    fills = list(YELLOW) + list(MASCOT_WHITE)
    restore = "".join(f'<use href="#p{i}"/>' for i in fills)
    mask = (
        '<mask id="keep" maskUnits="userSpaceOnUse" x="0" y="0" width="1080" height="1080">'
        '<rect width="1080" height="1080" fill="#fff"/>'
        f'<path d="{" ".join(CUTS)}" fill="#000"/>'
        # Wherever a cut crosses the mascot's own keyline, put the keyline back:
        # it is the band one outline-width outside each filled shape.
        f'<g fill="#fff" stroke="#fff" stroke-width="{OUTLINE}" stroke-linejoin="round">{restore}</g>'
        "</mask>"
    )
    body = (
        f"<defs>{mask}</defs>"
        + group(paths, YELLOW, MARIGOLD, ids=True)
        + f'<path fill="{RED}" mask="url(#keep)" d="{slim(paths[UNITED]["d"])}"/>'
        + group(paths, RED_DETAIL, RED)
        + group(paths, MASCOT_WHITE, "#fff", ids=True)
    )
    write("mascot.svg", (256, 228, 524, 600), body, "The Concert Calendar flower")


def build_marks(paths):
    write("star.svg", (192, 553, 45, 43), group(paths, [STAR], RED), "")
    write("note.svg", (70, 551, 80, 70), group(paths, [NOTE], RED), "")


def build_favicon(paths):
    """The flower's face on a marigold tile.

    A favicon cannot afford the 110 KB united shape, so here the keyline is a
    stroke on the face and petal fills instead. Whole-unit coordinates are
    plenty at 16 to 180 pixels.
    """
    def coarse(d):
        return re.sub(r"-?\d+\.\d+", lambda m: str(round(float(m.group(0)))), d)

    petals = "".join(f'<path d="{coarse(paths[i]["d"])}"/>' for i in range(1, 9))
    face = paths[72]["d"]
    face_outline = coarse(face[:face.index("M", 1)])   # first subpath: the disc
    features = "".join(f'<path d="{coarse(paths[i]["d"])}"/>' for i in (38, 40, 41, 42, 43))
    shines = "".join(f'<path d="{coarse(paths[i]["d"])}"/>' for i in (94, 95))
    size, x, y = 236, 407, 338
    out = ROOT / "docs" / "favicon.svg"
    out.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {size} {size}">'
        f'<clipPath id="t"><rect x="{x}" y="{y}" width="{size}" height="{size}" rx="52"/></clipPath>'
        f'<g clip-path="url(#t)"><rect x="{x}" y="{y}" width="{size}" height="{size}" fill="{MARIGOLD}"/>'
        f'<g fill="{MARIGOLD}" stroke="{RED}" stroke-width="14" stroke-linejoin="round">{petals}</g>'
        f'<path fill="#fff" stroke="{RED}" stroke-width="14" d="{face_outline}"/>'
        f'<g fill="{RED}">{features}</g><g fill="#fff">{shines}</g></g></svg>\n'
    )
    print(f"  {'../favicon.svg':28s} {out.stat().st_size / 1024:6.1f} KB")


def build_script_words(font_path):
    try:
        import uharfbuzz as hb
        from fontTools.pens.boundsPen import BoundsPen
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        from fontTools.ttLib import TTFont
    except ImportError:
        print("  (skipped the Buinton words: pip install fonttools uharfbuzz)")
        return

    tt = TTFont(font_path)
    glyphs, order = tt.getGlyphSet(), tt.getGlyphOrder()
    hb_font = hb.Font(hb.Face(hb.Blob.from_file_path(font_path)))

    def outline(text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hb_font, buf, {"kern": True, "liga": True})
        svg_pen, bounds = SVGPathPen(glyphs), BoundsPen(glyphs)
        x = 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            flip = (1, 0, 0, -1, x + pos.x_offset, pos.y_offset)
            name = order[info.codepoint]
            glyphs[name].draw(TransformPen(svg_pen, flip))
            glyphs[name].draw(TransformPen(bounds, flip))
            x += pos.x_advance
        x0, y0, x1, y1 = bounds.bounds
        pad = 8
        box = (round(x0 - pad), round(y0 - pad), round(x1 - x0 + 2 * pad), round(y1 - y0 + 2 * pad))
        return box, slim(svg_pen.getCommands(), 1)

    for name, text in [
        ("word-memphis.svg", "Memphis"),
        ("word-tonight.svg", "Tonight"),
        ("word-see-you.svg", "See you at the show"),
    ]:
        box, d = outline(text)
        write(name, box, f'<path fill="{RED}" d="{d}"/>', text)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--buinton", help="path to the licensed Buinton .otf (never copied)")
    args = parser.parse_args()

    paths = read_paths()
    print("docs/brand/")
    build_logo(paths)
    build_mascot(paths)
    build_marks(paths)
    build_favicon(paths)
    if args.buinton:
        build_script_words(args.buinton)


if __name__ == "__main__":
    main()
