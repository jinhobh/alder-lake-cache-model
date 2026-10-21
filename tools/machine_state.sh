#!/bin/sh
# Keep the entry point stable; Python handles JSON and failure reporting.
set -eu
exec python3 "$(dirname "$0")/machine_state.py" "$@"
