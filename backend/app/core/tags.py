"""文档与知识点共用的标签规范化。"""

from typing import Iterable

from app.config import settings


class TagValidationError(ValueError):
    """标签不满足规范化边界。"""


def normalize_tags(values: Iterable[object] | None) -> list[str]:
    """去空白、去空值、按规范化值去重并保留首次出现顺序。

    非字符串值、超长标签或超过数量上限都会抛出 `TagValidationError`，
    由调用方转换为 422 响应，绝不静默丢弃非法输入。
    """
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TagValidationError("标签必须是字符串数组")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise TagValidationError("标签必须是字符串")
        tag = raw.strip()
        if not tag:
            continue
        if len(tag) > settings.TAG_MAX_LENGTH:
            raise TagValidationError(
                f"单个标签长度不能超过 {settings.TAG_MAX_LENGTH} 个字符"
            )
        if tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    if len(normalized) > settings.TAG_MAX_COUNT:
        raise TagValidationError(f"标签数量不能超过 {settings.TAG_MAX_COUNT} 个")
    return normalized
