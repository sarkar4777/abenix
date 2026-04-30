#!/usr/bin/env bash

set -u
NS=${NS:-abenix}
PIDFILE=/tmp/pf_watchdog.pids
LOGFILE=/tmp/pf_watchdog.log

FORWARDS=(
  "3000:abenix-web:3000"
  "8000:abenix-api:8000"
  "3001:example_app-web:3000"
  "8001:example_app-api:8000"
  "3002:sauditourism-web:3000"
  "8002:sauditourism-api:8000"
  "3030:abenix-grafana:3000"
)

_stop() {
  if [ -f "$PIDFILE" ]; then
    while read -r pid; do
      kill "$pid" 2>/dev/null && echo "  killed pid $pid" >> "$LOGFILE"
    done < "$PIDFILE"
    rm -f "$PIDFILE"
  fi
  # Belt-and-braces on Windows Git-Bash (kill doesn't always trickle)
  powershell.exe -Command "Get-Process kubectl -ErrorAction SilentlyContinue | Stop-Process -Force" 2>/dev/null || true
  echo "all forwards stopped"
}

_watch_one() {
  local local_port="$1" svc="$2" svc_port="$3"
  local backoff=1
  while true; do
    echo "[$(date +%H:%M:%S)] START kubectl port-forward $svc $local_port:$svc_port" >> "$LOGFILE"
    kubectl port-forward -n "$NS" "svc/$svc" "$local_port:$svc_port" >> "$LOGFILE" 2>&1
    rc=$?
    echo "[$(date +%H:%M:%S)] EXITED  $svc code=$rc  restarting in ${backoff}s" >> "$LOGFILE"
    sleep "$backoff"
    # cap exponential backoff at 10s
    backoff=$(( backoff * 2 )); [ "$backoff" -gt 10 ] && backoff=10
  done
}

_start() {
  _stop >/dev/null 2>&1 || true
  : > "$LOGFILE"
  : > "$PIDFILE"
  for spec in "${FORWARDS[@]}"; do
    IFS=':' read -r lp svc sp <<< "$spec"
    _watch_one "$lp" "$svc" "$sp" &
    echo $! >> "$PIDFILE"
  done
  sleep 4
  echo "watchdog running (pids: $(tr '\n' ' ' < "$PIDFILE"))"
  echo "health:"
  for spec in "${FORWARDS[@]}"; do
    IFS=':' read -r lp svc sp <<< "$spec"
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://localhost:$lp" 2>/dev/null || echo "--")
    printf "  %-30s  :%s  http=%s\n" "$svc" "$lp" "$code"
  done
}

case "${1:-start}" in
  start) _start ;;
  stop)  _stop ;;
  *)     echo "usage: $0 {start|stop}"; exit 1 ;;
esac
