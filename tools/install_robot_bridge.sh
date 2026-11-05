#!/usr/bin/env bash
# Robot-side command-only bootstrap. Run as the normal ROS user, not root.
set -euo pipefail
pi_url=
ros_distro=
domain=0
install_dir="$HOME/robot-recorder"
configure_only=false
skip_dependencies=false
while (( $# )); do
  case "$1" in
    --pi-url) pi_url=${2:?}; shift 2 ;;
    --ros-distro) ros_distro=${2:?}; shift 2 ;;
    --domain) domain=${2:?}; shift 2 ;;
    --install-dir) install_dir=${2:?}; shift 2 ;;
    --configure-only) configure_only=true; shift ;;
    --skip-dependencies) skip_dependencies=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
trap 'echo "Setup stopped at line $LINENO. Fix the reported error, then run the same setup command again." >&2' ERR
[[ -n "$pi_url" ]] || { echo 'Required: --pi-url http://PI_IP:8080' >&2; exit 1; }
[[ $EUID -ne 0 ]] || { echo 'Run as your normal ROS user; setup requests sudo if needed.' >&2; exit 1; }
[[ "$domain" =~ ^[0-9]{1,3}$ ]] || { echo 'ROS domain must be 0–232.' >&2; exit 1; }
domain=$((10#$domain))
(( domain <= 232 )) || { echo 'ROS domain must be 0–232.' >&2; exit 1; }
case "$install_dir" in /*) ;; *) echo '--install-dir must be an absolute path.' >&2; exit 1 ;; esac
if [[ -z "$ros_distro" ]]; then
  available=()
  for distro in humble jazzy; do
    [[ ! -f "/opt/ros/$distro/setup.bash" ]] || available+=("$distro")
  done
  if (( ${#available[@]} == 1 )); then ros_distro=${available[0]};
  elif (( ${#available[@]} > 1 )); then read -rp 'ROS version (humble/jazzy): ' ros_distro;
  else echo 'Install ROS 2 Humble or Jazzy before setup.' >&2; exit 1; fi
fi
[[ "$ros_distro" == humble || "$ros_distro" == jazzy ]] && [[ -f "/opt/ros/$ros_distro/setup.bash" ]] || {
  echo 'ROS 2 Humble or Jazzy must already be installed.' >&2; exit 1;
}
pi_url=${pi_url%/}
pi_host=$(python3 - "$pi_url" <<'PY'
import sys, ipaddress
from urllib.parse import urlsplit
u=urlsplit(sys.argv[1])
assert u.scheme == 'http' and u.hostname and u.port and not u.username and not u.password
assert u.path in ('', '/') and not u.query and not u.fragment
ipaddress.IPv4Address(u.hostname)
print(u.hostname)
PY
)
python3 - "$pi_url" <<'PIGUARD'
import json,sys
from urllib.request import ProxyHandler,build_opener
with build_opener(ProxyHandler({})).open(sys.argv[1]+'/api/status',timeout=6) as response:
    state=json.load(response)
if state.get('state') != 'idle':
    raise SystemExit('Stop recording before installing or changing the robot bridge.')
PIGUARD
mkdir -p "$install_dir/tools" "$install_dir/zenoh/patches"
download() {
  local temporary
  temporary=$(mktemp)
  if ! curl -q --noproxy '*' -fL --retry 2 --connect-timeout 10 --max-time 60 \
    "$pi_url/setup/$1" -o "$temporary"; then rm -f "$temporary"; return 1; fi
  install -m 644 "$temporary" "$install_dir/$2"
  rm -f "$temporary"
}
if ! $configure_only; then
  if ! $skip_dependencies; then
    sudo apt-get update
    sudo apt-get install -y build-essential cmake libclang-dev pkg-config curl \
      ca-certificates patch git util-linux "ros-${ros_distro}-rmw-cyclonedds-cpp"
  fi
  download build_zenoh_bridge.sh tools/build_zenoh_bridge.sh
  download start_zenoh_bridge.sh tools/start_zenoh_bridge.sh
  download robot_bandwidth.py tools/robot_bandwidth.py
    download robot_bridge_service.py tools/robot_bridge_service.py
  download route-listener-lifetime.patch zenoh/patches/1.10.1-route-listener-lifetime.patch
  export PATH="$HOME/.cargo/bin:$PATH"
  if [[ -f "$install_dir/.bridge-build.sha256" ]] &&
     sha256sum -c --status "$install_dir/.bridge-build.sha256" &&
     "$install_dir/bin/zenoh-bridge-ros2dds-fixed" --version >/dev/null; then
    echo 'The corrected bridge is already installed.'
  else
    if ! command -v rustup >/dev/null; then
      rust_installer=$(mktemp)
      curl -q -fL --retry 3 https://sh.rustup.rs -o "$rust_installer"
      sh "$rust_installer" -y --profile minimal --default-toolchain none --no-modify-path
      rm -f "$rust_installer"
    fi
    rustup toolchain install 1.97.1 --profile minimal
    echo 'Preparing the corrected bridge automatically. First installation can take a while.'
    ZENOH_BUILD_JOBS=${ZENOH_BUILD_JOBS:-2} bash "$install_dir/tools/build_zenoh_bridge.sh"
    sha256sum "$install_dir/bin/zenoh-bridge-ros2dds-fixed" \
      "$install_dir/zenoh/patches/1.10.1-route-listener-lifetime.patch" \
      "$install_dir/tools/build_zenoh_bridge.sh" > "$install_dir/.bridge-build.sha256"
  fi
fi
[[ -x "$install_dir/bin/zenoh-bridge-ros2dds-fixed" ]] || { echo 'Corrected bridge not installed yet.' >&2; exit 1; }
python3 - "$install_dir" "$pi_host" "$ros_distro" "$domain" <<'PY'
import json, pathlib, shlex, sys
root=pathlib.Path(sys.argv[1]); host,distro,domain=sys.argv[2:]
config={"mode":"router","listen":{"endpoints":["tcp/127.0.0.1:7447"]},
        "connect":{"endpoints":[f"tcp/{host}:7447"]},
        "scouting":{"multicast":{"enabled":False}},
        "plugins":{"ros2dds":{"domain":int(domain),"ros_localhost_only":False,
                              "ros_automatic_discovery_range":"SUBNET"}}}
(root/'zenoh/robot.json5').write_text(json.dumps(config,indent=2)+'\n')
environment='#!/usr/bin/env bash\nset -e\n'
environment+=f'source /opt/ros/{distro}/setup.bash\n'
environment+='unset ROS_LOCALHOST_ONLY\n'
environment+=f'export ROS_DISTRO={distro} ROS_DOMAIN_ID={domain} RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET\n'
start=environment
start+=f'exec bash {shlex.quote(str(root/"tools/start_zenoh_bridge.sh"))} {shlex.quote(str(root/"zenoh/robot.json5"))}\n'
(root/'tools/start_robot_bridge.sh').write_text(start)
probe=environment+'exec ros2 topic pub -r 2 /zenoh_test std_msgs/msg/String "{data: \'hello over Zenoh\'}"\n'
(root/'tools/publish_bridge_test.sh').write_text(probe)
PY
if [[ ! -f "$install_dir/tools/robot_bridge_service.py" ]]; then
  download robot_bridge_service.py tools/robot_bridge_service.py
fi
python3 -B "$install_dir/tools/robot_bridge_service.py" install --root "$install_dir" \
  --config "$install_dir/zenoh/robot.json5" --ros-distro "$ros_distro" --pi-url "$pi_url"
echo 'Setup complete. The bridge starts automatically; no open terminal is required.'
