import { useEffect, useRef, useState } from "react";
import AgentThinking from "./AgentThinking.jsx";
import ResultView from "./ResultView.jsx";

const SUGGESTIONS = [
  "What is total revenue by region?",
  "Show the monthly revenue trend as a chart",
  "Which product has the highest average discount?",
  "Revenue by region as a chart and revenue by category",
];

// source looks like "csv:sales.csv" or "db:postgresql". The filename is what
// people recognise; the table behind a CSV upload is always just "data".
function datasetName(dataset) {
  const source = dataset.source || "";
  if (source.startsWith("csv:")) return source.slice(4);
  return dataset.table_name;
}

export default function ChatPanel({
  dataset,
  messages,
  running,
  liveSteps,
  liveElapsed,
  onAsk,
}) {
  const [draft, setDraft] = useState("");
  const feedRef = useRef(null);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, liveSteps, running]);

  const submit = () => {
    const question = draft.trim();
    if (!question || running) return;
    setDraft("");
    onAsk(question);
  };

  const onKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <section className="chat" aria-label="Conversation">
      <div className="chat-feed" ref={feedRef}>
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>
              <strong>{datasetName(dataset)}</strong> is loaded ·{" "}
              {dataset.row_count.toLocaleString()} rows · {dataset.columns.length} columns
            </h2>
            <p>Try one of these to see the agent plan, query and chart:</p>
            <div className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  className="chip"
                  onClick={() => onAsk(suggestion)}
                  disabled={running}
                >
                  {suggestion}
                </button>
              ))}
            </div>
            <details className="schema-peek">
              <summary>Peek at the columns</summary>
              <ul>
                {dataset.columns.map((column) => (
                  <li key={column.name}>
                    <code>{column.name}</code> <span className="dtype">{column.dtype}</span>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="user-message">
              {message.text}
            </div>
          ) : (
            <div key={message.id} className="agent-turn">
              <AgentThinking
                steps={message.result.trace ?? []}
                running={false}
                elapsedMs={message.elapsedMs}
              />
              <ResultView result={message.result} />
            </div>
          )
        )}

        {running && (
          <div className="agent-turn">
            <AgentThinking steps={liveSteps} running elapsedMs={liveElapsed} />
          </div>
        )}
      </div>

      <div className="composer">
        <div className="composer-inner">
        <textarea
          rows={1}
          placeholder="Ask about your data, e.g. “average order value by segment”"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={running}
          aria-label="Your question"
        />
        <button className="primary-button" onClick={submit} disabled={running || !draft.trim()}>
          {running ? "Working…" : "Ask"}
        </button>
        </div>
      </div>
    </section>
  );
}