#!/bin/bash

# Pre-push test script - Run this before pushing to main
# Usage: ./test_before_push.sh

set -e

echo "🧪 Running pre-push checks..."
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0

# Check 1: Environment variables
echo "1️⃣  Checking environment variables..."
if [ -f .env ]; then
    source .env
    if [ -z "$DATABASE_URL" ]; then
        echo -e "${RED}   ✗ DATABASE_URL not set${NC}"
        FAILED=$((FAILED + 1))
    else
        echo -e "${GREEN}   ✓ DATABASE_URL is set${NC}"
        PASSED=$((PASSED + 1))
    fi

    if [ -z "$ADMIN_PASSWORD" ]; then
        echo -e "${RED}   ✗ ADMIN_PASSWORD not set${NC}"
        FAILED=$((FAILED + 1))
    else
        echo -e "${GREEN}   ✓ ADMIN_PASSWORD is set${NC}"
        PASSED=$((PASSED + 1))
    fi
else
    echo -e "${YELLOW}   ⚠ No .env file found (using shell environment)${NC}"
fi
echo ""

# Check 2: Python dependencies
echo "2️⃣  Checking Python dependencies..."
if python3 -c "import flask, psycopg2, requests, bs4" 2>/dev/null; then
    echo -e "${GREEN}   ✓ All required Python packages installed${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}   ✗ Missing Python packages${NC}"
    echo "   Run: pip3 install -r requirements.txt --break-system-packages"
    FAILED=$((FAILED + 1))
fi
echo ""

# Check 3: Database connection
echo "3️⃣  Testing database connection..."
if [ -z "$DATABASE_URL" ]; then
    echo -e "${YELLOW}   ⚠ Skipped (no DATABASE_URL)${NC}"
else
    if python3 -c "from backend.db import init_db; init_db()" 2>/dev/null; then
        echo -e "${GREEN}   ✓ Database connection successful${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}   ✗ Database connection failed${NC}"
        echo "   Check your DATABASE_URL format"
        FAILED=$((FAILED + 1))
    fi
fi
echo ""

# Check 4: No API keys in code
echo "4️⃣  Checking for exposed API keys..."
if git grep -iE "(api_key|secret_key|password)\s*=\s*['\"][^'\"]{10,}" src/ backend/ docs/ 2>/dev/null | grep -v ".example" | grep -v "settings.local.json"; then
    echo -e "${RED}   ✗ Found potential API keys in code!${NC}"
    echo "   Remove hardcoded secrets before pushing"
    FAILED=$((FAILED + 1))
else
    echo -e "${GREEN}   ✓ No exposed API keys found${NC}"
    PASSED=$((PASSED + 1))
fi
echo ""

# Check 5: Python syntax
echo "5️⃣  Checking Python syntax..."
SYNTAX_ERRORS=0
for file in $(find src/ backend/ -name "*.py" 2>/dev/null); do
    if ! python3 -m py_compile "$file" 2>/dev/null; then
        echo -e "${RED}   ✗ Syntax error in $file${NC}"
        SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
done
if [ $SYNTAX_ERRORS -eq 0 ]; then
    echo -e "${GREEN}   ✓ All Python files have valid syntax${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}   ✗ Found $SYNTAX_ERRORS file(s) with syntax errors${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

# Check 6: Health check regression tests (offline — no DB, no network)
echo "6️⃣  Running health check regression tests..."
if python3 scripts/test_health_check.py > /tmp/health_check_tests.log 2>&1; then
    echo -e "${GREEN}   ✓ Health check regression tests passed${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}   ✗ Health check regression tests failed${NC}"
    tail -20 /tmp/health_check_tests.log | sed 's/^/     /'
    FAILED=$((FAILED + 1))
fi
echo ""

# Check 7: Normalization regression tests (offline — no DB, no network)
echo "7️⃣  Running normalization regression tests..."
if python3 scripts/test_normalization.py > /tmp/normalization_tests.log 2>&1; then
    echo -e "${GREEN}   ✓ Normalization regression tests passed${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}   ✗ Normalization regression tests failed${NC}"
    tail -20 /tmp/normalization_tests.log | sed 's/^/     /'
    FAILED=$((FAILED + 1))
fi
echo ""

# Check 8: Front-end escaping regression tests (needs node; skipped if absent)
echo "8️⃣  Running front-end escaping tests..."
if ! command -v node > /dev/null 2>&1; then
    echo -e "${YELLOW}   ⚠ Skipped (node not installed)${NC}"
elif node scripts/test_escaping.mjs > /tmp/escaping_tests.log 2>&1; then
    echo -e "${GREEN}   ✓ Escaping regression tests passed${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}   ✗ Escaping regression tests failed${NC}"
    tail -20 /tmp/escaping_tests.log | sed 's/^/     /'
    FAILED=$((FAILED + 1))
fi
echo ""

# Check 9: Git status
echo "9️⃣  Checking git status..."
if git diff --quiet && git diff --staged --quiet; then
    echo -e "${YELLOW}   ⚠ No changes to commit${NC}"
else
    CHANGED=$(git diff --name-only --staged | wc -l)
    echo -e "${GREEN}   ✓ $CHANGED file(s) staged for commit${NC}"
    PASSED=$((PASSED + 1))
fi
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! ($PASSED/$((PASSED+FAILED)))${NC}"
    echo ""
    echo "Ready to push? Run:"
    echo "  git push origin main"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Some checks failed ($FAILED failed, $PASSED passed)${NC}"
    echo ""
    echo "Fix the issues above before pushing."
    echo ""
    exit 1
fi
