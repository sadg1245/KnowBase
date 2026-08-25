import React from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import { normalizeMathDelimiters } from '../../features/learning/mathMarkdown';


interface Props {
  content: string;
}


const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];


export const LearningMessageContent: React.FC<Props> = React.memo(({ content }) => (
  <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS}>
    {normalizeMathDelimiters(content)}
  </ReactMarkdown>
));

LearningMessageContent.displayName = 'LearningMessageContent';
