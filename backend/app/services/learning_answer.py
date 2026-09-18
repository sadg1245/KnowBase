"""Deterministic follow-up question suggestions for the learning chat."""

from __future__ import annotations

import re


def build_follow_up_suggestions(question: str, mode: str) -> list[str]:
    topic = re.sub(r"[？?。！!]", "", question).strip()[:32] or "这个主题"
    mode_specific = {
        "direct": [
            f"{topic}最关键的依据是什么？",
            f"能给我一个{topic}的实际例子吗？",
            f"{topic}容易和什么概念混淆？",
        ],
        "simple": [
            f"再用一个生活类比解释{topic}",
            f"给我一个关于{topic}的简单例子",
            f"用三句话总结{topic}",
        ],
        "deep": [
            f"继续推导{topic}背后的原理",
            f"{topic}有哪些边界条件？",
            f"{topic}的常见误区是什么？",
        ],
        "socratic": [
            "继续问我下一个关键问题",
            "给我一个更小的提示",
            "根据我的回答判断理解漏洞",
        ],
        "feynman": [
            "请让我先复述，再帮我找漏洞",
            f"怎样把{topic}讲给初学者？",
            "给我一份费曼复述检查清单",
        ],
        "quiz": [
            "再出一道难一点的题",
            "先不要公布答案，给我一个提示",
            "根据我的错误生成一道变式题",
        ],
    }
    return mode_specific.get(mode, mode_specific["direct"])[:3]
