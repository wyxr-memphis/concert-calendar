// svg-anim: tiny zero-dependency SVG animation framework (ES module).
//
//   import { animate, tween, draw, morph, sequence, parallel, stagger,
//            scrollTrigger, autoInit, loadSVG } from './svg-anim.js';
//
// Everything that creates an animation returns it PAUSED at its first frame.
// Call .play() (or use scrollTrigger / autoInit). All animations share one interface:
//   play() pause() seek(ms) seekProgress(0..1) reverse() restart() finish() cancel()
//   destroy({commit}) shift(ms)   plus  .finished (Promise), .span (ms), .frozen
// Groups (sequence / parallel / stagger) expose the same interface.

import { resolveEasing } from './easing.js';
import { computeState, totalSpan, layout } from './timeline-math.js';
import { normalizeKeyframes, buildSampler, camel, canInterpolate } from './interp.js';
import { getPreset, validatePreset } from './presets.js';

export { resolveEasing, EASINGS, cubicBezier, spring } from './easing.js';
export { REGISTRY, registerPreset, getPreset, listPresets, validatePreset, loadPresetManifest } from './presets.js';

export const VERSION = '0.1.0';

// ---------------------------------------------------------------- settings / helpers

const defaults = { respectReducedMotion: true, forceRaf: false };
/** setDefaults({ respectReducedMotion: false, forceRaf: true }) */
export function setDefaults(o) { Object.assign(defaults, o); }

export function prefersReducedMotion() {
  try { return globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
}

const defer = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };

function resolveTargets(target, root = globalThis.document) {
  let list;
  if (typeof target === 'string') list = root ? root.querySelectorAll(target) : [];
  else if (target && target.nodeType === 1) list = [target];
  else list = target || [];
  return Array.from(list).filter((n) => n && n.nodeType === 1);
}

function normalizeOpts(o = {}) {
  const iterations = o.iterations === 'infinite' ? Infinity : (o.iterations ?? 1);
  const out = {
    duration: o.duration ?? 600, delay: o.delay ?? 0, iterations,
    direction: o.direction ?? 'normal', easing: o.easing ?? 'ease-out',
  };
  if (!(out.duration >= 0) || !(out.delay >= 0) || !(iterations > 0)) {
    throw new Error('svg-anim: duration/delay must be >= 0 and iterations > 0');
  }
  return out;
}

// ---------------------------------------------------------------- ticker for the rAF backend

const active = new Set();
let rafId = 0, lastNow = 0;
function loop(now) {
  const dt = Math.min(Math.max(now - lastNow, 0), 250); // clamp: no negative frames, no jump after a background tab
  lastNow = now;
  for (const a of [...active]) a._tick(dt);
  rafId = active.size ? requestAnimationFrame(loop) : 0;
}
function tickerAdd(a) {
  active.add(a);
  if (!rafId) { lastNow = performance.now(); rafId = requestAnimationFrame(loop); }
}

// ---------------------------------------------------------------- animation classes

const live = new Set();

class Anim {
  constructor(timing) {
    this.timing = { delay: 0, duration: 0, iterations: 1, direction: 'normal', ...timing };
    this._baseDelay = this.timing.delay;
    this._shift = 0;
    this._frozen = null;
    this._done = false;
    this._d = defer();
    live.add(this);
  }
  get span() { return totalSpan(this.timing); }
  get finished() { return this._d.promise; }
  get frozen() { return this._frozen !== null; }
  _renew() { if (this._done) { this._d = defer(); this._done = false; } }
  _resolve() { this._done = true; this._d.resolve(this); }
  /** Delay this animation's start by `ms` (used by groups to place children). */
  shift(ms) {
    this._shift += ms;
    this._setDelay(this._baseDelay + this._shift);
    this._refreeze();
    return this;
  }
  /** Reduced motion: park on a static frame, never run. */
  _freeze(progress) { this._frozen = progress; this._refreeze(); this._resolve(); }
  _refreeze() {
    if (this._frozen === null) return;
    this.pause();
    this.seek(this.timing.delay + this.timing.duration * this._frozen);
  }
  seekProgress(p) { if (Number.isFinite(this.span)) this.seek(this.span * p); return this; }
  restart() { this.seek(0); return this.play(); }
}

class WaapiAnim extends Anim {
  constructor(el, keyframes, timing, cssEasing) {
    super(timing);
    this.el = el;
    this.a = el.animate(keyframes, {
      duration: timing.duration, delay: timing.delay, iterations: timing.iterations,
      direction: timing.direction, easing: cssEasing, fill: 'both',
    });
    this.a.pause();
    this.a.currentTime = 0;
    this.a.onfinish = () => this._resolve();
  }
  get currentTime() { return this.a.currentTime ?? 0; }
  get playing() { return this.a.playState === 'running'; }
  _setDelay(d) { this.timing.delay = d; this.a.effect.updateTiming({ delay: d }); }
  play() { if (this.frozen) return this; this._renew(); this.a.play(); return this; }
  pause() { this.a.pause(); return this; }
  seek(ms) { this.a.currentTime = ms; return this; }
  reverse() {
    if (this.frozen) return this;
    this._renew();
    try { this.a.reverse(); } catch { /* infinite animations cannot be reversed from the start */ }
    return this;
  }
  finish() {
    try { this.a.finish(); } catch { this.seek(this.timing.delay + this.timing.duration); this._resolve(); }
    return this;
  }
  cancel() { this.a.cancel(); this._resolve(); return this; }
  destroy({ commit = false } = {}) {
    if (commit) { try { this.a.commitStyles(); } catch { /* element not rendered */ } }
    this.a.cancel();
    this._resolve();
    live.delete(this);
  }
}

class RafAnim extends Anim {
  constructor(apply, timing, easeFn, restore) {
    super(timing);
    this.apply = apply; this.ease = easeFn; this.restore = restore;
    this.t = 0; this.rate = 1;
    this._render();
  }
  get currentTime() { return this.t; }
  get playing() { return active.has(this); }
  _setDelay(d) { this.timing.delay = d; this._render(); }
  _render() { this.apply(this.ease(computeState(this.t, this.timing).progress)); }
  _tick(dt) {
    this.t += dt * this.rate;
    const span = this.span;
    if (this.rate > 0 && this.t >= span) { this.t = span; this._end(); }
    else if (this.rate < 0 && this.t <= 0) { this.t = 0; this._end(); }
    else this._render();
  }
  _end() { this._render(); active.delete(this); this._resolve(); }
  play() {
    if (this.frozen) return this;
    const span = this.span;
    if (this.rate > 0 && this.t >= span) this.t = 0;
    else if (this.rate < 0 && this.t <= 0 && Number.isFinite(span)) this.t = span;
    this._renew();
    tickerAdd(this);
    return this;
  }
  pause() { active.delete(this); return this; }
  seek(ms) {
    const span = this.span;
    this.t = Math.max(0, Number.isFinite(span) ? Math.min(ms, span) : ms);
    this._render();
    return this;
  }
  reverse() { if (this.frozen) return this; this.rate *= -1; return this.play(); }
  finish() {
    const span = this.span;
    this.t = Number.isFinite(span) ? span : this.timing.delay + this.timing.duration;
    this._end();
    return this;
  }
  cancel() { active.delete(this); this.restore?.(); this._resolve(); return this; }
  destroy({ commit = false } = {}) {
    if (commit) { active.delete(this); this._resolve(); } else this.cancel();
    live.delete(this);
  }
}

/** A set of animations driven together. Children keep absolute times (see shift()). */
class Group {
  constructor(children, { repeat = 0, yoyo = false } = {}) {
    this.children = children;
    this.repeat = repeat === 'infinite' ? Infinity : repeat;
    this.yoyo = yoyo;
    this._offset = 0; this._token = 0; this._running = false; this._done = false;
    this._d = defer();
  }
  get span() {
    const one = this.children.reduce((m, c) => Math.max(m, c.span), 0);
    return one * (this.repeat + 1);
  }
  get frozen() { return this.children.every((c) => c.frozen); }
  get finished() { return this._d.promise; }
  get currentTime() { return this.children[0]?.currentTime ?? 0; }
  get playing() { return this.children.some((c) => c.playing); }
  shift(ms) { this._offset += ms; this.children.forEach((c) => c.shift(ms)); return this; }
  _renew() { if (this._done) { this._d = defer(); this._done = false; } }
  _start(first) {
    this._running = true;
    this._renew();
    this._run(++this._token, first);
  }
  async _run(token, first) {
    if (this.frozen) { this._running = false; this._done = true; this._d.resolve(this); return; }
    let n = 0;
    first();
    for (;;) {
      await Promise.all(this.children.map((c) => c.finished));
      if (token !== this._token) return; // cancelled / restarted meanwhile
      if (n >= this.repeat) break;
      n++;
      if (this.yoyo) this.children.forEach((c) => c.reverse());
      else { this.children.forEach((c) => { c.seek(this._offset); c.play(); }); }
    }
    this._running = false; this._done = true; this._d.resolve(this);
  }
  play() {
    if (this._running) this.children.forEach((c) => c.play());
    else this._start(() => this.children.forEach((c) => c.play()));
    return this;
  }
  pause() { this.children.forEach((c) => c.pause()); return this; }
  seek(ms) { this.children.forEach((c) => c.seek(ms)); return this; }
  seekProgress(p) { if (Number.isFinite(this.span)) this.seek(this.span * p); return this; }
  reverse() {
    if (this._running) this.children.forEach((c) => c.reverse());
    else this._start(() => this.children.forEach((c) => c.reverse()));
    return this;
  }
  restart() { this._stop(); this.seek(this._offset); return this.play(); }
  _stop() { this._token++; this._running = false; }
  _settle() { this._stop(); this._done = true; this._d.resolve(this); }
  finish() { this._stop(); this.children.forEach((c) => c.finish()); this._settle(); return this; }
  cancel() { this._stop(); this.children.forEach((c) => c.cancel()); this._settle(); return this; }
  destroy(o) { this._stop(); this.children.forEach((c) => c.destroy(o)); this._settle(); }
}

// ---------------------------------------------------------------- tween

function setTransformOrigin(el, origin) {
  if (!el.style) return;
  if (!el.style.transformBox) el.style.transformBox = 'fill-box';
  if (origin || !el.style.transformOrigin) el.style.transformOrigin = origin || 'center';
}

/**
 * Tween one or many targets.
 *   spec  : [{...},{...}] keyframes | { from, to } | { keyframes }
 *           props may be any CSS property (camel or kebab), or shorthands x, y, rotate, scale, skewX
 *   opts  : duration=600 delay=0 easing='ease-out' iterations=1|'infinite' direction='normal'
 *           origin (transform-origin) | attr:true (animate attributes, e.g. r, cx, d, points)
 *           stagger (ms between targets) staggerFrom | staticProgress | reducedMotion:'ignore'
 *           forceRaf:true (skip the Web Animations API)
 * Returns a paused animation (a Group when several targets matched).
 */
export function tween(target, spec, opts = {}) {
  const els = resolveTargets(target);
  if (!els.length) throw new Error('svg-anim: tween() matched no elements');
  if (els.length > 1) {
    const { stagger: each = 0, staggerFrom: from = 'start', ...rest } = opts;
    return stagger(els, (el) => tween(el, spec, rest), { each, from });
  }
  const el = els[0];
  const o = normalizeOpts(opts);
  const ease = resolveEasing(o.easing);
  let kfs = normalizeKeyframes(spec, { shorthand: !opts.attr });
  if (!opts.attr) kfs = kfs.map((f) => Object.fromEntries(Object.entries(f).map(([k, v]) => [camel(k), v])));
  if (kfs.some((f) => 'transform' in f) && !opts.attr) setTransformOrigin(el, opts.origin);

  const canWaapi = !opts.attr && !opts.forceRaf && !defaults.forceRaf
    && typeof el.animate === 'function' && ease.css !== null;
  let anim;
  if (canWaapi) {
    anim = new WaapiAnim(el, kfs, o, ease.css);
  } else {
    const props = [...new Set(kfs.flatMap((f) => Object.keys(f).filter((k) => k !== 'offset' && k !== 'easing')))];
    const read = (k) => (opts.attr ? el.getAttribute(k) : globalThis.getComputedStyle(el)[k]);
    for (const k of props) { // fill in missing start/end values from the element's current state
      for (const f of [kfs[0], kfs[kfs.length - 1]]) if (f[k] === undefined) f[k] = read(k);
    }
    const sample = buildSampler(kfs);
    const original = Object.fromEntries(props.map((k) => [k, opts.attr ? el.getAttribute(k) : el.style[k]]));
    const set = opts.attr
      ? (k, v) => el.setAttribute(k, v)
      : (k, v) => { el.style[k] = v; };
    const apply = (p) => { const v = sample(p); for (const k of props) set(k, v[k]); };
    const restore = () => props.forEach((k) => {
      if (opts.attr) { if (original[k] == null) el.removeAttribute(k); else el.setAttribute(k, original[k]); }
      else el.style[k] = original[k];
    });
    anim = new RafAnim(apply, o, ease.fn, restore);
  }
  const reduced = opts.reducedMotion !== 'ignore' && defaults.respectReducedMotion && prefersReducedMotion();
  if (reduced) anim._freeze(opts.staticProgress ?? (Number.isFinite(o.iterations) ? 1 : 0));
  return anim;
}

/** A pure delay (use inside sequence()). Also accepted as a bare number there. */
export function delay(ms) {
  const a = new RafAnim(() => {}, normalizeOpts({ duration: ms, delay: 0 }), (t) => t);
  if (defaults.respectReducedMotion && prefersReducedMotion()) a._freeze(1);
  return a;
}

// ---------------------------------------------------------------- groups

function asAnim(x) { return typeof x === 'number' ? delay(x) : x; }

/** Play items one after another. Items: animations or numbers (ms of pause). */
export function sequence(items, { gap = 0, ...groupOpts } = {}) {
  const anims = items.map(asAnim);
  anims.slice(0, -1).forEach((a) => {
    if (!Number.isFinite(a.span)) throw new Error('svg-anim: only the last item of a sequence may loop forever');
  });
  const { offsets } = layout(anims.map((a) => a.span), 'sequence', { gap });
  anims.forEach((a, i) => a.shift(offsets[i]));
  return new Group(anims, groupOpts);
}

/** Play items together. */
export function parallel(items, groupOpts = {}) {
  return new Group(items.map(asAnim), groupOpts);
}

/**
 * Build one animation per item and start each `each` ms after the previous.
 * factory: (item, index) => animation, or a preset name. from: 'start'|'end'|'center'|'edges'|index
 */
export function stagger(items, factory, { each = 0, from = 'start', ...groupOpts } = {}) {
  const make = typeof factory === 'string' ? (el) => animate(el, factory) : factory;
  const anims = items.map((it, i) => make(it, i));
  const { offsets } = layout(anims.map((a) => a.span), 'stagger', { each, from });
  anims.forEach((a, i) => a.shift(offsets[i]));
  return new Group(anims, groupOpts);
}

// ---------------------------------------------------------------- draw (stroke line-drawing)

const DRAWABLE = 'path,line,polyline,polygon,circle,ellipse,rect';

function strokeLength(el) {
  const explicit = parseFloat(el.getAttribute('pathLength')); // dash units follow pathLength if set
  if (explicit > 0) return explicit;
  try { return el.getTotalLength(); } catch { return 0; }
}

/**
 * Line-draw strokes using stroke-dasharray/dashoffset. Target may be a shape or a group/svg
 * (every shape inside is drawn). opts: tween opts plus erase:true to un-draw instead.
 * Give shapes `fill="none"` and a stroke, or the fill will show before the line arrives.
 */
export function draw(target, opts = {}) {
  const shapes = resolveTargets(target).flatMap((el) => (el.matches(DRAWABLE) ? [el] : [...el.querySelectorAll(DRAWABLE)]));
  if (!shapes.length) throw new Error('svg-anim: draw() found no drawable shapes');
  const { stagger: each = 0, staggerFrom: from = 'start', erase = false, ...rest } = opts;
  const make = (el) => {
    const len = strokeLength(el);
    if (!(len > 0)) return delay(0);
    el.style.strokeDasharray = `${len}px`;
    const [a, b] = erase ? [0, len] : [len, 0];
    return tween(el, [{ strokeDashoffset: `${a}px` }, { strokeDashoffset: `${b}px` }], rest);
  };
  return shapes.length === 1 ? make(shapes[0]) : stagger(shapes, make, { each, from });
}

// ---------------------------------------------------------------- morph

/** True when two path strings have identical commands and number counts. */
export const canMorph = canInterpolate;

/**
 * Morph a path's `d` (or a polygon's `points`, via opts.attribute) to a new value.
 * Both shapes need the same commands and point counts, and arc flags must be space separated.
 */
export function morph(el, to, { attribute = 'd', ...opts } = {}) {
  const [node] = resolveTargets(el);
  if (!node) throw new Error('svg-anim: morph() matched no element');
  const from = node.getAttribute(attribute);
  if (!canInterpolate(from, to)) {
    throw new Error(`svg-anim: cannot morph "${attribute}": commands/point counts differ`);
  }
  return tween(node, [{ [attribute]: from }, { [attribute]: to }], { ...opts, attr: true });
}

// ---------------------------------------------------------------- presets

/**
 * Apply a preset (name or preset object) to target(s). `overrides` may contain any option
 * (duration, delay, easing, iterations, direction), plus stagger, staggerFrom, origin, staticProgress.
 */
export function animate(target, preset, overrides = {}) {
  const p = typeof preset === 'string' ? getPreset(preset) : preset;
  if (!p) throw new Error(`svg-anim: unknown preset "${preset}"`);
  if (typeof preset !== 'string') {
    const errs = validatePreset(p);
    if (errs.length) throw new Error(`svg-anim: ${errs.join('; ')}`);
  }
  const els = resolveTargets(target);
  if (!els.length) throw new Error('svg-anim: animate() matched no elements');
  const { stagger: sg, staggerFrom, origin, staticProgress, ...timing } = overrides;
  const opts = {
    ...p.options, ...timing,
    stagger: sg ?? p.stagger, staggerFrom: staggerFrom ?? p.staggerFrom,
  };
  if (p.kind === 'draw') return draw(els, opts);
  const targets = p.target === 'children' ? els.flatMap((e) => [...e.children]) : els;
  if (!targets.length) throw new Error(`svg-anim: preset "${p.name}" needs child elements`);
  return tween(targets, p.keyframes, {
    ...opts, origin: origin ?? p.origin, staticProgress: staticProgress ?? p.staticProgress,
  });
}

// ---------------------------------------------------------------- scroll trigger

/**
 * Play `anim` when `el` scrolls into view. Returns { disconnect() }.
 * opts: threshold=0.25, rootMargin='0px', once=true, reverseOnLeave=false
 */
export function scrollTrigger(anim, el, { threshold = 0.25, rootMargin = '0px', once = true, reverseOnLeave = false } = {}) {
  if (typeof IntersectionObserver === 'undefined') { anim.play(); return { disconnect() {} }; }
  let seen = false;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        if (reverseOnLeave && seen) anim.reverse(); else anim.play();
        seen = true;
        if (once) io.disconnect();
      } else if (reverseOnLeave && seen) {
        anim.reverse();
      }
    }
  }, { threshold, rootMargin });
  io.observe(el);
  return { disconnect: () => io.disconnect() };
}

// ---------------------------------------------------------------- loading SVG

/** Remove scripts, event handlers, foreignObject and non-local references from an <svg> subtree. */
export function sanitizeSVG(root) {
  root.querySelectorAll('script,foreignObject,iframe,object,embed').forEach((n) => n.remove());
  const all = [root, ...root.querySelectorAll('*')];
  for (const n of all) {
    for (const a of [...n.attributes]) {
      const name = a.name.toLowerCase();
      const val = a.value.trim().toLowerCase();
      const isHref = name === 'href' || name === 'xlink:href';
      if (name.startsWith('on')) n.removeAttribute(a.name);
      else if (isHref && (val.startsWith('javascript:') || (n.localName === 'use' && !val.startsWith('#')))) n.removeAttribute(a.name);
    }
  }
  return root;
}

/**
 * Get an inline <svg> element.
 *   src: URL string | <svg> element (returned as is) | <img src=*.svg> / <object data=*.svg> (replaced by inline svg)
 *   opts: into (element to append to), sanitize=true, fetchImpl, signal
 */
export async function loadSVG(src, { into, sanitize = true, fetchImpl = globalThis.fetch, signal } = {}) {
  let url = src, replace = null;
  if (typeof src !== 'string') {
    if (src && src.localName === 'svg') { into?.appendChild(src); return src; }
    if (src && src.localName === 'img') { url = src.currentSrc || src.src; replace = src; }
    else if (src && src.localName === 'object') { url = src.data; replace = src; }
    else throw new Error('svg-anim: loadSVG needs a URL, <svg>, <img> or <object>');
  }
  const res = await fetchImpl(url, { signal });
  if (!res.ok) throw new Error(`svg-anim: could not load ${url} (HTTP ${res.status})`);
  const doc = new DOMParser().parseFromString(await res.text(), 'image/svg+xml');
  if (doc.querySelector('parsererror') || doc.documentElement.localName !== 'svg') {
    throw new Error(`svg-anim: ${url} is not valid SVG`);
  }
  const svg = document.importNode(doc.documentElement, true);
  if (sanitize) sanitizeSVG(svg);
  if (replace) {
    if (replace.id) svg.id = replace.id;
    if (replace.className && typeof replace.className === 'string') svg.setAttribute('class', replace.className);
    const label = replace.getAttribute('alt') || replace.getAttribute('aria-label');
    if (label) { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label); }
    replace.replaceWith(svg);
  } else into?.appendChild(svg);
  return svg;
}

// ---------------------------------------------------------------- declarative autoInit

/**
 * Wire up every [data-anim] element under `root`.
 *   data-anim="slide-up"          preset name (or alias: draw, fade, equalizer)
 *   data-anim-delay="200"         ms           data-anim-duration="800"  ms
 *   data-anim-easing="spring"     any easing   data-anim-stagger="80"    ms between children/shapes
 *   data-anim-repeat="infinite"   or a count of EXTRA repeats
 *   data-anim-direction="alternate"
 *   data-anim-trigger="visible"   'visible' (default, on scroll into view) | 'load'
 *   data-anim-threshold="0.25"
 * Returns { anims, destroy() }.
 */
export function autoInit(root = globalThis.document, { warn = console.warn } = {}) {
  const els = [...root.querySelectorAll('[data-anim]')];
  if (root.matches?.('[data-anim]')) els.unshift(root);
  const anims = [], triggers = [];
  const num = (v) => (v !== undefined && v !== '' && Number.isFinite(+v) ? +v : undefined);
  for (const el of els) {
    const d = el.dataset;
    const preset = getPreset(d.anim);
    if (!preset) { warn(`svg-anim: unknown data-anim="${d.anim}"`); continue; }
    const over = {};
    if (num(d.animDelay) !== undefined) over.delay = num(d.animDelay);
    if (num(d.animDuration) !== undefined) over.duration = num(d.animDuration);
    if (num(d.animStagger) !== undefined) over.stagger = num(d.animStagger);
    if (d.animEasing) over.easing = d.animEasing;
    if (d.animDirection) over.direction = d.animDirection;
    if (d.animRepeat === 'infinite') over.iterations = 'infinite';
    else if (num(d.animRepeat) !== undefined) over.iterations = 1 + num(d.animRepeat);
    let anim;
    try { anim = animate(el, preset, over); } catch (e) { warn(e.message); continue; }
    anims.push(anim);
    if (d.animTrigger === 'load') anim.play();
    else triggers.push(scrollTrigger(anim, el, { threshold: num(d.animThreshold) ?? 0.25 }));
  }
  return {
    anims,
    destroy() { triggers.forEach((t) => t.disconnect()); anims.forEach((a) => a.destroy()); },
  };
}

/** Destroy every animation this module created (handy for SPA route changes). */
export function destroyAll() { [...live].forEach((a) => a.destroy()); }
