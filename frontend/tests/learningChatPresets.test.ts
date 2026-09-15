import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyLearningRecommendationPreset,
  executeLearningRecommendationCommands,
  planLearningRecommendationPresetCommit,
  planLearningRecommendationPresetReset,
  requestedLearningPreset,
} from '../src/pages/learningChatPresets';

const workspaces = [{ id: 'workspace-1' }, { id: 'workspace-2' }];
const points = [{ id: 'point-1', workspace_id: 'workspace-1', document_id: 'document-1', title: '勾股定理' }];

test('saved generic recommendation drafts include validated point context before manual send', () => {
  const preset = applyLearningRecommendationPreset(requestedLearningPreset(new URLSearchParams({
    workspace: 'workspace-1', knowledge_point_id: 'point-1', mode: 'simple', prompt: '请讲解这个知识点',
  })), workspaces, points, ['document-1']);
  let visibleDraft = '';
  executeLearningRecommendationCommands(planLearningRecommendationPresetCommit(preset), {
    cancelStream: () => undefined, detachSession: () => undefined,
    setWorkspace: () => undefined, setDocuments: () => undefined, setMode: () => undefined,
    setPointTitle: () => undefined, setDraft: value => { visibleDraft = value; },
  });
  assert.match(visibleDraft, /勾股定理/);
  assert.match(visibleDraft, /point-1/);
  assert.match(visibleDraft, /请讲解这个知识点/);
});

test('recommendation preset accepts workspace aliases, validates point and never auto-sends', () => {
  const modern = requestedLearningPreset(new URLSearchParams('workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=%E8%AF%B7%E8%AE%B2%E8%A7%A3'));
  assert.deepEqual(applyLearningRecommendationPreset(modern, workspaces, points, ['document-1']), {
    workspaceId: 'workspace-1', knowledgePointId: 'point-1', knowledgePointTitle: '勾股定理', documentIds: ['document-1'], mode: 'simple', draft: '知识点「勾股定理」（ID: point-1）\n\n请讲解',
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

test('production preset command plan resets and commits context without a send or stream-start command', () => {
  const state = { workspaceId: 'old-workspace' as string | undefined, documentIds: ['old-document'], mode: 'deep', draft: 'old', title: '旧知识点' as string | undefined, active: true, messages: 2, evidence: true };
  let cancelled = 0;
  const actions = {
    cancelStream: () => { cancelled += 1; },
    detachSession: () => { state.active = false; state.messages = 0; state.evidence = false; },
    setWorkspace: (value?: string) => { state.workspaceId = value; },
    setDocuments: (value: string[]) => { state.documentIds = value; },
    setMode: (value: 'simple') => { state.mode = value; },
    setDraft: (value: string) => { state.draft = value; },
    setPointTitle: (value?: string) => { state.title = value; },
  };

  const resetCommands = planLearningRecommendationPresetReset();
  assert.deepEqual(resetCommands, [
    { type: 'cancel-stream' },
    { type: 'detach-session' },
    { type: 'set-draft', value: '' },
    { type: 'set-point-title', value: undefined },
    { type: 'set-documents', value: [] },
  ]);
  executeLearningRecommendationCommands(resetCommands, actions);
  assert.equal(state.active, false);
  const applied = applyLearningRecommendationPreset(
    requestedLearningPreset(new URLSearchParams('workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=first')),
    workspaces, points, ['document-1'],
  );
  const commitCommands = planLearningRecommendationPresetCommit(applied);
  assert.deepEqual(commitCommands, [
    { type: 'set-workspace', value: 'workspace-1' },
    { type: 'set-documents', value: ['document-1'] },
    { type: 'set-mode', value: 'simple' },
    { type: 'set-draft', value: '知识点「勾股定理」（ID: point-1）\n\nfirst' },
    { type: 'set-point-title', value: '勾股定理' },
  ]);
  assert.deepEqual([...resetCommands, ...commitCommands].map(command => command.type), [
    'cancel-stream', 'detach-session', 'set-draft', 'set-point-title', 'set-documents',
    'set-workspace', 'set-documents', 'set-mode', 'set-draft', 'set-point-title',
  ]);
  executeLearningRecommendationCommands(commitCommands, actions);
  assert.deepEqual(state, { workspaceId: 'workspace-1', documentIds: ['document-1'], mode: 'simple', draft: '知识点「勾股定理」（ID: point-1）\n\nfirst', title: '勾股定理', active: false, messages: 0, evidence: false });
  assert.equal(cancelled, 1);

  executeLearningRecommendationCommands(planLearningRecommendationPresetReset(), actions);
  assert.equal(state.draft, '');
  assert.deepEqual(state.documentIds, []);
  assert.equal(state.title, undefined);
});
