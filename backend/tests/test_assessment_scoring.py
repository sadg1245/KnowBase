"""Pure business-rule tests for objective assessment scoring."""

import unittest
from datetime import datetime, timedelta, timezone

from app.services.assessment_scoring import (
    elapsed_seconds,
    grade_objective,
    next_mistake_state,
    normalize_answer,
)


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class AssessmentScoringTests(unittest.TestCase):
    def test_normalize_answer_handles_unicode_spaces_case_and_punctuation(self):
        self.assertEqual(normalize_answer("  A  B\u2003! "), "a b")
        self.assertEqual(normalize_answer("答案，。"), "答案")

    def test_single_choice_is_scalar_and_normalized(self):
        result = grade_objective("single_choice", " A ", "a")
        self.assertTrue(result.is_correct)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.max_score, 1.0)

    def test_true_false_compares_normalized_scalar(self):
        self.assertTrue(grade_objective("true_false", "正确", " 正确。 ").is_correct)
        self.assertFalse(grade_objective("true_false", True, False).is_correct)

    def test_multiple_choice_is_order_independent_but_requires_exact_set(self):
        result = grade_objective("multiple_choice", ["A", "C"], ["C", "A"])
        self.assertTrue(result.is_correct)
        self.assertFalse(grade_objective("multiple_choice", ["A", "C"], ["A"]).is_correct)

    def test_fill_blank_requires_each_position_and_accepts_answer_alternatives(self):
        result = grade_objective("fill_blank", [["Paris", "巴黎"], "France"], [" 巴黎。 ", "france"])
        self.assertTrue(result.is_correct)
        self.assertTrue(grade_objective("fill_blank", [["Paris", "巴黎"], "France"], ["Paris"]).is_correct is False)

    def test_unknown_or_non_objective_question_type_is_not_graded(self):
        result = grade_objective("short_answer", "x", "x")
        self.assertFalse(result.is_correct)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.error_reason, "unsupported_question_type")

    def test_two_correct_redos_master_a_mistake(self):
        first = next_mistake_state(None, correct=False, is_redo=False, now=NOW)
        improving = next_mistake_state(first, correct=True, is_redo=True, now=NOW)
        mastered = next_mistake_state(improving, correct=True, is_redo=True, now=NOW)
        self.assertEqual(mastered.mastery_status, "mastered")
        self.assertEqual(mastered.redo_count, 2)

    def test_mistake_error_resets_consecutive_correct_and_unmasters(self):
        first = next_mistake_state(None, correct=False, is_redo=False, now=NOW)
        improving = next_mistake_state(first, correct=True, is_redo=True, now=NOW)
        recovered = next_mistake_state(improving, correct=False, is_redo=True, now=NOW + timedelta(seconds=1))
        self.assertEqual(recovered.mastery_status, "unresolved")
        self.assertEqual(recovered.wrong_count, 2)
        self.assertEqual(recovered.consecutive_correct, 0)

    def test_correct_non_redo_does_not_create_or_change_mistake(self):
        self.assertIsNone(next_mistake_state(None, correct=True, is_redo=False, now=NOW))

    def test_elapsed_seconds_clamps_negative_and_limit(self):
        self.assertEqual(elapsed_seconds(NOW, NOW - timedelta(seconds=2), None), 0)
        self.assertEqual(elapsed_seconds(NOW, NOW + timedelta(seconds=12), 10), 10)
        self.assertEqual(elapsed_seconds(NOW, NOW + timedelta(milliseconds=1999), None), 1)


if __name__ == "__main__":
    unittest.main()
