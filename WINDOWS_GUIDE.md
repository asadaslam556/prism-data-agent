# Windows Setup Guide, Prism

Everything below is PowerShell. If anything here conflicts with
`PROJECT_GUIDE.md`, this file wins for Windows.

---

## Prerequisites

Install these once:

- **Python 3.11 or newer** — https://www.python.org/downloads/windows/
  During install, tick **"Add python.exe to PATH"**. Check with `python --version`.
- **Node.js 18 or newer** — https://nodejs.org (the LTS installer).
  Check with `node -v`.
- **Ollama** — https://ollama.com/download. This is what runs the model locally.
- **Docker Desktop** (optional) — only needed for Option B below.

Two ways to run the project: **manual** (two terminals, best for development)
or **Docker** (one command, best for a clean demo). Start with manual.

---

## Option A — Run it manually

### Step 1. Get the code and the model

```powershell
git clone https://github.com/asadaslam556/prism-data-agent.git
cd prism-data-agent
ollama pull qwen2.5
```

`qwen2.5` is the default and works well. Any tool-capable model works. Bigger
models write noticeably better SQL; smaller ones lean harder on the retry and
fallback machinery, which is interesting to watch in the trace panel.

To use a different model, copy `backend\.env.example` to `backend\.env` and set:

```
OLLAMA_MODEL=your-model-name
```

Leave everything else as-is.

> **Naming the file:** Windows Explorer hides extensions by default, so a file
> saved as `.env` can silently become `.env.txt` and be ignored. In VS Code use
> **File → New File**, then **Save As** and type `.env` exactly.

### Step 2. Start the backend (terminal 1)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

If activation fails with `Activate.ps1 cannot be loaded`, PowerShell's
execution policy is blocking it. Allow it for this terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then run the activate line again. This resets when you close the terminal.

Check it worked by opening http://localhost:8000/api/health. You should see:

```json
{"status":"ok","version":"1.6.1","provider":"ollama","model":"qwen2.5"}
```

The `model` field confirms which model the backend will actually use.

### Step 3. Start the frontend (terminal 2)

Open a **second** PowerShell window. Leave the backend running in the first.

```powershell
cd prism-data-agent\frontend
npm install
npm run dev
```

Open http://localhost:5173, click **Load sample dataset**, and try:

> "Show the monthly revenue trend as a chart"

Then try a compound question to watch it split into parallel branches:

> "Revenue by region as a chart and revenue by category"

---

## Option B — Run it with Docker

One command, no Python or Node needed. Docker Desktop must be running.

```powershell
docker compose up --build
docker compose exec ollama ollama pull qwen2.5   # once, to fetch the model
```

Frontend on http://localhost:5173, API on port 8000, Ollama on 11434.

To use a different model, set it before starting:

```powershell
$env:OLLAMA_MODEL="your-model-name"
docker compose up --build
docker compose exec ollama ollama pull your-model-name
```

Stop everything with `docker compose down`.

**This stack ignores `backend\.env`.** The compose file passes the backend only
`OLLAMA_BASE_URL`, `LLM_PROVIDER` and `OLLAMA_MODEL`, so it always runs Ollama
no matter what your `.env` says. If you want to run the DeepSeek setup in a
container, use the single deployment image instead:

```powershell
docker build -t prism .
docker run --rm -p 7860:7860 --env-file backend\.env prism
```

That one reads your `.env` and serves the whole app on http://localhost:7860.

---

## Setting environment variables in PowerShell

PowerShell uses different syntax from the `export` lines in the root README:

```powershell
$env:LLM_PROVIDER="anthropic"
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:LLM_MODEL="claude-sonnet-4-6"
```

These last only for the current terminal. For anything permanent, put it in
`backend\.env` instead.

---

## Using DeepSeek instead of Ollama

DeepSeek speaks the OpenAI schema, so it runs through the `openai` provider
with a different base URL. Copy `backend\.env.example` to `backend\.env` and
set:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=deepseek-v4-flash
OPENAI_API_KEY=sk-your-real-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}
```

That last line is required. DeepSeek's V4 models think by default, and thinking
mode refuses a forced tool choice, which is what the agent uses for its planner,
decomposer and verifier. Without it every question fails with
`400 Thinking mode does not support this tool_choice`.

Use the short model name. The long `deepseek-ai/deepseek-v4-flash-0731` is
NVIDIA's naming and 404s on DeepSeek's own endpoint. Keys start with `sk-`, not
`nvapi-`, and come from https://platform.deepseek.com. The API is prepaid, so
whatever you top up is the most you can spend.

Ollama doesn't need to be running when you're on DeepSeek.

---

## Starting clean

Config is read once when the server boots, and `uvicorn --reload` only watches
`.py` files. **Editing `backend\.env` does nothing until you stop the server
with Ctrl+C and start it again.** If a setting change seems to have no effect,
that is almost always why, and it is worth checking before anything else.

Make sure nothing is still holding the port:

```powershell
netstat -ano | findstr :8000
```

More than one PID means an old server is still running from a previous session.
Kill it with `taskkill /PID <pid> /F`, then start again.

If you want a genuinely clean baseline, rebuild both halves:

```powershell
cd backend
Remove-Item -Recurse -Force .venv
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

cd ..\frontend
Remove-Item -Recurse -Force node_modules
npm cache clean --force
npm install
```

Docker is the one place a real build cache exists, so it needs an explicit flag:

```powershell
docker build --no-cache -t prism .
```

Worth being honest about what this does: clearing `.venv` and `node_modules`
almost never fixes a bug. Python re-reads your own `.py` files on every start,
and `node_modules` has nothing to do with a backend error. It rules out
dependency-version confusion, which is occasionally the problem. The restart is
the part that usually matters.

---

## Running the checks

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest                          # 176 tests, no Ollama needed
ruff check app tests list_models.py       # lint

cd ..\frontend
npm run build                             # catches JSX breakage
```

These are exactly what CI runs, so if they pass locally you're in good shape.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Activate.ps1 cannot be loaded` | Execution policy. Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| `python` or `node` not recognised | Not on PATH. Reinstall Python with "Add python.exe to PATH" ticked, or restart the terminal after installing. |
| Answers fail instantly, log shows connection errors to `11434` | Ollama isn't running. Start the Ollama app from the Start menu. |
| Error saying the model was not found | Model not pulled: `ollama pull qwen2.5`, or whatever `OLLAMA_MODEL` is set to. |
| Changed `.env` but nothing happened | Config is read once at startup. Stop the server with Ctrl+C and start it again. `--reload` only watches `.py` files. |
| Questions fail with "Thinking mode does not support this tool_choice" | On DeepSeek, set `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}` in `backend\.env`, then restart the server. |
| Health shows a different model than you set | `backend\.env` wasn't picked up. Confirm the file is named exactly `.env` and not `.env.txt`, then restart the backend. |
| Port 8000 or 5173 already in use | Use another port: `uvicorn app.main:app --reload --port 8001` or `npm run dev -- --port 5174`. |
| First answer is very slow | The model loads into RAM on first use. Later questions are much faster. Keep Ollama running. |
| SQL keeps retrying in the trace | The model got a query wrong and is self-correcting. That's the loop working. A bigger model reduces it. |
| `npm install` complains about Node | Node 18+ required. Check with `node -v`. |
| Uploaded file rejected | Only `.csv` and `.tsv` are accepted, and the file must have rows. |

---

## Where to go next

`PROJECT_GUIDE.md` has the full walkthrough of what every file does and how a
question flows through the system. `docs/architecture.md` covers the state
design and the trade-offs behind the parallel graph.