import assert from 'node:assert/strict';
import test from 'node:test';

import { createTaskCompletionCoordinator } from '../src/features/practice/learningLoop';

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

test('different task completions keep independent loading and refresh every success', async () => {
  const pendingSnapshots: string[][] = [];
  const coordinator = createTaskCompletionCoordinator(ids => pendingSnapshots.push([...ids].sort()));
  const first = deferred<string>();
  const second = deferred<string>();
  const successes: string[] = [];
  const errors: string[] = [];

  const firstRun = coordinator.run('task-1', () => first.promise, value => { successes.push(value); }, error => { errors.push(String(error)); });
  const secondRun = coordinator.run('task-2', () => second.promise, value => { successes.push(value); }, error => { errors.push(String(error)); });
  assert.deepEqual(pendingSnapshots.at(-1), ['task-1', 'task-2']);

  first.resolve('task-1-refreshed');
  await firstRun;
  second.reject(new Error('task-2-failed'));
  await secondRun;
  assert.deepEqual(successes, ['task-1-refreshed']);
  assert.deepEqual(errors, ['Error: task-2-failed']);
  assert.deepEqual(pendingSnapshots.at(-1), []);
});

test('duplicate clicks for one pending task are ignored', async () => {
  const coordinator = createTaskCompletionCoordinator(() => undefined);
  const operation = deferred<void>();
  let calls = 0;
  const first = coordinator.run('task-1', () => { calls += 1; return operation.promise; }, () => undefined, () => undefined);
  const duplicate = await coordinator.run('task-1', async () => { calls += 1; }, () => undefined, () => undefined);
  assert.equal(duplicate, false);
  assert.equal(calls, 1);
  operation.resolve();
  assert.equal(await first, true);
});

test('disposed task completion coordinators ignore late page callbacks', async () => {
  const operation = deferred<void>();
  let successes = 0;
  let errors = 0;
  const coordinator = createTaskCompletionCoordinator(() => undefined);
  const completion = coordinator.run(
    'task-a',
    () => operation.promise,
    () => { successes += 1; },
    () => { errors += 1; },
  );

  coordinator.dispose();
  operation.resolve();

  assert.equal(await completion, false);
  assert.equal(successes, 0);
  assert.equal(errors, 0);
});
