#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/app"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
BACKEND_API_BASE="${BACKEND_API_BASE:-}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--host HOST] [--port PORT] [--backend-api-base URL]

Starts a simple static server for the HTML frontends in app/.

Options:
  --host HOST              Static server host (default: ${HOST})
  --port PORT              Static server port (default: ${PORT})
  --backend-api-base URL   Backend API base override (default: infer from browser host on port 8000)
  -h, --help               Show this help

Examples:
  $(basename "$0")
  $(basename "$0") --port 8081 --backend-api-base http://192.168.1.50:8000/api
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --backend-api-base)
      BACKEND_API_BASE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "Python is required to run the static frontend server." >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 || command -v python)"

if [[ -n "${BACKEND_API_BASE}" ]]; then
  ENCODED_API="$("${PYTHON_BIN}" - <<PY
import urllib.parse
print(urllib.parse.quote("${BACKEND_API_BASE}", safe=":/"))
PY
)"
else
  ENCODED_API=""
fi

frontend_url() {
  local filename="$1"
  if [[ -n "${ENCODED_API}" ]]; then
    echo "http://localhost:${PORT}/${filename}?api=${ENCODED_API}"
  else
    echo "http://localhost:${PORT}/${filename}"
  fi
}

cat <<EOF
Serving static HTML frontends from:
  ${APP_DIR}

Static server:
  http://localhost:${PORT}/

Backend API base override:
  ${BACKEND_API_BASE:-auto: browser host on port 8000}

Frontend URLs:
  Full app:                 $(frontend_url "hk_full_app.html")
  Full app portrait:        $(frontend_url "hk_full_app_portrait.html")
  Calibration app:          $(frontend_url "hk_calibration_app.html")
  Calibration app portrait: $(frontend_url "hk_calibration_app_portrait.html")
  Camera test:              $(frontend_url "hk_camera_test.html")

Press Ctrl+C to stop.
EOF

cd "${APP_DIR}"
exec "${PYTHON_BIN}" -m http.server "${PORT}" --bind "${HOST}"
