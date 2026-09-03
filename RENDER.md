# Deploying Prism to Render, step by step

Render is the one free host that runs a real container, which is what Prism
needs. Everything below assumes you have never used it before.

Roughly 30 minutes, most of it waiting for a build.

---

## Part 1: What makes this deployable

Three things in the repo already handle the Render-specific parts. Nothing to
download; this section is just so you know why they look the way they do.

| File | What it handles |
| --- | --- |
| `Dockerfile` (repo root) | Builds React and serves it from FastAPI, listens on `$PORT` |
| `backend/app/main.py` | Optional HTTP Basic login |
| `backend/.env.example` | Documents every variable you'll need below |

**Why the Dockerfile reads `$PORT`.** Render decides which port your app runs
on and passes it in as an environment variable called `PORT`. A hardcoded port
means Render sends traffic somewhere nothing is listening and the deploy fails
with "no open ports detected". The `CMD` line uses `${PORT:-7860}`, so Render
gets its port and local Docker still works exactly the same on 7860.

**Why the login exists.** Render has no private mode. Without it, anyone who
finds your URL can ask questions, and your DeepSeek balance pays for every one
of them.

Note that the root `Dockerfile` and `backend/Dockerfile` are different files
doing different jobs. The root one is this single deployment image. The backend
one is only used by `docker-compose.yml` for the local three-service Ollama
stack. Don't merge them.

---

## Part 2: Set up your local .env

Copy `backend/.env.example` to `backend/.env` and set these five values:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=deepseek-v4-flash
OPENAI_API_KEY=sk-your-real-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}
```

Three things to notice:

- `LLM_MODEL=deepseek-v4-flash` — the short name. The long
  `deepseek-ai/deepseek-v4-flash-0731` is NVIDIA's naming and gives a 400 here.
- DeepSeek keys start with `sk-`, not `nvapi-`.
- `LLM_EXTRA_BODY` is required, not optional. DeepSeek's V4 models run in
  thinking mode by default, and thinking mode refuses a forced tool choice —
  which is exactly what the agent's planner, decomposer and verifier use. Leave
  it blank and every question fails with
  `400 Thinking mode does not support this tool_choice`.

Config is read once when the server starts, so if you edit `.env` while it's
running, stop it with Ctrl+C and start it again. `uvicorn --reload` only
watches `.py` files.

Get the key at https://platform.deepseek.com → API keys. You need to top up a
balance first; the API is prepaid, so $5 is a hard ceiling on what you can
possibly spend.

Test locally before going near Render:

```powershell
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/api/health. It should say:

```json
{"status":"ok","version":"1.6.1","provider":"openai","model":"deepseek-v4-flash"}
```

Then start the frontend in a second terminal and ask a real question. If that
works, the deploy will work.

---

## Part 3: Test the container

Render runs your Dockerfile, so build it yourself first. Debugging a build
through someone else's log viewer is miserable.

```powershell
cd path\to\prism-data-agent
docker build -t prism .
docker run --rm -p 7860:7860 --env-file backend/.env -e APP_USERNAME=admin -e APP_PASSWORD=choose-a-long-one prism
```

Open http://localhost:7860. You should get a browser login box. Enter the
username and password you just passed in.

If the login appears and the app works behind it, you are ready.

---

## Part 4: Push to GitHub

Render deploys from GitHub, not from your hard drive. Nothing you haven't
pushed exists as far as Render is concerned.

```powershell
git add .
git commit -m "Add Dockerfile and optional login for deployment"
git push
```

Quick safety check before you push:

```powershell
git status --short | Select-String "\.env$"
```

Must print nothing. Your `.gitignore` already handles it.

---

## Part 5: Create the service on Render

1. Go to https://render.com and **Sign up with GitHub**. No card needed.
2. Authorise Render to see your repositories.
3. Click **New +** → **Web Service**.
4. Find `prism-data-agent` and click **Connect**.
5. Fill in the form:

| Field | Value |
| --- | --- |
| Name | `prism` |
| Language / Runtime | **Docker** |
| Branch | `main` |
| Region | **Frankfurt** (closest to you) |
| Dockerfile Path | `./Dockerfile` |
| Instance Type | **Free** |

Leave "Root Directory" and "Docker Build Context Directory" blank. Your
Dockerfile is at the repo root, which is the default.

**Do not click Create yet.** Add the environment variables first, or the first
build starts without a key and fails.

---

## Part 6: Environment variables

Scroll to **Environment Variables** and add these one at a time. Click
**Add Environment Variable** for each.

| Key | Value |
| --- | --- |
| `APP_USERNAME` | your choice |
| `APP_PASSWORD` | something long you haven't used elsewhere |
| `OPENAI_API_KEY` | your DeepSeek key, `sk-...` |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_PROVIDER` | `openai` |
| `LLM_MODEL` | `deepseek-v4-flash` |
| `LLM_EXTRA_BODY` | `{"thinking": {"type": "disabled"}}` |
| `LLM_TEMPERATURE` | `0.0` |
| `LLM_MAX_TOKENS` | `2048` |
| `LLM_REQUEST_TIMEOUT` | `180` |
| `MAX_UPLOAD_MB` | `5` |
| `MAX_SESSIONS` | `3` |
| `MAX_PARALLEL_BRANCHES` | `2` |
| `LOG_LEVEL` | `INFO` |

**`LLM_EXTRA_BODY` is not optional.** It is the same line from Part 2. Skip it
here and the deployed app fails on every question with
`400 Thinking mode does not support this tool_choice`, even though it worked
locally, because Render does not read your `backend/.env`.

**The last three are not optional either.** The free instance has 512 MB of RAM.
pandas, numpy, matplotlib, langchain and SQLAlchemy together take roughly
300 MB before any data is loaded. A 25 MB CSV becomes a much larger DataFrame
in memory and the container gets killed. Dropping the upload cap to 5 MB,
sessions to 3, and parallel branches to 2 keeps it inside the budget.

You do **not** need to set `PORT` — Render sets it for you.

You do **not** need to set `ENABLE_DB_CONNECT` — the Dockerfile forces it off.

---

## Part 7: Deploy

Click **Create Web Service**.

The first build takes 5–10 minutes: it installs npm packages, builds React,
then installs the Python dependencies. Watch the **Logs** tab.

You are looking for:

```
INFO:     Uvicorn running on http://0.0.0.0:10000
==> Your service is live 🎉
```

Your URL will be something like `https://prism.onrender.com`.

Open it. You should get the login prompt, then the app.

---

## Part 8: Your phone

Open the URL in your phone browser and enter the username and password. The
browser remembers them.

- **Android/Chrome:** menu → **Install app**
- **iPhone/Safari:** Share → **Add to Home Screen**

Now you have an icon that works whether or not your laptop is on.

---

## Things that will happen, and are normal

**The first visit after a few hours is slow.** Free services sleep after 15
minutes of no traffic. Waking takes about 50 seconds. Once awake it's normal
speed. If you're demoing to someone, open the link yourself a minute
beforehand.

**"Database connections are disabled."** Correct. The image sets
`ENABLE_DB_CONNECT=false` on purpose. Sample dataset and CSV upload both work.

**Pushing to GitHub redeploys automatically.** That's the default. Turn it off
under Settings → Build & Deploy if you'd rather deploy manually.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Build fails: "no open ports detected" | Old Dockerfile still in the repo. It must use `${PORT:-7860}`. |
| Build fails at `npm ci` | `package-lock.json` out of sync. Run `npm install` locally, commit the lockfile, push. |
| Deploy succeeds, page is blank | The `static` folder didn't get copied. Check the `COPY --from=frontend` line survived. |
| No login prompt | One of `APP_USERNAME` / `APP_PASSWORD` is blank. Both are required. |
| Login rejected repeatedly | A trailing space got pasted into the password value in Render. Retype it. |
| Questions fail with 401 | `OPENAI_API_KEY` wrong, or you pasted an `nvapi-` key instead of `sk-`. |
| Questions fail with "Thinking mode does not support this tool_choice" | `LLM_EXTRA_BODY` is missing or blank in the Render dashboard. Set it to `{"thinking": {"type": "disabled"}}` and redeploy. |
| Questions fail with "model not found" | `LLM_MODEL` must be `deepseek-v4-flash`, not the NVIDIA long form. |
| Service restarts mid-question | Out of memory. Lower `MAX_UPLOAD_MB` to 2 and `MAX_SESSIONS` to 2. |
| Everything times out | DeepSeek balance is empty. Check platform.deepseek.com. |

---

## Cost

Render: $0.

DeepSeek: roughly half a cent per question at off-peak rates. Fifty questions a
month is about 25 cents. Because it's prepaid, whatever you top up is the
absolute maximum you can ever spend — top up $5 and forget about it.