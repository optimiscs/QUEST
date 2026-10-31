#!/usr/bin/env bash
# Reconnect local-only forwards for independent remote vLLM replicas.
set -euo pipefail
if [[ $# -lt 4 ]]; then
  echo 'Usage: ssh_vllm_tunnel.sh HOST SSH_PORT IDENTITY LOCAL:REMOTE [...]' >&2
  exit 2
fi
host=$1; ssh_port=$2; identity=$3; shift 3
[[ $ssh_port =~ ^[0-9]+$ && -r $identity ]] || exit 2
args=()
for pair in "$@"; do
  [[ $pair =~ ^([0-9]+):([0-9]+)$ ]] || exit 2
  args+=(-L "127.0.0.1:${BASH_REMATCH[1]}:127.0.0.1:${BASH_REMATCH[2]}")
done
while true; do
  ssh -N -i "$identity" -p "$ssh_port" -o IdentitiesOnly=yes -o BatchMode=yes \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
    "${args[@]}" "$host" || true
  printf '%s SSH tunnel disconnected; retrying in 5 seconds\n' "$(date -Is)" >&2
  sleep 5
done
