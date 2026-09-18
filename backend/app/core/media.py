"""头像与知识库封面的受控本地文件服务。

规则（见第一阶段设计）：
- 只接受明确允许的图片 MIME 类型与扩展名，并同时检查文件头。
- 限制文件大小与像素范围，拒绝畸形或超大图片。
- 使用随机文件名，用户输入不参与磁盘路径。
- 文件保存在专用目录，不与原始学习文档混放。
"""

from __future__ import annotations

import io
import os
import re
import secrets
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile
from loguru import logger

from app.config import Settings, settings as global_settings


MEDIA_KINDS = ("avatar", "cover")
_SUBDIRS = {"avatar": "avatars", "cover": "covers"}

# MIME -> (规范扩展名, 文件头签名列表)
ALLOWED_IMAGE_TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/gif": (".gif", (b"GIF87a", b"GIF89a")),
    "image/webp": (".webp", ()),
}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_SAFE_NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")
_GENERIC_MIME = {"application/octet-stream", ""}


@dataclass(frozen=True)
class StoredImage:
    relative_path: str
    url: str
    content_type: str
    size_bytes: int
    width: int
    height: int


def _sniff(data: bytes) -> str | None:
    """按文件头判断真实图片类型；不能只信任客户端 MIME。"""
    for mime, (_extension, signatures) in ALLOWED_IMAGE_TYPES.items():
        if mime == "image/webp":
            if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
                return mime
            continue
        for signature in signatures:
            if data.startswith(signature):
                return mime
    return None


def _measure(data: bytes) -> tuple[int, int]:
    """使用 Pillow 校验图片可解码并返回像素尺寸。"""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow 是运行依赖
        raise HTTPException(503, "图片校验组件不可用") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception as exc:
        raise HTTPException(422, "图片文件已损坏或格式不受支持") from exc


def media_root(kind: str, settings: Settings | None = None) -> str:
    config = settings or global_settings
    if kind not in _SUBDIRS:
        raise ValueError(f"Unknown media kind: {kind}")
    return os.path.join(config.MEDIA_DIR, _SUBDIRS[kind])


async def store_image(
    upload: UploadFile,
    kind: str,
    *,
    settings: Settings | None = None,
) -> StoredImage:
    """校验并写入一张图片，返回受控相对路径。"""
    config = settings or global_settings
    if kind not in _SUBDIRS:
        raise HTTPException(422, "不支持的图片来源类型")

    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared not in ALLOWED_IMAGE_TYPES and declared not in _GENERIC_MIME:
        raise HTTPException(422, f"不支持的图片类型：{declared or '未知'}")
    extension = os.path.splitext(upload.filename or "")[1].lower()
    if extension and extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(422, f"不支持的图片扩展名：{extension}")

    max_bytes = config.IMAGE_MAX_SIZE_MB * 1024 * 1024
    buffer = bytearray()
    while chunk := await upload.read(256 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(413, f"图片超过 {config.IMAGE_MAX_SIZE_MB} MB 上限")
    if not buffer:
        raise HTTPException(422, "图片内容为空")

    data = bytes(buffer)
    sniffed = _sniff(data)
    if sniffed is None:
        raise HTTPException(422, "文件内容不是受支持的图片格式")
    if declared not in _GENERIC_MIME and declared != sniffed:
        raise HTTPException(422, "图片声明类型与文件内容不一致")

    width, height = _measure(data)
    if width < config.IMAGE_MIN_WIDTH or height < config.IMAGE_MIN_HEIGHT:
        raise HTTPException(422, "图片尺寸过小")
    if width * height > config.IMAGE_MAX_PIXELS:
        raise HTTPException(422, "图片像素总量超过上限")

    canonical_extension = ALLOWED_IMAGE_TYPES[sniffed][0]
    filename = f"{uuid.uuid4().hex}{canonical_extension}"
    directory = media_root(kind, config)
    os.makedirs(directory, exist_ok=True)
    final_path = os.path.join(directory, filename)
    temporary_path = f"{final_path}.{secrets.token_hex(4)}.part"
    try:
        with open(temporary_path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, final_path)
    except OSError as exc:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:  # pragma: no cover - 尽力清理
                logger.warning("Could not remove temporary image '{}'", temporary_path)
        logger.error("Failed to store {} image: {}", kind, exc)
        raise HTTPException(500, "图片保存失败") from exc

    relative = f"{_SUBDIRS[kind]}/{filename}"
    return StoredImage(
        relative_path=relative,
        url=media_url(relative, config),
        content_type=sniffed,
        size_bytes=len(data),
        width=width,
        height=height,
    )


def media_url(relative_path: str, settings: Settings | None = None) -> str:
    config = settings or global_settings
    return f"{config.MEDIA_URL_PREFIX.rstrip('/')}/{relative_path.lstrip('/')}"


def resolve_media_path(relative_path: str, settings: Settings | None = None) -> str | None:
    """把受控相对路径解析为磁盘路径；越界或命名不合法时返回 None。"""
    config = settings or global_settings
    if not relative_path or "\\" in relative_path:
        return None
    parts = relative_path.split("/")
    if len(parts) != 2 or parts[0] not in set(_SUBDIRS.values()):
        return None
    if not _SAFE_NAME.match(parts[1]):
        return None
    root = os.path.realpath(os.path.join(config.MEDIA_DIR, parts[0]))
    candidate = os.path.realpath(os.path.join(root, parts[1]))
    if os.path.dirname(candidate) != root:
        return None
    return candidate


def delete_media(relative_path: str | None, settings: Settings | None = None) -> bool:
    """仅清理确认属于本记录且位于受控目录内的本地文件。"""
    if not relative_path:
        return False
    if relative_path.startswith(("http://", "https://")):
        return False
    path = resolve_media_path(relative_path, settings)
    if path is None or not os.path.isfile(path):
        return False
    try:
        os.remove(path)
    except OSError as exc:
        logger.warning("Could not remove media file '{}': {}", path, exc)
        return False
    return True


def validate_external_image_url(value: str, settings: Settings | None = None) -> str:
    """外部图片只保存 URL，且必须是 https 且长度受控。"""
    config = settings or global_settings
    candidate = (value or "").strip()
    if not candidate:
        raise HTTPException(422, "外链地址不能为空")
    if len(candidate) > config.EXTERNAL_IMAGE_URL_MAX_LENGTH:
        raise HTTPException(422, "外链地址过长")
    if not candidate.lower().startswith("https://"):
        raise HTTPException(422, "外链图片必须使用 https")
    if any(character in candidate for character in ('"', "<", ">", " ", "\n", "\r", "\t")):
        raise HTTPException(422, "外链地址包含非法字符")
    return candidate


def is_external_url(value: str | None) -> bool:
    return bool(value) and str(value).lower().startswith(("http://", "https://"))


def public_image_url(kind: str, image_kind: str | None, image_value: str | None) -> str | None:
    """把存储值转换为客户端可直接展示的 URL。"""
    if not image_value:
        return None
    if image_kind == "url" or is_external_url(image_value):
        return image_value
    if image_kind == "upload":
        return media_url(image_value)
    return None
