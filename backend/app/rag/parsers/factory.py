"""ParserFactory：扩展名 → 解析器的唯一注册表，也是上传白名单的唯一来源。

设计约束（设计文档 §6.1）：

1. 注册表取代 `if/elif` 链，新增解析器不改工厂代码；
2. `supported_types()` 同时供上传白名单与解析路由使用，杜绝「上传成功但解析必然失败」；
3. 解析器实例无状态，按类型缓存复用。
"""

from __future__ import annotations

import importlib
from pathlib import Path

from loguru import logger

from app.collector.parsers.base import BaseParser
from app.rag.contracts import Document
from app.rag.parsers.adapters import parse_with_parser

# 扩展名 → 规范类型；`rst` 复用 Markdown 的宽松模式，纯文本族归入 txt。
_FILE_TYPE_ALIASES: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "pptx": "pptx",
    "md": "md",
    "markdown": "md",
    "rst": "md",
    "txt": "txt",
    "json": "txt",
    "xml": "txt",
    "yaml": "txt",
    "yml": "txt",
    "xlsx": "xlsx",
    "csv": "csv",
    "html": "html",
    "htm": "html",
}

# 规范类型 → 解析器实现（模块路径 + 类名，按需导入避免循环依赖）。
_PARSER_TARGETS: dict[str, str] = {
    "pdf": "app.collector.parsers.pdf_parser:PDFParser",
    "docx": "app.collector.parsers.docx_parser:DocxParser",
    "pptx": "app.collector.parsers.pptx_parser:PptxParser",
    "md": "app.collector.parsers.markdown_parser:MarkdownParser",
    "txt": "app.collector.pipeline:_TxtParser",
    "xlsx": "app.collector.pipeline:_XlsxParser",
    "csv": "app.collector.pipeline:_CsvParser",
    "html": "app.collector.pipeline:_HtmlParser",
}


def detect_signature(file_path: str) -> str:
    """按文件头判定真实类型：pdf / zip(office) / text / binary / missing。"""
    path = Path(file_path)
    if not path.is_file():
        return "missing"
    try:
        head = path.open("rb").read(8)
    except OSError:
        return "binary"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if not head:
        return "text"
    if b"\x00" in head:
        return "binary"
    return "text"


# 扩展名 → 可接受的文件头；「上传成功但解析必然失败」的组合在这里被拦住。
_SIGNATURE_RULES: dict[str, frozenset[str]] = {
    "pdf": frozenset({"pdf"}),
    "docx": frozenset({"zip"}),
    "pptx": frozenset({"zip"}),
    "xlsx": frozenset({"zip"}),
    "md": frozenset({"text"}),
    "txt": frozenset({"text"}),
    "csv": frozenset({"text"}),
    "html": frozenset({"text"}),
}


def validate_signature(file_type: str, signature: str) -> None:
    """文件头与扩展名不一致时给出可操作错误，而不是解析出空内容。"""
    allowed = _SIGNATURE_RULES.get(file_type)
    if not allowed or not signature or signature == "missing":
        return
    if signature not in allowed:
        raise ValueError(
            f"文件头与扩展名不一致：扩展名 .{file_type}，实际文件签名 {signature}。"
            "请确认文件没有损坏或被改名。"
        )


class ParserFactory:
    """解析器注册表。"""

    _registry: dict[str, str | type[BaseParser]] = {}
    _instances: dict[str, BaseParser] = {}

    # ---------------------------------------------------------------- #
    # 注册与查询
    # ---------------------------------------------------------------- #

    @classmethod
    def register(cls, file_type: str, target: str | type[BaseParser]) -> None:
        """注册一个规范类型；`target` 可以是解析器类，也可以是 "module:Class"。"""
        canonical = _FILE_TYPE_ALIASES.get(file_type.lower().strip().lstrip("."), file_type)
        cls._registry[canonical] = target
        cls._instances.pop(canonical, None)

    @classmethod
    def _ensure_registered(cls) -> None:
        if cls._registry:
            return
        for canonical, target in _PARSER_TARGETS.items():
            cls._registry[canonical] = target

    @classmethod
    def canonical_type(cls, file_type: str) -> str | None:
        if not file_type:
            return None
        normalized = file_type.lower().strip().lstrip(".")
        return _FILE_TYPE_ALIASES.get(normalized)

    @classmethod
    def supported_types(cls) -> set[str]:
        """上传白名单：所有可解析的扩展名（含别名）。"""
        return set(_FILE_TYPE_ALIASES)

    @classmethod
    def file_type_aliases(cls) -> dict[str, str]:
        """扩展名 → 规范类型；供旧的 `_FILE_TYPE_MAP` 复用同一份真相。"""
        return dict(_FILE_TYPE_ALIASES)

    @classmethod
    def canonical_types(cls) -> set[str]:
        return set(_PARSER_TARGETS)

    @classmethod
    def get_parser(cls, file_type: str) -> BaseParser:
        canonical = cls.canonical_type(file_type)
        if canonical is None:
            raise ValueError(
                f"Unsupported file type: '{file_type}'. "
                f"Supported types: {', '.join(sorted(cls.supported_types()))}"
            )
        cls._ensure_registered()
        cached = cls._instances.get(canonical)
        if cached is not None:
            return cached
        target = cls._registry[canonical]
        if isinstance(target, str):
            module_name, _, class_name = target.partition(":")
            module = importlib.import_module(module_name)
            parser_cls = getattr(module, class_name)
        else:
            parser_cls = target
        parser = parser_cls()
        cls._instances[canonical] = parser
        return parser

    @classmethod
    def reset(cls) -> None:
        """清空缓存，供测试与配置变更后重建。"""
        cls._instances.clear()
        cls._registry.clear()

    # ---------------------------------------------------------------- #
    # 统一入口
    # ---------------------------------------------------------------- #

    @classmethod
    def parse_document(
        cls,
        file_path: str,
        *,
        document_id: str,
        workspace_id: str,
        file_type: str,
        filename: str | None = None,
    ) -> Document:
        """解析文件并返回统一 `Document`（Block[] + 质量标记）。"""
        canonical = cls.canonical_type(file_type) or file_type
        parser = cls.get_parser(canonical)
        signature = detect_signature(file_path)
        validate_signature(canonical, signature)
        return parse_with_parser(
            parser,
            file_path,
            document_id=document_id,
            workspace_id=workspace_id,
            filename=filename or Path(file_path).name,
            file_type=canonical,
            signature=signature,
        )


def supported_file_types() -> set[str]:
    """兼容旧调用方：上传白名单仍来自解析器注册表。"""
    return ParserFactory.supported_types()
