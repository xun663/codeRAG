#!/bin/bash
# Start Celery worker for CodeRAG background tasks.
# Usage: bash start_celery.sh
#
# Requires Redis running on localhost:6379 (see start_redis.sh).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "Starting Celery worker for CodeRAG..."
cd "$BACKEND_DIR"

# Worker name derived from host so multiple devs don't collide
HOST=$(hostname 2>/dev/null || echo "dev")
WORKER_NAME="worker-${HOST}"

celery -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    --queues=default \
    --hostname="$WORKER_NAME" \
    --logfile=/tmp/coderag_celery.log \
    --pidfile=/tmp/coderag_celery.pid

echo "Celery worker stopped."
