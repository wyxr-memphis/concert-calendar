# svg-animation

A small, zero-dependency framework for animating SVG on the concert-calendar site.
Plain ES modules: no build step, no npm install. It uses the Web Animations API
(`element.animate`) and falls back to `requestAnimationFrame` automatically.

This is a **dev tool, not a deploy path**. It lives in `tools/` (not `docs/`, which Vercel
publishes), so nothing here ships until someone copies the files they want into `docs/`.
Local-dev tool recommendations (editors, optimisers, etc.) live on the separate branch
**`svg-tools-library`**, not here.

```
tools/svg-animation/
  src/svg-anim.js        the library (public API)
  src/presets.js         REGISTRY of named animation presets + validation
  src/easing.js          easing functions (pure)
  src/timeline-math.js   timeline / stagger maths (pure)
  src/interp.js          value + keyframe interpolation (pure)
  presets/index.json     manifest of extra, file-based presets (+ one JSON file per preset)
  examples/              index.html demo, vinyl.svg, note.svg
  tests/                 node:test unit tests
```

## Try it

```bash
cd tools/svg-animation
python3 -m http.server 8080      # any static server; ES modules need http://, not file://
# open http://localhost:8080/examples/
```

## Quick start

```html
<svg viewBox="0 0 160 110">
  <g data-anim="equalizer-bars" data-anim-trigger="load">
    <rect x="10" y="20" width="20" height="80"/> <!-- ...more bars -->
  </g>
</svg>
<script type="module">
  import { autoInit } from './src/svg-anim.js';
  autoInit();
</script>
```

Or from code:

```js
import { animate, draw, tween, sequence, stagger, loadSVG } from './src/svg-anim.js';

const svg = await loadSVG('./logo.svg', { into: document.querySelector('#logo') });
animate(svg.querySelector('#record'), 'spin').play();
draw(svg.querySelector('#outline'), { duration: 1200 }).play();
```

**Everything that creates an animation returns it paused on its first frame.** Call `.play()`,
or hand it to `scrollTrigger()` / `autoInit()`. That makes it safe to build animations first
and compose them into a `sequence()` afterwards.

## API

### Creating animations

| Function | What it does |
|---|---|
| `animate(target, preset, overrides?)` | Apply a preset (name or object). Overrides: `duration delay easing iterations direction stagger staggerFrom origin staticProgress`. |
| `tween(target, spec, opts?)` | Animate attributes/CSS/transforms. `spec` is `[{...},{...}]` keyframes, `{from, to}`, or `{keyframes}`. |
| `draw(target, opts?)` | Stroke line-drawing via `stroke-dasharray` / `stroke-dashoffset`. Accepts a shape or any group/`<svg>` (draws every shape inside). `erase: true` un-draws. |
| `morph(el, toD, opts?)` | Morph `d` (or `points` with `{attribute:'points'}`) to a new value. Both need identical commands and point counts; `canMorph(a, b)` checks. |
| `delay(ms)` | A pure pause. A bare number inside `sequence([...])` does the same. |

`target` can be an element, a `NodeList`/array, or a CSS selector. With several targets you get
a group; pass `stagger: 80` (ms) and optionally `staggerFrom: 'start'|'end'|'center'|'edges'|<index>`.

`tween` options: `duration=600  delay=0  easing='ease-out'  iterations=1|'infinite'
direction='normal'|'reverse'|'alternate'|'alternate-reverse'  origin  attr  forceRaf
staticProgress  reducedMotion`.

- Keyframe props may be any CSS property (camel or kebab case). Shorthands `x`, `y` (px),
  `rotate` (deg), `scale`, `skewX` (deg) are folded into one consistent `transform`.
  Transforms use `transform-box: fill-box` and `transform-origin: center` unless you pass `origin`.
- `attr: true` animates real SVG attributes (`r`, `cx`, `d`, `points`, ...) through the rAF
  backend; the shorthands are off in this mode because `x`/`y` are real attributes.
- Keyframes may carry `offset` (0..1) as in CSS.

### Composing

```js
const intro = sequence([
  stagger(bars, (el) => animate(el, 'pop'), { each: 90 }),   // each bar starts 90ms after the last
  300,                                                         // 300ms pause
  parallel([animate(title, 'slide-up'), animate(note, 'fade-in')]),
], { repeat: 2, yoyo: true });                                 // groups take repeat / yoyo
intro.play();
```

- `sequence(items, {gap, repeat, yoyo})`, `parallel(items, {repeat, yoyo})`,
  `stagger(items, factory, {each, from, repeat, yoyo})`. `factory` is `(item, i) => animation` or a preset name.
- Only the last item of a sequence may loop forever.
- Put `repeat`/`yoyo` on the outermost group; nested repeating groups that start late replay
  from their own start but reverse through the lead-in.

### Controls (every animation and group)

`play() pause() seek(ms) seekProgress(0..1) reverse() restart() finish() cancel() destroy({commit})`
plus `.finished` (Promise), `.span` (ms, `Infinity` if looping), `.playing`, `.currentTime`, `.frozen`.
`cancel()` reverts the element; `destroy({commit:true})` keeps the final styles and removes the animation.
`destroyAll()` tears down everything this module created (useful on SPA navigation).

### Scroll trigger

```js
scrollTrigger(anim, element, { threshold: 0.25, rootMargin: '0px', once: true, reverseOnLeave: false });
```
Uses `IntersectionObserver`; without it the animation just plays. Returns `{ disconnect() }`.

### Loading SVG

`loadSVG(src, { into, sanitize = true })` accepts a URL, an `<svg>` element, or an
`<img src="x.svg">` / `<object data="x.svg">` (which is replaced in place by the inline SVG,
keeping `id`, `class` and its alt text as `aria-label`). It must be same-origin (or CORS-enabled).
`sanitize` strips `<script>`, `<foreignObject>`, `on*` handlers, `javascript:` links and non-local `<use>`
references. Keep it on for anything not authored in this repo; the site's CSP and
`dev/security.md` treat third-party content as untrusted.

### Easing

Names: `linear ease ease-in ease-out ease-in-out ease-in-cubic ease-out-cubic ease-in-out-cubic
ease-in-back ease-out-back ease-in-out-back ease-out-bounce spring`.
Also accepted anywhere an easing is: `[x1, y1, x2, y2]`, `'cubic-bezier(...)'`,
`{ spring: { damping: 0.3 } }` (0.05 bouncy ... 1 no overshoot), or a function `t => number`.
Function-style easings run as CSS `linear()` where the browser supports it, else on the rAF backend.
Add a named easing by adding an entry to `EASINGS` in `src/easing.js`.

### Declarative: `data-anim`

| Attribute | Meaning |
|---|---|
| `data-anim="slide-up"` | preset name or alias (`draw`, `fade`, `equalizer`) |
| `data-anim-delay`, `data-anim-duration` | ms |
| `data-anim-easing` | any easing name |
| `data-anim-stagger` | ms between children / shapes |
| `data-anim-repeat` | `infinite`, or the number of extra repeats |
| `data-anim-direction` | `alternate`, `reverse`, ... |
| `data-anim-trigger` | `visible` (default, scroll into view) or `load` |
| `data-anim-threshold` | 0..1 visibility needed for `visible` |

`autoInit(root = document)` wires them all and returns `{ anims, destroy() }`. Unknown preset
names log a warning and are skipped. Elements sit on their first frame (e.g. invisible for
`fade-in`) as soon as the script runs; hide them in CSS if you need that before JS loads.

## Presets

A preset is a plain data object (full schema is at the top of `src/presets.js`):

```js
{
  name: 'slide-up',                       // kebab-case, unique
  description: 'Rise 24 units into place while fading in.',
  keyframes: [{ opacity: 0, y: 24 }, { opacity: 1, y: 0 }],
  options: { duration: 700, easing: 'ease-out-cubic' },   // iterations may be 'infinite'
  // optional: kind:'draw', target:'children', stagger, staggerFrom, origin, staticProgress
}
```

Built in: `fade-in fade-out slide-up slide-down slide-left slide-right pop bounce pulse spin
wiggle float blink draw-stroke equalizer-bars marquee`. Run `listPresets()` for the live list.

### Adding a preset

There are three ways. All are validated (`validatePreset`) and unit-tested.

1. **Built-in:** add an entry to `REGISTRY` in `src/presets.js`. Best for general-purpose presets.
2. **Drop-in file (no JS edits):**
   1. Create `presets/<name>.json` with the object above.
   2. Add `{ "name": "<name>", "file": "<name>.json" }` to `presets/index.json`.
   3. In the page, `await loadPresetManifest('./presets/index.json')` before using it
      (the examples do this; `heartbeat` and `needle-drop` are file-based).
3. **At runtime:** `registerPreset({...})` (pass `{ replace: true }` to override one).

Then run `node --test tools/svg-animation/tests`. The suite fails if a preset is invalid, clashes
with a built-in name, or a JSON file in `presets/` is not listed in the manifest.
Use `animate(el, presetObject)` to try a preset without registering it.

## Accessibility

- **`prefers-reduced-motion` is respected by default.** When it is on, animations never run;
  each one parks on a static frame instead (the end state for finite animations, the start for
  looping ones, or the preset's `staticProgress`). Promises resolve immediately and `.frozen` is true.
  The setting is read when an animation is created. Opt out per animation with
  `reducedMotion: 'ignore'`, or globally with `setDefaults({ respectReducedMotion: false })`
  (only do that for motion that carries information, never for decoration).
- Animation is decoration: keep meaning in the SVG itself (`role="img"`, `<title>`, `aria-label`),
  never only in a transition. Content revealed by animation must still be present and
  readable in the static frame.
- Avoid flashing faster than 3 times per second (`blink` runs at 1 Hz) and give users a pause
  control for anything looping for a long time (see the vinyl demo).

## Deploying to the site

Nothing here is wired into `docs/`. If a feature adopts it, copy `src/` into `docs/` (or a subfolder)
and import it with a `<script type="module">`. No CSP change is needed: modules are served from
`'self'`, WAAPI and CSSOM style writes are allowed under the current `style-src`, and `loadSVG`
fetches are same-origin. Re-run `scripts/test_security_headers.py` after adding any third-party embed.
Remember `docs/index.html` is one self-contained file by design (see `dev/frontend.md`), so check there
first before adding a module import.

## Tests

```bash
node --test tools/svg-animation/tests      # plain node, nothing to install (Node 20+)
```

Covers easing maths, timeline/stagger/direction maths, interpolation and keyframe normalisation,
and preset + manifest validation. The DOM-facing code is exercised by `examples/index.html`.

## Limitations

- Morph needs matching path structure; compact arc flags (`a5 5 0 011 10`) must be written with spaces.
- Colour interpolation understands `#rgb`/`#rrggbb`; other colour syntaxes flip at the end.
- Reduced-motion is evaluated at creation time and is not live-updated.
- `repeat`/`yoyo` on nested groups: see Composing above.
