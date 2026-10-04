# Documentation audit

A review of every doc and diagram in the repository against the code at `408ad3b` (v1.8.0). Statuses: **accurate**, **outdated** (was right, the code moved on), **wrong**, **duplicate**, **missing**.

> **Resolved.** Every finding below about the docs and diagrams was fixed in the documentation overhaul: the pages were rewritten, the Mermaid diagrams were replaced by `docs/diagrams/`, and the replaced files are in `docs/archive/`. The code findings at the end are not doc problems; they are left as notes and no code was changed.

## Documents

| File | Status | Reason |
| --- | --- | --- |
| `README.md` | outdated | Config table misses `CORS_ORIGINS` and the `OPENAI_MODEL` / `OLLAMA_*` fallbacks; the request sequence predates the 1.8.0 disconnect handling; "Extending it" leaves out the `Action` and `TraceStep.node` literals a new skill needs |
| `docs/README.md` | accurate | Index is correct; calls SECURITY.md "five sandbox layers" where it lists five plus server limits |
| `docs/architecture.md` | outdated | Streaming section has no stop event or disconnect watcher (1.8.0); the concurrency diagram shows three locks, the code has four (session registry) |
| `docs/guide.md` | outdated | Module map misses `main → providers`, `main → config`, `skills → session`; DataUpload row doesn't mention the database card is hidden when connecting is off; troubleshooting tells you to move the backend to port 8001, which breaks the frontend (the Vite proxy is fixed to 8000) |
| `docs/windows.md` | wrong (one row) | Same port-8001 advice; everything else is accurate |
| `docs/deploy-render.md` | accurate | Env table and troubleshooting match the image and code |
| `backend/README.md` | accurate | Endpoint table matches `main.py` |
| `frontend/README.md` | outdated | DataUpload row lists database connect unconditionally |
| `SECURITY.md` | accurate | Layers and known gaps match the code |
| `CONTRIBUTING.md` | accurate | Matches CI jobs and the squash-only merge setting |
| `CHANGELOG.md` | accurate | Historical record; left as written |
| `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md` | accurate | |
| `backend/app/agent/graph.py` module docstring (ASCII graph) | accurate | Source code; not edited |

## Diagrams

| Where | Kind | Status | Reason |
| --- | --- | --- | --- |
| `README.md` system overview | Mermaid flowchart | accurate | Being replaced by `docs/diagrams/system-overview` |
| `README.md` layers | Mermaid flowchart | accurate | |
| `README.md` orchestrator | Mermaid flowchart | accurate | |
| `README.md` branch loop | Mermaid flowchart | accurate | |
| `README.md` question end to end | Mermaid sequence | outdated | No client-disconnect path |
| `README.md` security layers | Mermaid flowchart | accurate | |
| `README.md` deployment | Mermaid flowchart | accurate | |
| `docs/architecture.md` worker graph | Mermaid state | accurate | |
| `docs/architecture.md` orchestrator graph | Mermaid state | accurate | |
| `docs/architecture.md` state and reducers | Mermaid flowchart | accurate | |
| `docs/architecture.md` concurrency locks | Mermaid flowchart | outdated | Three of four locks |
| `docs/architecture.md` planner fallbacks | Mermaid flowchart | accurate | |
| `docs/architecture.md` streaming | Mermaid sequence | outdated | No stop event |
| `docs/architecture.md` provider layer | Mermaid flowchart | accurate | |
| `docs/architecture.md` skills and hooks | Mermaid flowchart | accurate | |
| `docs/guide.md` module map | Mermaid flowchart | outdated | Missing import edges |
| `docs/guide.md` frontend components | Mermaid flowchart | accurate | |
| `docs/README.md` doc picker | Mermaid flowchart | accurate | |
| `docs/windows.md` setup | Mermaid flowchart | accurate | |
| `docs/deploy-render.md` deploy steps | Mermaid flowchart | accurate | |
| `SECURITY.md` layers | Mermaid flowchart | duplicate | Same content as the README security diagram |
| `CONTRIBUTING.md` PR flow | Mermaid flowchart | accurate | |
| `docs/images/agent-graph.png` | PNG | wrong | Says "168 tests" (205 now), omits the `python` action, a label overlaps a route, footer predates module views and the audit hook |
| `docs/images/getting-started.png` | PNG | accurate | Local run; the deployment image hides the database card |
| `docs/images/demo.gif`, `kpi-cards.png`, `revenue-by-region.png` | Screenshots | accurate | Real runs |

## Flows with no diagram

- Dataset loading: sample, CSV upload and database URL into a session
- Dataset session lifecycle: created, in use, expired, evicted, disposed
- Agent run lifecycle, including the stop on client disconnect
- Data flow from source rows to the JSON response and the chart the UI draws
- SQL validation steps in order
- How the frontend picks SVG redraw, the model's PNG, or KPI cards
- The three Docker topologies (dev, compose, single image) side by side
- CI jobs and the checks `main` requires

## Found in the code while auditing (for the maintainer to decide)

1. `TraceStep.status` allows `"running"`, but nothing emits it (`backend/app/schemas.py:47`).
2. The verifier marks "found a gap, going back" with `status: "error"` (`graph.py`, `verify_node`), so a normal retry is styled like a failure in the reasoning panel.
3. `CORS_ORIGINS` is a real setting (`config.py:118`) that `.env.example` doesn't mention.
4. `backend/pyproject.toml` sets `line-length = 100` and then ignores `E501`, so line length isn't checked.
5. The frontend has no lint or test script, and CI only builds it.
6. Before `/api/health` answers, the landing page shows the database card and may then hide it.
