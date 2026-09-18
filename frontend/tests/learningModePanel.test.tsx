import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { LearningModePanel } from '../src/components/learning/LearningModePanel';

test('learning mode panel explains the source-first policy without a strict switch', () => {
  const html = renderToStaticMarkup(<LearningModePanel
    workspaces={[{ id: 'ws-1', name: '线性代数' } as any]}
    workspaceId="ws-1"
    documents={[]}
    documentIds={[]}
    documentsLoading={false}
    mode="simple"
    evidenceStatus="model_only"
    onWorkspace={() => undefined}
    onDocuments={() => undefined}
    onMode={() => undefined}
  />);

  assert.match(html, /资料优先/);
  assert.match(html, /模型补充/);
  assert.doesNotMatch(html, /严格依据资料/);
});
