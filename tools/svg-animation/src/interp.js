// Value interpolation helpers (pure). Used by the rAF backend, attribute tweens and morph().

const NUM_RE = /-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/gi;
const HEX_RE = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

/** Split a string into literal pieces and numbers: "M1 2L3 4" -> { strings:['M',' ','L',' ',''], nums:[1,2,3,4] } */
export function parseTemplate(str) {
  const strings = [], nums = [];
  let last = 0;
  String(str).replace(NUM_RE, (m, offset) => {
    strings.push(str.slice(last, offset));
    nums.push(parseFloat(m));
    last = offset + m.length;
    return m;
  });
  strings.push(String(str).slice(last));
  return { strings, nums };
}

/** Two strings can be interpolated if they differ only in their numbers. */
export function canInterpolate(a, b) {
  const pa = parseTemplate(a), pb = parseTemplate(b);
  return pa.nums.length === pb.nums.length
    && pa.strings.length === pb.strings.length
    && pa.strings.every((s, i) => s === pb.strings[i]);
}

export function parseHex(str) {
  const m = HEX_RE.exec(str);
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

const round = (n) => +n.toFixed(4);

/** Interpolate numbers, #hex colours, or number-templates (transforms, path data, "10px 20px"). */
export function lerpValue(a, b, p) {
  if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * p;
  const ca = typeof a === 'string' && parseHex(a), cb = typeof b === 'string' && parseHex(b);
  if (ca && cb) {
    return `rgb(${ca.map((v, i) => Math.min(255, Math.max(0, Math.round(v + (cb[i] - v) * p)))).join(', ')})`;
  }
  const sa = String(a), sb = String(b);
  if (!canInterpolate(sa, sb)) return p < 1 ? a : b; // discrete flip at the end
  const ta = parseTemplate(sa), tb = parseTemplate(sb);
  let out = ta.strings[0];
  for (let i = 0; i < ta.nums.length; i++) {
    out += round(ta.nums[i] + (tb.nums[i] - ta.nums[i]) * p) + ta.strings[i + 1];
  }
  return out;
}

const SHORTHAND_DEFAULTS = { x: 0, y: 0, rotate: 0, scale: 1, skewX: 0 };

/**
 * Normalise keyframes:
 *  - { x, y, rotate, scale, skewX } shorthands become one consistent `transform` string
 *    (every keyframe gets the same function list so the strings interpolate)
 *  - accepts { from, to } form
 *  - { shorthand: false } leaves x/y/scale/rotate alone (attribute mode, where x and y are real attributes)
 * Returns a new array; never mutates input.
 */
export function normalizeKeyframes(spec, { shorthand = true } = {}) {
  let kfs = Array.isArray(spec) ? spec : spec && (spec.keyframes || [spec.from || {}, spec.to || {}]);
  if (!Array.isArray(kfs) || kfs.length < 2) throw new Error('svg-anim: need at least two keyframes');
  const used = !shorthand ? [] : Object.keys(SHORTHAND_DEFAULTS).filter((k) => kfs.some((f) => k in f));
  return kfs.map((f) => {
    const out = {};
    for (const [k, v] of Object.entries(f)) if (!shorthand || !(k in SHORTHAND_DEFAULTS)) out[k] = v;
    if (used.length) {
      const g = (k) => (k in f ? f[k] : SHORTHAND_DEFAULTS[k]);
      const parts = [];
      if (used.includes('x') || used.includes('y')) parts.push(`translate(${g('x')}px, ${g('y')}px)`);
      if (used.includes('rotate')) parts.push(`rotate(${g('rotate')}deg)`);
      if (used.includes('scale')) parts.push(`scale(${g('scale')})`);
      if (used.includes('skewX')) parts.push(`skewX(${g('skewX')}deg)`);
      out.transform = parts.join(' ');
    }
    return out;
  });
}

/** kebab-case or camelCase -> camelCase (for el.style[prop] and WAAPI). */
export const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

/**
 * Build sampler(progress) -> { prop: value } from normalised keyframes.
 * Keyframes may carry `offset`; otherwise they are spread evenly.
 */
export function buildSampler(keyframes) {
  const n = keyframes.length;
  const offsets = keyframes.map((f, i) => (typeof f.offset === 'number' ? f.offset : i / (n - 1)));
  const props = new Set();
  keyframes.forEach((f) => Object.keys(f).forEach((k) => { if (k !== 'offset' && k !== 'easing') props.add(k); }));
  const tracks = {};
  for (const prop of props) {
    tracks[prop] = keyframes.map((f, i) => [offsets[i], f[prop]]).filter(([, v]) => v !== undefined);
  }
  return (p) => {
    const out = {};
    for (const prop of props) {
      const tr = tracks[prop];
      if (tr.length === 1) { out[prop] = tr[0][1]; continue; }
      // Outside 0..1 (easing overshoot) we extrapolate along the first/last segment.
      let i = 0;
      if (p >= tr[tr.length - 1][0]) i = tr.length - 2;
      else while (i < tr.length - 2 && p > tr[i + 1][0]) i++;
      const [o0, v0] = tr[i], [o1, v1] = tr[i + 1];
      out[prop] = lerpValue(v0, v1, (p - o0) / (o1 - o0 || 1));
    }
    return out;
  };
}
