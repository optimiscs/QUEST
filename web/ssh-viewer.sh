#!/usr/bin/env bash
# Run on the computer whose browser will access the viewer.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash ssh-viewer.sh [options] [user@]host

  -p PORT  SSH port (default: use SSH configuration)
  -i FILE  SSH identity file
  -l PORT  local browser port (default: 6080)
  -r PORT  remote viewer port (default: 6080)
  -d PATH  remote QUEST directory (default: /root/autodl-tmp/Quest)
  -h       show help

Example: bash ssh-viewer.sh -p 2222 -l 6080 root@server.example.com
The tunnel stays in the foreground; press Ctrl-C to close it.
EOF
}

local_port=6080
remote_port=6080
remote_dir=/root/autodl-tmp/Quest
ssh_options=()
while getopts ':p:i:l:r:d:h' opt; do
  case "$opt" in
    p) ssh_options+=(-p "$OPTARG") ;;
    i) ssh_options+=(-i "$OPTARG") ;;
    l) local_port=$OPTARG ;;
    r) remote_port=$OPTARG ;;
    d) remote_dir=$OPTARG ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
if [[ $# != 1 || $1 == -* ]]; then usage >&2; exit 2; fi
host=$1
for port in "$local_port" "$remote_port"; do
  if [[ ! $port =~ ^[0-9]{1,5}$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
    echo "Invalid port: $port" >&2; exit 2
  fi
done

printf -v remote_command 'bash -s -- %q %q' "$remote_dir" "$remote_port"
ssh "${ssh_options[@]}" "$host" "$remote_command" <<'REMOTE'
set -euo pipefail
quest_dir=$1
port=$2
python="$quest_dir/workspace/env/bin/python"
[[ -x $python ]] || python=$(command -v python3 || true)
if [[ -z $python || ! -f $quest_dir/web/serve.py ]]; then
  echo "Python or web/serve.py not found in $quest_dir" >&2; exit 1
fi
check_viewer() {
  "$python" - "$port" <<'PY'
import json, sys, urllib.request
try:
    base = 'http://127.0.0.1:' + sys.argv[1]
    with urllib.request.urlopen(base + '/api/v1/health/ready', timeout=5) as r:
        data = json.load(r)
    with urllib.request.urlopen(base + '/trace-viewer-zh/', timeout=5) as r:
        ok = r.status == 200
    sys.exit(0 if ok and isinstance(data, dict) and data.get('status') == 'ok' else 1)
except Exception:
    sys.exit(1)
PY
}
if check_viewer; then
  echo "Remote QUEST viewer is already running on port $port."
  exit 0
fi
if ! "$python" - "$port" <<'PY'
import socket, sys
try:
    with socket.socket() as s:
        s.bind(('127.0.0.1', int(sys.argv[1])))
except OSError:
    sys.exit(1)
PY
then
  echo "Remote port $port is occupied, but its service is not a healthy QUEST viewer; refusing to replace it." >&2
  exit 1
fi
runtime="$quest_dir/workspace/viewer/logs"
mkdir -p "$runtime"
nohup "$python" -u "$quest_dir/web/serve.py" --host 127.0.0.1 --port "$port" \
  </dev/null >>"$runtime/ssh-viewer-server.log" 2>&1 &
server_pid=$!
for _ in {1..20}; do
  if check_viewer; then
    echo "Started remote QUEST viewer on port $port (PID $server_pid)."
    exit 0
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
  sleep 1
done
echo "Viewer failed to start; inspect $runtime/ssh-viewer-server.log" >&2
exit 1
REMOTE

echo "Opening http://127.0.0.1:$local_port/trace-viewer-zh/"
echo "Keep this terminal open; Ctrl-C closes the tunnel."
exec ssh "${ssh_options[@]}" -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L "127.0.0.1:$local_port:127.0.0.1:$remote_port" "$host"
