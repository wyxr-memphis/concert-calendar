import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cubicBezier, spring, bounceOut, resolveEasing, toLinearCss, EASINGS } from '../src/easing.js';

const near = (a, b, eps = 1e-3) => assert.ok(Math.abs(a - b) < eps, `${a} !~ ${b}`);

test('every named easing starts at 0 and ends at 1', () => {
  for (const [name, { fn }] of Object.entries(EASINGS)) {
    near(fn(0), 0); near(fn(1), 1);
    assert.ok(Number.isFinite(fn(0.5)), name);
  }
});

test('linear and symmetric bezier midpoints', () => {
  near(resolveEasing('linear').fn(0.37), 0.37);
  near(EASINGS['ease-in-out'].fn(0.5), 0.5);
  near(cubicBezier(0.25, 0.25, 0.75, 0.75)(0.4), 0.4);
});

test('ease-in is slower than linear early; ease-out faster', () => {
  assert.ok(EASINGS['ease-in'].fn(0.25) < 0.25);
  assert.ok(EASINGS['ease-out'].fn(0.25) > 0.25);
});

test('back easing overshoots 1; spring overshoots then settles', () => {
  assert.ok(EASINGS['ease-out-back'].fn(0.7) > 1);
  const s = spring({ damping: 0.3 });
  assert.ok(Math.max(...Array.from({ length: 100 }, (_, i) => s(i / 99))) > 1.05);
  near(s(1), 1); near(s(0.999), 1, 0.02);
  assert.ok(Math.max(...Array.from({ length: 100 }, (_, i) => spring({ damping: 1 })(i / 99))) <= 1.0001);
});

test('bounceOut stays in 0..1', () => {
  for (let i = 0; i <= 50; i++) { const v = bounceOut(i / 50); assert.ok(v >= 0 && v <= 1.0001); }
});

test('resolveEasing accepts names, arrays, cubic-bezier strings, functions, spring objects', () => {
  assert.equal(resolveEasing('ease-in').css, 'cubic-bezier(0.42, 0, 1, 1)');
  assert.equal(resolveEasing([0.1, 0.2, 0.3, 0.4]).css, 'cubic-bezier(0.1, 0.2, 0.3, 0.4)');
  assert.equal(resolveEasing('cubic-bezier(0, 0, 1, 1)').css, 'cubic-bezier(0, 0, 1, 1)');
  assert.equal(resolveEasing((t) => t * t).css, null);
  assert.equal(resolveEasing({ spring: { damping: 0.5 } }, { supportsLinear: false }).css, null);
});

test('functions become linear() css only when supported', () => {
  assert.match(resolveEasing('spring', { supportsLinear: true }).css, /^linear\(0, /);
  assert.equal(resolveEasing('spring', { supportsLinear: false }).css, null);
  assert.equal(toLinearCss((t) => t, 4), 'linear(0, 0.25, 0.5, 0.75, 1)');
});

test('unknown easing throws', () => {
  assert.throws(() => resolveEasing('nope'), /unknown easing/);
  assert.throws(() => resolveEasing([1, 2, 3]), /unknown easing/);
});
