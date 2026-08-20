/**
 * Shared admin utilities — authentication, API calls, navigation.
 *
 * Include this script on every admin page:
 *   <script src="/admin/admin-common.js"></script>
 *
 * Configuration:
 *   Set window.__API_BASE before including this script to point to
 *   the Render backend URL.
 */

const AdminAPI = (() => {
    // API base URL — must be set via window.__API_BASE
    const BASE = window.__API_BASE || '';

    function getToken() {
        return sessionStorage.getItem('admin_token');
    }

    function setToken(token) {
        sessionStorage.setItem('admin_token', token);
    }

    function clearToken() {
        sessionStorage.removeItem('admin_token');
    }

    function headers(extra = {}) {
        const h = { ...extra };
        const token = getToken();
        if (token) {
            h['Authorization'] = 'Bearer ' + token;
        }
        return h;
    }

    async function apiFetch(path, opts = {}) {
        const url = BASE ? BASE + path : path;
        opts.credentials = BASE ? 'include' : 'same-origin';
        opts.headers = headers(opts.headers || {});

        // Add timeout (default 30 seconds, configurable)
        const timeout = opts.timeout || 30000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            opts.signal = controller.signal;
            const response = await fetch(url, opts);
            clearTimeout(timeoutId);
            return response;
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                throw new Error('Request timeout - backend may be cold starting. Please wait 30 seconds and refresh.');
            }
            throw err;
        }
    }

    async function apiJSON(path, opts = {}) {
        const resp = await apiFetch(path, opts);
        if (resp.status === 401) {
            clearToken();
            window.location.href = '/admin/login.html';
            throw new Error('Not authenticated');
        }
        let data;
        try {
            data = await resp.json();
        } catch {
            throw new Error(`Server error (${resp.status}) — backend may be cold starting, try again`);
        }
        return { resp, data };
    }

    async function checkAuth() {
        try {
            const resp = await apiFetch('/api/admin/me', { timeout: 30000 });
            if (!resp.ok) {
                console.error('Auth check failed:', resp.status);
                window.location.href = '/admin/login.html';
                return false;
            }
            return true;
        } catch (err) {
            console.error('Auth check error:', err.message);
            // Show error message before redirecting
            if (err.message.includes('timeout')) {
                alert('Backend is taking too long to respond (cold start). Please wait 30 seconds and try again.');
            }
            window.location.href = '/admin/login.html';
            return false;
        }
    }

    async function logout() {
        await apiFetch('/api/admin/logout', { method: 'POST' });
        clearToken();
        window.location.href = '/admin/login.html';
    }

    return { apiFetch, apiJSON, checkAuth, logout, getToken, setToken, clearToken, headers };
})();

// Escape HTML text content. Encodes &, < and > but NOT quotes, so this is only
// safe between tags — never inside an attribute value. Use escAttr() there.
function esc(str) {
    const el = document.createElement('span');
    el.textContent = str || '';
    return el.innerHTML;
}

// Escape for an HTML attribute value. Required anywhere a value is interpolated
// into a quoted attribute: esc() leaves quotes intact, so a value containing one
// closes the attribute early. That was a stored-XSS vector in the admin origin —
// API key names arrive from the unauthenticated POST /api/request-key and were
// interpolated into single-quoted inline onclick handlers, which put attacker
// script in the same origin as sessionStorage.admin_token.
function escAttr(str) {
    return esc(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Reject URL schemes that can execute script, for values reaching an href or
// src. Sponsor and event image URLs are admin-entered but pass through scrapers
// and OCR too, and escaping alone does not stop a "javascript:" value.
// Scheme-less values (relative paths) pass through untouched.
function safeUrl(url) {
    const raw = (url == null ? '' : String(url)).trim();
    if (!raw) return '';
    // Control characters and whitespace can smuggle a scheme past this test
    // ("java\tscript:"), so probe a stripped copy.
    const probe = raw.replace(/[\u0000-\u0020]/g, '').toLowerCase();
    const scheme = probe.match(/^([a-z][a-z0-9+.\-]*):/);
    if (scheme && !['http', 'https', 'mailto', 'tel'].includes(scheme[1])) {
        return '';
    }
    return raw;
}

// Show status message
function showStatus(msg, type, containerId = 'statusBar') {
    const bar = document.getElementById(containerId);
    if (!bar) return;
    bar.textContent = msg;
    bar.className = 'status-bar ' + type;
    if (type !== 'error') {
        setTimeout(() => { bar.className = 'status-bar'; }, 5000);
    }
}

// Relative time display
function timeAgo(dateStr) {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffMin < 1) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
