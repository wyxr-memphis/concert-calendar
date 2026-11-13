#!/bin/bash

# Serve frontend locally with Python's built-in HTTP server
# Usage: ./run_local_frontend.sh

set -e

echo "🌐 Starting local frontend server..."
echo ""
echo "✅ Frontend will run at: http://localhost:8000"
echo "✅ Homepage: http://localhost:8000/  (loads production data)"
if [ -f docs/admin/local.html ]; then
    echo "✅ Local admin: http://localhost:8000/admin/local.html"
    echo ""
    echo "⚠️  For the local admin, start the backend first: ./run_local_backend.sh"
else
    echo "ℹ️  No docs/admin/local.html (it is gitignored) — the admin pages here"
    echo "   point at the PRODUCTION API. See LOCAL_DEVELOPMENT.md."
fi
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Mirrors vercel.json "cleanUrls": /thisweek serves thisweek.html
cd docs && python3 - <<'PY'
import http.server, os

class CleanUrlHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.path.split('?', 1)[0].split('#', 1)[0]
        if path != '/' and not os.path.splitext(path)[1]:
            local = self.translate_path(path)
            if not os.path.exists(local) and os.path.isfile(local + '.html'):
                self.path = path + '.html' + self.path[len(path):]
        return super().send_head()

http.server.ThreadingHTTPServer(('', 8000), CleanUrlHandler).serve_forever()
PY
