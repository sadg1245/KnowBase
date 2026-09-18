"""Prompt assembly order, budgets, and citation-space isolation."""

import unittest

from app.services import learning_answer_service as service


class PromptAssemblyTests(unittest.TestCase):
    def test_blocks_follow_the_fixed_order(self):
        prompt = service.build_learning_prompt(
            question="什么是闭包",
            mode="simple",
            context_blocks=["[资料1] 来源：a.md\n闭包捕获外部变量。"],
            profile_block="- 闭包掌握度 45%",
            memory_block="- [mistake_pattern] 循环变量绑定错误",
            history_lines=["user: 上次讲到作用域"],
        )
        positions = [
            prompt.index("## 学习画像"),
            prompt.index("## 学习者记忆"),
            prompt.index("## 私人资料"),
            prompt.index("## 会话历史"),
            prompt.index("## 教学模式"),
            prompt.index("## 用户问题"),
        ]

        self.assertEqual(positions, sorted(positions))

    def test_missing_context_is_stated_explicitly(self):
        prompt = service.build_learning_prompt(
            question="问题", mode="direct", context_blocks=[]
        )

        self.assertIn("没有检索到可用的资料片段", prompt)
        self.assertIn("你的资料里没有讲这个问题", prompt)

    def test_profile_and_memory_blocks_forbid_citation_use(self):
        prompt = service.build_learning_prompt(
            question="问题",
            mode="direct",
            context_blocks=["[资料1] 来源：a.md\n内容"],
            profile_block="- 薄弱点：闭包",
            memory_block="- [preference] 喜欢先看例子",
        )

        self.assertIn("不是事实证据，也不能引用", prompt)
        self.assertEqual(prompt.count("## 私人资料"), 1)

    def test_unknown_mode_falls_back_to_simple_instruction(self):
        prompt = service.build_learning_prompt(
            question="问题", mode="unknown-mode", context_blocks=[]
        )

        self.assertIn(service.MODE_INSTRUCTIONS["simple"], prompt)


if __name__ == "__main__":
    unittest.main()
