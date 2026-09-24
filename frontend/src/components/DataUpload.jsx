import { useRef, useState } from "react";
import { connectDatabase, getSample, uploadFile } from "../api.js";

// "Failed to fetch" means the browser never reached the API. Every other error
// is a real answer from the server and already explains itself.
function looksOffline(message) {
  return /failed to fetch|networkerror|load failed/i.test(message || "");
}

export default function DataUpload({ onReady, canConnect = true }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [dbUrl, setDbUrl] = useState("");
  const [dbTable, setDbTable] = useState("");
  const fileInput = useRef(null);

  const run = async (label, action) => {
    setBusy(label);
    setError("");
    try {
      onReady(await action());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };

  const onFileChosen = (event) => {
    const file = event.target.files?.[0];
    if (file) run("upload", () => uploadFile(file));
    event.target.value = "";
  };

  return (
    <section className="onboarding">
      <p className="eyebrow">AI data analyst agent</p>
      <h1>
        Ask your data a question.
        <br />
        Watch the agent work.
      </h1>
      <p className="lede">
        Bring a dataset, ask in plain English, and an agent plans its own steps: it writes
        SQL, runs pandas, draws charts, and explains the result, showing every move live.
      </p>

      {error && (
        <p className="form-error" role="alert">
          {error}
          {looksOffline(error) && " Is the backend running on port 8000?"}
        </p>
      )}

      <div className="onboarding-grid">
        <article className="option-card">
          <h2>Try the sample</h2>
          <p>
            1,400 sales orders across regions, products and segments. The fastest way to
            see the agent think.
          </p>
          <button
            className="primary-button"
            onClick={() => run("sample", getSample)}
            disabled={!!busy}
          >
            {busy === "sample" ? "Loading…" : "Load sample dataset"}
          </button>
        </article>

        <article className="option-card">
          <h2>Upload a CSV</h2>
          <p>Your file is loaded into an in-memory database for this session only.</p>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.tsv"
            onChange={onFileChosen}
            hidden
          />
          <button
            className="secondary-button"
            onClick={() => fileInput.current?.click()}
            disabled={!!busy}
          >
            {busy === "upload" ? "Uploading…" : "Choose a .csv file"}
          </button>
        </article>

        {canConnect && (
          <article className="option-card">
            <h2>Connect a database</h2>
            <p>Any SQLAlchemy URL: Postgres, MySQL, SQLite. Read-only queries only.</p>
            <input
              className="text-input"
              placeholder="postgresql+psycopg2://user:pass@host/db"
              value={dbUrl}
              onChange={(e) => setDbUrl(e.target.value)}
              aria-label="Database URL"
            />
            <input
              className="text-input"
              placeholder="Table (optional, defaults to the first one)"
              value={dbTable}
              onChange={(e) => setDbTable(e.target.value)}
              aria-label="Table name"
            />
            <button
              className="secondary-button"
              onClick={() => run("connect", () => connectDatabase(dbUrl, dbTable))}
              disabled={!!busy || !dbUrl.trim()}
            >
              {busy === "connect" ? "Connecting…" : "Connect"}
            </button>
          </article>
        )}
      </div>
    </section>
  );
}