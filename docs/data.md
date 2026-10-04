# Data

Where datasets come from, how they're kept, how the numbers in an answer are produced, and the locks that keep parallel branches honest. Code: `backend/app/data/connectors.py` and `backend/app/services/session.py`.

**On this page:** [Loading a dataset](#loading-a-dataset) · [Sessions](#sessions) · [Where the numbers come from](#where-the-numbers-come-from) · [Concurrency](#concurrency) · [The sample dataset](#the-sample-dataset)

## Loading a dataset

[![Loading a dataset](diagrams/dataset-loading.sequence.svg)](diagrams/dataset-loading.sequence.html)

| Source | Route | What happens |
| --- | --- | --- |
| Bundled sample | `GET /api/sample` | `sales.csv` is read and written into a new in-memory SQLite database |
| CSV or TSV upload | `POST /api/upload` | The same, from the uploaded file |
| Database URL | `POST /api/connect` | SQLAlchemy connects to your database; nothing is copied |

Uploads are rejected before loading when the name doesn't end in `.csv` or `.tsv` (400), when the file is over `MAX_UPLOAD_MB` (413; only one byte past the limit is read to find out), when pandas can't parse it (400), or when it has no rows (400). `/api/connect` returns 403 when `ENABLE_DB_CONNECT` is off and 400 on any connection or table error.

Every source ends up behind one SQLAlchemy engine, so the SQL skill never needs to know where the data came from. Uploads and the sample always become a table named `data`. For a database URL, the table is the one you name, or the first table found.

Loading then introspects the table: its columns and types, `COUNT(*)`, and five sample rows. That schema goes into every prompt the agent writes.

> **In-memory SQLite and threads.** The in-memory engines use SQLAlchemy's `StaticPool`: one connection shared by every thread. Without it, each FastAPI worker thread would get its own empty database and the table you just loaded would be missing.

## Sessions

[![Dataset session lifecycle](diagrams/session.lifecycle.svg)](diagrams/session.lifecycle.html)

Each loaded dataset is a `DatasetSession` in an in-memory registry, keyed by a random 12-character id that the browser sends with every question.

- **Lookups refresh it.** `get()` updates the session's last-used time and marks it most recently used.
- **Too old:** a session idle longer than `SESSION_TTL_MINUTES` (default 120) is dropped on the next lookup, or when any new dataset loads.
- **Too many:** past `MAX_SESSIONS` (default 24), the least recently used session is dropped when a new one loads.
- **Dropping** disposes of the engine straight away, so its connection pool is freed. Later requests with that id get 404, and a question already running on it ends with a readable "that dataset is no longer loaded" answer.
- **A failed load** (say, a table that doesn't exist) never creates a session; its engine is disposed and the API returns 400.

Sessions live in the process: a restart clears them all, and running several server processes would need a shared store instead.

## Where the numbers come from

[![Where the numbers come from](diagrams/data-flow.dataflow.svg)](diagrams/data-flow.dataflow.html)

1. The SQL skill runs a validated `SELECT` and gets a DataFrame of at most `MAX_SQL_ROWS` rows (default 1000). The result is marked `truncated` when it reaches the cap.
2. The pandas and chart skills work on that DataFrame. If the branch has no query result yet, they get the whole table instead.
3. The pandas result is turned into text and capped at 4000 characters; a chart becomes a base64 PNG.
4. Rows are converted with pandas' own JSON encoder, so `NaN`, numpy types and timestamps become valid JSON (`null`, plain numbers, ISO strings).
5. The final answer is written from a summary of those results.

The browser shows the rows as a table. When the agent drew a chart, bar and line charts are redrawn as interactive SVG from the rows, and other shapes (scatter, pie, histogram, heatmap) show the model's PNG. A single-row result with 2 to 8 columns, at least one of them numeric, becomes KPI cards. See [frontend.md](frontend.md#charts).

## Concurrency

[![The four locks parallel branches need](diagrams/concurrency-locks.architecture.svg)](diagrams/concurrency-locks.architecture.html)

| Lock | Where | Protects | Without it |
| --- | --- | --- | --- |
| Per-engine read lock | `connectors._read_guard` | The shared in-memory SQLite connection | Branches silently received each other's rows |
| Plot lock | `sandbox._PLOT_LOCK` | pyplot's global figure state, through PNG encoding | Two charts at once deadlocked the request |
| Budget lock | `BudgetTracker._lock` | The shared step counter | Steps went missing and the budget overran |
| Registry lock | `session._LOCK` | The session registry | Eviction could change it mid-iteration |

The read lock only applies to `StaticPool` engines. A real database gives each thread its own connection, so its queries still run concurrently. SQLite queries take milliseconds and model calls take seconds, so serialising the in-memory reads costs nothing noticeable.

## The sample dataset

`backend/data/samples/sales.csv` has 1,400 synthetic orders from January 2024 to October 2025, across 4 regions, 15 countries, 4 categories, 14 products and 3 customer segments. Twelve rows have an empty `sales_rep`, which is how the JSON-encoding bug in [design-notes.md](design-notes.md) was found.

Columns: `order_id`, `order_date`, `region`, `country`, `category`, `product`, `customer_segment`, `sales_rep`, `quantity`, `unit_price`, `discount`, `revenue`.
