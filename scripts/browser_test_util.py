"""Shared plumbing for the tests that drive docs/ in a real browser.

Both browser tests need the same two awkward things: locating a Chromium binary
across the several places a playwright install can leave one, and serving the
``docs/`` directory over HTTP (the page uses absolute ``/`` paths and localStorage,
neither of which behaves under ``file://``).

Import raises ``SkipTest`` rather than exiting, so the caller decides how to
report a machine without playwright — a browser test that silently vanishes is
how a green run hides a real gap.
"""

import functools
import http.server
import os
import socketserver
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


class SkipTest(Exception):
    """Raised when the environment cannot run a browser test at all."""


def require_playwright():
    """Return playwright's sync_playwright, or raise SkipTest."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SkipTest("playwright is not installed (pip install playwright)")
    return sync_playwright


def find_chrome():
    """Locate a Chromium binary, or raise SkipTest.

    Checks an explicit ``CHROME_PATH`` override first, then the caches a
    playwright install writes to. The macOS path matters: playwright puts its
    cache under ``~/Library/Caches``, not ``~/.cache``, and without it this
    silently skipped on every Mac.
    """
    explicit = os.environ.get("CHROME_PATH")
    if explicit and os.path.exists(explicit):
        return explicit

    roots = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        "/opt/pw-browsers",
        os.path.expanduser("~/.cache/ms-playwright"),
        os.path.expanduser("~/Library/Caches/ms-playwright"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in ("chrome", "headless_shell", "chrome-headless-shell"):
                if name in filenames:
                    candidate = os.path.join(dirpath, name)
                    if os.access(candidate, os.X_OK):
                        return candidate
    raise SkipTest(
        "no Chromium binary found (set CHROME_PATH or run: playwright install chromium)"
    )


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve_docs(port):
    """Serve docs/ on 127.0.0.1:port from a daemon thread."""
    def _run():
        socketserver.TCPServer.allow_reuse_address = True
        handler = functools.partial(_QuietHandler, directory=DOCS)
        with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
            httpd.serve_forever()

    threading.Thread(target=_run, daemon=True).start()
    return f"http://127.0.0.1:{port}"


class Checker:
    """Prints PASS/FAIL as it goes and remembers the failures."""

    def __init__(self):
        self.failures = []

    def __call__(self, label, cond, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}"
              + (f"  — {detail}" if detail else ""))
        if not cond:
            self.failures.append(label)

    def equals(self, label, actual, expected):
        """Assert equality, and say what was found when it differs.

        Distinct from __call__ on purpose: passing a value and an expectation to
        a truthiness check silently succeeds for any non-empty value and fails
        for a legitimately empty one — so "hash cleared" would fail on the empty
        string it was asserting.
        """
        ok = actual == expected
        print(f"  {'PASS' if ok else 'FAIL'}  {label}  — {actual!r}"
              + ("" if ok else f" (expected {expected!r})"))
        if not ok:
            self.failures.append(label)

    def section(self, title):
        print(f"\n{title}")

    def report(self, name):
        print()
        if self.failures:
            print(f"FAILED ({len(self.failures)}): " + ", ".join(self.failures))
            return 1
        print(f"All {name} checks passed.")
        return 0
