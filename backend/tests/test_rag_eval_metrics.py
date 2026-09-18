"""Retrieval evaluation metrics, case loading, and aggregation."""

import json
import tempfile
import unittest
from pathlib import Path

from app.rag.eval.metrics import (
    evaluate,
    load_cases,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


class RetrievalMetricTests(unittest.TestCase):
    def test_recall_at_k_counts_expected_hits_inside_the_window(self):
        ranked = ["a", "b", "c", "d"]
        self.assertEqual(recall_at_k(ranked, ["b", "d"], 2), 0.5)
        self.assertEqual(recall_at_k(ranked, ["b", "d"], 4), 1.0)

    def test_recall_at_k_is_zero_without_expected_ids(self):
        self.assertEqual(recall_at_k(["a"], [], 5), 0.0)

    def test_reciprocal_rank_uses_the_first_relevant_position(self):
        self.assertEqual(reciprocal_rank(["x", "b", "y"], ["b"]), 0.5)
        self.assertEqual(reciprocal_rank(["x", "y"], ["b"]), 0.0)

    def test_ndcg_at_k_rewards_early_hits_and_normalizes_to_one(self):
        expected = ["a", "b"]
        self.assertAlmostEqual(ndcg_at_k(["a", "b"], expected, 10), 1.0)
        self.assertLess(ndcg_at_k(["c", "a", "b"], expected, 10), 1.0)
        self.assertGreater(ndcg_at_k(["a", "c"], expected, 10), 0.0)


class RetrievalEvaluationTests(unittest.TestCase):
    def test_evaluate_aggregates_per_case_rows_and_a_summary(self):
        cases = [
            {"query": "q1", "workspace_id": "w", "expected_chunk_ids": ["a"]},
            {"query": "q2", "workspace_id": "w", "expected_chunk_ids": ["z"]},
        ]
        rankings = {"q1": ["a", "b"], "q2": ["x", "y"]}

        def retrieve(case):
            return [{"chunk_id": chunk_id} for chunk_id in rankings[case["query"]]]

        report = evaluate(cases, retrieve)

        self.assertEqual([row["query"] for row in report["cases"]], ["q1", "q2"])
        self.assertEqual(report["cases"][0]["recall@5"], 1.0)
        self.assertEqual(report["cases"][1]["recall@5"], 0.0)
        self.assertAlmostEqual(report["summary"]["mrr"], 0.5)
        self.assertEqual(report["summary"]["case_count"], 2)

    def test_load_cases_reads_jsonl_and_defaults_document_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "query": "什么是条件概率",
                        "workspace_id": "ws-1",
                        "expected_chunk_ids": ["doc_1_chunk_0"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            cases = load_cases(path)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["query"], "什么是条件概率")
        self.assertEqual(cases[0]["document_ids"], [])

    def test_load_cases_reports_the_offending_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text('{"query": "缺少 workspace"}\n', encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                load_cases(path)

        self.assertIn("line 1", str(caught.exception))
