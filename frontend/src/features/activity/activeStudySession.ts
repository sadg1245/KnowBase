export type ActiveStudyContext = {
  contextType: 'document' | 'conversation';
  contextId: string;
  workspaceId?: string;
};

export interface ActiveStudyClock {
  now(): number;
  setInterval(callback: () => void | Promise<void>, milliseconds: number): number;
  clearInterval(id: number): void;
}

export type ActiveStudyDependencies = {
  clock: ActiveStudyClock;
  createId: () => string;
  start: (context: ActiveStudyContext, sessionId: string) => Promise<{ id?: string; last_sequence?: number } | unknown>;
  heartbeat: (sessionId: string, sequence: number) => Promise<unknown>;
  finish: (sessionId: string, sequence: number, keepalive: boolean) => Promise<unknown>;
};

const sameContext = (left: ActiveStudyContext | null, right: ActiveStudyContext | null) => (
  left?.contextType === right?.contextType
  && left?.contextId === right?.contextId
  && left?.workspaceId === right?.workspaceId
);

export const createActiveStudyController = (deps: ActiveStudyDependencies) => {
  let context: ActiveStudyContext | null = null;
  let sessionId: string | null = null;
  let sequence = 0;
  let visible = true;
  let disposed = false;
  let lastActivityAt = deps.clock.now();
  let heartbeatInFlight = false;
  let startedSessionId: string | null = null;
  let lifecycle = Promise.resolve();

  const startCurrent = () => {
    if (disposed || !visible || !context || sessionId) return;
    const requestedId = deps.createId();
    sessionId = requestedId;
    lifecycle = lifecycle.then(async () => {
      const result = await deps.start(context!, requestedId) as { id?: string; last_sequence?: number } | undefined;
      if (sessionId !== requestedId) return;
      const actualId = result?.id || requestedId;
      sessionId = actualId;
      startedSessionId = actualId;
      sequence = result?.last_sequence || 0;
    }).catch(() => {
      if (sessionId === requestedId) sessionId = null;
    });
  };

  const heartbeat = async () => {
    if (disposed || !visible || !sessionId || heartbeatInFlight) return;
    if (deps.clock.now() - lastActivityAt > 60_000) return;
    heartbeatInFlight = true;
    try {
      await lifecycle;
      const heartbeatSessionId = sessionId;
      if (disposed || !visible || !heartbeatSessionId || startedSessionId !== heartbeatSessionId) return;
      const nextSequence = sequence + 1;
      await deps.heartbeat(heartbeatSessionId, nextSequence);
      sequence = nextSequence;
    } catch {
      // Network recovery retries the same sequence on the next interval.
    } finally {
      heartbeatInFlight = false;
    }
  };
  const timer = deps.clock.setInterval(heartbeat, 30_000);

  const finishCurrent = (keepalive: boolean) => {
    const oldId = sessionId;
    const oldSequence = sequence;
    sessionId = null;
    startedSessionId = null;
    sequence = 0;
    if (oldId) lifecycle = lifecycle.then(async () => {
      await deps.finish(oldId, oldSequence, keepalive);
    }).catch(() => undefined);
  };

  return {
    userActivity() {
      if (disposed) return;
      const now = deps.clock.now();
      if (now - lastActivityAt > 60_000 && sessionId) {
        finishCurrent(false);
        startCurrent();
      }
      lastActivityAt = now;
    },
    visibilityChanged(nextVisible: boolean) {
      if (visible === nextVisible || disposed) return;
      visible = nextVisible;
      if (!nextVisible) finishCurrent(false);
      else {
        lastActivityAt = deps.clock.now();
        startCurrent();
      }
    },
    contextChanged(nextContext: ActiveStudyContext | null) {
      if (disposed || sameContext(context, nextContext)) return;
      finishCurrent(false);
      context = nextContext;
      if (!nextContext) return;
      lastActivityAt = deps.clock.now();
      startCurrent();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      deps.clock.clearInterval(timer);
      finishCurrent(true);
      context = null;
    },
  };
};
