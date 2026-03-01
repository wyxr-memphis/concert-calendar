#!/bin/bash

# Run Flask backend locally for testing
# Usage: ./run_local_backend.sh

set -e

echo "🚀 Starting local Flask backend..."

# Check if .env exists
if [ -f .env ]; then
    echo "📝 Loading environment from .env"
    source .env
else
    echo "⚠️  No .env file found. Using environment variables from shell."
    echo "   Create .env from .env.example if you need to override variables."
fi

# Verify required variables
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL is not set"
    exit 1
fi

if [ -z "$ADMIN_PASSWORD" ]; then
    echo "❌ ERROR: ADMIN_PASSWORD is not set"
    exit 1
fi

if [ -z "$ADMIN_SECRET_KEY" ]; then
    echo "❌ ERROR: ADMIN_SECRET_KEY is not set"
    exit 1
fi

# Install dependencies if needed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Installing backend dependencies..."
    pip3 install -r backend/requirements.txt --break-system-packages
fi

# Set Flask environment
export FLASK_APP=backend.app
export FLASK_ENV=development
export PORT=5001

echo ""
echo "✅ Backend will run at: http://localhost:5001"
echo "✅ API endpoints at: http://localhost:5001/api/*"
echo "✅ Admin login at: http://localhost:5001/api/admin/login"
echo ""
echo "⚠️  Using port 5001 (port 5000 is often used by macOS AirPlay)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run Flask
python3 -m flask run --host=0.0.0.0 --port=5001
