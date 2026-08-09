# Frontend

React + Vite console for Prism. See the root [README](../README.md) for setup
and [`docs/architecture.md`](../docs/architecture.md) for the internals.

```bash
npm install
npm run dev        # dev server on http://localhost:5173
npm run build      # production build into dist/
npm run preview    # serve the production build locally
```

The dev server proxies `/api` to the backend on port 8000 (see
`vite.config.js`), so no CORS configuration is needed while developing. In the
Docker image, nginx proxies the same path.

Set `VITE_API_BASE` only for a split deployment where the backend lives on a
different host. Copy `.env.example` to `.env` if you need it.

## Components

| File | What it does |
| --- | --- |
| `App.jsx` | Top-level state: dataset, message feed, live run |
| `api.js` | Fetch wrappers plus the SSE stream reader |
| `components/AgentThinking.jsx` | Collapsible live reasoning panel |
| `components/ChatPanel.jsx` | Feed, suggestions, composer |
| `components/DataChart.jsx` | Interactive SVG charts with hover values |
| `components/DataUpload.jsx` | Sample, CSV upload, database connect |
| `components/Markdown.jsx` | Renders the model's markdown answers |
| `components/ResultView.jsx` | Answer, charts, tables, generated code |

No runtime dependencies beyond React. Markdown rendering and charting are both
hand-rolled to keep the bundle small and avoid injecting model text as HTML.