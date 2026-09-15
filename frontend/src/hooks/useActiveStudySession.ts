import { useEffect, useRef } from 'react';

import { createActiveStudyController } from '../features/activity/activeStudySession';
import {
  finishStudySession,
  finishStudySessionKeepalive,
  heartbeatStudySession,
  startStudySession,
} from '../services/api';

type Options = {
  contextType: 'document' | 'conversation';
  contextId?: string;
  workspaceId?: string;
  enabled?: boolean;
};

const browserClock = {
  now: () => Date.now(),
  setInterval: (callback: () => void | Promise<void>, milliseconds: number) => window.setInterval(callback, milliseconds),
  clearInterval: (id: number) => window.clearInterval(id),
};

export const useActiveStudySession = ({ contextType, contextId, workspaceId, enabled = true }: Options) => {
  const controllerRef = useRef<ReturnType<typeof createActiveStudyController> | null>(null);

  useEffect(() => {
    const controller = createActiveStudyController({
      clock: browserClock,
      createId: () => crypto.randomUUID(),
      start: (context, id) => startStudySession({
        id,
        context_type: context.contextType,
        context_id: context.contextId,
        workspace_id: context.workspaceId,
      }),
      heartbeat: (id, sequence) => heartbeatStudySession(id, sequence),
      finish: (id, sequence, keepalive) => keepalive
        ? finishStudySessionKeepalive(id, sequence)
        : finishStudySession(id, sequence),
    });
    controllerRef.current = controller;
    const activity = () => controller.userActivity();
    const visibility = () => controller.visibilityChanged(document.visibilityState === 'visible');
    const options: AddEventListenerOptions = { passive: true };
    window.addEventListener('pointerdown', activity, options);
    window.addEventListener('keydown', activity);
    window.addEventListener('touchstart', activity, options);
    window.addEventListener('scroll', activity, options);
    document.addEventListener('visibilitychange', visibility);
    visibility();
    return () => {
      window.removeEventListener('pointerdown', activity);
      window.removeEventListener('keydown', activity);
      window.removeEventListener('touchstart', activity);
      window.removeEventListener('scroll', activity);
      document.removeEventListener('visibilitychange', visibility);
      controller.dispose();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, []);

  useEffect(() => {
    controllerRef.current?.contextChanged(enabled && contextId ? {
      contextType, contextId, workspaceId,
    } : null);
  }, [contextId, contextType, enabled, workspaceId]);
};
