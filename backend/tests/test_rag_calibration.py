"""阶段 4：阈值重标定只在样本充分时给建议，且不编造数字。"""

import unittest

from app.rag.eval.calibration import cases_from_retrieval, suggest_thresholds


def sample(score: float, relevant: bool) -> dict:
    return {"top_score": score, "has_relevant": relevant}


class ThresholdCalibrationTests(unittest.TestCase):
    def test_insufficient_or_single_label_samples_are_rejected(self):
        self.assertIsNone(suggest_thresholds([]))
        self.assertIsNone(suggest_thresholds([sample(0.9, True)] * 4))
        self.assertIsNone(suggest_thresholds([sample(0.9, True)] * 20))          # 全是正例
        self.assertIsNone(suggest_thresholds([sample(0.2, False)] * 20))         # 全是负例

    def test_separable_samples_recover_the_boundary(self):
        cases = (
            [sample(0.80 + index * 0.01, True) for index in range(4)]
            + [sample(0.30 + index * 0.01, False) for index in range(4)]
        )
        suggestion = suggest_thresholds(cases, current_supported=0.58)

        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertAlmostEqual(suggestion.supported, 0.80, places=4)
        self.assertAlmostEqual(suggestion.second, 0.67, places=4)
        self.assertAlmostEqual(suggestion.limited, 0.64, places=4)
        self.assertEqual(suggestion.f1, 1.0)
        self.assertEqual(suggestion.cases, 8)
        self.assertTrue(suggestion.reasons)

    def test_overlapping_samples_trade_precision_for_recall(self):
        cases = (
            [sample(0.62, True), sample(0.55, True), sample(0.50, True), sample(0.48, True)]
            + [sample(0.60, False), sample(0.52, False), sample(0.40, False), sample(0.20, False)]
        )
        suggestion = suggest_thresholds(cases, current_supported=0.58)
        assert suggestion is not None

        self.assertLess(suggestion.f1, 1.0)
        self.assertLessEqual(suggestion.limited, suggestion.second)
        self.assertLessEqual(suggestion.second, suggestion.supported)

    def test_cases_from_retrieval_uses_labelled_expectations(self):
        cases = [
            {"query": "甲", "expected_chunk_ids": ["c1"]},
            {"query": "乙", "expected_chunk_ids": []},          # 未标注 → 跳过
        ]

        def retrieve(case):
            if case["query"] == "甲":
                return [{"chunk_id": "c9", "score": 0.7}, {"chunk_id": "c1", "score": 0.6}]
            return []

        samples = cases_from_retrieval(cases, retrieve)

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["top_score"], 0.7)
        self.assertTrue(samples[0]["has_relevant"])


if __name__ == "__main__":
    unittest.main()
