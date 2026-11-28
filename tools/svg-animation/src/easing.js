// Easing functions. Pure (no DOM), so they can be unit-tested with plain node.
//
// resolveEasing(spec) -> { fn, css }
//   fn  : (t:0..1) => number   used by the requestAnimationFrame backend
//   css : string | null        used by the Web Animations backend; null means
//                              "not expressible in CSS here" (use the rAF backend)

/** Build a cubic-bezier easing function, same maths as CSS cubic-bezier(). */
export function cubicBezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t) => ((ax * t + bx) * t + cx) * t;
  const sy = (t) => ((ay * t + by) * t + cy) * t;
  const dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
  const solveX = (x) => {
    let t = x;
    for (let i = 0; i < 8; i++) { // Newton-Raphson
      const err = sx(t) - x;
      if (Math.abs(err) < 1e-6) return t;
      const d = dx(t);
      if (Math.abs(d) < 1e-6) break;
      t -= err / d;
    }
    let lo = 0, hi = 1; t = x; // bisection fallback
    while (lo < hi && hi - lo > 1e-6) {
      const v = sx(t);
      if (Math.abs(v - x) < 1e-6) return t;
      if (x > v) lo = t; else hi = t;
      t = (lo + hi) / 2;
    }
    return t;
  };
  return (t) => (t <= 0 ? 0 : t >= 1 ? 1 : sy(solveX(t)));
}

/**
 * Damped-spring step response, normalised so it starts at 0 and lands on 1 at t=1.
 * `damping` is the damping ratio: 1 = no overshoot, ~0.2 = very bouncy.
 */
export function spring({ damping = 0.35 } = {}) {
  const z = Math.min(Math.max(damping, 0.05), 1.5);
  const k = 6.9; // decay constant: envelope falls to ~0.1% by t=1
  return (t) => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    if (z >= 1) return 1 - (1 + k * t) * Math.exp(-k * t);
    const w = k / z, wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-k * t) * (Math.cos(wd * t) + (k / wd) * Math.sin(wd * t));
  };
}

export function bounceOut(t) {
  const n = 7.5625, d = 2.75;
  if (t < 1 / d) return n * t * t;
  if (t < 2 / d) return n * (t -= 1.5 / d) * t + 0.75;
  if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + 0.9375;
  return n * (t -= 2.625 / d) * t + 0.984375;
}

/** Sample any easing function into a CSS `linear(...)` timing function string. */
export function toLinearCss(fn, points = 48) {
  const stops = [];
  for (let i = 0; i <= points; i++) stops.push(+fn(i / points).toFixed(4));
  return `linear(${stops.join(', ')})`;
}

const bez = (x1, y1, x2, y2) => ({
  fn: cubicBezier(x1, y1, x2, y2),
  css: `cubic-bezier(${x1}, ${y1}, ${x2}, ${y2})`,
});

/** Named presets. Add an entry here to add an easing. */
export const EASINGS = {
  linear: { fn: (t) => t, css: 'linear' },
  ease: bez(0.25, 0.1, 0.25, 1),
  'ease-in': bez(0.42, 0, 1, 1),
  'ease-out': bez(0, 0, 0.58, 1),
  'ease-in-out': bez(0.42, 0, 0.58, 1),
  'ease-in-cubic': bez(0.32, 0, 0.67, 0),
  'ease-out-cubic': bez(0.33, 1, 0.68, 1),
  'ease-in-out-cubic': bez(0.65, 0, 0.35, 1),
  'ease-in-back': bez(0.36, 0, 0.66, -0.56),
  'ease-out-back': bez(0.34, 1.56, 0.64, 1),
  'ease-in-out-back': bez(0.68, -0.6, 0.32, 1.6),
  'ease-out-bounce': { fn: bounceOut, css: null },
  spring: { fn: spring(), css: null },
};

const CB_RE = /^cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)$/;

/** Does this browser support CSS linear() easing? (false under node) */
export function supportsLinearEasing() {
  try {
    return typeof CSS !== 'undefined' && CSS.supports('animation-timing-function', 'linear(0, 1)');
  } catch { return false; }
}

/**
 * Accepts: a name from EASINGS, 'cubic-bezier(a,b,c,d)', [a,b,c,d],
 * { spring: { damping } }, or a function (t)=>number. Throws on anything else.
 */
export function resolveEasing(spec = 'ease-out', { supportsLinear = supportsLinearEasing() } = {}) {
  let res;
  if (typeof spec === 'function') res = { fn: spec, css: null };
  else if (Array.isArray(spec) && spec.length === 4 && spec.every(Number.isFinite)) res = bez(...spec);
  else if (spec && typeof spec === 'object' && spec.spring) res = { fn: spring(spec.spring), css: null };
  else if (typeof spec === 'string') {
    const m = CB_RE.exec(spec.trim());
    if (m) res = bez(...m.slice(1).map(Number));
    else if (EASINGS[spec]) res = EASINGS[spec];
  }
  if (!res) throw new Error(`svg-anim: unknown easing ${JSON.stringify(spec)}`);
  if (res.css === null && supportsLinear) return { fn: res.fn, css: toLinearCss(res.fn) };
  return res;
}
