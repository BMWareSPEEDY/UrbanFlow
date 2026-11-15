# `scratch/` — Working Memory for the UrbanFLOW Command Layer

This directory is **not** production code and is not imported by `app.py`. It is the project's
durable scratchpad: raw briefs, distilled specs, factual snapshots of the codebase, and a
decision log. Its purpose is that nothing you say in conversation gets lost.

## Layout

```
scratch/
├── README.md                 ← you are here (index + rules)
├── inbox/                    ← raw captures, verbatim, never edited after capture
├── specs/                    ← distilled, buildable specifications
├── reference/                ← factual snapshots of the *existing* system
└── decisions/                ← ADR-style decision log (one entry per irreversible choice)
```

| Folder | Rule |
|---|---|
| `inbox/` | Append-only. Date + sequence prefix. Verbatim dump of what was said. Never "improved" after the fact. |
| `specs/` | Living documents. Edited freely. Versioned in the filename (`UF-COMMAND-V1`, `-V2`, …). |
| `reference/` | Facts read out of the codebase. Re-verify before trusting; each file states its snapshot date. |
| `decisions/` | Append-only. Never delete an entry — supersede it with a new one and mark the old as `SUPERSEDED`. |

## Naming convention

```
inbox/YYYY-MM-DD-NN__short-slug.md
specs/UF-COMMAND-Vn__short-slug.md
reference/YYYY-MM-DD__what-it-describes.md
decisions/decision-log.md            # single running file, numbered entries D-01, D-02, ...
```

## Current contents

| File | What it holds |
|---|---|
| `inbox/2026-11-14-01__municipal-flood-command-brief.md` | The original brief for the Command & Dispatch System, as given. |
| `specs/UF-COMMAND-V1__municipal-flood-command-and-dispatch-spec.md` | The detailed build document: architecture, algorithms, thresholds, API contracts, UI, milestones, demo. |
| `reference/2026-11-14__baseline-system-snapshot.md` | What the repo actually contains today — endpoints, regions, node counts, real thresholds, dependencies, and every place the brief conflicts with the code. |
| `decisions/decision-log.md` | Open and closed decisions, with rationale and consequences. |
| `figures/` | Screenshots produced by `web/scripts/verify.mjs` (1920×1080, 1366×768, Red-Alert state). |

Related, outside this directory: `web/` is the React + TypeScript dashboard source (D-17). It builds
into `static/command/`, which is committed, so the demo never needs Node.

## How to use this with an agent

1. New brief → drop it in `inbox/`, then update `specs/` and record any new choice in `decisions/`.
2. Any claim about the existing system must be traceable to `reference/` or re-read from source.
3. Numbers that appear in the demo (latency, node counts, F1, MAE) must match `reference/`, not memory.
