import { describe, expect, test } from 'vitest';
import { brokenStreamOf, collect, sseText, streamOf } from '../test/streams';
import { parseBlock, readEvents } from './sse';
import type { TurnEvent } from './types';

const reply: TurnEvent = {
  kind: 'reply',
  speaker: 'Mr Grey',
  text: 'I was in the library. Ask anyone: 10:30, sharp.',
  source: 'draft',
  degraded: false,
  violations: [],
  model: 'ministral-3:14b',
  drafts: 1,
  latency_ms: 812.5,
};
const done: TurnEvent = { kind: 'done', turn_ms: 1200 };

describe('readEvents', () => {
  test('reads whole blocks', async () => {
    const events = await collect(readEvents(streamOf([sseText([reply, done])])));
    expect(events).toEqual([reply, done]);
  });

  test('tolerates a chunk boundary at every position', async () => {
    const text = sseText([reply, done]);
    for (let cut = 1; cut < text.length; cut += 1) {
      const events = await collect(readEvents(streamOf([text.slice(0, cut), text.slice(cut)])));
      expect(events, `cut at ${cut}`).toEqual([reply, done]);
    }
  });

  test('tolerates one byte per chunk, including multi-byte characters', async () => {
    const accented: TurnEvent = { ...reply, text: 'Café — déjà vu' };
    const bytes = new TextEncoder().encode(sseText([accented]));
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const b of bytes) controller.enqueue(new Uint8Array([b]));
        controller.close();
      },
    });
    expect(await collect(readEvents(stream))).toEqual([accented]);
  });

  test('ignores ping comments', async () => {
    const text = `: ping\n\n${sseText([reply])}: ping\n\n${sseText([done])}`;
    expect(await collect(readEvents(streamOf([text])))).toEqual([reply, done]);
  });

  test('skips a malformed block and keeps reading', async () => {
    const text = `event: reply\ndata: {not json\n\n${sseText([done])}`;
    expect(await collect(readEvents(streamOf([text])))).toEqual([done]);
  });

  test('skips an unknown kind and an event name that does not match its kind', async () => {
    const text =
      'event: novel\ndata: {"kind":"novel"}\n\n' +
      'event: reply\ndata: {"kind":"done","turn_ms":1}\n\n' +
      sseText([done]);
    expect(await collect(readEvents(streamOf([text])))).toEqual([done]);
  });

  test('accepts CRLF line endings', async () => {
    const text = sseText([reply, done]).replace(/\n/g, '\r\n');
    expect(await collect(readEvents(streamOf([text])))).toEqual([reply, done]);
  });

  test('an empty stream yields nothing', async () => {
    expect(await collect(readEvents(streamOf([])))).toEqual([]);
  });

  test('a dropped connection rejects after the events already read', async () => {
    const seen: TurnEvent[] = [];
    const reading = (async () => {
      for await (const e of readEvents(brokenStreamOf([sseText([reply])]))) seen.push(e);
    })();
    await expect(reading).rejects.toThrow('network error');
    expect(seen).toEqual([reply]);
  });
});

describe('parseBlock', () => {
  test('a comment-only block is skipped', () => {
    expect(parseBlock(': ping')).toBeNull();
  });
});
