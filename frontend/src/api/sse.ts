import { EVENT_KINDS, type EventKind, type TurnEvent } from './types';

const KINDS = new Set<string>(EVENT_KINDS);

/** One SSE block (the text between blank lines) as an event, or null to skip it. */
export function parseBlock(block: string): TurnEvent | null {
  let name: string | null = null;
  const data: string[] = [];
  for (const raw of block.split('\n')) {
    const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw;
    if (line === '' || line.startsWith(':')) continue; // comments: `: ping`
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') name = value;
    else if (field === 'data') data.push(value);
  }
  if (data.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data.join('\n'));
  } catch {
    return null; // malformed block: skip it, keep reading
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const kind = (parsed as { kind?: unknown }).kind;
  if (typeof kind !== 'string' || !KINDS.has(kind)) return null;
  if (name !== null && name !== kind) return null;
  return parsed as TurnEvent & { kind: EventKind };
}

/** Yields each event of a `text/event-stream` body. Chunk boundaries may fall anywhere. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<TurnEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, '\n');
      let end = buffer.indexOf('\n\n');
      while (end !== -1) {
        const event = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event !== null) yield event;
        end = buffer.indexOf('\n\n');
      }
      if (done) {
        const tail = buffer.trim() === '' ? null : parseBlock(buffer);
        if (tail !== null) yield tail;
        finished = true;
        return;
      }
    }
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
