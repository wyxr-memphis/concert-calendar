/**
 * Tests for the GA4 URL-shaping helpers in docs/index.html.
 *
 * GA4 cuts every event parameter value at 100 characters, so raw ticket URLs
 * sent as `destination_url` on `external_link_click` arrived chopped mid-path.
 * analyticsUrl() reports host + path (no protocol, www, query or hash) capped
 * at 100; analyticsDomain() reports the bare hostname for grouping.
 *
 * The helper sources are extracted from the shipped page rather than copied,
 * so this fails if the real implementation regresses.
 *
 * Runs offline. Node only — no npm dependencies, no browser.
 *
 * Usage:
 *     node scripts/test_analytics_url.mjs
 */
import fs from 'fs';
import path from 'path';
import url from 'url';

const ROOT = path.dirname(path.dirname(url.fileURLToPath(import.meta.url)));

/** Extract a top-level `function name(...) { ... }` by brace matching. */
function grabFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`${name}() not found in docs/index.html`);
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

const NAMES = ['_analyticsTarget', 'analyticsUrl', 'analyticsDomain'];
const source = fs.readFileSync(path.join(ROOT, 'docs/index.html'), 'utf8');
const { analyticsUrl, analyticsDomain } = new Function(
    `${NAMES.map((n) => grabFunction(source, n)).join('\n')}; return {${NAMES.join(', ')}};`
)();

const FAILURES = [];

function check(label, cond, detail = '') {
    console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${label}${detail ? `  — ${detail}` : ''}`);
    if (!cond) FAILURES.push(label);
}

function eq(label, got, want) {
    check(label, got === want, got === want ? '' : `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

// ---------------------------------------------------------------------------
// The four URLs GA showed arriving cut off. The full originals are
// reconstructed: GA only kept the first 100 characters.

const LONG_HITONE = 'https://hitonecafe.com/event/choir-boy-optic-sink-decoration-policy-small-room-downstairs/hi-tone-cafe/';
const EVENTIM = 'https://wl.eventim.us/event/mike-cooley-of-drive-by-truckers-at-hernandos-hide-a-way/705991?afflky=HernandosHideAWay';
const TICKETMASTER = 'https://www.ticketmaster.com/medium-build-presents-the-king-of-memphis-tennessee-11-12-2026/event/1B006336A1B2C3D4';
const GOOGLE_WRAPPED = 'https://www.google.com/url?q=https://www.eventbrite.com/e/the-green-house-party-tickets-2001018191277?aff=ebdssbdestsearch&sa=D&source=calendar&usg=AOvVaw0';

console.log('\nThe four examples from GA');
eq('hi-tone: protocol dropped, 95 chars so nothing trimmed',
    analyticsUrl(LONG_HITONE),
    'hitonecafe.com/event/choir-boy-optic-sink-decoration-policy-small-room-downstairs/hi-tone-cafe/');
eq('eventim: afflky query stripped, full path kept',
    analyticsUrl(EVENTIM),
    'wl.eventim.us/event/mike-cooley-of-drive-by-truckers-at-hernandos-hide-a-way/705991');
eq('ticketmaster: www dropped, 102-char path trimmed to 100 with …',
    analyticsUrl(TICKETMASTER),
    'ticketmaster.com/medium-build-presents-the-king-of-memphis-tennessee-11-12-2026/event/1B006336A1B2C…');
eq('google redirect unwrapped to the eventbrite target, its query stripped',
    analyticsUrl(GOOGLE_WRAPPED),
    'eventbrite.com/e/the-green-house-party-tickets-2001018191277');

console.log('\ndestination_domain');
eq('hi-tone domain', analyticsDomain(LONG_HITONE), 'hitonecafe.com');
eq('eventim domain keeps its subdomain', analyticsDomain(EVENTIM), 'wl.eventim.us');
eq('ticketmaster domain drops www', analyticsDomain(TICKETMASTER), 'ticketmaster.com');
eq('google redirect reports the target domain', analyticsDomain(GOOGLE_WRAPPED), 'eventbrite.com');
eq('malformed URL gives an empty domain', analyticsDomain('not a url'), '');
eq('missing URL gives an empty domain', analyticsDomain(undefined), '');

console.log('\nShort and odd inputs');
eq('short URL passes through minus protocol/www/query/hash',
    analyticsUrl('https://www.growlersmemphis.com/tickets?popup=1&feature_id=9#top'),
    'growlersmemphis.com/tickets');
eq('bare domain has no trailing slash', analyticsUrl('https://www.ticketmaster.com/'), 'ticketmaster.com');
eq('http works too', analyticsUrl('http://example.org/show'), 'example.org/show');
eq('malformed URL falls back to the raw string', analyticsUrl('not a url'), 'not a url');
check('malformed URL longer than 100 is cut to 100', analyticsUrl('x'.repeat(250)).length === 100);
eq('missing URL gives an empty string, not "undefined"', analyticsUrl(undefined), '');
eq('google link that is not a redirect is reported as itself',
    analyticsUrl('https://www.google.com/maps/place/Growlers'), 'google.com/maps/place/Growlers');
eq('google redirect with an unparseable target falls back',
    analyticsUrl('https://www.google.com/url?q=nonsense'), 'https://www.google.com/url?q=nonsense');

console.log('\nThe 100-character limit');
const host = 'tickets.example.com';
const exact = `https://${host}/${'a'.repeat(100 - host.length - 1)}`;
eq('exactly 100 characters passes through untrimmed', analyticsUrl(exact), exact.slice('https://'.length));
const over = analyticsUrl(exact + 'b');
check('101 characters is trimmed to exactly 100', over.length === 100, `length ${over.length}`);
check('trimmed value ends with …', over.endsWith('…'));
check('trimmed value keeps the full hostname', over.startsWith(host + '/'));
const hugeHost = analyticsUrl(`https://${'sub.'.repeat(40)}example.com/path`);
check('a hostname over 100 characters is still capped at 100', hugeHost.length === 100, `length ${hugeHost.length}`);
for (const u of [LONG_HITONE, EVENTIM, TICKETMASTER, GOOGLE_WRAPPED, 'https://a.com/' + 'p/'.repeat(500)]) {
    const out = analyticsUrl(u);
    check(`≤ 100: ${out.slice(0, 40)}…`, out.length <= 100, `length ${out.length}`);
}

// ---------------------------------------------------------------------------

console.log('');
if (FAILURES.length) {
    console.log(`${FAILURES.length} FAILED`);
    process.exit(1);
}
console.log('All analytics URL tests passed');
