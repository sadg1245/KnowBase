import assert from 'node:assert/strict';
import test from 'node:test';

import { applyLearningRecommendationPreset, requestedLearningPreset } from '../src/pages/learningChatPresets';

const workspaces = [{ id: 'workspace-1' }, { id: 'workspace-2' }];
const points = [{ id: 'point-1', workspace_id: 'workspace-1', document_id: 'document-1', title: '勾股定理' }];

test('recommendation preset accepts workspace aliases, validates point and never auto-sends', () => {
  const modern = requestedLearningPreset(new URLSearchParams('workspace=workspace-1&knowledge_point_id=point-1&mode=simple&prompt=%E8%AF%B7%E8%AE%B2%E8%A7%A3'));
  assert.deepEqual(applyLearningRecommendationPreset(modern, workspaces, points, ['document-1']), {
    workspaceId: 'workspace-1', knowledgePointId: 'point-1', knowledgePointTitle: '勾股定理', documentIds: ['document-1'], mode: 'simple', draft: '请讲解', shouldAutoSend: false,
  });

  const legacy = requestedLearningPreset(new URLSearchParams('workspace_id=workspace-2&mode=deep&prompt=ignored'));
  assert.deepEqual(legacy, { workspaceId: 'workspace-2', knowledgePointId: undefined, mode: undefined, prompt: 'ignored' });
  assert.deepEqual(applyLearningRecommendationPreset(legacy, workspaces, points, []), {
    workspaceId: 'workspace-2', knowledgePointId: undefined, knowledgePointTitle: undefined, documentIds: [], mode: undefined, draft: '', shouldAutoSend: false,
  });
});

test('invalid workspace or cross-workspace point resets the recommendation draft and context', () => {
  const invalid = requestedLearningPreset(new URLSearchParams('workspace=workspace-2&knowledge_point_id=point-1&mode=simple&prompt=stale'));
  assert.deepEqual(applyLearningRecommendationPreset(invalid, workspaces, points, ['document-1']), {
    workspaceId: 'workspace-2', knowledgePointId: undefined, knowledgePointTitle: undefined, documentIds: [], mode: undefined, draft: '', shouldAutoSend: false,
  });
  assert.deepEqual(applyLearningRecommendationPreset(requestedLearningPreset(new URLSearchParams()), workspaces, points, []), {
    workspaceId: undefined, knowledgePointId: undefined, knowledgePointTitle: undefined, documentIds: [], mode: undefined, draft: '', shouldAutoSend: false,
  });
});
