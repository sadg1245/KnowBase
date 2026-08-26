import React from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import { normalizeMathDelimiters } from '../../features/learning/mathMarkdown';
import { linkifySourceCitations } from '../../features/learning/sourceNavigation';
import type { SourceItem } from '../../services/api';


interface Props {
  content: string;
  sources?: SourceItem[];
  onSource?: (source: SourceItem) => void;
}


const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];


export const LearningMessageContent: React.FC<Props> = React.memo(({ content, sources = [], onSource }) => (
  <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} components={{
    a: ({ href, children, ...props }) => {
      const match = href?.match(/^knowbase-source:\/\/(\d+)$/);
      if (match) return <a href={href} {...props} onClick={event => { event.preventDefault(); const source = sources[Number(match[1]) - 1]; if (source) onSource?.(source); }}>{children}</a>;
      return <a href={href} {...props} target="_blank" rel="noreferrer noopener">{children}</a>;
    },
  }}>
    {linkifySourceCitations(normalizeMathDelimiters(content), sources.length)}
  </ReactMarkdown>
));

LearningMessageContent.displayName = 'LearningMessageContent';
