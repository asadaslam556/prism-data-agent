import { useMemo, useState } from "react";

// The agent draws with matplotlib and sends back a PNG. A PNG is dead on the
// page, so where we can we redraw the same numbers as SVG and get hover values.
//
// Three things this has to get right, all learned from getting them wrong:
//
// 1. Long category names. Rotated labels under a vertical bar chart run off the
//    bottom of the viewBox and get sliced in half. Anything with long or
//    numerous labels becomes a horizontal bar chart instead, where the names sit
//    on their own line and simply fit.
// 2. Categories are not a time series. Fifteen countries were drawn as a line
//    chart purely because there were more than fourteen of them, which implies a
//    continuity that isn't there. Only genuinely date-like labels get a line.
// 3. What the model actually drew. If it wrote a bubble or pie chart, redrawing
//    it as bars contradicts the answer text sitting right above it. We read the
//    generated code, and anything we can't reproduce faithfully falls back to
//    the model's own image.

const WIDTH = 720;
const VERTICAL_PLOT = 300;
const ROW_HEIGHT = 30;

function isNumeric(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function looksLikeTime(values) {
  const timeish = /^\d{4}([-/]\d{1,2}){0,2}$/;
  const hits = values.filter((v) => typeof v === "string" && timeish.test(v.trim()));
  return hits.length >= values.length * 0.8;
}

function formatValue(value) {
  if (!isNumeric(value)) return String(value ?? "—");
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(Number(value.toFixed(4)));
}

function shortAxisLabel(value) {
  const abs = Math.abs(value);
  if (abs >= 1000000) return `${(value / 1000000).toFixed(abs >= 10000000 ? 0 : 1)}M`;
  if (abs >= 1000) return `${(value / 1000).toFixed(abs >= 10000 ? 0 : 1)}k`;
  return String(Number(value.toFixed(2)));
}

function niceTicks(min, max, count = 4) {
  if (min === max) return [min];
  const step = (max - min) / count;
  return Array.from({ length: count + 1 }, (_, i) => min + step * i);
}

/** What did the model actually draw? */
function readChartCode(code) {
  const text = (code || "").toLowerCase();
  if (!text) return null;
  // shapes we can't reproduce honestly -- show the model's own picture instead
  if (/scatter|bubble|\.pie\(|kind=['"]pie|hist\(|kind=['"]hist|boxplot|kind=['"]box|imshow|heatmap|stackplot|pcolor/.test(text)) {
    return "asdrawn";
  }
  if (/barh|kind=['"]barh/.test(text)) return "hbar";
  if (/\.bar\(|kind=['"]bar/.test(text)) return "bar";
  if (/\.plot\(|kind=['"]line/.test(text)) return "line";
  return null;
}

function analyse(sql, chartCode) {
  if (!sql || !sql.rows || !sql.rows.length || !sql.columns || !sql.columns.length) return null;
  const rows = sql.rows;

  const numericColumns = sql.columns.filter(
    (column) =>
      rows.some((row) => isNumeric(row[column])) &&
      rows.every((row) => row[column] === null || isNumeric(row[column]))
  );
  if (!numericColumns.length) return null;

  const valueColumn = numericColumns[0];
  const labelColumn =
    sql.columns.find((column) => column !== valueColumn && !numericColumns.includes(column)) || null;

  const points = rows
    .map((row, index) => ({
      label: labelColumn ? String(row[labelColumn] === null ? "—" : row[labelColumn]) : `#${index + 1}`,
      value: isNumeric(row[valueColumn]) ? row[valueColumn] : 0,
    }))
    .slice(0, 40);

  if (points.length < 2) return null;

  if (readChartCode(chartCode) === "asdrawn") return { asDrawn: true };
  const declared = readChartCode(chartCode);

  const longestLabel = Math.max(...points.map((p) => p.label.length));
  const timeLike = looksLikeTime(points.map((p) => p.label));
  const crowded = longestLabel > 12 || points.length > 8;

  let kind;
  if (declared === "bar") {
    // The model was told to draw bars, either because the user asked for
    // them outright or because it judged bars right for the data. Honour
    // that: an earlier version forced every time series to a line and
    // silently contradicted answers that said "a bar chart has been
    // created". Vertical while the labels still fit, horizontal after that.
    kind = crowded && !timeLike ? "hbar" : "bar";
  } else if (declared === "hbar") {
    kind = "hbar";
  } else if (declared === "line") {
    kind = "line";
  } else if (timeLike) {
    // Nothing declared: dates read left to right, so a line by default.
    kind = "line";
  } else {
    kind = crowded ? "hbar" : "bar";
  }

  return {
    points,
    valueColumn,
    labelColumn,
    kind,
    longestLabel,
    extraSeries: numericColumns.length - 1,
    truncated: rows.length > points.length,
  };
}

export function looksLikeKpis(sql) {
  if (!sql || !sql.rows || sql.rows.length !== 1) return false;
  const columns = sql.columns || [];
  if (columns.length < 2 || columns.length > 8) return false;
  // a row of pure text is a record, not a dashboard
  return columns.some((column) => isNumeric(sql.rows[0][column]));
}

function prettyLabel(name) {
  const spaced = String(name).replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function KpiCards({ sql }) {
  const row = sql.rows[0];
  return (
    <div className="kpi-grid">
      {sql.columns.map((column) => (
        <div className="kpi-card" key={column}>
          <span className="kpi-value">{formatValue(row[column])}</span>
          <span className="kpi-label">{prettyLabel(column)}</span>
        </div>
      ))}
    </div>
  );
}

export default function DataChart({ sql, fallbackPng, chartCode }) {
  const [hovered, setHovered] = useState(null);
  const chart = useMemo(() => analyse(sql, chartCode), [sql, chartCode]);

  const png = fallbackPng ? (
    <figure className="chart-figure">
      <img src={`data:image/png;base64,${fallbackPng}`} alt="Chart produced by the agent" />
    </figure>
  ) : null;

  // cards instead of whatever the model drew for this shape
  if (looksLikeKpis(sql)) return <KpiCards sql={sql} />;

  if (!chart || chart.asDrawn) return png;

  const { points, valueColumn, labelColumn, kind, longestLabel, extraSeries, truncated } = chart;

  const values = points.map((p) => p.value);
  const rawMax = Math.max(...values);
  const rawMin = Math.min(...values, 0);
  const max = rawMax === rawMin ? rawMax + 1 : rawMax;
  const min = rawMin;
  const ticks = niceTicks(min, max);

  const readout =
    hovered !== null ? (
      <span className="chart-readout">
        <strong>{points[hovered].label}</strong>
        <span className="chart-readout-value">{formatValue(points[hovered].value)}</span>
        <span className="chart-readout-key">{valueColumn}</span>
      </span>
    ) : (
      <span className="chart-hint">
        Hover to read exact values
        {extraSeries > 0 && ` · ${extraSeries} more numeric column${extraSeries > 1 ? "s" : ""} below`}
        {truncated && ` · first ${points.length} rows`}
      </span>
    );

  // ------------------------------------------------------------- horizontal
  if (kind === "hbar") {
    const left = Math.min(230, Math.max(90, longestLabel * 7.2 + 14));
    const pad = { top: 14, right: 24, bottom: 34, left };
    const plotHeight = points.length * ROW_HEIGHT;
    const height = pad.top + plotHeight + pad.bottom;
    const plotWidth = WIDTH - pad.left - pad.right;
    const xFor = (value) => pad.left + ((value - min) / (max - min)) * plotWidth;

    return (
      <figure className="chart-figure chart-interactive">
        <svg
          viewBox={`0 0 ${WIDTH} ${height}`}
          role="img"
          aria-label={`${valueColumn} by ${labelColumn || "row"}`}
          onMouseLeave={() => setHovered(null)}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                className="chart-grid"
                x1={xFor(tick)}
                x2={xFor(tick)}
                y1={pad.top}
                y2={pad.top + plotHeight}
              />
              <text
                className="chart-axis-label"
                x={xFor(tick)}
                y={pad.top + plotHeight + 18}
                textAnchor="middle"
              >
                {shortAxisLabel(tick)}
              </text>
            </g>
          ))}

          {points.map((point, index) => {
            const y = pad.top + index * ROW_HEIGHT;
            const barHeight = ROW_HEIGHT * 0.62;
            return (
              <g key={index} onMouseEnter={() => setHovered(index)}>
                <rect className="chart-hit" x={0} y={y} width={WIDTH} height={ROW_HEIGHT} />
                <text
                  className="chart-axis-label"
                  x={pad.left - 10}
                  y={y + ROW_HEIGHT / 2 + 4}
                  textAnchor="end"
                >
                  {point.label.length > 30 ? `${point.label.slice(0, 29)}…` : point.label}
                </text>
                <rect
                  className={`chart-bar${hovered === index ? " chart-bar-hot" : ""}`}
                  x={Math.min(xFor(0), xFor(point.value))}
                  y={y + (ROW_HEIGHT - barHeight) / 2}
                  width={Math.max(1, Math.abs(xFor(point.value) - xFor(0)))}
                  height={barHeight}
                  rx="2"
                />
              </g>
            );
          })}
        </svg>
        <figcaption className="chart-caption">{readout}</figcaption>
      </figure>
    );
  }

  // --------------------------------------------------------------- vertical
  // Bottom padding scales with the longest label so rotated text never runs off
  // the canvas -- that clipping was the original bug here.
  const bottom = Math.min(120, Math.max(46, longestLabel * 5.4 + 26));
  const pad = { top: 16, right: 18, bottom, left: 68 };
  const height = pad.top + VERTICAL_PLOT + bottom;
  const plotWidth = WIDTH - pad.left - pad.right;
  const plotHeight = VERTICAL_PLOT;
  const yFor = (value) => pad.top + plotHeight - ((value - min) / (max - min)) * plotHeight;
  const band = plotWidth / points.length;
  const xCentre = (index) => pad.left + band * index + band / 2;
  const labelEvery = Math.ceil(points.length / 12);

  return (
    <figure className="chart-figure chart-interactive">
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        role="img"
        aria-label={`${valueColumn} by ${labelColumn || "row"}`}
        onMouseLeave={() => setHovered(null)}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              className="chart-grid"
              x1={pad.left}
              x2={WIDTH - pad.right}
              y1={yFor(tick)}
              y2={yFor(tick)}
            />
            <text className="chart-axis-label" x={pad.left - 10} y={yFor(tick) + 4} textAnchor="end">
              {shortAxisLabel(tick)}
            </text>
          </g>
        ))}

        {kind === "bar" &&
          points.map((point, index) => {
            const barWidth = Math.max(4, band * 0.62);
            const y = yFor(Math.max(point.value, 0));
            const zeroY = yFor(0);
            return (
              <rect
                key={index}
                className={`chart-bar${hovered === index ? " chart-bar-hot" : ""}`}
                x={xCentre(index) - barWidth / 2}
                y={Math.min(y, zeroY)}
                width={barWidth}
                height={Math.max(1, Math.abs(zeroY - y))}
                rx="2"
                onMouseEnter={() => setHovered(index)}
              />
            );
          })}

        {kind === "line" && (
          <>
            <polyline
              className="chart-line"
              points={points.map((p, i) => `${xCentre(i)},${yFor(p.value)}`).join(" ")}
            />
            {points.map((point, index) => (
              <circle
                key={index}
                className={`chart-dot${hovered === index ? " chart-dot-hot" : ""}`}
                cx={xCentre(index)}
                cy={yFor(point.value)}
                r={hovered === index ? 5 : 3}
              />
            ))}
          </>
        )}

        {points.map((point, index) => (
          <rect
            key={`hit-${index}`}
            className="chart-hit"
            x={pad.left + band * index}
            y={pad.top}
            width={band}
            height={plotHeight}
            onMouseEnter={() => setHovered(index)}
          />
        ))}

        {points.map((point, index) =>
          index % labelEvery === 0 ? (
            <text
              key={`x-${index}`}
              className="chart-axis-label"
              x={xCentre(index)}
              y={pad.top + plotHeight + 16}
              textAnchor="end"
              transform={`rotate(-38 ${xCentre(index)} ${pad.top + plotHeight + 16})`}
            >
              {point.label.length > 18 ? `${point.label.slice(0, 17)}…` : point.label}
            </text>
          ) : null
        )}

        {hovered !== null && (
          <line
            className="chart-crosshair"
            x1={xCentre(hovered)}
            x2={xCentre(hovered)}
            y1={pad.top}
            y2={pad.top + plotHeight}
          />
        )}
      </svg>
      <figcaption className="chart-caption">{readout}</figcaption>
    </figure>
  );
}