import { useEffect, useRef, useState } from "react";

// The reasoning used to live in a fixed panel on the right, which had a flaw:
// it only ever showed the most recent run. Scroll back to an older answer and
// the panel beside it described something else entirely. Now each answer keeps
// its own reasoning underneath it, open while it works and folded away after.

// Node names are internal. Nobody outside this codebase should have to know
// what "interpret" means.
const STEP_LABELS = {
  decompose: "Planning the approach",
  plan: "Deciding what to do next",
  sql: "Querying the data",
  python: "Running the numbers",
  chart: "Drawing the chart",
  merge: "Bringing the results together",
  verify: "Checking the answer holds up",
  interpret: "Writing the answer",
  retry: "First attempt rejected, trying again",
  error: "Ran into a problem",
};

const LANE_STAGES = [
  { key: "sql", label: "query" },
  { key: "python", label: "analyse" },
  { key: "chart", label: "chart" },
];

function describe(step) {
  return STEP_LABELS[step.node] ?? step.title;
}

export default function AgentThinking({ steps, running, elapsedMs }) {
  const [open, setOpen] = useState(running);
  const wasRunning = useRef(running);
  const bodyRef = useRef(null);

  // Open it when a run starts, fold it away when that run finishes -- but
  // never fight the user if they've opened it themselves.
  useEffect(() => {
    if (running && !wasRunning.current) setOpen(true);
    if (!running && wasRunning.current) setOpen(false);
    wasRunning.current = running;
  }, [running]);

  useEffect(() => {
    if (open && running && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [steps, open, running]);

  if (!steps?.length && !running) return null;

  // group the per-task work so parallel runs are legible
  const tasks = new Map();
  for (const step of steps) {
    if (step.branch === undefined || step.branch === null) continue;
    if (!tasks.has(step.branch)) tasks.set(step.branch, { stages: new Set(), failed: false });
    const task = tasks.get(step.branch);
    if (step.node === "error") task.failed = true;
    else task.stages.add(step.node);
  }
  const taskList = [...tasks.entries()].sort((a, b) => a[0] - b[0]);

  const last = steps.length ? steps[steps.length - 1] : null;
  const seconds = elapsedMs ? (elapsedMs / 1000).toFixed(1) : null;

  const summary = running
    ? last
      ? describe(last)
      : "Getting started"
    : `Thought for ${steps.length} step${steps.length === 1 ? "" : "s"}` +
      (seconds ? ` · ${seconds}s` : "");

  return (
    <section className={`thinking${running ? " thinking-live" : ""}`}>
      <button
        type="button"
        className="thinking-header"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {running ? (
          <span className="thinking-spinner" aria-hidden="true" />
        ) : (
          <span className="thinking-tick" aria-hidden="true">
            ✓
          </span>
        )}
        <span className="thinking-summary">{summary}</span>
        {taskList.length > 1 && (
          <span className="thinking-tasks-badge">{taskList.length} tasks in parallel</span>
        )}
        <span className={`thinking-chevron${open ? " thinking-chevron-open" : ""}`} aria-hidden="true">
          ›
        </span>
      </button>

      {open && (
        <div className="thinking-body" ref={bodyRef}>
          {taskList.length > 1 && (
            <div className="lane-strip">
              {taskList.map(([id, task]) => (
                <div key={id} className={`lane-pill${task.failed ? " lane-pill-failed" : ""}`}>
                  <span className="lane-pill-name">Task {id + 1}</span>
                  <span className="lane-pill-stages">
                    {LANE_STAGES.filter((stage) => task.stages.has(stage.key))
                      .map((stage) => stage.label)
                      .join(" · ") || "starting"}
                  </span>
                </div>
              ))}
            </div>
          )}

          <ol className="thinking-steps">
            {steps.map((step, index) => (
              <li key={index} className={`thinking-step thinking-step-${step.status}`}>
                <span className="thinking-step-dot" aria-hidden="true" />
                <div className="thinking-step-text">
                  <p className="thinking-step-title">
                    {describe(step)}
                    {step.branch !== undefined && step.branch !== null && taskList.length > 1 && (
                      <span className="thinking-step-task">Task {step.branch + 1}</span>
                    )}
                  </p>
                  {step.detail && <p className="thinking-step-detail">{step.detail}</p>}
                </div>
              </li>
            ))}
            {running && (
              <li className="thinking-step thinking-step-pending">
                <span className="thinking-step-dot thinking-step-dot-live" aria-hidden="true" />
                <div className="thinking-step-text">
                  <p className="thinking-step-title thinking-step-working">Working…</p>
                </div>
              </li>
            )}
          </ol>
        </div>
      )}
    </section>
  );
}
