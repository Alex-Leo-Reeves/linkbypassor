#!/bin/bash
# Auto-start ngrok tunnel for LinkBypassor
# Routes https://rigor-snowsuit-handcraft.ngrok-free.dev → localhost:5000
#
# Usage:
#   ./start_ngrok.sh          # start tunnel
#   ./start_ngrok.sh stop     # stop tunnel
#   ./start_ngrok.sh status   # check if running
#   ./start_ngrok.sh restart  # restart tunnel

NGROK_BIN="/tmp/ngrok"
LOG_FILE="/tmp/ngrok.log"
PID_FILE="/tmp/ngrok.pid"
DOMAIN="rigor-snowsuit-handcraft.ngrok-free.dev"

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

start_tunnel() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ngrok already running (PID $(cat "$PID_FILE"))"
    return 0
  fi

  echo "Starting ngrok tunnel: https://$DOMAIN → http://localhost:5000"
  nohup "$NGROK_BIN" http 5000 \
    --host-header=rewrite \
    --log=stdout > "$LOG_FILE" 2>&1 &

  echo $! > "$PID_FILE"

  # Wait for tunnel to be ready
  for i in $(seq 1 15); do
    sleep 2
    if curl -s --max-time 3 http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q "$DOMAIN"; then
      echo "Tunnel ready: https://$DOMAIN"
      echo "Logs: $LOG_FILE"
      return 0
    fi
    echo "Waiting... ($((i*2))s)"
  done

  echo "ERROR: Tunnel did not start. Check $LOG_FILE"
  cat "$LOG_FILE" | tail -n 10
  rm -f "$PID_FILE"
  return 1
}

stop_tunnel() {
  if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "Stopping ngrok (PID $PID)..."
      kill "$PID" 2>/dev/null
      sleep 2
      kill -9 "$PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    echo "Stopped."
  else
    # Try to find and kill any ngrok process
    pkill -f 'ngrok http' 2>/dev/null && echo "Stopped orphaned ngrok process." || echo "No ngrok process found."
  fi
}

check_status() {
  # Check by process pattern (more reliable than PID file)
  NGROK_PID=$(pgrep -f 'ngrok http' 2>/dev/null | head -n1)
  if [ -n "$NGROK_PID" ]; then
    echo "ngrok running (PID $NGROK_PID)"
    curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data.get('tunnels', []):
    print(f\"  {t['name']}: {t['public_url']} → {t['config']['addr']}\")
" 2>/dev/null || echo "  (inspector not responding)"
  else
    echo "ngrok not running"
  fi
}

case "${1:-start}" in
  start)    start_tunnel ;;
  stop)     stop_tunnel ;;
  restart)  stop_tunnel; sleep 2; start_tunnel ;;
  status)   check_status ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
