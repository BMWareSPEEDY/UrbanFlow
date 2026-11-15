#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"

echo "==> Checking /health"
curl -sf "$BASE/health" | grep -q '"total_nodes":12436'

echo "==> Checking /api/v1/bootstrap"
curl -sf "$BASE/api/v1/bootstrap" | grep -q '"depots"'

echo "==> Creating isolated operator session (12 pumps, 8 barriers, 6 wardens)"
SES_JSON=$(curl -sf -X POST "$BASE/api/v1/session" \
  -H 'Content-Type: application/json' \
  -d '{"operator":"smoke-test","region":"all","rain_mmhr":95,"duration_min":60,"mode":"red_alert","pumps":12,"barriers":8,"wardens":6}')
SID=$(echo "$SES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session: $SID"

echo "==> Running /api/v1/scenario"
SCEN_JSON=$(curl -sf -X POST "$BASE/api/v1/scenario" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"region\":\"all\",\"rain_mmhr\":95,\"duration_min\":60,\"mode\":\"red_alert\"}")
ALERT_ID=$(echo "$SCEN_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(next(a['alert_id'] for a in d['alerts'] if a['feasible']))")
echo "Top feasible alert: $ALERT_ID"

echo "==> Dispatching $ALERT_ID"
curl -sf -X POST "$BASE/api/v1/dispatch" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"alert_id\":\"$ALERT_ID\"}" | grep -q '"ok":true'

echo "==> Checking /api/v1/transit (BMTC corridors)"
TRANSIT_JSON=$(curl -sf "$BASE/api/v1/transit?session_id=$SID&rain_mmhr=95")
ORIG=$(echo "$TRANSIT_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['corridors'][0]['origin_node'])")
DEST=$(echo "$TRANSIT_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['corridors'][0]['dest_node'])")

echo "==> Checking /api/v1/route"
curl -sf -X POST "$BASE/api/v1/route" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"origin\":\"$ORIG\",\"dest\":\"$DEST\",\"vehicle\":\"bus\",\"rain_mmhr\":95}" | grep -q '"standard"'

echo "==> Stepping simulation clock +5m & reading /api/v1/log"
curl -sf -X POST "$BASE/api/v1/tick" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"minutes\":5}" | grep -q '"sim_clock_min":5.0'

curl -sf "$BASE/api/v1/log?session_id=$SID" | grep -q 'DISPATCH'

echo "SMOKE PASSED"
