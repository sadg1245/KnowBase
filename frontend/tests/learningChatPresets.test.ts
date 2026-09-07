import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyLearningRecommendationPreset,
  commitLearningRecommendationPreset,
  requestedLearningPreset,
  resetLearningRecommendationPreset,
} from '../src/pages/learningChatPresets';

const workspaces = [{ id: 'workspace-1' }, { id: 'workspace-2' }];
const points = [{ id: 'point-1', workspace_id: 'workspace-1', document_id: 'document-1', title: '勾股定理' }];

test('recommendation preset accepts workspace aliases, validates point and never auto-sends', () => {
  const modern = requestedLearningPreset(new URLSearchParams('workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=%E8%AF%B7%E8%AE%B2%E8%A7%A3'));
  assert.deepEqual(applyLearningRecommendationPreset(modern, workspaces, points, ['document-1']), {
    workspaceId: 'workspace-1', knowledgePointId: 'point-1', knowledgePointTitle: '勾股定理', documentIds: ['document-1'], mode: 'simple', draft: '请讲解',
  });

  const legacy = requestedLearningPreset(new URLSearchParams('workspace_id=workspace-2&mode=deep&prompt=ignored'));
  assert.deepEqual(legacy, { workspaceId: 'workspace-2', knowledgePointId: undefined, mode: undefined, prompt: 'ignored' });
  assert.deepEqual(applyLearningRecommendationPreset(legacy, workspaces, points, []), {
    workspaceId: 'workspace-2', knowledgePointId: undefined, knowledgePointTitle: undefined, documentIds: [], mode: undefined, draft: '',
  });
});

test('invalid workspace or cross-workspace point resets the recommendation draft and context', () => {
  const invalid = requestedLearningPreset(new URLSearchParams('workspace=workspace-2&knowledge_point_id=point-1&mode=simple&prompt=stale'));
  assert.deepEqual(applyLearningRecommendationPreset(invalid, workspaces, points, ['document-1']), {
    workspaceId: 'workspace-2', knowledgePointId: undefined, knowledgePointTitle: undefined, documentIds: [], mode: undefined, draft: '',
  });
  assert.deepEqual(applyLearningRecommendationPreset(requestedLearningPreset(new URLSearchParams()), workspaces, points, []), {
    workspaceId: undefined, knowledgePointId: undefined, knowledgePointTitle: undefined, documentIds: [], mode: undefined, draft: '',
  });
});

test('production preset orchestration resets URL state and detaches an unrelated session without sending', () => {
  const state = { workspaceId: 'old-workspace' as string | undefined, documentIds: ['old-document'], mode: 'deep', draft: 'old', title: '旧知识点' as string | undefined, active: true, messages: 2, evidence: true };
  let cancelled = 0;
  let sends = 0;
  const actions = {
    cancelStream: () => { cancelled += 1; },
    resetDraft: () => { state.draft = ''; },
    resetPointTitle: () => { state.title = undefined; },
    resetDocuments: () => { state.documentIds = []; },
    detachSession: () => { state.active = false; state.messages = 0; state.evidence = false; },
    setWorkspace: (value?: string) => { state.workspaceId = value; },
    setDocuments: (value: string[]) => { state.documentIds = value; },
    setMode: (value: 'simple') => { state.mode = value; },
    setDraft: (value: string) => { state.draft = value; },
    setPointTitle: (value?: string) => { state.title = value; },
  };

  resetLearningRecommendationPreset(actions);
  assert.equal(state.active, false);
  const applied = applyLearningRecommendationPreset(
    requestedLearningPreset(new URLSearchParams('workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=first')),
    workspaces, points, ['document-1'],
  );
  const committed = commitLearningRecommendationPreset(applied, { workspace_id: 'old-workspace', document_ids: ['old-document'], mode: 'deep' }, actions);
  assert.equal(committed, true);
  assert.deepEqual(state, { workspaceId: 'workspace-1', documentIds: ['document-1'], mode: 'simple', draft: 'first', title: '勾股定理', active: false, messages: 0, evidence: false });
  assert.equal(cancelled, 1);
  assert.equal(sends, 0);

  sends += 0;
  resetLearningRecommendationPreset(actions);
  assert.equal(state.draft, '');
  assert.deepEqual(state.documentIds, []);
  assert.equal(state.title, undefined);
  assert.equal(sends, 0);
});
