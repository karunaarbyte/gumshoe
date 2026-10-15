import type { TurnEvent } from '../api/types';

/** A ReadableStream that delivers exactly these chunks, in order. */
export function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

/** A stream that delivers these chunks and then fails, like a dropped connection. */
export function brokenStreamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let next = 0;
  return new ReadableStream({
    pull(controller) {
      const chunk = chunks[next];
      next += 1;
      if (chunk === undefined) controller.error(new TypeError('network error'));
      else controller.enqueue(encoder.encode(chunk));
    },
  });
}

/** Events as the server writes them: `event: <kind>\ndata: <json>\n\n`. */
export function sseText(events: TurnEvent[]): string {
  return events.map((e) => `event: ${e.kind}\ndata: ${JSON.stringify(e)}\n\n`).join('');
}

export function sseResponse(events: TurnEvent[], init?: { broken?: boolean }): Response {
  const text = sseText(events);
  const body = init?.broken === true ? brokenStreamOf([text]) : streamOf([text]);
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

export function errorResponse(status: number, code: string, message = code): Response {
  return jsonResponse({ code, message }, status);
}

export async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of items) out.push(item);
  return out;
}
