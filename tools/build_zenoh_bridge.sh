#!/usr/bin/env bash
# Build the pinned bridge with the route-lifetime correction, without sudo.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
build_dir=${ZENOH_BUILD_DIR:-"$project_dir/.build/zenoh-1.10.1"}
for tool in curl tar patch cargo cmake gcc g++; do
  command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
mkdir -p "$build_dir" "$project_dir/bin"
curl -fL --retry 3 https://codeload.github.com/eclipse-zenoh/zenoh-plugin-ros2dds/tar.gz/refs/tags/1.10.1 \
  -o "$build_dir/source.tar.gz"
echo "2c66aec0ab999d346c17497f2a6e84600478e57a197bb8c1dc5e6dd5bbbe5c03  $build_dir/source.tar.gz" | sha256sum -c -
tar -xf "$build_dir/source.tar.gz" -C "$build_dir"
source_dir="$build_dir/zenoh-plugin-ros2dds-1.10.1"
patch -d "$source_dir" -p1 < "$project_dir/zenoh/patches/1.10.1-route-listener-lifetime.patch"
(
  cd "$source_dir"
  CARGO_PROFILE_RELEASE_LTO=thin CARGO_PROFILE_RELEASE_CODEGEN_UNITS=8 \
    BINDGEN_EXTRA_CLANG_ARGS="${BINDGEN_EXTRA_CLANG_ARGS:-} -isystem $(gcc -print-file-name=include)" \
    cargo build --release --locked -p zenoh-bridge-ros2dds -j "${ZENOH_BUILD_JOBS:-4}"
)
install -m 755 "$source_dir/target/release/zenoh-bridge-ros2dds" "$project_dir/bin/zenoh-bridge-ros2dds-fixed"
sha256sum "$project_dir/bin/zenoh-bridge-ros2dds-fixed"
echo 'Fixed bridge built. Start it with tools/start_zenoh_bridge.sh.'
