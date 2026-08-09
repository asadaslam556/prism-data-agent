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
git clone https://github.com/<your-username>/prism.git
cd prism
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
{"status":"ok","version":"1.5.0","provider":"ollama","model":"qwen2.5"}
```

The `model` field confirms which model the backend will actually use.

### Step 3. Start the frontend (terminal 2)

Open a **second** PowerShell window. Leave the backend running in the first.

```powershell
cd prism\frontend
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

## Running the checks

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest                          # 168 tests, no Ollama needed
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