#!/bin/bash
# Astra Development Startup Script
# Starts the entire Astra web application from the repo root.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${DIR}/web/astra-web" "$@"