# Troubleshooting

Find the symptom, then the fix. Windows-specific problems are in [windows.md](windows.md#troubleshooting), and Render-specific ones are in [deploy-render.md](deploy-render.md).

## Starting up

| Symptom | Cause and fix |
| --- | --- |
| A changed `.env` setting has no effect | Settings are read once at startup, and `--reload` only watches `.py` files. Restart the backend. |
| `/api/health` shows a different model than you set | The model comes from `LLM_MODEL`, then `OLLAMA_MODEL` or `OPENAI_MODEL`. `OPENAI_MODEL` in `backend/.env` is ignored; use `LLM_MODEL` there ([models.md](models.md#which-model-is-used)). |
| `LLM_PROVIDER=openai but no key found` | Set `OPENAI_API_KEY`. |
| Port 8000 is in use | Stop whatever holds it. Don't move the backend to another port: the frontend's dev proxy always points at 8000. |
| Port 5173 is in use | `npm run dev -- --port 5174`. |
| **Load sample dataset** says "Not Found" | Something other than Prism is answering on port 8000, such as an old server or a Docker container. Stop it and start the backend again. |
| `npm install` or `npm run dev` fails | Node is older than 20.19. Check with `node -v`. |

## Asking questions

| Symptom | Cause and fix |
| --- | --- |
| Answers fail at once with connection errors to port 11434 | Ollama isn't running. Start the app (Windows, macOS) or `ollama serve` (Linux). |
| The model isn't found | Pull it: `ollama pull qwen2.5`, or whatever `OLLAMA_MODEL` names. |
| A hosted provider says the model doesn't exist | Gateways rename models. Run `python list_models.py` from `backend/` to see the real names. |
| DeepSeek fails with `Thinking mode does not support this tool_choice` | Set `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}` ([models.md](models.md#deepseek)). |
| A provider rejects `temperature` | Set `LLM_TEMPERATURE` blank, so it isn't sent. |
| The first answer is very slow | The model loads into memory on first use. Later questions are faster. |
| Answers are wrong, or SQL keeps retrying | Small local models are weak at SQL; the retries show in the reasoning panel. Try a bigger model or a hosted provider. |
| "That dataset is no longer loaded" | It was idle longer than `SESSION_TTL_MINUTES`, or more than `MAX_SESSIONS` datasets were loaded after it. Load it again. |
| The reasoning panel says "Step budget reached" | The question needed more than `MAX_AGENT_STEPS` planner steps, so it answered with what it had. Split the question, or raise the setting. |

## Loading data

| Message | Cause and fix |
| --- | --- |
| `Please upload a .csv or .tsv file.` | Only those two types are accepted. |
| `File is too large. The limit is N MB.` | Raise `MAX_UPLOAD_MB`, or upload a smaller file. |
| `The uploaded file has no rows.` | The file has a header and nothing else. |
| `Could not parse the file: ...` | The file isn't valid CSV or TSV; the rest of the message says where. |
| `Database connections are disabled on this deployment.` | `ENABLE_DB_CONNECT` is `false`, which the deployment image sets on purpose. |
| `Could not connect: ...` | The database URL, credentials or driver. Postgres and MySQL need their driver installed. |

## Logs

Every response carries an `X-Request-ID` header, and for `/api` routes the matching server log line ends with `rid=<id>`. A 500 response includes it as `request_id`, and the stack trace is logged under that id. Set `LOG_LEVEL=DEBUG` for more detail.
