import { useCallback, useEffect, useRef, useState } from 'react';

import { ChatEvent, LearningMode, RetrievalScopePayload, streamChat } from '../services/api';


interface SendChatInput {
  question: string;
  workspaceId?: string;
  documentIds: string[];
  mode: LearningMode;
  sessionId?: string;
  scope?: RetrievalScopePayload;
}


export const useStreamingChat = (onEvent: (event: ChatEvent) => void) => {
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const requestRef = useRef(0);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  const cancel = useCallback(() => {
    requestRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setLoading(false);
  }, []);

  const send = useCallback(async (input: SendChatInput) => {
    controllerRef.current?.abort();
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      await streamChat(
        input.question,
        input.workspaceId,
        (event) => {
          if (requestRef.current === requestId) handlerRef.current(event);
        },
        controller.signal,
        input.mode,
        input.sessionId,
        input.documentIds,
        input.scope,
      );
    } finally {
      if (requestRef.current === requestId) {
        controllerRef.current = null;
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => cancel, [cancel]);
  return { send, cancel, loading };
};
