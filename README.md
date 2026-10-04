<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.png">
    <img src="docs/images/logo.png" alt="Prism logo: a prism splitting a question into data, code, table and chart" width="200" height="200">
  </picture>
</p>

<h1 align="center">Prism</h1>

<p align="center">
  <strong>Ask your data questions in plain English.</strong><br>
  A LangGraph agent splits the question up, writes the SQL, runs pandas, draws the charts<br>
  and checks its own answer, showing every step live while it works.
</p>

<p align="center">
  <a href="https://github.com/asadaslam556/prism-data-agent/actions/workflows/ci.yml"><img src="https://github.com/asadaslam556/prism-data-agent/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/asadaslam556/prism-data-agent/security/code-scanning"><img src="https://github.com/asadaslam556/prism-data-agent/actions/workflows/github-code-scanning/codeql/badge.svg" alt="CodeQL"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white" alt="Python 3.11 | 3.12">
  <img src="https://img.shields.io/badge/node-20.19%2B-5FA04E?logo=nodedotjs&logoColor=white" alt="Node 20.19+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#security-model">Security</a> ·
  <a href="docs/README.md">Docs</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" alt="A session on the bundled sample: a simple question, a line chart, a two-part question running as parallel tasks, and KPI cards" width="900">
  <br>
  <em>One session on the bundled sample: a simple question, a monthly trend as a line chart, a two-part question that runs as parallel tasks, and KPI cards.</em>
</p>

---

## Contents

- [Highlights](#highlights)
- [What it looks like](#what-it-looks-like)
- [Tech stack](#tech-stack)
- [Quickstart](#quickstart)
- [Using a hosted model](#using-a-hosted-model)
- [Usage](#usage)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Security model](#security-model)
- [Deployment](#deployment)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Extending it](#extending-it)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [License](#license)

## Highlights

- **Runs on your machine.** The model (through [Ollama](https://ollama.com)), the database and the code sandbox all stay local. No API keys, and your data never leaves the box.
- **Parallel by design.** A question with independent parts is split into separate agent loops that run at the same time, then merged.
- **Checks its own work.** A separate verifier looks at the merged results and can send the work back for another pass.
- **Shows its reasoning.** Every step streams to the browser as it happens, and folds away once the answer arrives.
- **Safe to point at real data.** Generated SQL is read-only and row-capped; generated Python runs in a sandbox with static checks, restricted modules, a runtime audit hook and a watchdog.
- **Swappable model.** One environment variable moves from Ollama to OpenAI or any OpenAI-compatible service, such as DeepSeek or Groq.

## What it looks like

| Load data | Get a grounded answer |
| :---: | :---: |
| <img src="docs/images/getting-started.png" alt="Three ways to load data: the bundled sample, a CSV upload, or any SQLAlchemy database URL" width="440"> | <img src="docs/images/kpi-cards.png" alt="A finished answer: the reasoning panel collapsed, the written explanation, and KPI cards built from the query result" width="440"> |
| Upload a CSV, connect Postgres, MySQL or SQLite, or use the bundled 1,400-order sample. | The answer, plus the SQL it wrote, the result table, any pandas analysis and the chart. |

| The agent graph | A chart it drew |
| :---: | :---: |
| <img src="docs/diagrams/orchestrator.architecture.svg" alt="The orchestrator graph: decompose, parallel branches, merge, verify with a bounded retry, interpret" width="440"> | <img src="docs/images/revenue-by-region.png" alt="Total revenue by region, drawn by the agent from the bundled sample" width="440"> |
| Decompose, fan out, merge, verify, answer. | Bar and line charts are redrawn as SVG with hover values; anything else is shown as drawn. |

## Tech stack

<p align="center">
  <img src="https://skillicons.dev/icons?i=python,fastapi,react,vite,docker,githubactions,sqlite,postgres,mysql,nginx" alt="Python, FastAPI, React, Vite, Docker, GitHub Actions, SQLite, PostgreSQL, MySQL, nginx">
</p>

| Layer | Built with | Why |
| --- | --- | --- |
| Frontend | ![React](https://img.shields.io/badge/React_19-20232A?logo=react&logoColor=61DAFB) ![Vite](https://img.shields.io/badge/Vite_8-646CFF?logo=vite&logoColor=white) | A small console with no runtime dependencies beyond React. Charts and markdown are drawn by hand. |
| API | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white) | REST endpoints plus a Server-Sent Events stream for live steps. |
| Agent | ![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?logo=langgraph&logoColor=white) ![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white) | Two explicit state graphs: an orchestrator and a worker loop. |
| Models | ![Ollama](https://img.shields.io/badge/Ollama-000000?logo=ollama&logoColor=white) ![OpenAI compatible](https://img.shields.io/badge/OpenAI--compatible-412991) ![DeepSeek](https://img.shields.io/badge/DeepSeek-4D6BFE?logo=deepseek&logoColor=white) | Local by default, hosted with one variable. |
| Analysis | ![pandas](https://img.shields.io/badge/pandas-150458?logo=pandas&logoColor=white) ![NumPy](https://img.shields.io/badge/NumPy-013243?logo=numpy&logoColor=white) ![Matplotlib](https://img.shields.io/badge/Matplotlib-11557C) | The sandboxed analysis and charting environment. |
| Data | ![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?logo=sqlalchemy&logoColor=white) ![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white) | Every dataset sits behind one SQLAlchemy engine, whatever its source. |
| Quality | ![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white) ![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black) ![CodeQL](https://img.shields.io/badge/CodeQL-2F3237?logo=github&logoColor=white) | Tests with the model mocked, linting, and code scanning on every push. |
| Delivery | ![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white) ![Render](https://img.shields.io/badge/Render-46E3B7?logo=render&logoColor=black) | One deployment image, CI on Python 3.11 and 3.12, hosted on Render. |

## Quickstart

You need **Python 3.11+**, **Node 20.19+** and **[Ollama](https://ollama.com/download)**.

![Running Prism locally: install once, pull a model, start the backend and the frontend in two terminals, open localhost:5173](docs/diagrams/local-setup.workflow.svg)

**1. Pull a model** (once):

```bash
ollama pull qwen2.5
```

Any tool-capable model works. Bigger models write better SQL; smaller ones lean harder on the retry and fallback logic.

**2. Start the backend** (terminal 1):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**3. Start the frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and click **Load sample dataset**. The Vite dev server proxies `/api` to port 8000, so keep the backend there.

On Windows, [docs/windows.md](docs/windows.md) walks through the same steps in PowerShell.

<details>
<summary><strong>Or run everything with Docker</strong></summary>

```bash
docker compose up --build
docker compose exec ollama ollama pull qwen2.5   # once
```

Frontend on http://localhost:5173, API on port 8000, Ollama on 11434. This stack always runs on Ollama; see [docs/deployment.md](docs/deployment.md) for the single-image option.

</details>

## Using a hosted model

Set `LLM_PROVIDER=openai` and a key, then restart the backend. The provider package is already in `requirements.txt`.

**OpenAI:**

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=<YOUR_API_KEY>
export LLM_MODEL=gpt-4o-mini
```

**DeepSeek**, or any other OpenAI-compatible service, uses the same provider with a different base URL:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=<YOUR_API_KEY>
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-v4-flash
export LLM_EXTRA_BODY='{"thinking": {"type": "disabled"}}'
```

> [!IMPORTANT]
> Don't skip the last line. DeepSeek's V4 models run in thinking mode by default, and thinking mode rejects a forced tool choice (`400 Thinking mode does not support this tool_choice`). The planner, decomposer and verifier all rely on exactly that, so without it every question fails. Turning thinking off also makes runs faster.

- `OPENAI_BASE_URL` points the provider at any compatible server: LM Studio, vLLM, Groq, a company gateway.
- Gateways often rename models (`gpt-4o-mini@default`, say). Run `python list_models.py` from `backend/` to list what your endpoint serves.
- Some models reject `temperature`. Set `LLM_TEMPERATURE=` (blank) to leave it out of the request.
- The pill in the app header shows which model is answering.

If the backend can't reach the model (Ollama not running, a bad key) you get a readable message saying what to check, not a stack trace. More in [docs/models.md](docs/models.md).

## Usage

Load the sample, then try:

| Ask | What you'll see |
| --- | --- |
| *What is total revenue by region?* | One query, a table and a short answer |
| *Show the monthly revenue trend as a chart* | A query and a chart; bar and line charts are redrawn from the rows |
| *Revenue by region as a chart and revenue by category* | Two branches running at the same time, one per part |
| *Total revenue, average order value and order count* | A single-row result shown as KPI cards |

Each answer comes with the SQL the agent wrote, the result table, any pandas code it ran, and a collapsible panel with every step it took.

The same agent is available over HTTP:

```bash
# load the sample and keep its session id
curl -s http://localhost:8000/api/sample

# ask a question in one request
curl -s http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<SESSION_ID>", "question": "What is total revenue by region?"}'
```

`POST /api/query/stream` streams the same run as Server-Sent Events. Every route is in [docs/api.md](docs/api.md).

## Configuration

Everything is an environment variable. Copy `backend/.env.example` to `backend/.env` and edit it; the file is read once at startup, so restart the server after a change. Defaults and details for every setting are in [docs/configuration.md](docs/configuration.md).

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `ollama` or `openai` (OpenAI or any compatible endpoint) |
| `LLM_MODEL` | Model for the active provider |
| `LLM_TEMPERATURE`, `LLM_TOP_P`, `LLM_MAX_TOKENS` | Sampling and length; blank leaves temperature and top-p out |
| `LLM_REQUEST_TIMEOUT` | Seconds per model call |
| `LLM_EXTRA_BODY` | Raw JSON merged into the request, for switches like DeepSeek's thinking mode |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | The hosted provider's key and endpoint |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Where Ollama listens, and its model |
| `MAX_AGENT_STEPS` | Planner steps, shared by all branches of one question |
| `MAX_PARALLEL_BRANCHES` | Sub-questions run at once; `1` gives a single loop |
| `MAX_VERIFY_PASSES`, `ENABLE_VERIFIER` | How often the verifier may send work back, or turn it off |
| `MAX_SQL_ROWS`, `SQL_RETRY_ATTEMPTS` | Row cap on every query, and retries after a failed one |
| `SANDBOX_TIMEOUT_SECONDS` | Wall-clock cap on one generated snippet |
| `MAX_UPLOAD_MB`, `MAX_SESSIONS`, `SESSION_TTL_MINUTES` | Upload size, datasets kept loaded, and for how long |
| `APP_USERNAME`, `APP_PASSWORD` | Set both to put the whole app behind a browser login |
| `ENABLE_DB_CONNECT` | Allows `/api/connect`; the deployment image turns it off |
| `CORS_ORIGINS` | Origins allowed to call the API from another host |
| `LOG_LEVEL` | App log level |

## Architecture

One React app, one FastAPI process, one agent. The model provider and the data source are both swappable.

<a href="docs/diagrams/system-overview.architecture.html"><img src="docs/diagrams/system-overview.architecture.svg" alt="System overview: the React console talks to one FastAPI process holding the agent graph, skills, guardrails, sandbox, model layer, session registry and connectors; the model provider and your own database sit outside it"></a>

The question is split into independent parts by an **orchestrator** graph, and each part runs its own **plan-act loop** at the same time:

| Orchestrator | Branch loop |
| :---: | :---: |
| <img src="docs/diagrams/orchestrator.architecture.svg" alt="Orchestrator: decompose, branches in parallel, merge, verify with a bounded retry, interpret" width="440"> | <img src="docs/diagrams/branch-loop.architecture.svg" alt="Branch loop: plan picks sql, python or chart, each tool returns to plan, answer ends the branch" width="440"> |

Every step streams to the browser as it finishes:

![A question end to end: the browser posts to FastAPI, the graph runs on its own thread, branches query the data and stream steps over SSE, then the final answer arrives](docs/diagrams/question.sequence.svg)

[docs/architecture.md](docs/architecture.md) walks through all 21 diagrams. Each one also has an interactive version (`.html` next to the image in [docs/diagrams/](docs/diagrams/)) with search, focus and light and dark themes; in the code-level architecture diagrams, components link to their source lines.

## Security model

Running SQL and Python that a model wrote is the main risk here, so everything it writes passes through independent layers.

![Layers around model-written Python: AST check, restricted namespace, audit hook, watchdog; a rejection, error or timeout goes back to the planner](docs/diagrams/python-sandbox.architecture.svg)

![How a generated query gets run: validate_sql, then run_select, with rejections and query errors sent back to the model](docs/diagrams/sql-guard.architecture.svg)

This is hardening for a local, single-user tool, not a jail. CPython can't be fully locked down from inside its own process. [SECURITY.md](SECURITY.md) lists the known gaps and how to report a vulnerability; [docs/guardrails.md](docs/guardrails.md) covers each layer.

## Deployment

![Three ways to run Prism: Vite and uvicorn on your machine, docker compose with three containers, or the single image on a host such as Render](docs/diagrams/deployment.architecture.svg)

The root `Dockerfile` builds one image: FastAPI serves the built React app and the API on one port (`$PORT`, 7860 by default), with `/api/connect` turned off. [docs/deployment.md](docs/deployment.md) compares the three setups, and [docs/deploy-render.md](docs/deploy-render.md) puts the image on Render's free tier behind a login.

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
ruff check app tests list_models.py
```

The model is mocked in every test, so the suite runs anywhere, CI included, without Ollama. It covers:

- both guardrails, and every sandbox escape route found so far
- the data layer, the API and the server limits
- the worker loop, its fallbacks and the step budget
- the orchestration layer: decomposition, real thread-level parallelism, verifier retries
- provider selection and outage handling
- the concurrency bugs that only appeared once branches ran at the same time

CI runs the same checks on Python 3.11 and 3.12, builds the frontend and builds the deployment image; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Project structure

```
prism-data-agent/
├── backend/
│   ├── app/
│   │   ├── agent/          # graphs, state, prompts, model providers
│   │   ├── skills/         # sql, python, chart, interpret
│   │   ├── hooks/          # guardrails, step budget, logging
│   │   ├── services/       # dataset sessions, execution sandbox
│   │   ├── data/           # SQLAlchemy connectors
│   │   ├── config.py       # settings, all overridable by env var
│   │   ├── schemas.py      # API models
│   │   └── main.py         # FastAPI app, middleware and routes
│   ├── data/samples/       # the bundled sales dataset
│   ├── tests/
│   ├── list_models.py      # asks the configured endpoint what it serves
│   ├── Dockerfile          # backend image for docker-compose
│   └── requirements*.txt
├── frontend/               # React + Vite console
├── docs/
│   ├── diagrams/           # archify sources (.json), interactive .html, .svg and .png
│   ├── images/             # screenshots, demo and logo
│   └── archive/            # superseded pages, kept for history
├── Dockerfile              # single deployment image
└── docker-compose.yml      # Ollama + backend + frontend for local use
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Answers fail with connection errors to port 11434 | Ollama isn't running. Start it, or run `ollama serve`. |
| "Not Found" when loading the sample | Something else is listening on port 8000. Stop it; the frontend always proxies to 8000. |
| A changed `.env` setting has no effect | It's read once at startup. Restart the backend. |
| DeepSeek fails with `Thinking mode does not support this tool_choice` | Set `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}`. |

More in [docs/troubleshooting.md](docs/troubleshooting.md).

## Extending it

To add a capability, say forecasting:

1. Create `backend/app/skills/forecast_skill.py` exposing `NAME`, `DESCRIPTION` and `run(...) -> SkillResult`.
2. In `backend/app/agent/graph.py`, add the action to the `Action` type, add a node with a loop-back edge to `plan`, and map it in `branch_route`.
3. Describe the action in `PLANNER_SYSTEM` in `backend/app/agent/prompts.py`.
4. Add the node name to `TraceStep.node` in `backend/app/schemas.py`, or `/api/query` rejects the new step.

The reasoning panel picks the new steps up with no frontend change. A new model provider is one function in `backend/app/agent/providers.py` with `@register("name")` on it.

## Roadmap

- [ ] Keep intermediate DataFrames across a conversation so follow-ups don't re-query
- [ ] Dependent sub-questions, where one branch feeds another
- [ ] Multiple tables and joins
- [ ] Result caching keyed on question and schema
- [ ] Export a run as a notebook

## Documentation

Start at [docs/README.md](docs/README.md), which maps every page.

| Document | What's in it |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Every diagram, explained |
| [docs/agent.md](docs/agent.md) | The orchestrator, the branch loop, the planner, streaming |
| [docs/data.md](docs/data.md) | Loading data, sessions, where the numbers come from, concurrency |
| [docs/guardrails.md](docs/guardrails.md) | The SQL guard and the Python sandbox |
| [docs/configuration.md](docs/configuration.md) | Every setting, with defaults |
| [docs/api.md](docs/api.md) | Every route and the streaming format |
| [docs/deployment.md](docs/deployment.md) | Local, compose and single-image setups, and CI |
| [SECURITY.md](SECURITY.md) | Known gaps and how to report a vulnerability |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup for contributors, checks, and where things go |

## License

Built and maintained by **Asad Aslam** · [GitHub](https://github.com/asadaslam556) · [asadaslam.tech](https://asadaslam.tech/)

Released under the [MIT License](LICENSE).
