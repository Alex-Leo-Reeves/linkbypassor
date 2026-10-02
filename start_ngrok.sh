#!/bin/bash
# Auto-start script for LinkBypassor
# Starts the Python Flask API server and an ngrok tunnel that maps
# https://rigor-snowsuit-handcraft.ngrok-free.dev -> http://localhost:5000
#
# Usage:
#   ./start_ngrok.sh          # start server + tunnel
#   ./start_ngrok.sh stop     # stop server + tunnel
#   ./start_ngrok.sh status   # check if running
#   ./start_ngrok.sh restart  # restart server + tunnel

set -euo pipefail

# --- Configuration (override any of these via environment variables) ---------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASK_APP="$PROJECT_DIR/backend/app.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-5000}"
DOMAIN="${NGROK_DOMAIN:-rigor-snowsuit-handcraft.ngrok-free.dev}"
LOG_DIR="${LOG_DIR:-/tmp/linkbypass-logs}"
PID_DIR="${PID_DIR:-/tmp/linkbypass-pids}"
FLASK_LOG="$LOG_DIR/flask.log"
NGROK_LOG="$LOG_DIR/ngrok.log"
FLASK_PID_FILE="$PID_DIR/flask.pid"
NGROK_PID_FILE="$PID_DIR/ngrok.pid"

# ngrok must be told which config file to use. The snap build runs confined and
# CANNOT read hidden paths such as ~/.config/ngrok/ngrok.yml, so we materialise
# a non-hidden config from the authtoken (NGROK_AUTHTOKEN, or the token already
# present in the user's ngrok config file).
NGROK_CFG="${NGROK_CFG:-$HOME/ngrok-linkbypass.yml}"

mkdir -p "$LOG_DIR" "$PID_DIR"

# --- ngrok discovery + config ------------------------------------------------
find_ngrok() {
  local candidate
  for candidate in \
    "${NGROK_BIN:-}" \
    /tmp/ngrok \
    "$HOME/bin/ngrok" \
    "$HOME/.local/bin/ngrok" \
    /snap/bin/ngrok \
    /usr/local/bin/ngrok \
    /usr/bin/ngrok; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if command -v ngrok >/dev/null 2>&1; then
    command -v ngrok
    return 0
  fi
  return 1
}

ensure_ngrok_config() {
  local token="" saved_umask
  if [ -n "${NGROK_AUTHTOKEN:-}" ]; then
    token="$NGROK_AUTHTOKEN"
  elif [ -f "$HOME/.config/ngrok/ngrok.yml" ]; then
    token="$(sed -nE 's/^[[:space:]]*authtoken:[[:space:]]*"?([^"]*)"?[[:space:]]*$/\1/p' \
      "$HOME/.config/ngrok/ngrok.yml" | head -n1)"
  fi
  if [ -z "$token" ]; then
    echo "ERROR: no ngrok authtoken found."
    echo "       Set NGROK_AUTHTOKEN or add one to ~/.config/ngrok/ngrok.yml"
    return 1
  fi
  saved_umask="$(umask)"
  umask 077
  printf 'version: "3"\nagent:\n    authtoken: %s\n' "$token" > "$NGROK_CFG"
  umask "$saved_umask"
}

NGROK_BIN="$(find_ngrok || true)"
if [ -z "$NGROK_BIN" ]; then
  echo "ERROR: ngrok not found. Install from https://ngrok.com/download"
  exit 1
fi

# --- ngrok process helpers ---------------------------------------------------
# Snap builds run under an AppArmor profile that REJECTS signals from our
# unconfined shell (kill -> "permission denied"). The one exception is a shell
# running inside the same snap, so we fall back to `snap run --shell`.
ngrok_pids() {
  local pid
  if [ -f "$NGROK_PID_FILE" ]; then
    pid="$(cat "$NGROK_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then printf '%s\n' "$pid"; fi
  fi
  pgrep -f "ngrok http" 2>/dev/null || true
}

kill_ngrok_pid() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 0
  # Unconfined binaries (official ngrok tarball) die to a plain signal.
  kill -9 "$pid" 2>/dev/null || true
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then return 0; fi
  # Confined snap build: signal it from inside the snap's own shell.
  if [[ "$NGROK_BIN" == /snap/* ]] && command -v snap >/dev/null 2>&1; then
    printf 'kill -9 %s\n' "$pid" | snap run --shell "$(basename "$NGROK_BIN")" >/dev/null 2>&1 || true
    sleep 1
    if ! kill -0 "$pid" 2>/dev/null; then return 0; fi
  fi
  return 1
}

start_flask() {
  if [ -f "$FLASK_PID_FILE" ] && kill -0 "$(cat "$FLASK_PID_FILE")" 2>/dev/null; then
    echo "Flask server already running (PID $(cat "$FLASK_PID_FILE"))"
    return 0
  fi

  echo "Starting Flask API server..."
  (
    cd "$(dirname "$FLASK_APP")"
    PORT="$PORT" nohup "$PYTHON_BIN" "$FLASK_APP" > "$FLASK_LOG" 2>&1 &
    echo $! > "$FLASK_PID_FILE"
  )

  local i
  for i in $(seq 1 10); do
    sleep 1
    if curl -s --max-time 2 "http://127.0.0.1:$PORT/api/health" 2>/dev/null | grep -q "ok"; then
      echo "Flask server ready on http://localhost:$PORT"
      echo "Flask logs: $FLASK_LOG"
      return 0
    fi
    echo "  Waiting for Flask... ($i)s"
  done

  echo "ERROR: Flask server did not start. Check $FLASK_LOG"
  tail -n 15 "$FLASK_LOG"
  rm -f "$FLASK_PID_FILE"
  return 1
}

start_ngrok() {
  local existing pid i
  existing="$(pgrep -f "ngrok http" 2>/dev/null | head -n1 || true)"
  if [ -n "$existing" ]; then
    echo "ngrok already running (PID $existing)"
    printf '%s\n' "$existing" > "$NGROK_PID_FILE"
    return 0
  fi

  ensure_ngrok_config

  echo "Starting ngrok tunnel: https://$DOMAIN -> http://localhost:$PORT"
  nohup "$NGROK_BIN" http "$PORT" \
    --url="https://$DOMAIN" \
    --config="$NGROK_CFG" \
    --log=stdout > "$NGROK_LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$NGROK_PID_FILE"

  for i in $(seq 1 15); do
    sleep 2
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "ERROR: ngrok exited during startup. Check $NGROK_LOG"
      tail -n 15 "$NGROK_LOG"
      rm -f "$NGROK_PID_FILE"
      return 1
    fi
    if curl -s --max-time 3 http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q "$DOMAIN"; then
      echo "Tunnel ready: https://$DOMAIN"
      echo "ngrok logs: $NGROK_LOG"
      return 0
    fi
    echo "  Waiting for ngrok... ($((i*2))s)"
  done

  echo "ERROR: Tunnel did not start. Check $NGROK_LOG"
  tail -n 15 "$NGROK_LOG"
  rm -f "$NGROK_PID_FILE"
  return 1
}

stop_flask() {
  local pid
  if [ -f "$FLASK_PID_FILE" ]; then
    pid="$(cat "$FLASK_PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping Flask server (PID $pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$FLASK_PID_FILE"
  fi
  fuser -k "$PORT/tcp" 2>/dev/null || true
}

stop_ngrok() {
  local pid seen=""
  for pid in $(ngrok_pids); do
    case " $seen " in *" $pid "*) continue ;; esac
    seen="$seen $pid"
    echo "Stopping ngrok (PID $pid)..."
    if ! kill_ngrok_pid "$pid"; then
      echo "  WARNING: could not stop ngrok PID $pid (try: snap run --shell ngrok)"
    fi
  done
  rm -f "$NGROK_PID_FILE"
}

check_status() {
  echo "=== Flask Server ==="
  local flask_pid ngrok_pid
  flask_pid="$(pgrep -f "python3.*app\.py" 2>/dev/null | head -n1 || true)"
  if [ -n "$flask_pid" ]; then
    echo "  Running (PID $flask_pid)"
    curl -s --max-time 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || echo "  (not responding)"
  else
    echo "  Not running"
  fi

  echo ""
  echo "=== ngrok Tunnel ==="
  ngrok_pid="$(pgrep -f "ngrok http" 2>/dev/null | head -n1 || true)"
  if [ -n "$ngrok_pid" ]; then
    echo "  Running (PID $ngrok_pid)"
    curl -s --max-time 3 http://127.0.0.1:4040/api/tunnels 2>/dev/null | "$PYTHON_BIN" -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print('  (inspector not responding)')
    raise SystemExit(0)
for t in data.get('tunnels', []):
    print('  {}: {} -> {}'.format(t['name'], t['public_url'], t['config']['addr']))
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
    echo "  Flask API:  http://localhost:$PORT"
    echo "  ngrok URL:  https://$DOMAIN"
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
