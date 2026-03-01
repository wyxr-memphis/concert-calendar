#!/bin/bash

# Serve frontend locally with Python's built-in HTTP server
# Usage: ./run_local_frontend.sh

set -e

echo "🌐 Starting local frontend server..."
echo ""
echo "✅ Frontend will run at: http://localhost:8000"
echo "✅ Homepage: http://localhost:8000/docs/"
echo "✅ Admin: http://localhost:8000/docs/admin/local.html"
echo ""
echo "⚠️  Make sure the backend is running first: ./run_local_backend.sh"
echo ""
echo "Press Ctrl+C to stop"
echo ""

cd docs && python3 -m http.server 8000
