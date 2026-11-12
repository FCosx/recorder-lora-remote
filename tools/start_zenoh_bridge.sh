#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
binary="$project_dir/bin/zenoh-bridge-ros2dds-fixed"
config=${1:-"$project_dir/zenoh/laptop.json5"}
if [[ ! -x "$binary" ]]; then
  echo 'Fixed bridge missing. Build it with tools/build_zenoh_bridge.sh.' >&2
  exit 1
fi
[[ -f "$config" ]] || { echo "Config not found: $config" >&2; exit 1; }
# One launcher owns both the bridge and its idle-only rate helper.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/robot-recorder-bridge-$UID.lock"
flock -n 9 || { echo 'A recorder bridge launcher is already running.' >&2; exit 1; }
unset ROS_LOCALHOST_ONLY
export ROS_DISTRO=${ROS_DISTRO:-jazzy}
# Use the managed buffer-only profile unless an operator supplied a custom one.
dds_profile="$project_dir/zenoh/source-cyclonedds.xml"
if [[ -z "${CYCLONEDDS_URI:-}" && -f "$dds_profile" ]]; then
  export CYCLONEDDS_URI="file://$dds_profile"
fi
helper="$project_dir/tools/robot_bandwidth.py"
[[ -f "$helper" ]] || { echo 'Robot rate helper missing. Rerun robot bridge setup.' >&2; exit 1; }
source_domain=$(python3 - "$config" <<'PYDOMAIN'
import json,sys
config=json.load(open(sys.argv[1]))
print(int(config.get('plugins',{}).get('ros2dds',{}).get('domain',0)))
PYDOMAIN
)
# Both processes use the selected source domain and standard ROS environment. The helper
# keeps control routes warm but creates sensor readers only for a requested scan.
export ROS_DOMAIN_ID="$source_domain"
bridge_pid= helper_pid=
cleanup() {
  trap - EXIT INT TERM HUP
  [[ -z "$helper_pid" ]] || kill -TERM "$helper_pid" 2>/dev/null || true
  [[ -z "$helper_pid" ]] || wait "$helper_pid" 2>/dev/null || true
  [[ -z "$bridge_pid" ]] || kill -TERM "$bridge_pid" 2>/dev/null || true
  [[ -z "$bridge_pid" ]] || wait "$bridge_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
"$binary" -c "$config" &
bridge_pid=$!
python3 -B "$helper" --role source --domain "$source_domain" &
helper_pid=$!
set +e
wait -n "$bridge_pid" "$helper_pid"
result=$?
set -e
exit "$result"
