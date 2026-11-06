#!/usr/bin/env bash
# Small bootstrap; the Python installer handles detection, verification and rollback.
set -euo pipefail
pi_url=
arguments=("$@")
while (( $# )); do
  case "$1" in
    --pi-url) pi_url=${2:?}; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$pi_url" ]] || { echo 'Required: --pi-url http://PI_WIRED_IP:8080' >&2; exit 1; }
[[ $EUID -ne 0 ]] || { echo 'Run as your normal ROS user; setup requests sudo when needed.' >&2; exit 1; }
pi_url=$(python3 - "$pi_url" <<'PY'
import ipaddress,sys
from urllib.parse import urlsplit
value=urlsplit(sys.argv[1])
if (value.scheme!='http' or not value.hostname or not value.port or value.username or value.password
    or value.path not in ('','/') or value.query or value.fragment):
    raise SystemExit('Use --pi-url http://PI_WIRED_IP:8080')
ipaddress.IPv4Address(value.hostname)
print(sys.argv[1].rstrip('/'))
PY
)
setup_stage=$(mktemp -d)
trap 'rm -rf -- "$setup_stage"' EXIT
for name in install_robot_bridge.py robot_environment.py bridge_packages.py; do
  curl -q --noproxy '*' -fL --retry 2 --connect-timeout 5 --max-time 60 \
    "$pi_url/setup/$name" -o "$setup_stage/$name"
done
python3 -B "$setup_stage/install_robot_bridge.py" "${arguments[@]}"
