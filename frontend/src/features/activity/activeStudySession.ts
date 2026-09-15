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
  start: (context: ActiveStudyContext, sessionId: string) => Promise<unknown>;
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

  const heartbeat = async () => {
    if (disposed || !visible || !sessionId || heartbeatInFlight) return;
    if (deps.clock.now() - lastActivityAt > 60_000) return;
    heartbeatInFlight = true;
    const heartbeatSessionId = sessionId;
    try {
      await lifecycle;
      if (disposed || !visible || sessionId !== heartbeatSessionId || startedSessionId !== heartbeatSessionId) return;
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
      if (!disposed) lastActivityAt = deps.clock.now();
    },
    visibilityChanged(nextVisible: boolean) {
      visible = nextVisible;
    },
    contextChanged(nextContext: ActiveStudyContext | null) {
      if (disposed || sameContext(context, nextContext)) return;
      finishCurrent(false);
      context = nextContext;
      if (!nextContext) return;
      sessionId = deps.createId();
      const nextId = sessionId;
      lastActivityAt = deps.clock.now();
      lifecycle = lifecycle.then(async () => {
        await deps.start(nextContext, nextId);
        if (sessionId === nextId) startedSessionId = nextId;
      }).catch(() => undefined);
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
