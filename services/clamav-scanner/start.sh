#!/bin/sh
set -eu

/init &
clamav_pid=$!

cleanup() {
  kill -TERM "$clamav_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

deadline=$(( $(date +%s) + ${CLAMD_STARTUP_TIMEOUT:-300} ))
until python3 -c 'import os,socket; s=socket.create_connection((os.getenv("CLAMD_HOST","127.0.0.1"),int(os.getenv("CLAMD_PORT","3310"))),2); s.sendall(b"zPING\0"); ok=s.recv(16).split(b"\0",1)[0]==b"PONG"; s.close(); raise SystemExit(0 if ok else 1)' 2>/dev/null; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "clamd startup timed out" >&2
    exit 1
  fi
  sleep 2
done

exec python3 /opt/edoc-av/scanner.py
