#!/bin/bash
# CodeRAG Startup Script (Git Bash / Linux)
# Usage: bash start_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# ── 1. UTF-8 ──────────────────────────────────────────────
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
echo "[1/4] UTF-8 encoding configured"

# ── 2. Kill zombie python processes ───────────────────────
echo "[2/4] Cleaning up old processes..."
# Kill any uvicorn/python processes from previous runs
pkill -f "uvicorn app.main" 2>/dev/null || true
sleep 2

# Find available port (8080 → 8090)
PORT=8085
found=0
for p in 8085 8086 8087 8088 8089; do
    if ! netstat -ano 2>/dev/null | grep ":$p " | grep -q LISTENING; then
        PORT=$p
        found=1
        break
    fi
done

echo "       Backend port: $PORT"

# ── 3. Update vite config ────────────────────────────────
VITE_CFG="$FRONTEND_DIR/vite.config.ts"
if [ -f "$VITE_CFG" ]; then
    sed -i "s/target: 'http:\/\/localhost:[0-9]*'/target: 'http:\/\/localhost:$PORT'/" "$VITE_CFG"
    echo "       vite.config.ts → :$PORT"
fi

# ── 4. Start services ─────────────────────────────────────
echo "[3/4] Starting backend..."
cd "$BACKEND_DIR"
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload \
    > /tmp/coderag_api.log 2>&1 &
BACKEND_PID=$!
echo "       Backend PID: $BACKEND_PID"

# Wait for backend
for i in $(seq 1 20); do
    if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
        echo "       Backend ready (attempt $i)"
        break
    fi
    sleep 1
done

echo "[4/4] Starting frontend..."
cd "$FRONTEND_DIR"
npx vite --host 0.0.0.0 --port 5173 \
    > /tmp/coderag_frontend.log 2>&1 &
FRONTEND_PID=$!
echo "       Frontend PID: $FRONTEND_PID"

# ── 5. Start Celery worker (if Redis is available) ────────────
echo "[5/5] Starting Celery worker..."
if redis-cli ping 2>/dev/null | grep -q PONG; then
    cd "$BACKEND_DIR"
    # --pool=solo：Windows 上 prefork 模式 fast_trace_task 会崩（_loc unpack 错误）
    python -m celery -A app.tasks.celery_app worker --loglevel=info --pool=solo \
        --queues=default --hostname="worker-dev" \
        > /tmp/coderag_celery.log 2>&1 &
    CELERY_PID=$!
    echo "       Celery PID: $CELERY_PID"
else
    echo "       Redis not available — skipping Celery"
    CELERY_PID=""
fi
sleep 2

echo ""
echo "================================================="
echo "  CodeRAG Running"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:$PORT"
echo "  Swagger:   http://localhost:$PORT/docs"
echo "================================================="
echo ""
echo "Stop with: kill $BACKEND_PID $FRONTEND_PID"
echo "Backend log:  /tmp/coderag_api.log"
echo "Frontend log: /tmp/coderag_frontend.log"
