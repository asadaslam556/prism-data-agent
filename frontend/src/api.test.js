import { afterEach, describe, expect, it, vi } from "vitest";
import { streamQuery } from "./api.js";

// A fetch that answers with the given chunks as a streamed body.
function serve(chunks, init = { status: 200 }) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, init)));
}

function run() {
  const calls = { steps: [], final: null, errors: [] };
  const done = streamQuery({
    sessionId: "abc",
    question: "q",
    history: [],
    onStep: (step) => calls.steps.push(step),
    onFinal: (final) => (calls.final = final),
    onError: (error) => calls.errors.push(error.message),
  });
  return done.then(() => calls);
}

afterEach(() => vi.unstubAllGlobals());

describe("streamQuery", () => {
  it("reads steps and the final answer, even when a frame is split across chunks", async () => {
    serve([
      'event: step\ndata: {"step": 1, "node": "dec',
      'ompose"}\n\nevent: step\ndata: {"step": 2, "node": "plan"}\n\n',
      'event: final\ndata: {"answer": "42"}\n\n',
    ]);
    const calls = await run();
    expect(calls.steps.map((s) => s.node)).toEqual(["decompose", "plan"]);
    expect(calls.final).toEqual({ answer: "42" });
    expect(calls.errors).toEqual([]);
  });

  it("reports an error event", async () => {
    serve(['event: error\ndata: {"message": "Internal error"}\n\n']);
    const calls = await run();
    expect(calls.errors).toEqual(["Internal error"]);
  });

  it("reports a connection that closes before the answer", async () => {
    serve(['event: step\ndata: {"step": 1}\n\n']);
    const calls = await run();
    expect(calls.errors).toEqual(["The connection closed before the answer arrived."]);
  });

  it("uses the server's detail on a failed request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "Unknown session. Upload a dataset first." }, { status: 404 }))
    );
    const calls = await run();
    expect(calls.errors).toEqual(["Unknown session. Upload a dataset first."]);
  });
});
