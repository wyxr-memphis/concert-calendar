// Pure timeline maths shared by the rAF backend and the group/sequence layout.
// Times are milliseconds. "Span" = total time an animation occupies, delay included.

/** Total span of an animation: delay + duration * iterations (Infinity if looping forever). */
export function totalSpan({ delay = 0, duration = 0, iterations = 1 } = {}) {
  if (iterations === Infinity) return duration > 0 ? Infinity : delay;
  return delay + duration * iterations;
}

/**
 * Where is an animation at time `t`?
 * Returns { phase: 'before'|'active'|'after', iteration, progress }
 * `progress` is 0..1 AFTER applying `direction`, BEFORE easing (same as the Web Animations spec).
 */
export function computeState(t, { delay = 0, duration = 0, iterations = 1, direction = 'normal' } = {}) {
  const flip = (it, p) => {
    const rev = direction === 'reverse'
      || (direction === 'alternate' && it % 2 === 1)
      || (direction === 'alternate-reverse' && it % 2 === 0);
    return rev ? 1 - p : p;
  };
  const at = t - delay;
  if (at < 0) return { phase: 'before', iteration: 0, progress: flip(0, 0) };
  if (duration <= 0) {
    const last = Number.isFinite(iterations) ? Math.max(Math.ceil(iterations) - 1, 0) : 0;
    return { phase: 'after', iteration: last, progress: flip(last, 1) };
  }
  const active = duration * iterations;
  if (Number.isFinite(active) && at >= active) {
    const iteration = Math.max(Math.ceil(iterations) - 1, 0);
    const frac = iterations % 1 === 0 ? 1 : iterations % 1;
    return { phase: 'after', iteration, progress: flip(iteration, frac) };
  }
  const raw = at / duration;
  const iteration = Math.floor(raw);
  return { phase: 'active', iteration, progress: flip(iteration, raw - iteration) };
}

/** Per-item stagger multipliers: which "slot" each item occupies given a start point. */
export function staggerOrder(count, from = 'start') {
  const idx = Array.from({ length: count }, (_, i) => i);
  if (from === 'start') return idx;
  if (from === 'end') return idx.map((i) => count - 1 - i);
  if (from === 'center') return idx.map((i) => Math.abs(i - (count - 1) / 2));
  if (from === 'edges') return idx.map((i) => (count - 1) / 2 - Math.abs(i - (count - 1) / 2));
  if (Number.isInteger(from) && from >= 0 && from < count) return idx.map((i) => Math.abs(i - from));
  throw new Error(`svg-anim: bad stagger "from" ${JSON.stringify(from)}`);
}

/**
 * Compute start offsets for a list of item spans.
 *   mode 'sequence': each starts when the previous ends (+ gap)
 *   mode 'parallel': all start at 0
 *   mode 'stagger' : item i starts at slot(i) * each
 * Returns { offsets: number[], span: number } where span is the whole group's span.
 */
export function layout(spans, mode = 'sequence', { gap = 0, each = 0, from = 'start' } = {}) {
  let offsets;
  if (mode === 'sequence') {
    offsets = [];
    let cursor = 0;
    for (const s of spans) { offsets.push(cursor); cursor += s + gap; }
  } else if (mode === 'parallel') {
    offsets = spans.map(() => 0);
  } else if (mode === 'stagger') {
    offsets = staggerOrder(spans.length, from).map((slot) => slot * each);
  } else {
    throw new Error(`svg-anim: unknown layout mode "${mode}"`);
  }
  const span = spans.reduce((m, s, i) => Math.max(m, offsets[i] + s), 0);
  return { offsets, span };
}
