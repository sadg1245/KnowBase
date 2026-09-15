import assert from 'node:assert/strict';
import test from 'node:test';

import { createActiveStudyController, type ActiveStudyClock } from '../src/features/activity/activeStudySession';

const fakeClock = () => {
  let now = 0;
  let nextId = 1;
  const timers = new Map<number, { callback: () => void | Promise<void>; interval: number; next: number }>();
  const clock: ActiveStudyClock = {
    now: () => now,
    setInterval: (callback, interval) => {
      const id = nextId++;
      timers.set(id, { callback, interval, next: now + interval });
      return id;
    },
    clearInterval: id => { timers.delete(id); },
  };
  return {
    clock,
    advance: async (milliseconds: number) => {
      const target = now + milliseconds;
      while (true) {
        const next = [...timers.entries()].sort((a, b) => a[1].next - b[1].next)[0];
        if (!next || next[1].next > target) break;
        now = next[1].next;
        next[1].next += next[1].interval;
        await next[1].callback();
        await Promise.resolve();
      }
      now = target;
      for (let index = 0; index < 8; index += 1) await Promise.resolve();
    },
  };
};

test('heartbeats only while visible and recently active', async () => {
  const fake = fakeClock();
  const calls: string[] = [];
  const controller = createActiveStudyController({
    clock: fake.clock, createId: () => 'session-1',
    start: async () => { calls.push('start'); },
    heartbeat: async (_id, sequence) => { calls.push(`beat:${sequence}`); },
    finish: async () => { calls.push('finish'); },
  });
  controller.contextChanged({ contextType: 'document', contextId: 'doc', workspaceId: 'ws' });
  controller.userActivity();
  await fake.advance(30_000);
  assert.deepEqual(calls, ['start', 'beat:1']);
  await fake.advance(61_000);
  assert.deepEqual(calls, ['start', 'beat:1', 'beat:2']);
  await fake.advance(30_000);
  assert.deepEqual(calls, ['start', 'beat:1', 'beat:2']);
});

test('hidden state pauses, interaction resumes, and failed beat retries its sequence', async () => {
  const fake = fakeClock();
  const sequences: number[] = [];
  let fail = true;
  const controller = createActiveStudyController({
    clock: fake.clock, createId: () => 'session-1', start: async () => undefined,
    heartbeat: async (_id, sequence) => {
      sequences.push(sequence);
      if (fail) { fail = false; throw new Error('offline'); }
    },
    finish: async () => undefined,
  });
  controller.contextChanged({ contextType: 'document', contextId: 'doc' });
  controller.userActivity();
  controller.visibilityChanged(false);
  await fake.advance(30_000);
  assert.deepEqual(sequences, []);
  controller.visibilityChanged(true);
  controller.userActivity();
  await fake.advance(60_000);
  assert.deepEqual(sequences, [1, 1]);
});

test('context switch finishes old session and dispose uses keepalive', async () => {
  const fake = fakeClock();
  const calls: string[] = [];
  let id = 0;
  const controller = createActiveStudyController({
    clock: fake.clock, createId: () => `session-${++id}`,
    start: async (_context, sessionId) => { calls.push(`start:${sessionId}`); },
    heartbeat: async () => undefined,
    finish: async (sessionId, sequence, keepalive) => { calls.push(`finish:${sessionId}:${sequence}:${keepalive}`); },
  });
  controller.contextChanged({ contextType: 'document', contextId: 'doc-1' });
  await fake.advance(0);
  controller.contextChanged({ contextType: 'document', contextId: 'doc-2' });
  await fake.advance(0);
  controller.dispose();
  await fake.advance(0);
  assert.deepEqual(calls, [
    'start:session-1', 'finish:session-1:0:false', 'start:session-2', 'finish:session-2:0:true',
  ]);
});
