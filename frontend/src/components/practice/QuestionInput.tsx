import React from 'react';
import { Checkbox, Input, Radio } from 'antd';

import type { AssessmentQuestion, PracticeAnswer } from '../../features/practice/types';


export const answerIsPresent = (answer: PracticeAnswer | undefined): boolean => (
  typeof answer === 'string'
    ? answer.trim().length > 0
    : Array.isArray(answer) && answer.length > 0 && answer.every(item => item.trim().length > 0)
);

interface QuestionInputProps {
  question: AssessmentQuestion;
  value?: PracticeAnswer;
  disabled?: boolean;
  onChange: (answer: PracticeAnswer) => void;
}

export const QuestionInput: React.FC<QuestionInputProps> = ({ question, value, disabled = false, onChange }) => {
  const options = question.options ?? [];
  if (question.question_type === 'multiple_choice') {
    return <Checkbox.Group
      className="practice-answer-options"
      aria-label="多项选择答案"
      disabled={disabled}
      value={Array.isArray(value) ? value : []}
      onChange={values => onChange(values.map(String))}
    >
      {options.map((option, index) => <Checkbox key={option} value={option}>
        <b>{String.fromCharCode(65 + index)}</b><span>{option}</span>
      </Checkbox>)}
    </Checkbox.Group>;
  }

  if (question.question_type === 'single_choice' || question.question_type === 'true_false') {
    const choiceOptions = question.question_type === 'true_false' && options.length === 0 ? ['正确', '错误'] : options;
    return <Radio.Group
      className="practice-answer-options"
      aria-label={question.question_type === 'true_false' ? '判断题答案' : '单项选择答案'}
      disabled={disabled}
      value={typeof value === 'string' ? value : undefined}
      onChange={event => onChange(event.target.value)}
    >
      {choiceOptions.map((option, index) => <Radio key={option} value={option}>
        <b>{question.question_type === 'true_false' ? (index === 0 ? '✓' : '×') : String.fromCharCode(65 + index)}</b>
        <span>{option}</span>
      </Radio>)}
    </Radio.Group>;
  }

  if (question.question_type === 'fill_blank') {
    const blankCount = question.blank_count ?? 1;
    const values = Array.from({ length: blankCount }, (_, index) => Array.isArray(value) ? value[index] ?? '' : index === 0 ? value ?? '' : '');
    return <div className="practice-blank-fields">{values.map((blank, index) => <Input
      key={index}
      className="practice-fill-blank"
      aria-label={blankCount === 1 ? '填空题答案' : `第 ${index + 1} 空答案`}
      disabled={disabled}
      value={blank}
      onChange={event => onChange(values.map((item, slot) => slot === index ? event.target.value : item))}
      placeholder={blankCount === 1 ? '填写缺失的关键词或短语' : `填写第 ${index + 1} 空`}
    />)}</div>;
  }

  return <Input.TextArea
    className="practice-text-answer"
    aria-label={question.question_type === 'concept_explanation' ? '概念解释答案' : '简答题答案'}
    disabled={disabled}
    value={typeof value === 'string' ? value : ''}
    onChange={event => onChange(event.target.value)}
    rows={6}
    placeholder={question.question_type === 'concept_explanation' ? '用自己的话解释概念，并说明它为什么重要' : '写下你的推理过程和结论'}
  />;
};
