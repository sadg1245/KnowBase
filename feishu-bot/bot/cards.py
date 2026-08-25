"""
飞书交互式卡片（schema 2.0）构建函数。
所有面向用户的文本均使用中文。
"""

from __future__ import annotations


def build_answer_card(answer: str, sources: list[dict], confidence: float) -> dict:
    """
    构建展示 KnowBase 回答的飞书交互式卡片。

    Args:
        answer: 回答文本（支持 markdown）。
        sources: 来源字典列表，每个包含 'file'、'page'、'snippet' 等键。
        confidence: 置信度分数，范围 0 到 1。

    Returns:
        表示飞书卡片 JSON 的字典。
    """
    # 构建来源部分
    source_lines = []
    for i, src in enumerate(sources, 1):
        file_name = src.get("source_file", src.get("file", "unknown"))
        page = src.get("page_num", src.get("page"))
        snippet = src.get("content", src.get("snippet", ""))
        if page:
            source_lines.append(f"**{i}. {file_name}** (Page {page})")
        else:
            source_lines.append(f"**{i}. {file_name}**")
        if snippet:
            # 截断过长的摘要
            short = snippet[:150] + ("..." if len(snippet) > 150 else "")
            source_lines.append(f"> {short}")
        source_lines.append("")

    sources_text = "\n".join(source_lines) if source_lines else "*No sources available.*"

    # 置信度指示器
    if confidence >= 0.8:
        conf_label = f"**Confidence:** {confidence:.0%} - High"
        conf_color = "green"
    elif confidence >= 0.5:
        conf_label = f"**Confidence:** {confidence:.0%} - Medium"
        conf_color = "orange"
    else:
        conf_label = f"**Confidence:** {confidence:.0%} - Low"
        conf_color = "red"

    card = {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "\U0001f4da KnowBase \u56de\u7b54",
            },
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": answer,
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**\U0001f4c4 \u53c2\u8003\u6765\u6e90**",
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": sources_text,
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "lark_md",
                        "content": conf_label,
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "\U0001f44d \u6709\u5e2e\u52a9",
                        },
                        "type": "primary",
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "\U0001f44e \u9700\u6539\u8fdb",
                        },
                        "type": "default",
                    },
                ],
            },
        ],
    }

    return card


def build_help_card() -> dict:
    """
    构建帮助卡片，展示可用的机器人命令。
    """
    card = {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "\U0001f4d6 KnowBase \u5e2e\u52a9",
            },
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "\u6b22\u8fce\u4f7f\u7528 **KnowBase** \u77e5\u8bc6\u5e93\u52a9\u624b\uff01"
                        "\u4ee5\u4e0b\u662f\u53ef\u7528\u7684\u547d\u4ee4\uff1a"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**\u76f4\u63a5\u63d0\u95ee**\n"
                        "\u53d1\u9001\u4efb\u4f55\u95ee\u9898\uff0c\u6211\u4f1a\u4ece\u77e5\u8bc6\u5e93\u4e2d\u67e5\u627e\u7b54\u6848\n\n"
                        "**/search \u5173\u952e\u8bcd**\n"
                        "\u641c\u7d22\u77e5\u8bc6\u5e93\uff0c\u8fd4\u56de\u76f8\u5173\u6587\u6863\u7247\u6bb5\n\n"
                        "**/status**\n"
                        "\u67e5\u770b\u77e5\u8bc6\u5e93\u72b6\u6001\n\n"
                        "**/today**\n"
                        "查看今天的学习任务和进度\n\n"
                        "**/review**\n"
                        "开始复习今天到期的知识卡\n\n"
                        "**/mode 通俗|深入|引导|费曼|测试**\n"
                        "切换 AI 的教学方式\n\n"
                        "**/ws \u5de5\u4f5c\u533a\u540d\u79f0**\n"
                        "\u5207\u6362\u77e5\u8bc6\u5e93\u5de5\u4f5c\u533a\n\n"
                        "**/help**\n"
                        "\u663e\u793a\u5e2e\u52a9\u4fe1\u606f"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "lark_md",
                        "content": "\U0001f4a1 \u63d0\u793a\uff1a\u76f4\u63a5\u53d1\u9001\u95ee\u9898\u5373\u53ef\u5f00\u59cb\u4f7f\u7528",
                    },
                ],
            },
        ],
    }

    return card


def build_status_card(stats: dict) -> dict:
    """
    构建状态卡片，展示知识库统计信息。

    Args:
        stats: 包含 workspace_count、document_count、
               total_chunks、last_updated 等键的字典。
    """
    workspace_count = stats.get("workspace_count", 0)
    document_count = stats.get("document_count", 0)
    total_chunks = stats.get("total_chunks", 0)
    last_updated = stats.get("last_updated", "N/A")

    card = {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "\U0001f4ca KnowBase \u72b6\u6001",
            },
            "template": "purple",
        },
        "elements": [
            {
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "default",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": (
                                        f"**\U0001f4c1 \u5de5\u4f5c\u533a\u6570\u91cf**\n{workspace_count}"
                                    ),
                                },
                            },
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": (
                                        f"**\U0001f4c4 \u6587\u6863\u6570\u91cf**\n{document_count}"
                                    ),
                                },
                            },
                        ],
                    },
                ],
            },
            {
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "default",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": (
                                        f"**\U0001f9e9 \u603b\u5207\u7247\u6570**\n{total_chunks}"
                                    ),
                                },
                            },
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": (
                                        f"**\U0001f552 \u6700\u540e\u66f4\u65b0**\n{last_updated}"
                                    ),
                                },
                            },
                        ],
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "lark_md",
                        "content": "\u77e5\u8bc6\u5e93\u8fd0\u884c\u6b63\u5e38 \u2705",
                    },
                ],
            },
        ],
    }

    return card


def build_not_found_card(query: str) -> dict:
    """
    构建未找到结果时的卡片。
    """
    card = {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "\U0001f50d \u672a\u627e\u5230\u7ed3\u679c",
            },
            "template": "grey",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"\u77e5\u8bc6\u5e93\u4e2d\u6682\u672a\u627e\u5230\u4e0e"
                        f"\u300c**{query}**\u300d\u76f8\u5173\u7684\u4fe1\u606f\u3002"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**\U0001f4a1 \u5efa\u8bae\uff1a**\n"
                        "\u2022 \u68c0\u67e5\u5173\u952e\u8bcd\u662f\u5426\u6b63\u786e\n"
                        "\u2022 \u5c1d\u8bd5\u4f7f\u7528\u4e0d\u540c\u7684\u8868\u8ff0\u65b9\u5f0f\n"
                        "\u2022 \u4e0a\u4f20\u76f8\u5173\u7684\u6587\u6863\u5230\u77e5\u8bc6\u5e93\n"
                        "\u2022 \u4f7f\u7528 `/help` \u67e5\u770b\u66f4\u591a\u547d\u4ee4"
                    ),
                },
            },
        ],
    }

    return card


def build_error_card(error_msg: str) -> dict:
    """
    构建错误展示卡片，包含故障排查建议。
    """
    card = {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "\u26a0\ufe0f \u51fa\u9519\u4e86",
            },
            "template": "red",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"\u5904\u7406\u60a8\u7684\u8bf7\u6c42\u65f6\u53d1\u751f\u4e86\u9519\u8bef\uff1a\n\n`{error_msg}`",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**\U0001f527 \u6392\u67e5\u5efa\u8bae\uff1a**\n"
                        "\u2022 \u7a0d\u540e\u91cd\u8bd5\u4e00\u4e0b\n"
                        "\u2022 \u68c0\u67e5\u77e5\u8bc6\u5e93\u540e\u7aef\u670d\u52a1\u662f\u5426\u6b63\u5e38\u8fd0\u884c\n"
                        "\u2022 \u786e\u8ba4\u7f51\u7edc\u8fde\u63a5\u662f\u5426\u6b63\u5e38\n"
                        "\u2022 \u5982\u679c\u95ee\u9898\u6301\u7eed\uff0c\u8bf7\u8054\u7cfb\u7ba1\u7406\u5458"
                    ),
                },
            },
        ],
    }

    return card
