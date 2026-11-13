import { test } from 'node:test';
import assert from 'node:assert/strict';
import { totalSpan, computeState, staggerOrder, layout } from '../src/timeline-math.js';

test('totalSpan', () => {
  assert.equal(totalSpan({ delay: 100, duration: 500, iterations: 2 }), 1100);
  assert.equal(totalSpan({ duration: 500, iterations: Infinity }), Infinity);
  assert.equal(totalSpan({ delay: 50, duration: 0, iterations: Infinity }), 50);
});

test('computeState phases', () => {
  const t = { delay: 100, duration: 200, iterations: 1 };
  assert.deepEqual(computeState(50, t), { phase: 'before', iteration: 0, progress: 0 });
  assert.equal(computeState(200, t).progress, 0.5);
  assert.deepEqual(computeState(300, t), { phase: 'after', iteration: 0, progress: 1 });
  assert.equal(computeState(9999, t).progress, 1);
});

test('computeState iterations and directions', () => {
  const base = { duration: 100, iterations: 3 };
  assert.equal(computeState(150, base).iteration, 1);
  assert.equal(computeState(150, base).progress, 0.5);
  assert.equal(computeState(125, { ...base, direction: 'alternate' }).progress, 0.75); // iteration 1 reversed
  assert.equal(computeState(25, { ...base, direction: 'reverse' }).progress, 0.75);
  assert.equal(computeState(25, { ...base, direction: 'alternate-reverse' }).progress, 0.75);
});

test('alternate ends where the last iteration ends', () => {
  // 2 iterations alternate: it0 forward (0->1), it1 backward (1->0) so finishes at 0
  assert.equal(computeState(500, { duration: 100, iterations: 2, direction: 'alternate' }).progress, 0);
  // 3 iterations: it2 forward -> ends at 1
  assert.equal(computeState(500, { duration: 100, iterations: 3, direction: 'alternate' }).progress, 1);
});

test('fractional and infinite iterations', () => {
  assert.equal(computeState(1000, { duration: 100, iterations: 1.5 }).progress, 0.5);
  const inf = { duration: 100, iterations: Infinity };
  assert.equal(computeState(1250, inf).phase, 'active');
  assert.equal(computeState(1250, inf).progress, 0.5);
});

test('zero duration jumps to the end after the delay', () => {
  assert.equal(computeState(0, { delay: 10, duration: 0 }).phase, 'before');
  assert.equal(computeState(10, { delay: 10, duration: 0 }).progress, 1);
});

test('staggerOrder', () => {
  assert.deepEqual(staggerOrder(4, 'start'), [0, 1, 2, 3]);
  assert.deepEqual(staggerOrder(4, 'end'), [3, 2, 1, 0]);
  assert.deepEqual(staggerOrder(5, 'center'), [2, 1, 0, 1, 2]);
  assert.deepEqual(staggerOrder(5, 'edges'), [0, 1, 2, 1, 0]);
  assert.deepEqual(staggerOrder(4, 1), [1, 0, 1, 2]);
  assert.throws(() => staggerOrder(3, 'bogus'), /stagger/);
});

test('layout: sequence, parallel, stagger', () => {
  assert.deepEqual(layout([100, 200, 50], 'sequence'), { offsets: [0, 100, 300], span: 350 });
  assert.deepEqual(layout([100, 200, 50], 'sequence', { gap: 10 }), { offsets: [0, 110, 320], span: 370 });
  assert.deepEqual(layout([100, 200, 50], 'parallel'), { offsets: [0, 0, 0], span: 200 });
  assert.deepEqual(layout([100, 100, 100], 'stagger', { each: 40 }), { offsets: [0, 40, 80], span: 180 });
  assert.deepEqual(layout([100, 100, 100], 'stagger', { each: 40, from: 'end' }), { offsets: [80, 40, 0], span: 180 });
  assert.deepEqual(layout([], 'sequence'), { offsets: [], span: 0 });
  assert.throws(() => layout([1], 'nope'), /unknown layout/);
});
