import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, streamQuery } from "./api.js";
import ChatPanel from "./components/ChatPanel.jsx";
import DataUpload from "./components/DataUpload.jsx";


// Gateways tack a version tag onto the model name, like "@default" or
// "@20251001". Fine in config, noise in the header.
function displayModel(name) {
  return String(name || "").split("@")[0];
}

let nextId = 1;

export default function App() {
  const [dataset, setDataset] = useState(null);
  const [messages, setMessages] = useState([]);
  const [running, setRunning] = useState(false);
  const [liveSteps, setLiveSteps] = useState([]);
  const [liveElapsed, setLiveElapsed] = useState(0);
  const [meta, setMeta] = useState(null); // {provider, model} from /api/health
  const historyRef = useRef([]); // [{question, answer}] sent back for follow-ups
  const startedAt = useRef(0);

  useEffect(() => {
    // best effort -- the pill just stays hidden if the backend isn't up yet
    getHealth().then(setMeta).catch(() => setMeta(null));
  }, []);

  // ticks the "thinking" timer while a question is in flight
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setLiveElapsed(Date.now() - startedAt.current), 100);
    return () => clearInterval(timer);
  }, [running]);

  const ask = useCallback(
    (question) => {
      if (!dataset || running) return;
      startedAt.current = Date.now();
      setRunning(true);
      setLiveSteps([]);
      setLiveElapsed(0);
      setMessages((prev) => [...prev, { id: nextId++, role: "user", text: question }]);

      streamQuery({
        sessionId: dataset.session_id,
        question,
        history: historyRef.current.slice(-3),
        onStep: (step) => setLiveSteps((prev) => [...prev, step]),
        onFinal: (result) => {
          const elapsedMs = Date.now() - startedAt.current;
          setMessages((prev) => [
            ...prev,
            { id: nextId++, role: "agent", result, elapsedMs },
          ]);
          if (result.answer) {
            historyRef.current = [...historyRef.current, { question, answer: result.answer }];
          }
          setRunning(false);
          setLiveSteps([]);
        },
        onError: (error) => {
          const elapsedMs = Date.now() - startedAt.current;
          setMessages((prev) => [
            ...prev,
            {
              id: nextId++,
              role: "agent",
              elapsedMs,
              result: { answer: "", error: error.message, trace: [], branches: [] },
            },
          ]);
          setRunning(false);
          setLiveSteps([]);
        },
      });
    },
    [dataset, running]
  );

  const reset = useCallback(() => {
    setDataset(null);
    setMessages([]);
    setLiveSteps([]);
    historyRef.current = [];
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="wordmark">
          <span className="wordmark-node" aria-hidden="true" />
          Prism
        </div>
        <div className="topbar-right">
          {meta && (
            <span className="model-pill" title={`${meta.provider} · ${meta.model}`}>
              {displayModel(meta.model)}
            </span>
          )}
          {dataset && (
            <>
              <span className="dataset-pill" title={dataset.source}>
                {dataset.source} · {dataset.row_count.toLocaleString()} rows
              </span>
              <button className="ghost-button" onClick={reset}>
                Change dataset
              </button>
            </>
          )}
        </div>
      </header>

      {!dataset ? (
        <main className="landing">
          <DataUpload onReady={setDataset} />
        </main>
      ) : (
        <main className="workspace">
          <ChatPanel
            dataset={dataset}
            messages={messages}
            running={running}
            liveSteps={liveSteps}
            liveElapsed={liveElapsed}
            onAsk={ask}
          />
        </main>
      )}
    </div>
  );
}
