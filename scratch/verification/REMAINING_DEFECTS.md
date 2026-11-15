# Remaining defects — for manual fixing

Status of the tree when this was written:

- Backend audit (`scripts/command/audit_api.py`): **79 pass / 5 fail / 1 warn**.
  Of those 5, **3 are harness bugs** and **2 are real** (both have unverified
  edits on disk).
- UI audit (`web/scripts/audit_ui.mjs`): **38 pass / 4 fail / 2 warn** (pre-fix run;
  not re-run after the backend edits).
- `pytest command/tests`: **24/24 pass** in 3.9 s — but the suite does not cover
  any of the P0s below.
- The running server on :8000 was started **before** the last round of edits
  (reopen endpoint, delta clamp, barrier route preview). Restart it to test them.

Already edited but **not yet re-audited** (do not redo, just verify):

| File | Change |
| --- | --- |
| `command/app.py` | JSON handlers for 400/404/405/HTTPException/Exception; `_get_json_body` rejects non-dict; route `_coord()` guard; `log?since` guard; bool `minutes` rejected; dismiss applies `cleared_nodes` on a copy; new `POST /api/v1/reopen` |
| `command/fleet.py` | barrier-first route preview; `LATE ·` directive when ETA > peak; `beats_peak` on pending+assigned; `addedMinutes` clamped ≥ 0 with signed `delta_vs_naive_min`; `reopen_barrier()` |
| `command/triage.py` | `classify_action` closes an inundated underpass before pumping it |
| `command/state.py` | `SessionStore` bounded at 64 (oldest-first eviction) |

---

## A. Real product defects still open

### A1. Queue says INFEASIBLE, dispatch says success (P1)
`command/fleet.py` — `enrich_alerts_with_fleet` (`reserved_ids`) vs `dispatch_alert` (~L585)

The preview reserves units greedily so later cards show `dispatch_status: INFEASIBLE`
with `infeasible_reason: no_unit`. A real `POST /api/v1/dispatch` for that same alert
recomputes with `excluded_unit_ids=set()` and returns `200 {"ok": true}`.

Repro (95 mm/hr, 12P/8B/6W):
```
scenario.alerts[n].dispatch_status == "INFEASIBLE"
POST /dispatch {alert_id: alerts[n].alert_id}  ->  200 ok:true
```
Fix: pick one semantics. Either dispatch honours the reservation list (409
`unit_reserved`) or the preview should say "QUEUED · behind N units" instead of
INFEASIBLE. The second is better product behaviour — scarcity is the story.

### A2. Cross-catchment route claims a stub but returns none (P1)
`command/routing.py` ~L430–508

Audit section G prints `inter_catchment=True, stub=False`. `stub_coords` is `None`
while `penalty_min` is 20. Consequences: the map draws a discontinuous corridor and
the promised 20-minute highway leg (D-14) is invisible/unexplained.
Fix: emit the arterial stub geometry, or if the two catchments touch, set
`inter_catchment=False` and drop the penalty. A third option is to keep the penalty
and label the card "inter-catchment · +20 m penalty (stub not drawn)".

### A3. Session eviction is now silent (P2)
`command/state.py` — `SessionStore.create`

At 64 sessions the oldest is dropped; a live operator whose session is evicted gets
a generic `404 session_not_found` mid-demo. `recoverSession()` in `App.tsx` handles
it, but the user is never told why their dispatch vanished.
Fix: return `410 session_expired` (or a `session_evicted: true` flag) and surface
"Session expired — rebuilt" in the log.

### A4. Barrier reopen is backend-only (P2)
`command/fleet.py::reopen_barrier`, `command/app.py` `POST /api/v1/reopen`

After the 60 s veto window a `CLOSED` barrier stays closed for the rest of the
session and the UI offers nothing. The endpoint exists now (unverified); the card
needs a "Reopen barrier" control when `unit_state === 'CLOSED'`.

### A5. Internal exception text is echoed to the client (P3)
`command/app.py::_handle_unexpected` — returns `f"{type(err).__name__}: {err}"`.
Fine for a demo, not for a public deployment. Log the detail, return a generic
message plus a correlation id.

### A6. No request-body size cap (P3)
`command/app.py` — nothing limits `Content-Length`. A 200 MB POST is read into
memory. `app.config["MAX_CONTENT_LENGTH"] = 1 << 20` would fix it.

### A7. Decision needed: late-but-feasible (WARN, not a bug)
7/30 alerts are `feasible: true` with `eta_min > ttp_min`. They now carry
`beats_peak: false` and a `LATE · ETA Xm arrives after T+Ym peak` directive.
Decide whether "feasible" should mean "a unit exists" (current) or "a unit can
arrive in time" (would flip those 7 to infeasible).

---

## B. Frontend defects — none of these are touched yet

### B1. Inventory fields accept impossible values (P2)
`web/src/components/SetupScreen.tsx:148–195` (inputs) vs `:71–73` (submit clamp)

`9999`, `-5`, `3.5` all stay in the field; they are silently clamped only on submit.
The audit flags this at 1920×1080. Fix: clamp + `Math.round` in `onChange`/`onBlur`
and show an inline "0–30" error instead of silently rewriting.

### B2. Reconfigure leaks the previous session (P2)
`web/src/App.tsx:713–716`

```tsx
onReconfigure={() => { setAutoClock(false); setConfig(null) }}
```
Leaves `scenario`, `sessionId`, `fleet`, `logs`, `activeRoute`, `selectedAlertId`,
`activeTransitId`, `degraded` intact. Confirmed in the audit: after switching to a
zero fleet, the queue still showed the previous session's cards with a live
**Approve & Dispatch**. Fix: reset every session-bound piece of state (and
`lastLogSeqRef.current = 0`), abort in-flight requests, then re-enter setup.

### B3. Empty state shown while the queue is still loading (P2)
`web/src/components/DispatchQueue.tsx:497–502`

Headless Chromium takes 4–6 s to paint the 30 cards; until then the panel says
**"No active directives match current filter."** Fix: pass a `loading` prop from
`App.tsx` and render a skeleton/"Computing consequence scores…" row.

### B4. Handlers throw unhandled rejections (P2)
- `web/src/App.tsx:519–524` `handleVetoBarrier` — no try/catch; a 409 leaves the UI
  showing the stale assigned card with no feedback.
- `web/src/App.tsx:405–427` `handleTick5m` — same.
- `web/src/App.tsx:429–441` `refreshScenarioNow` — same; callers assume it never throws.

Fix: wrap each, log a `*_FAILED` audit/local event, and revert optimistic state.

### B5. Auto-clock has no in-flight guard (P2)
`web/src/App.tsx:385–403`

`setInterval(async () => tickClockApi(...), 1000)` with a ~200–300 ms tick can overlap
on a slow machine, applying out-of-order clock values. Fix: a `tickInFlight` ref.

### B6. `roads` memo rebuilds on every clock tick (P2)
`web/src/App.tsx:670–674` — dependency array ends with `simClockMin`, but
`buildMockFallback(...)` roads do not depend on it. With 29,717 roads this is a real
cost. Fix: drop the dependency.

### B7. Mock mode can never produce a barrier (P2)
`web/src/App.tsx:74`

```tsx
const uclass = a.action === 'barrier' ? 'barrier' : ...
```
The API value is `barrier_closure`, so mock/offline mode always assigns pumps. Fix:
`a.action === 'barrier' || a.action === 'barrier_closure'`.

### B8. Barrier cards have no post-lock action (P2)
`web/src/components/DispatchQueue.tsx` card action row — veto exists only while
`veto_remaining_sec > 0`. Once `unit_state === 'CLOSED'` there is no control. Wire
`POST /api/v1/reopen` (add `reopenBarrierApi` in `web/src/lib/api.ts`).

---

## C. Harness / test defects (your green runs are lying)

### C1. `scripts/command/audit_api.py:463`
`j['id'] if 'node_id' in j else j` raises `KeyError: 'id'` and masks the real
failure. Use `j.get("node_id")`.

### C2. `scripts/command/audit_api.py:508–524`
`_tick` dispatches `alerts[0]`, which is now a **barrier** closure (barrier-first
classification), so the state trace is `CLOSED` and the check fails. Pick the first
`action == "pump_dispatch"` alert. Add a second check for the barrier lifecycle
`PENDING_CLOSE -> CLOSED -> (reopen) -> STANDBY`.

### C3. `scripts/command/audit_api.py:627–632`
`veto: unknown unit -> 409` expects the wrong code. `404` is correct REST for a
non-existent unit. Assert `404` here and add a separate `409 veto_not_pending`
check against an existing `IDLE` barrier.

### C4. `scripts/command/audit_api.py:773–780`
Detail string still says "never evicted; bounded by process life". Eviction is now
implemented; assert `after <= 64`.

### C5. `web/scripts/audit_ui.mjs` section D
`record('veto: a barrier closure is reachable in the UI', hasBarrier, …)` passes a
**boolean** as `status`. `record` indexes `{PASS,FAIL,WARN}[status]`, so the entry is
neither counted nor printed as a failure. Convert with `hasBarrier ? 'PASS' : 'FAIL'`.

### C6. `web/scripts/audit_ui.mjs` section D
Pins 25 mm/hr because that used to be the only setting producing a closure. Now
closures appear in 16/16 settings — move the check to 95 mm/hr so the demo path is
the one under test.

### C7. `web/scripts/audit_ui.mjs` section C
The zero-fleet block calls `waitQueue(page)` which can match the **previous**
session's cards. Wait for `PUMPS 0/0` (or a changed `SES-` id) before asserting.

### C8. `command/tests/` (24 tests, all green)
Nothing covers: barrier reachability at any storm setting, dismiss actually mutating
`depths`, the reopen lifecycle, the `addedMinutes` clamp, or `beats_peak`. These are
exactly the defects the audit found, so add one regression test per item.

---

## D. Reproduce everything

```bash
# backend audit (server must be restarted on the current code first)
.venv/bin/python -m command.app &
.venv/bin/python -m scripts.command.audit_api --base http://127.0.0.1:8000

# UI audit
cd web && node scripts/audit_ui.mjs

# unit tests
.venv/bin/python -m pytest command/tests -q

# machine-readable results
scratch/verification/api-audit.json
scratch/verification/ui-audit.json
```
