import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTemplate, canInterpolate, lerpValue, normalizeKeyframes, buildSampler, camel, parseHex } from '../src/interp.js';

test('parseTemplate splits numbers from text', () => {
  const t = parseTemplate('M10 -5.5L.5 2e1');
  assert.deepEqual(t.nums, [10, -5.5, 0.5, 20]);
  assert.deepEqual(t.strings, ['M', ' ', 'L', ' ', '']);
});

test('canInterpolate needs identical skeletons', () => {
  assert.ok(canInterpolate('M0 0 L10 10 Z', 'M5 5 L20 30 Z'));
  assert.ok(!canInterpolate('M0 0 L10 10 Z', 'M5 5 C20 30 1 2 3 4 Z'));
  assert.ok(!canInterpolate('M0 0 L10 10', 'M0 0 L10 10 L1 1'));
});

test('lerpValue: numbers, templates, colours, discrete', () => {
  assert.equal(lerpValue(0, 10, 0.25), 2.5);
  assert.equal(lerpValue('translate(0px, 10px)', 'translate(20px, 30px)', 0.5), 'translate(10px, 20px)');
  assert.equal(lerpValue('#000000', '#ff8000', 0.5), 'rgb(128, 64, 0)');
  assert.equal(lerpValue('#fff', '#000', 1), 'rgb(0, 0, 0)');
  assert.equal(lerpValue('none', 'block', 0.5), 'none');
  assert.equal(lerpValue('none', 'block', 1), 'block');
  assert.equal(lerpValue(0, 10, 1.2), 12); // overshoot extrapolates
  assert.equal(lerpValue('#000', '#fff', 2), 'rgb(255, 255, 255)'); // colours clamp
});

test('parseHex', () => {
  assert.deepEqual(parseHex('#f80'), [255, 136, 0]);
  assert.equal(parseHex('red'), null);
});

test('normalizeKeyframes folds shorthands into one transform string', () => {
  const k = normalizeKeyframes([{ opacity: 0, y: 24 }, { opacity: 1, y: 0, scale: 1.2 }]);
  assert.equal(k[0].transform, 'translate(0px, 24px) scale(1)');
  assert.equal(k[1].transform, 'translate(0px, 0px) scale(1.2)');
  assert.deepEqual(Object.keys(k[0]).sort(), ['opacity', 'transform']);
});

test('normalizeKeyframes: from/to form, attribute mode, errors, no mutation', () => {
  const input = [{ x: 1 }, { x: 2 }];
  normalizeKeyframes(input);
  assert.deepEqual(input, [{ x: 1 }, { x: 2 }]);
  assert.equal(normalizeKeyframes({ from: { rotate: 0 }, to: { rotate: 90 } })[1].transform, 'rotate(90deg)');
  assert.deepEqual(normalizeKeyframes([{ x: 1 }, { x: 2 }], { shorthand: false }), [{ x: 1 }, { x: 2 }]);
  assert.throws(() => normalizeKeyframes([{ a: 1 }]), /two keyframes/);
});

test('camel', () => assert.equal(camel('stroke-dashoffset'), 'strokeDashoffset'));

test('buildSampler: even offsets, explicit offsets, extrapolation', () => {
  const s = buildSampler([{ a: 0 }, { a: 10 }, { a: 0 }]);
  assert.equal(s(0.25).a, 5); assert.equal(s(0.5).a, 10); assert.equal(s(1).a, 0);
  const o = buildSampler([{ a: 0 }, { a: 10, offset: 0.2 }, { a: 20 }]);
  assert.equal(o(0.1).a, 5); assert.equal(o(0.6).a, 15);
  assert.equal(buildSampler([{ a: 0 }, { a: 10 }])(1.5).a, 15);
  assert.equal(buildSampler([{ a: 0 }, { a: 10 }])(-0.5).a, -5);
});

test('buildSampler handles props missing from some keyframes', () => {
  const s = buildSampler([{ a: 0, b: 1 }, { a: 5 }, { a: 10, b: 3 }]);
  assert.equal(s(0.5).b, 2);
});
