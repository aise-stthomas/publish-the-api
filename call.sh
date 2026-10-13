#!/usr/bin/env bash
# One request to the deployed API, with curl. No signature: the URL is public, the token is the key.
#   ./call.sh                                            the sample ticket, to your own API
#   ./call.sh body.json                                  another ticket
#   LAB_URL=https://.../triage LAB_TOKEN=... ./call.sh   a classmate's API, with the token they gave you
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
: "${LAB_URL:?run ./deploy.sh first, or set LAB_URL}"
curl -s -X POST "$LAB_URL" -H "x-lab-token: ${LAB_TOKEN:-}" -H 'content-type: application/json' \
  -d @"${1:-src/function/sample-event-body.json}" -w '\n%{http_code} in %{time_total}s\n'
