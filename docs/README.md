# Prism documentation

Everything beyond the [main README](../README.md), grouped by what you're trying to do.

![Where to find what: run it, configure it, deploy it, understand it, call the API, fix a problem, change it](diagrams/docs-map.architecture.svg)

## Using Prism

| Page | Read it when |
| --- | --- |
| [Quickstart](../README.md#quickstart) | You're on macOS or Linux and want it running |
| [Running on Windows](windows.md) | You're on Windows, or something in PowerShell isn't behaving |
| [Configuration](configuration.md) | You want every setting, its default, and what it does |
| [Models](models.md) | You'd rather use OpenAI, DeepSeek or another compatible API than Ollama |
| [Deployment](deployment.md) | You want to compare running locally, with compose, or as one image |
| [Deploying to Render](deploy-render.md) | You want it on a public URL behind a login |
| [Troubleshooting](troubleshooting.md) | Something isn't working |

## How it works

| Page | What's in it |
| --- | --- |
| [Architecture](architecture.md) | Every diagram, explained, from the system overview down |
| [The agent](agent.md) | The orchestrator, the branch loop, the planner, streaming and stopping |
| [Data](data.md) | Loading datasets, sessions, where the numbers come from, the locks |
| [Guardrails](guardrails.md) | The SQL guard and the Python sandbox, layer by layer |
| [Frontend](frontend.md) | The React components and how charts are drawn |
| [API reference](api.md) | Every route, the request and response shapes, the SSE events |
| [Design notes](design-notes.md) | The bugs that shaped the design |
| [Security](../SECURITY.md) | Known gaps, and how to report a vulnerability |

## Working on it

| Page | What's in it |
| --- | --- |
| [Contributing](../CONTRIBUTING.md) | Setup, the checks CI runs, where new code goes |
| [Changelog](../CHANGELOG.md) | What changed in each version |
| [Code of Conduct](../CODE_OF_CONDUCT.md) | How we treat each other here |
| [Documentation audit](AUDIT.md) | The review this documentation was rebuilt from |

## Diagrams

Every diagram lives in [`diagrams/`](diagrams/) in four forms: the archify source (`.json`), an interactive page (`.html`), and the `.svg` and `.png` exports the docs embed. The SVGs follow your system's light or dark setting.

To explore one interactively, open its `.html` file in a browser (on GitHub, download the file first; GitHub shows HTML as source). The page lets you search, focus on a part, switch themes and step through guided views. In the code-level architecture diagrams, components link to the lines of code they stand for.

To change a diagram, edit its `.json` and re-render it with [archify](https://github.com/tt-a1i/archify):

```bash
node <archify>/bin/archify.mjs validate architecture docs/diagrams/system-overview.architecture.json --quality showcase --repo-root .
node <archify>/bin/archify.mjs deliver architecture docs/diagrams/system-overview.architecture.json docs/diagrams/system-overview.architecture.html --quality showcase --repo-root .
```

`<archify>` is wherever you cloned archify. The type (`architecture`, `workflow`, `sequence`, `dataflow`, `lifecycle`) is the middle part of each file name; `--repo-root .` is only for architecture diagrams, where it checks every source link.

Then export the `.svg` and `.png` from the page's **Export** menu.

## Images

The screenshots and the demo in [`images/`](images/) come from real runs against the bundled sample dataset.

| File | Shows |
| --- | --- |
| `demo.gif` | A full session: a simple question, a line chart, parallel tasks and KPI cards |
| `getting-started.png` | The landing screen run locally; the deployment image hides the database card |
| `kpi-cards.png` | A finished answer with KPI cards |
| `revenue-by-region.png` | A chart the agent drew |
| `logo.png` | The README logo as a rounded tile, for light mode |
| `logo-dark.png` | The same logo on a transparent background, for dark mode |
| `social-preview.png` | The 1280×640 card GitHub shows when the repository link is shared |

Superseded pages and images are kept in [`archive/`](archive/).
