# Frontend

A React 19 + Vite 8 console with no runtime dependencies beyond React. Code: `frontend/src`.

[![Frontend components](diagrams/frontend.architecture.svg)](diagrams/frontend.architecture.html)

## Components

| File | Does |
| --- | --- |
| `App.jsx` | Owns the state: the loaded dataset, the message feed, the live run and the model pill. Shows the landing screen until a dataset is loaded, then the chat |
| `api.js` | The only file that calls the backend. `fetch` wrappers for health and the load routes, plus `streamQuery`, which reads Server-Sent Events from a `fetch` body |
| `components/DataUpload.jsx` | The landing screen: load the sample, upload a CSV or TSV, or connect a database |
| `components/ChatPanel.jsx` | The message feed, suggested questions and the input box |
| `components/AgentThinking.jsx` | The reasoning panel: open with a running timer while the agent works, folded to "Thought for N steps" afterwards |
| `components/ResultView.jsx` | The answer, then each task's chart, result table, generated SQL and Python. Tasks get a heading only when there's more than one |
| `components/DataChart.jsx` | Redraws charts as SVG, or shows KPI cards |
| `components/Markdown.jsx` | Renders the answer's markdown |

## Talking to the backend

`EventSource` can't send a POST body, so `streamQuery` reads the response stream itself and splits it into `event:` / `data:` frames. A `step` frame adds a line to the reasoning panel, `final` replaces it with the answer, and `error` shows a message. If the connection closes before a `final` or `error` arrives, it reports "The connection closed before the answer arrived" instead of waiting forever.

Each question carries the last three question-and-answer pairs as `history`, so follow-ups like "now by month" have context.

In development, Vite proxies `/api` to `http://localhost:8000`. In the compose stack nginx does the same, and in the single image FastAPI serves the app itself. `VITE_API_BASE` is only needed when the backend lives on another host.

## The database card

On load, `App.jsx` calls `/api/health`. When it reports `db_connect: false` (the deployment image), the "Connect a database" card is hidden instead of failing with a 403. Until the health check answers, the card shows, as it did before this check existed.

## Charts

When the agent drew a chart, or the result is a single row, `ResultView` renders `DataChart`:

- **A single row with 2 to 8 columns, at least one numeric:** KPI cards.
- **A bar or line chart:** redrawn as SVG from the result rows, with hover values. The chart type follows the model's code; long labels switch bars to horizontal, and dates read as a line when nothing was declared. Up to 40 points are drawn.
- **Anything else** (scatter, pie, histogram, box plot, heatmap): the model's own PNG, shown as drawn.

The result table shows the first 10 rows and says when the query hit the row cap.

## Markdown

`Markdown.jsx` renders the subset the model uses: headings up to `####`, bold, italic, inline code, and bullet and numbered lists. It builds React elements rather than HTML, so nothing the model writes can inject markup.

## Running and building

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # production build into dist/
npm run preview    # serve the production build
```

Node 20.19 or newer is required (`engines` in `package.json`). There is no frontend test suite; CI checks that the production build succeeds.
