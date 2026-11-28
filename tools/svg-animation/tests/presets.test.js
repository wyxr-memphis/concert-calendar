import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { REGISTRY, validatePreset, registerPreset, getPreset, listPresets, loadPresetManifest, ALIASES } from '../src/presets.js';

const presetsDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'presets');
const readJson = (f) => JSON.parse(readFileSync(join(presetsDir, f), 'utf8'));

test('every built-in preset is valid and keyed by its own name', () => {
  for (const [key, p] of Object.entries(REGISTRY)) {
    assert.equal(p.name, key);
    assert.deepEqual(validatePreset(p), [], key);
  }
});

test('built-ins cover the documented set', () => {
  for (const n of ['fade-in', 'slide-up', 'pop', 'pulse', 'spin', 'wiggle', 'draw-stroke', 'equalizer-bars', 'marquee']) {
    assert.ok(REGISTRY[n], n);
  }
});

test('aliases point at real presets', () => {
  for (const target of Object.values(ALIASES)) assert.ok(REGISTRY[target], target);
  assert.equal(getPreset('draw').name, 'draw-stroke');
  assert.equal(getPreset('nope'), null);
});

test('validatePreset catches mistakes', () => {
  const ok = { name: 'ok-one', description: 'd', keyframes: [{ opacity: 0 }, { opacity: 1 }] };
  assert.deepEqual(validatePreset(ok), []);
  const bad = (patch) => validatePreset({ ...ok, ...patch });
  assert.ok(bad({ name: 'Bad Name' }).length);
  assert.ok(bad({ description: '' }).length);
  assert.ok(bad({ keyframes: [{ opacity: 0 }] }).length);
  assert.ok(bad({ keyframes: [{}, { opacity: 1 }] }).length);
  assert.ok(bad({ keyframes: [{ opacity: 0, offset: 2 }, { opacity: 1 }] }).length);
  assert.ok(bad({ options: { duration: -1 } }).length);
  assert.ok(bad({ options: { easing: 'wobbly' } }).length);
  assert.ok(bad({ options: { iterations: 0 } }).length);
  assert.ok(bad({ options: { speed: 2 } }).length);
  assert.ok(bad({ target: 'parent' }).length);
  assert.ok(bad({ staggerFrom: 'middle' }).length);
  assert.ok(bad({ staticProgress: 2 }).length);
  assert.ok(bad({ typo: true }).length);
  assert.ok(validatePreset(null).length);
  assert.ok(validatePreset({ name: 'd', description: 'x', kind: 'draw', keyframes: [{}, {}] }).length);
  assert.deepEqual(validatePreset({ name: 'd', description: 'x', kind: 'draw' }), []);
});

test('registerPreset adds, refuses duplicates, and can replace', () => {
  const p = { name: 'test-only-preset', description: 'tmp', keyframes: [{ opacity: 0 }, { opacity: 1 }] };
  registerPreset(p);
  assert.equal(getPreset('test-only-preset'), p);
  assert.throws(() => registerPreset(p), /already exists/);
  registerPreset({ ...p, description: 'new' }, { replace: true });
  assert.equal(REGISTRY['test-only-preset'].description, 'new');
  assert.throws(() => registerPreset({ name: 'x' }), /invalid preset/);
  delete REGISTRY['test-only-preset'];
  assert.ok(listPresets().every((x) => x.name && x.description));
});

test('presets/index.json manifest: files exist, are valid, and do not clash with built-ins', () => {
  const manifest = readJson('index.json');
  assert.equal(manifest.version, 1);
  const names = new Set();
  for (const entry of manifest.presets) {
    const p = readJson(entry.file);
    assert.equal(p.name, entry.name, `${entry.file} name must match manifest`);
    assert.deepEqual(validatePreset(p), [], entry.file);
    assert.ok(!(entry.name in REGISTRY), `${entry.name} clashes with a built-in`);
    assert.ok(!names.has(entry.name), `duplicate ${entry.name}`);
    names.add(entry.name);
  }
});

test('every preset json file in presets/ is listed in the manifest', () => {
  const listed = new Set(readJson('index.json').presets.map((e) => e.file));
  const files = readdirSync(presetsDir).filter((f) => f.endsWith('.json') && f !== 'index.json');
  for (const f of files) assert.ok(listed.has(f), `${f} is not listed in presets/index.json`);
});

test('loadPresetManifest registers valid presets and skips bad ones', async (t) => {
  const files = {
    'http://x.test/p/index.json': { presets: [{ name: 'load-ok', file: 'a.json' }, { name: 'load-bad', file: 'b.json' }] },
    'http://x.test/p/a.json': { name: 'load-ok', description: 'ok', keyframes: [{ opacity: 0 }, { opacity: 1 }] },
    'http://x.test/p/b.json': { name: 'load-bad' },
  };
  const fetchImpl = async (u) => ({ ok: String(u) in files, status: 404, json: async () => files[String(u)] });
  t.mock.method(console, 'warn', () => {});
  const added = await loadPresetManifest('http://x.test/p/index.json', { fetchImpl });
  assert.deepEqual(added, ['load-ok']);
  assert.ok(getPreset('load-ok') && !getPreset('load-bad'));
  delete REGISTRY['load-ok'];
});
