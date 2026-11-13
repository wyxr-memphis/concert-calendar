#!/bin/bash

# Serve frontend locally with Python's built-in HTTP server
# Usage: ./run_local_frontend.sh

set -e

echo "🌐 Starting local frontend server..."
echo ""
echo "✅ Frontend will run at: http://localhost:8000"
echo "✅ Homepage preview: http://localhost:8000/local_index_home.html"
echo "   (built live from docs/index.html, events from your local backend —"
echo "    start ./run_local_backend.sh first)"
echo "ℹ️  http://localhost:8000/ shows the layout but no events: the production"
echo "   API does not accept requests from localhost."
if [ -f docs/admin/local.html ]; then
    echo "✅ Local admin: http://localhost:8000/admin/local.html"
else
    echo "ℹ️  No docs/admin/local.html (it is gitignored) — the admin pages here"
    echo "   point at the PRODUCTION API. See LOCAL_DEVELOPMENT.md."
fi
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Mirrors vercel.json "cleanUrls": /thisweek serves thisweek.html.
# /local_index_home.html is generated on every request from docs/index.html
# with API_BASE pointed at the local backend, so it can never go stale.
cd docs && python3 - <<'PY'
import http.server, io, os, re

LOCAL_API = 'http://localhost:5001'
API_BASE_LINE = re.compile(r"const API_BASE = '[^']*';")

class CleanUrlHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.path.split('?', 1)[0].split('#', 1)[0]
        if path == '/local_index_home.html':
            return self.local_home()
        if path != '/' and not os.path.splitext(path)[1]:
            local = self.translate_path(path)
            if not os.path.exists(local) and os.path.isfile(local + '.html'):
                self.path = path + '.html' + self.path[len(path):]
        return super().send_head()

    def local_home(self):
        with open('index.html', encoding='utf-8') as f:
            page, n = API_BASE_LINE.subn(f"const API_BASE = '{LOCAL_API}';", f.read(), count=1)
        if n != 1:
            self.send_error(500, "No `const API_BASE = '...';` line in docs/index.html")
            return None
        body = page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        return io.BytesIO(body)

http.server.ThreadingHTTPServer(('', 8000), CleanUrlHandler).serve_forever()
PY
