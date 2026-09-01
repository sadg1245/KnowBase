"""Pure scoring, timing, and mistake-state rules for assessments."""

from __future__ import annotations

import re
import string
from copy import copy
from dataclasses import dataclass
from datetime import datetime


_SURROUNDING_PUNCTUATION = string.punctuation + "，。！？；：、（）【】［］「」『』《》〈〉“”‘’"
_WHITESPACE = re.compile(r"\s+", re.UNICODE)


@dataclass(frozen=True)
class GradeResult:
    is_correct: bool
    score: float
    max_score: float
    feedback: str | None = None
    error_reason: str | None = None


@dataclass
class MistakeState:
    wrong_count: int = 1
    redo_count: int = 0
    consecutive_correct: int = 0
    mastery_status: str = "unresolved"
    first_wrong_at: datetime | None = None
    last_wrong_at: datetime | None = None
    last_redone_at: datetime | None = None
    resolved_at: datetime | None = None


def normalize_answer(value: object) -> object:
    """Normalize answer text without changing its semantic content."""
    if isinstance(value, str):
        text = _WHITESPACE.sub(" ", value).strip()
        text = text.strip(_SURROUNDING_PUNCTUATION).strip()
        return "".join(chr(ord(char) + 32) if "A" <= char <= "Z" else char for char in text)
    if isinstance(value, list):
        return [normalize_answer(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_answer(item) for item in value)
    if isinstance(value, set):
        return {normalize_answer(item) for item in value}
    if isinstance(value, dict):
        return {key: normalize_answer(item) for key, item in value.items()}
    return value


def _result(correct: bool, *, feedback: str | None = None, error_reason: str | None = None) -> GradeResult:
    return GradeResult(correct, 1.0 if correct else 0.0, 1.0, feedback, error_reason)


def grade_objective(question_type: str, expected: object, actual: object) -> GradeResult:
    """Grade supported objective question types with exact normalized matching."""
    if question_type in {"single_choice", "true_false"}:
        correct = normalize_answer(expected) == normalize_answer(actual)
    elif question_type == "multiple_choice":
        expected_value = normalize_answer(expected)
        actual_value = normalize_answer(actual)
        if not isinstance(expected_value, (list, tuple, set)) or not isinstance(actual_value, (list, tuple, set)):
            return _result(False, error_reason="invalid_answer_shape")
        correct = set(expected_value) == set(actual_value)
    elif question_type == "fill_blank":
        expected_blanks = expected if isinstance(expected, (list, tuple)) else [expected]
        actual_blanks = actual if isinstance(actual, (list, tuple)) else [actual]
        if len(expected_blanks) != len(actual_blanks):
            correct = False
        else:
            correct = all(
                normalize_answer(actual_blank)
                in (
                    {normalize_answer(option) for option in expected_blank}
                    if isinstance(expected_blank, (list, tuple, set))
                    else {normalize_answer(expected_blank)}
                )
                for expected_blank, actual_blank in zip(expected_blanks, actual_blanks)
            )
    else:
        return _result(False, error_reason="unsupported_question_type")
    return _result(correct, feedback="Correct" if correct else "Incorrect", error_reason=None if correct else "incorrect_answer")


def next_mistake_state(
    previous: MistakeState | None,
    *,
    correct: bool,
    is_redo: bool,
    now: datetime,
) -> MistakeState | None:
    """Advance an in-memory mistake state; persistence is left to callers."""
    if previous is None:
        return None if correct else MistakeState(first_wrong_at=now, last_wrong_at=now)

    state = copy(previous)
    if not correct:
        state.wrong_count += 1
        state.consecutive_correct = 0
        state.mastery_status = "unresolved"
        state.last_wrong_at = now
        state.resolved_at = None
        return state

    if not is_redo:
        return state

    state.redo_count += 1
    state.consecutive_correct += 1
    state.last_redone_at = now
    if state.consecutive_correct >= 2:
        state.mastery_status = "mastered"
        state.resolved_at = now
    else:
        state.mastery_status = "improving"
    return state


def elapsed_seconds(started_at: datetime, finished_at: datetime, limit: int | None) -> int:
    """Return elapsed whole seconds, clamped to zero and an optional limit."""
    elapsed = max(0, int((finished_at - started_at).total_seconds()))
    return min(elapsed, max(0, limit)) if limit is not None else elapsed
