import React from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import { normalizeMathDelimiters } from '../../features/learning/mathMarkdown';
import { linkifySourceCitations } from '../../features/learning/sourceNavigation';
import { layerNotice, splitAnswerSections } from '../../features/learning/answerLayers';
import type { SourceItem } from '../../services/api';


interface Props {
  content: string;
  sources?: SourceItem[];
  onSource?: (source: SourceItem) => void;
}


const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];


export const LearningMessageContent: React.FC<Props> = React.memo(({ content, sources = [], onSource }) => {
  const sections = splitAnswerSections(content);
  const components = {
    a: ({ href, children, ...props }: { href?: string; children?: React.ReactNode }) => {
      const match = href?.match(/^knowbase-source:\/\/(\d+)$/);
      if (match) {
        return <a href={href} {...props} onClick={event => {
          event.preventDefault();
          const source = sources[Number(match[1]) - 1];
          if (source) onSource?.(source);
        }}>{children}</a>;
      }
      return <a href={href} {...props} target="_blank" rel="noreferrer noopener">{children}</a>;
    },
  };
  return <div className="learning-answer-layers">
    {sections.map((section, index) => <section
      key={`${section.key}-${index}`}
      className={`learning-answer-layer layer-${section.key}`}
    >
      {section.title ? <header className="learning-layer-heading">
        <span>{section.title}</span>
        {layerNotice(section.key) ? <small>{layerNotice(section.key)}</small> : null}
      </header> : null}
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} components={components}>
        {linkifySourceCitations(normalizeMathDelimiters(section.body), sources.length)}
      </ReactMarkdown>
    </section>)}
  </div>;
});

LearningMessageContent.displayName = 'LearningMessageContent';
