/**
 * Regression tests for the front-end escaping helpers.
 *
 * These pin the three XSS holes fixed in REVIEW.md 1.4:
 *
 *   1. esc() encodes &, < and > but not quotes, yet it was interpolated into
 *      HTML *attributes* on the public page (data-neighborhood, aria-label,
 *      src, data-raw, sponsor href/src). Event titles containing a double
 *      quote are real data, so this broke out of the attribute today.
 *   2. Event descriptions were assigned with innerHTML.
 *   3. Admin API-key names — which arrive from the *unauthenticated*
 *      POST /api/request-key — were interpolated into single-quoted inline
 *      onclick handlers, putting attacker script in the admin origin where
 *      sessionStorage.admin_token lives.
 *
 * The helper sources are extracted from the real files rather than copied, so
 * this fails if the shipped implementation regresses.
 *
 * Runs offline. Node only — no npm dependencies, no browser.
 *
 * Usage:
 *     node scripts/test_escaping.mjs
 */
import fs from 'fs';
import path from 'path';
import url from 'url';

const ROOT = path.dirname(path.dirname(url.fileURLToPath(import.meta.url)));

// Minimal shim reproducing how a browser encodes textContent -> innerHTML.
// esc() relies on that round-trip, so the tests need it to resolve at all.
globalThis.document = {
    createElement: () => ({
        set textContent(v) { this._t = v; },
        get innerHTML() {
            return String(this._t)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
    }),
};

/** Extract a top-level `function name(...) { ... }` by brace matching. */
function grabFunction(source, name, where) {
    const start = source.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`${name}() not found in ${where}`);
    let depth = 0, started = false, i = start;
    for (; i < source.length; i++) {
        if (source[i] === '{') { depth++; started = true; }
        else if (source[i] === '}') {
            depth--;
            if (started && depth === 0) { i++; break; }
        }
    }
    return source.slice(start, i);
}

function loadHelpers(file, names) {
    const source = fs.readFileSync(path.join(ROOT, file), 'utf8');
    const src = names.map((n) => grabFunction(source, n, file)).join('\n');
    return new Function(`${src}; return {${names.join(', ')}};`)();
}

const FAILURES = [];

function check(label, cond, detail = '') {
    console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${label}${detail ? `  — ${detail}` : ''}`);
    if (!cond) FAILURES.push(label);
}

function eq(label, got, want) {
    check(label, got === want, got === want ? '' : `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

// ---------------------------------------------------------------------------

const page = loadHelpers('docs/index.html', ['esc', 'escAttr', 'safeUrl']);
const admin = loadHelpers('docs/admin/admin-common.js', ['esc', 'escAttr']);

function testAttributeEscaping(name, escAttr) {
    console.log(`\n${name}: a quote can no longer close an attribute`);
    check('double quote is encoded',
        !escAttr('a" onerror="alert(1)').includes('"'),
        escAttr('a" onerror="alert(1)'));
    check('single quote is encoded',
        !escAttr("a' onerror='alert(1)").includes("'"),
        escAttr("a' onerror='alert(1)"));
    // A title that exists in the production database today.
    eq('real quoted title stays readable',
        escAttr('Elizabeth Barraclough\'s "Hi"'),
        'Elizabeth Barraclough&#39;s &quot;Hi&quot;');
    eq('angle brackets still encoded',
        escAttr('<img src=x onerror=alert(1)>'),
        '&lt;img src=x onerror=alert(1)&gt;');
    eq('ampersand is not double-encoded', escAttr('Rock & Roll'), 'Rock &amp; Roll');
    eq('empty input is empty', escAttr(''), '');
    eq('null input is empty', escAttr(null), '');
}

function testTextEscaping(name, esc) {
    console.log(`\n${name}: text content`);
    eq('tags are encoded', esc('<script>alert(1)</script>'),
        '&lt;script&gt;alert(1)&lt;/script&gt;');
    eq('quotes are left alone in text context', esc('say "hi"'), 'say "hi"');
}

function testSafeUrl(safeUrl) {
    console.log('\nsafeUrl: script-bearing schemes are rejected');
    for (const bad of [
        'javascript:alert(1)',
        'JavaScript:alert(1)',
        '   javascript:alert(1)',
        'java\tscript:alert(1)',
        'java\nscript:alert(1)',
        'data:text/html,<script>alert(1)</script>',
        'vbscript:msgbox(1)',
        'file:///etc/passwd',
    ]) {
        eq(`rejected ${JSON.stringify(bad)}`, safeUrl(bad), '');
    }

    console.log('\nsafeUrl: legitimate URLs pass through untouched');
    for (const good of [
        'https://example.com/x?a=1&b=2',
        'http://example.com',
        '//res.cloudinary.com/wyxr/image/upload/v1/y.jpg',
        '/event-images/foo.jpg',
        'event-images/foo.jpg',          // legacy relative path
        'mailto:booking@example.com',
        'tel:+19015550123',
        '#anchor',
    ]) {
        eq(`preserved ${good}`, safeUrl(good), good);
    }
    eq('null is empty', safeUrl(null), '');
    eq('undefined is empty', safeUrl(undefined), '');
    eq('whitespace is empty', safeUrl('   '), '');
}

function testNoEscInAttributes() {
    console.log('\nno esc() left inside an attribute value');
    for (const file of ['docs/index.html', 'docs/admin/index.html']) {
        const source = fs.readFileSync(path.join(ROOT, file), 'utf8');
        const offenders = source
            .split('\n')
            .map((line, i) => [i + 1, line])
            .filter(([, line]) => /="\$\{esc\(/.test(line));
        check(`${file} uses escAttr in attributes`, offenders.length === 0,
            offenders.map(([n]) => `line ${n}`).join(', '));
    }
}

function testDescriptionNotInnerHtml() {
    console.log('\nevent description is not assigned via innerHTML');
    const source = fs.readFileSync(path.join(ROOT, 'docs/index.html'), 'utf8');
    check('descEl uses textContent',
        !/descEl\.innerHTML\s*=\s*ev\.description/.test(source));
}

console.log('Front-end escaping regression tests (offline)');
testAttributeEscaping('public page', page.escAttr);
testTextEscaping('public page', page.esc);
testSafeUrl(page.safeUrl);
testAttributeEscaping('admin', admin.escAttr);
testTextEscaping('admin', admin.esc);
testNoEscInAttributes();
testDescriptionNotInnerHtml();

console.log('');
if (FAILURES.length) {
    console.log(`FAILED (${FAILURES.length}): ${FAILURES.join(', ')}`);
    process.exit(1);
}
console.log('All escaping regression tests passed.');
