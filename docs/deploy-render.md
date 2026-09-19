# Deploying to Render

Render's free tier runs a real container, which is what Prism needs. This guide assumes you've never used it, and uses DeepSeek as the model provider because it's cheap and prepaid. Any provider from the README works the same way; only the environment variables change.

Budget about 30 minutes, most of it waiting for the first build.

## 1. What's already in the repo

| File | What it handles |
| --- | --- |
| `Dockerfile` (repo root) | Builds the React app and serves it from FastAPI on `$PORT` |
| `backend/app/main.py` | The optional HTTP Basic login |
| `backend/.env.example` | Every variable you'll set below |

**Why `$PORT` matters.** Render picks the port and passes it in as `PORT`. A hardcoded port means Render sends traffic where nothing is listening, and the deploy fails with "no open ports detected". The `CMD` line uses `${PORT:-7860}`, so Render gets its port and local Docker still uses 7860.

**Why the login matters.** Render has no private mode. Without the login, anyone who finds the URL can ask questions, and your API balance pays for every one of them.

The root `Dockerfile` and `backend/Dockerfile` do different jobs. The root one is this single deployment image. The backend one is only used by `docker-compose.yml` for the local three-service stack with Ollama.

## 2. Set up and test locally

Copy `backend/.env.example` to `backend/.env` and set:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=deepseek-v4-flash
OPENAI_API_KEY=sk-your-real-key
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}
```

- Use the short model name. The long `deepseek-ai/deepseek-v4-flash-0731` is NVIDIA NIM's naming and fails on DeepSeek's own endpoint.
- DeepSeek keys start with `sk-`, not `nvapi-`. Get one at https://platform.deepseek.com under API keys. The API is prepaid, so top up a small balance first; that balance is the most you can ever spend.
- `LLM_EXTRA_BODY` is required. DeepSeek's V4 models think by default, and thinking mode refuses the forced tool choice the planner, decomposer and verifier rely on. Leave it out and every question fails with `400 Thinking mode does not support this tool_choice`.

The server reads `.env` once at startup, and `uvicorn --reload` only watches `.py` files, so restart it after any change.

```powershell
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

http://localhost:8000/api/health should return something like:

```json
{"status":"ok","version":"1.7.0","provider":"openai","model":"deepseek-v4-flash"}
```

Start the frontend in a second terminal and ask a real question. If that works, the deploy will too.

## 3. Test the container

Render builds your Dockerfile, so build it yourself first. Debugging a failed build through Render's log viewer is much slower.

```powershell
docker build -t prism .
docker run --rm -p 7860:7860 --env-file backend/.env -e APP_USERNAME=admin -e APP_PASSWORD=choose-a-long-one prism
```

Open http://localhost:7860. You should get a browser login prompt; enter the username and password you just passed in. If the app works behind it, you're ready.

## 4. Push to GitHub

Render deploys from GitHub, so anything not pushed doesn't exist as far as it's concerned. Before pushing, make sure your `.env` isn't about to go with it:

```powershell
git status --short | Select-String "\.env$"
```

That should print nothing; `.gitignore` already excludes it. Then push as usual.

## 5. Create the service

1. Sign up at https://render.com with **Sign up with GitHub**. No card needed.
2. Let Render see your repositories.
3. Click **New +** → **Web Service**, find `prism-data-agent` and click **Connect**.
4. Fill in the form:

| Field | Value |
| --- | --- |
| Name | `prism` |
| Language | **Docker** |
| Branch | `main` |
| Region | whichever is closest to you |
| Dockerfile Path | `./Dockerfile` |
| Instance Type | **Free** |

Leave Root Directory and Docker Build Context Directory blank; the Dockerfile is at the repo root, which is the default.

Don't click **Create** yet. Add the environment variables first, or the first build starts without a key.

## 6. Environment variables

Under **Environment Variables**, add each of these:

| Key | Value |
| --- | --- |
| `APP_USERNAME` | your choice |
| `APP_PASSWORD` | something long you don't use anywhere else |
| `OPENAI_API_KEY` | your DeepSeek key |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_PROVIDER` | `openai` |
| `LLM_MODEL` | `deepseek-v4-flash` |
| `LLM_EXTRA_BODY` | `{"thinking": {"type": "disabled"}}` |
| `MAX_UPLOAD_MB` | `5` |
| `MAX_SESSIONS` | `3` |
| `MAX_PARALLEL_BRANCHES` | `2` |

Render doesn't read your `backend/.env`, so `LLM_EXTRA_BODY` has to be set here too, even though it already works locally.

The last three keep the app inside the free instance's 512 MB of RAM. pandas, numpy, matplotlib, LangChain and SQLAlchemy take roughly 300 MB before any data is loaded, and a 25 MB CSV becomes a much bigger DataFrame in memory.

You don't need to set `PORT` (Render does) or `ENABLE_DB_CONNECT` (the image already sets it to `false`).

## 7. Deploy

Click **Create Web Service**. The first build takes 5 to 10 minutes: npm packages, the React build, then the Python dependencies. Watch the **Logs** tab for:

```
INFO:     Uvicorn running on http://0.0.0.0:10000
==> Your service is live
```

Your URL will look like `https://prism.onrender.com`. Open it, log in, and you're in.

## 8. On your phone

Open the URL in your phone's browser and log in; the browser remembers the credentials.

- **Android / Chrome:** menu → **Install app**
- **iPhone / Safari:** Share → **Add to Home Screen**

## What to expect

- **The first visit after a while is slow.** Free services sleep after 15 minutes without traffic and take about 50 seconds to wake. If you're showing it to someone, open it yourself a minute beforehand.
- **"Database connections are disabled."** That's intended. The image turns off `/api/connect`; the sample and CSV upload both work.
- **Every push to `main` redeploys.** Turn that off under Settings → Build & Deploy if you'd rather deploy by hand.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "No open ports detected" | The Dockerfile's `CMD` must use `${PORT:-7860}`. |
| Build fails at `npm ci` | `package-lock.json` is out of sync. Run `npm install` locally, commit the lockfile, push. |
| Deploy succeeds but the page is blank | The frontend build wasn't copied. Check the `COPY --from=frontend` line in the Dockerfile. |
| No login prompt | `APP_USERNAME` or `APP_PASSWORD` is blank. Both are required. |
| Login keeps failing | A trailing space got pasted into the password in Render. Retype it. |
| Questions fail with 401 | Wrong `OPENAI_API_KEY`, or an `nvapi-` key instead of an `sk-` one. |
| "Thinking mode does not support this tool_choice" | `LLM_EXTRA_BODY` is missing in Render. Set it and redeploy. |
| "Model not found" | `LLM_MODEL` must be `deepseek-v4-flash`, not the NVIDIA long form. |
| The service restarts mid-question | Out of memory. Lower `MAX_UPLOAD_MB` to 2 and `MAX_SESSIONS` to 2. |
| Everything times out | The DeepSeek balance is empty. |

## Cost

Render's free tier costs nothing. DeepSeek works out to roughly half a cent per question, and since it's prepaid, whatever you top up is the ceiling.
