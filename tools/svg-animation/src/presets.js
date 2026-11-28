// Animation presets as plain data. To add one, see "Adding a preset" in README.md.
//
// Preset shape:
//   name            kebab-case, unique                                   (required)
//   description     one line                                             (required)
//   kind            'keyframes' (default) | 'draw'  (draw = stroke line-drawing, no keyframes)
//   keyframes       array of >= 2 keyframes (kind 'keyframes' only). Besides any CSS property,
//                   x / y (px), rotate (deg), scale and skewX shorthands are allowed.
//   options         { duration, delay, easing, iterations (number | 'infinite'), direction }
//   target          'self' (default) | 'children'  -> animate the element itself or each child
//   stagger         ms between children (target 'children' only)
//   staggerFrom     'start' | 'end' | 'center' | 'edges' | index
//   origin          CSS transform-origin (default 'center'); SVG uses the element's own box
//   staticProgress  0..1 frame to show when the user prefers reduced motion
//                   (default: 1 for finite animations, 0 for infinite ones)
//
// REGISTRY is a plain object so it can be inspected, extended at runtime with
// registerPreset(), or filled from JSON files via loadPresetManifest().

import { resolveEasing } from './easing.js';
import { staggerOrder } from './timeline-math.js';

export const REGISTRY = {
  'fade-in': {
    name: 'fade-in', description: 'Fade from transparent to opaque.',
    keyframes: [{ opacity: 0 }, { opacity: 1 }],
    options: { duration: 600, easing: 'ease-out' },
  },
  'fade-out': {
    name: 'fade-out', description: 'Fade from opaque to transparent.',
    keyframes: [{ opacity: 1 }, { opacity: 0 }],
    options: { duration: 600, easing: 'ease-in' },
  },
  'slide-up': {
    name: 'slide-up', description: 'Rise 24 units into place while fading in.',
    keyframes: [{ opacity: 0, y: 24 }, { opacity: 1, y: 0 }],
    options: { duration: 700, easing: 'ease-out-cubic' },
  },
  'slide-down': {
    name: 'slide-down', description: 'Drop 24 units into place while fading in.',
    keyframes: [{ opacity: 0, y: -24 }, { opacity: 1, y: 0 }],
    options: { duration: 700, easing: 'ease-out-cubic' },
  },
  'slide-left': {
    name: 'slide-left', description: 'Slide in from the right while fading in.',
    keyframes: [{ opacity: 0, x: 32 }, { opacity: 1, x: 0 }],
    options: { duration: 700, easing: 'ease-out-cubic' },
  },
  'slide-right': {
    name: 'slide-right', description: 'Slide in from the left while fading in.',
    keyframes: [{ opacity: 0, x: -32 }, { opacity: 1, x: 0 }],
    options: { duration: 700, easing: 'ease-out-cubic' },
  },
  pop: {
    name: 'pop', description: 'Scale up from 60% with a springy overshoot.',
    keyframes: [{ opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1 }],
    options: { duration: 600, easing: 'ease-out-back' },
  },
  bounce: {
    name: 'bounce', description: 'Drop in from above and bounce to rest.',
    keyframes: [{ opacity: 0, y: -60 }, { opacity: 1, y: 0 }],
    options: { duration: 900, easing: 'ease-out-bounce' },
  },
  pulse: {
    name: 'pulse', description: 'Gentle heartbeat scale, loops forever.',
    keyframes: [{ scale: 1 }, { scale: 1.12 }, { scale: 1 }],
    options: { duration: 1200, easing: 'ease-in-out', iterations: 'infinite' },
  },
  spin: {
    name: 'spin', description: 'Continuous rotation (a turning record).',
    keyframes: [{ rotate: 0 }, { rotate: 360 }],
    options: { duration: 3000, easing: 'linear', iterations: 'infinite' },
  },
  wiggle: {
    name: 'wiggle', description: 'Quick side-to-side shake, repeats.',
    keyframes: [{ rotate: -8 }, { rotate: 8 }, { rotate: -6 }, { rotate: 6 }, { rotate: 0 }],
    options: { duration: 700, easing: 'ease-in-out', iterations: 'infinite' },
    staticProgress: 1,
  },
  float: {
    name: 'float', description: 'Slow vertical bob, loops forever.',
    keyframes: [{ y: 0 }, { y: -8 }],
    options: { duration: 1800, easing: 'ease-in-out', iterations: 'infinite', direction: 'alternate' },
  },
  blink: {
    name: 'blink', description: 'On-air light: opacity flashes on and off.',
    keyframes: [{ opacity: 1 }, { opacity: 1, offset: 0.55 }, { opacity: 0.15 }],
    options: { duration: 1000, easing: 'linear', iterations: 'infinite', direction: 'alternate' },
  },
  'draw-stroke': {
    name: 'draw-stroke', kind: 'draw', description: 'Line-draw: strokes trace themselves in (paths, lines, circles...).',
    options: { duration: 1400, easing: 'ease-in-out' },
  },
  'equalizer-bars': {
    name: 'equalizer-bars', description: 'Child bars bounce like a level meter; each bar is offset in time.',
    target: 'children', stagger: 140, origin: 'center bottom',
    keyframes: [{ scale: 1 }, { scale: 0.25 }],
    options: { duration: 700, easing: 'ease-in-out', iterations: 'infinite', direction: 'alternate' },
    staticProgress: 0.5,
  },
  marquee: {
    name: 'marquee', description: 'Scroll left 200 units and loop; seamless if the content repeats every 200 units.',
    keyframes: [{ x: 0 }, { x: -200 }],
    options: { duration: 8000, easing: 'linear', iterations: 'infinite' },
  },
};

const ALLOWED_KEYS = new Set([
  'name', 'description', 'kind', 'keyframes', 'options', 'target', 'stagger', 'staggerFrom', 'origin', 'staticProgress',
]);
const ALLOWED_OPTS = new Set(['duration', 'delay', 'easing', 'iterations', 'direction']);
const DIRECTIONS = ['normal', 'reverse', 'alternate', 'alternate-reverse'];

/** Returns an array of human-readable problems; empty array = valid. */
export function validatePreset(p) {
  const errs = [];
  if (!p || typeof p !== 'object' || Array.isArray(p)) return ['preset must be an object'];
  const label = p.name ? `preset "${p.name}"` : 'preset';
  const err = (m) => errs.push(`${label}: ${m}`);
  for (const k of Object.keys(p)) if (!ALLOWED_KEYS.has(k)) err(`unknown key "${k}"`);
  if (typeof p.name !== 'string' || !/^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.test(p.name)) err('name must be kebab-case');
  if (typeof p.description !== 'string' || !p.description.trim()) err('description is required');
  const kind = p.kind ?? 'keyframes';
  if (!['keyframes', 'draw'].includes(kind)) err(`kind must be "keyframes" or "draw"`);
  if (kind === 'keyframes') {
    if (!Array.isArray(p.keyframes) || p.keyframes.length < 2) err('keyframes needs at least 2 entries');
    else p.keyframes.forEach((f, i) => {
      if (!f || typeof f !== 'object' || !Object.keys(f).length) err(`keyframes[${i}] must be a non-empty object`);
      else if ('offset' in f && !(f.offset >= 0 && f.offset <= 1)) err(`keyframes[${i}].offset must be 0..1`);
    });
  } else if (p.keyframes) err('draw presets must not define keyframes');
  if (p.target !== undefined && !['self', 'children'].includes(p.target)) err('target must be "self" or "children"');
  if (p.stagger !== undefined && !(typeof p.stagger === 'number' && p.stagger >= 0)) err('stagger must be a number >= 0');
  if (p.staggerFrom !== undefined) {
    try { staggerOrder(3, p.staggerFrom); } catch { err('staggerFrom must be start|end|center|edges|<index>'); }
  }
  if (p.staticProgress !== undefined && !(p.staticProgress >= 0 && p.staticProgress <= 1)) err('staticProgress must be 0..1');
  if (p.origin !== undefined && typeof p.origin !== 'string') err('origin must be a string');
  const o = p.options;
  if (o !== undefined) {
    if (!o || typeof o !== 'object') err('options must be an object');
    else {
      for (const k of Object.keys(o)) if (!ALLOWED_OPTS.has(k)) err(`unknown option "${k}"`);
      if (o.duration !== undefined && !(o.duration >= 0)) err('options.duration must be >= 0');
      if (o.delay !== undefined && !(o.delay >= 0)) err('options.delay must be >= 0');
      if (o.iterations !== undefined && o.iterations !== 'infinite' && !(o.iterations > 0)) err('options.iterations must be > 0 or "infinite"');
      if (o.direction !== undefined && !DIRECTIONS.includes(o.direction)) err(`options.direction must be one of ${DIRECTIONS.join(', ')}`);
      if (o.easing !== undefined) {
        try { resolveEasing(o.easing, { supportsLinear: false }); } catch { err(`options.easing "${o.easing}" is not a known easing`); }
      }
    }
  }
  return errs;
}

/** Add (or, with { replace: true }, overwrite) a preset. Throws if invalid. */
export function registerPreset(preset, { replace = false } = {}) {
  const errs = validatePreset(preset);
  if (errs.length) throw new Error(`svg-anim: invalid preset: ${errs.join('; ')}`);
  if (REGISTRY[preset.name] && !replace) throw new Error(`svg-anim: preset "${preset.name}" already exists`);
  REGISTRY[preset.name] = preset;
  return preset;
}

/** Short aliases used by data-anim="..." */
export const ALIASES = { draw: 'draw-stroke', fade: 'fade-in', equalizer: 'equalizer-bars' };

export function getPreset(name) {
  return REGISTRY[ALIASES[name] || name] || null;
}

export function listPresets() {
  return Object.values(REGISTRY).map(({ name, description }) => ({ name, description }));
}

/**
 * Load extra presets listed in a JSON manifest (see presets/index.json).
 * Manifest: { "version": 1, "presets": [ { "name": "x", "file": "x.json" } ] }; files are
 * resolved relative to the manifest URL. Invalid presets are skipped with a console warning.
 * Returns the names that were registered.
 */
export async function loadPresetManifest(url, { fetchImpl = globalThis.fetch } = {}) {
  const base = new URL(url, globalThis.location?.href ?? 'http://localhost/');
  const manifest = await (await fetchImpl(base)).json();
  const added = [];
  for (const entry of manifest.presets || []) {
    try {
      const res = await fetchImpl(new URL(entry.file, base));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      registerPreset(await res.json(), { replace: true });
      added.push(entry.name);
    } catch (e) {
      console.warn(`svg-anim: skipped preset "${entry.name}": ${e.message}`);
    }
  }
  return added;
}
