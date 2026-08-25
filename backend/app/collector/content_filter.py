"""Select the learnable body of parsed documents before chunking and indexing."""

from __future__ import annotations

import re
from typing import Any


_CHINESE_FRONT_EXACT = {
    "封面",
    "扉页",
    "版权页",
    "版权信息",
    "内容提要",
    "出版说明",
    "目录",
    "作译者介绍",
    "作者介绍",
    "译者介绍",
    "关于作者",
    "关于译者",
}

_CHINESE_TERMINAL_EXACT = {
    "致谢",
    "鸣谢",
    "后记",
    "跋",
    "索引",
    "作者简介",
    "译者简介",
    "广告",
    "连接图灵",
    "看完了",
}


def _normalized_heading(value: Any) -> str:
    heading = str(value or "").strip().casefold()
    heading = re.sub(r"[\s\u3000]+", "", heading)
    return heading.strip("-—:：·.．")


def _is_main_body_heading(heading: str) -> bool:
    if not heading:
        return False
    if re.match(r"^第[0-9一二三四五六七八九十百]+[章篇部]", heading):
        return True
    if re.match(r"^\d+(?:[.．]\d+)*(?:[、.．:：]|(?=[a-z\u4e00-\u9fff]))", heading):
        return True
    return bool(re.match(r"^(?:chapter|part)(?:\d+|[ivxlcdm]+|one|two|three|four|five)\b", heading))


def _is_front_matter_heading(heading: str) -> bool:
    if not heading:
        return False
    if heading in _CHINESE_FRONT_EXACT:
        return True
    if heading.endswith("版权声明"):
        return True
    if re.match(r"^(?:译者|作者|推荐|中文版|第[0-9一二三四五六七八九十]+版)?(?:序|序言|前言)$", heading):
        return True
    if "oreillymedia" in heading and heading.endswith("介绍"):
        return True
    return bool(re.match(
        r"^(?:copyright|contents|tableofcontents|preface|foreword|titlepage|abouttheauthor|aboutthetranslator)$",
        heading,
    ))


def _is_terminal_matter_heading(heading: str) -> bool:
    if not heading:
        return False
    if heading in _CHINESE_TERMINAL_EXACT:
        return True
    return bool(re.match(r"^(?:acknowledg(?:e)?ments?|index|colophon)$", heading))


def _is_non_body_heading(heading: str) -> bool:
    return _is_front_matter_heading(heading) or _is_terminal_matter_heading(heading)


def filter_learning_content(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return body chunks while preserving appendices and references.

    A clear numbered chapter near the beginning, or following recognized front
    matter, establishes the body boundary. Without that signal the filter only
    removes explicitly labeled non-body sections and keeps the rest intact.
    """
    if not chunks:
        return []

    headings = [
        _normalized_heading((chunk.get("metadata") or {}).get("heading"))
        for chunk in chunks
    ]
    first_main = next((index for index, heading in enumerate(headings) if _is_main_body_heading(heading)), None)
    start = 0
    if first_main is not None:
        early_limit = max(5, int(len(chunks) * 0.35))
        has_front_before = any(_is_front_matter_heading(heading) for heading in headings[:first_main])
        if first_main <= early_limit or has_front_before:
            start = first_main

    result: list[dict[str, Any]] = []
    skip_section = False
    for chunk, heading in zip(chunks[start:], headings[start:]):
        if heading:
            skip_section = _is_non_body_heading(heading)
        if not skip_section:
            result.append(chunk)
    return result
