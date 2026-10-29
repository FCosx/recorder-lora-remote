#!/usr/bin/env bash
# Optional wrapper for an offline installer supplied with the remote radio.
set -euo pipefail
if (($# == 0)) || [[ "$1" == --pi-* ]]; then
  printf 'Copy the pre-paired recorder-lora-remote.pyz file from USB, then run:\n  python3 /path/to/recorder-lora-remote.pyz install\nNo Pi IP, SSH, internet, pip, or apt is required.\n' >&2
  exit 2
fi
bundle="$1"
shift
exec python3 "$bundle" install "$@"
