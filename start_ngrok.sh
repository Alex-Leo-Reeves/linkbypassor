#!/bin/bash
# Auto-start script for LinkBypassor
# Starts the Python Flask API server and ngrok tunnel
# Routes https://rigor-snowsuit-handcraft.ngrok-free.dev -> localhost:5000
#
# Usage:
#   ./start_ngrok.sh          # start server + tunnel
#   ./start_ngrok.sh stop     # stop server + tunnel
#   ./start_ngrok.sh status   # check if running
#   ./start_ngrok.sh restart  # restart server + tunnel

set -e

NGROK_BIN="/tmp/ngrok"
PYTHON_BIN="python3"
FLASK_APP="/home/masteralex/Desktop/linkbypass/backend/app.py"
LOG_DIR="/tmp/linkbypass-logs"
NGROK_LOG="$LOG_DIR/ngrok.log"
FLASK_LOG="$LOG_DIR/flask.log"
PID_DIR="/tmp/linkbypass-pids"
NGROK_PID_FILE="$PID_DIR/ngrok.pid"
FLASK_PID_FILE="$PID_DIR/flask.pid"
DOMAIN="rigor-snowsuit-handcraft.ngrok-free.dev"

mkdir -p "$LOG_DIR" "$PID_DIR"

# Fallback: check common ngrok locations
if [ ! -x "$NGROK_BIN" ]; then
  for path in /usr/local/bin/ngrok /usr/bin/ngrok ~/bin/ngrok; do
    if [ -x "$path" ]; then
      NGROK_BIN="$path"
      break
    fi
  done
fi

if ! command -v "$NGROK_BIN" &>/dev/null && [ ! -x "$NGROK_BIN" ]; then
  echo "ERROR: ngrok not found. Install from https://ngrok.com/download"
  exit 1
fi

start_flask() {
  if [ -f "$FLASK_PID_FILE" ] && kill -0 "$(cat "$FLASK_PID_FILE")" 2>/dev/null; then
    echo "Flask server already running (PID $(cat "$FLASK_PID_FILE"))"
    return 0
  fi

  echo "Starting Flask API server..."
  cd "$(dirname "$FLASK_APP")"
  nohup "$PYTHON_BIN" "$FLASK_APP" > "$FLASK_LOG" 2>&1 &
  echo $! > "$FLASK_PID_FILE"

  for i in $(seq 1 10); do
    sleep 1
    if curl -s --max-time 2 http://127.0.0.1:5000/api/health 2>/dev/null | grep -q "ok"; then
      echo "Flask server ready on http://localhost:5000"
      echo "Flask logs: $FLASK_LOG"
      return 0
    fi
    echo "  Waiting for Flask... ($i)s"
  done

  echo "ERROR: Flask server did not start. Check $FLASK_LOG"
  cat "$FLASK_LOG" | tail -n 10
  rm -f "$FLASK_PID_FILE"
  return 1
}

start_ngrok() {
  if [ -f "$NGROK_PID_FILE" ] && kill -0 "$(cat "$NGROK_PID_FILE")" 2>/dev/null; then
    echo "ngrok already running (PID $(cat "$NGROK_PID_FILE"))"
    return 0
  fi

  echo "Starting ngrok tunnel: https://$DOMAIN -> http://localhost:5000"
  nohup "$NGROK_BIN" http 5000 \
    --host-header=rewrite \
    --domain="$DOMAIN" \
    --log=stdout > "$NGROK_LOG" 2>&1 &

  echo $! > "$NGROK_PID_FILE"

  for i in $(seq 1 15); do
    sleep 2
    if curl -s --max-time 3 http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q "$DOMAIN"; then
      echo "Tunnel ready: https://$DOMAIN"
      echo "ngrok logs: $NGROK_LOG"
      return 0
    fi
    echo "  Waiting for ngrok... ($((i*2))s)"
  done

  echo "ERROR: Tunnel did not start. Check $NGROK_LOG"
  cat "$NGROK_LOG" | tail -n 10
  rm -f "$NGROK_PID_FILE"
  return 1
}

stop_flask() {
  if [ -f "$FLASK_PID_FILE" ]; then
    PID=$(cat "$FLASK_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "Stopping Flask server (PID $PID)..."
      kill "$PID" 2>/dev/null
      sleep 1
      kill -9 "$PID" 2>/dev/null
    fi
    rm -f "$FLASK_PID_FILE"
  fi
  fuser -k 5000/tcp 2>/dev/null || true
}

stop_ngrok() {
  if [ -f "$NGROK_PID_FILE" ]; then
    PID=$(cat "$NGROK_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "Stopping ngrok (PID $PID)..."
      kill "$PID" 2>/dev/null
      sleep 2
      kill -9 "$PID" 2>/dev/null
    fi
    rm -f "$NGROK_PID_FILE"
  else
    pkill -f 'ngrok http' 2>/dev/null && echo "Stopped orphaned ngrok process." || true
  fi
}

check_status() {
  echo "=== Flask Server ==="
  FLASK_PID=$(pgrep -f "python3.*app.py" 2>/dev/null | head -n1)
  if [ -n "$FLASK_PID" ]; then
    echo "  Running (PID $FLASK_PID)"
    curl -s http://127.0.0.1:5000/api/health 2>/dev/null || echo "  (not responding)"
  else
    echo "  Not running"
  fi

  echo ""
  echo "=== ngrok Tunnel ==="
  NGROK_PID=$(pgrep -f 'ngrok http' 2>/dev/null | head -n1)
  if [ -n "$NGROK_PID" ]; then
    echo "  Running (PID $NGROK_PID)"
    curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data.get('tunnels', []):
    print(f\"  {t['name']}: {t['public_url']} -> {t['config']['addr']}\")
" 2>/dev/null || echo "  (inspector not responding)"
  else
    echo "  Not running"
  fi
}

case "${1:-start}" in
  start)
    start_flask
    start_ngrok
    echo ""
    echo "=== LinkBypassor Ready ==="
    echo "  Flask API:  http://localhost:5000"
    echo "  ngrok UI:   https://$DOMAIN"
    echo "  Inspector:  http://127.0.0.1:4040"
    ;;
  stop)
    stop_ngrok
    stop_flask
    ;;
  restart)
    stop_ngrok
    stop_flask
    sleep 2
    start_flask
    start_ngrok
    ;;
  status)
    check_status
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
