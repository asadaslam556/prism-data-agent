import DataChart, { looksLikeKpis } from "./DataChart.jsx";
import Markdown from "./Markdown.jsx";

const PREVIEW_ROWS = 10;

function formatCell(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function ResultTable({ sql }) {
  if (!sql || !sql.rows?.length) return null;
  const rows = sql.rows.slice(0, PREVIEW_ROWS);
  return (
    <div className="result-table-wrap">
      <table className="result-table">
        <thead>
          <tr>
            {sql.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {sql.columns.map((column) => (
                <td key={column}>{formatCell(row[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {sql.row_count > PREVIEW_ROWS && (
        <p className="table-note">
          Showing {PREVIEW_ROWS} of {sql.row_count.toLocaleString()} rows
          {sql.truncated ? " (query capped by the row limit)" : ""}.
        </p>
      )}
    </div>
  );
}

// One task's findings. Only labelled when there's more than one, so a normal
// question reads as a plain answer rather than a report with sections.
function TaskBlock({ branch, index, showHeading }) {
  return (
    <section className="task-block">
      {showHeading && (
        <h4 className="task-heading">
          <span className="task-tag">Task {index + 1}</span>
          <span className="task-question">{branch.task}</span>
        </h4>
      )}
      {branch.error && <p className="agent-error-detail">{branch.error}</p>}
      {(branch.chart_png_base64 || looksLikeKpis(branch.sql)) && (
        <DataChart
          sql={branch.sql}
          fallbackPng={branch.chart_png_base64}
          chartCode={branch.chart_code}
        />
      )}
      {!looksLikeKpis(branch.sql) && <ResultTable sql={branch.sql} />}
      {branch.sql?.sql && (
        <details className="code-details">
          <summary>SQL the agent wrote</summary>
          <pre>
            <code>{branch.sql.sql}</code>
          </pre>
        </details>
      )}
      {branch.python_code && (
        <details className="code-details">
          <summary>Python analysis</summary>
          <pre>
            <code>{branch.python_code}</code>
          </pre>
          {branch.python_result && (
            <pre className="code-output">
              <code>{branch.python_result}</code>
            </pre>
          )}
        </details>
      )}
    </section>
  );
}

export default function ResultView({ result }) {
  const failed = !!result.error && !result.answer;
  const branches = result.branches?.length
    ? result.branches
    : // pre-branch response shape, kept working
      [
        {
          branch_id: 0,
          task: result.question,
          sql: result.sql,
          python_code: result.python_code,
          python_result: result.python_result,
          chart_png_base64: result.chart_png_base64,
          error: null,
        },
      ];
  const multi = branches.length > 1;

  return (
    <article className={`agent-message${failed ? " agent-message-error" : ""}`}>
      {failed ? (
        <>
          <p className="agent-answer">The agent could not finish this one.</p>
          <p className="agent-error-detail">{result.error}</p>
        </>
      ) : (
        <Markdown text={result.answer} className="agent-answer" />
      )}

      {!failed &&
        branches.map((branch, index) => (
          <TaskBlock
            key={branch.branch_id ?? index}
            branch={branch}
            index={index}
            showHeading={multi}
          />
        ))}
    </article>
  );
}