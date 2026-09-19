// Thin API client. VITE_API_BASE is empty in dev (Vite proxies /api) and in the
// Docker build (nginx proxies /api); set it only if the backend lives elsewhere.
const BASE = import.meta.env.VITE_API_BASE || "";

async function asJson(response) {
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) message = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(message);
  }
  return response.json();
}

export function getHealth() {
  return fetch(`${BASE}/api/health`).then(asJson);
}

export function getSample() {
  return fetch(`${BASE}/api/sample`).then(asJson);
}

export function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${BASE}/api/upload`, { method: "POST", body: form }).then(asJson);
}

export function connectDatabase(dbUrl, table) {
  return fetch(`${BASE}/api/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ db_url: dbUrl, table: table || null }),
  }).then(asJson);
}

/**
 * Stream a query over Server-Sent Events.
 *
 * EventSource cannot POST, so we read the response body manually and parse the
 * SSE frames ("event: ...\ndata: ...\n\n") out of the stream.
 */
export async function streamQuery({ sessionId, question, history, onStep, onFinal, onError }) {
  const response = await fetch(`${BASE}/api/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, question, history }),
  });

  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) message = body.detail;
    } catch {
      /* ignore */
    }
    onError?.(new Error(message));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let settled = false;

  const handleFrame = (frame) => {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    const payload = JSON.parse(data);
    if (event === "step") onStep?.(payload);
    else if (event === "final") {
      settled = true;
      onFinal?.(payload);
    } else if (event === "error") {
      settled = true;
      onError?.(new Error(payload.message || "Agent error"));
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.trim()) handleFrame(frame);
      }
    }
    if (buffer.trim()) handleFrame(buffer);
  } catch (error) {
    settled = true;
    onError?.(error);
  }
  // The server restarted or the connection dropped mid-run. Without this the
  // UI would sit on "Working..." forever, waiting for a final event.
  if (!settled) onError?.(new Error("The connection closed before the answer arrived."));
}
