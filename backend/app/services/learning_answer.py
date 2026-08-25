"""Hard evidence gates and deterministic learning-answer helpers."""

from __future__ import annotations

import re


def answer_requires_model(strict_sources: bool, evidence_status: str) -> bool:
    return not strict_sources or evidence_status == "supported"


def strict_refusal(evidence_status: str) -> str:
    if evidence_status == "limited":
        return (
            "当前资料与问题有一定关联，但证据不足，严格资料模式下我不能据此下结论。"
            "请补充更具体的问题、选择相关文件，或关闭严格资料模式后查看明确标注的 AI 补充。"
        )
    return (
        "我在当前选定的私人资料中没有找到足以回答这个问题的内容。"
        "你可以调整关键词、扩大文件范围，或先导入相关资料。"
    )


def filter_strict_answer(answer: str, source_count: int) -> str:
    """Keep only substantive paragraphs whose citation IDs exist in this run."""
    valid: list[str] = []
    for paragraph in re.split(r"\n\s*\n", answer.strip()):
        citations = [int(value) for value in re.findall(r"\[资料(\d+)\]", paragraph)]
        if citations and all(1 <= value <= source_count for value in citations):
            valid.append(paragraph.strip())
    return "\n\n".join(valid)


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
