"""用户偏好的本地持久化（目前是模型提供商与 API Key）。

容器部署过去只把 `/api/settings/llm` 的修改留在内存里，重启就丢；
本地部署更是必须落盘。这里把用户自己配置的内容写到 `<应用主目录>/settings.json`（0600）。

注意：文件按"用户自己的机器"假设设计，Key 以明文存放并收紧文件权限。
若要更强的保护，可把它换成系统凭据库（Windows DPAPI / macOS Keychain）。
"""

from __future__ import annotations

import json
import os
import stat
from typing import Optional

from loguru import logger

from app.config import Settings, settings as global_settings
from app.core.app_paths import ensure_directory


SETTINGS_VERSION = 1

# 提供商 -> Settings 中保存该 Key 的字段
PROVIDER_KEY_FIELDS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
}


def snapshot(config: Settings) -> dict:
    """把当前生效的模型配置整理成可写盘的结构。"""
    return {
        "version": SETTINGS_VERSION,
        "llm": {
            "provider": config.DEFAULT_LLM_PROVIDER,
            "model": config.DEFAULT_LLM_MODEL,
            "base_url": config.OLLAMA_BASE_URL,
        },
        "api_keys": {
            provider: getattr(config, field, None)
            for provider, field in PROVIDER_KEY_FIELDS.items()
        },
        "embedding": {
            "provider": config.DEFAULT_EMBEDDING_PROVIDER,
            "model": config.DEFAULT_EMBEDDING,
        },
    }


def load_raw(path: Optional[str] = None) -> dict:
    """读取持久化配置；文件不存在或损坏时返回空字典并记录告警。"""
    target = path or global_settings.SETTINGS_FILE
    if not os.path.isfile(target):
        return {}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("本地偏好文件无法读取（{}），本次使用默认配置。", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def apply_persisted(config: Settings, payload: Optional[dict] = None) -> bool:
    """把持久化配置应用到运行中的设置对象，返回是否有内容被应用。"""
    data = payload if payload is not None else load_raw(config.SETTINGS_FILE)
    if not data:
        return False

    llm = data.get("llm") or {}
    if isinstance(llm.get("provider"), str) and llm["provider"].strip():
        config.DEFAULT_LLM_PROVIDER = llm["provider"].strip()
    if isinstance(llm.get("model"), str) and llm["model"].strip():
        config.DEFAULT_LLM_MODEL = llm["model"].strip()
    if isinstance(llm.get("base_url"), str) and llm["base_url"].strip():
        config.OLLAMA_BASE_URL = llm["base_url"].strip()

    api_keys = data.get("api_keys") or {}
    if isinstance(api_keys, dict):
        for provider, field in PROVIDER_KEY_FIELDS.items():
            value = api_keys.get(provider)
            if isinstance(value, str) and value.strip():
                setattr(config, field, value.strip())

    embedding = data.get("embedding") or {}
    if isinstance(embedding.get("provider"), str) and embedding["provider"].strip():
        config.DEFAULT_EMBEDDING_PROVIDER = embedding["provider"].strip()
    if isinstance(embedding.get("model"), str) and embedding["model"].strip():
        config.DEFAULT_EMBEDDING = embedding["model"].strip()
    return True


def save(config: Settings, payload: Optional[dict] = None) -> None:
    """写入持久化配置；写入失败只记日志，不影响当前请求。"""
    data = payload if payload is not None else snapshot(config)
    target = config.SETTINGS_FILE
    temporary = f"{target}.tmp"
    try:
        ensure_directory(os.path.dirname(target))
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - 某些文件系统不支持 chmod
            logger.debug("Could not restrict permissions on '{}'", temporary)
        os.replace(temporary, target)
    except OSError as exc:
        logger.warning("本地偏好文件写入失败（{}），本次修改仅在当前进程内生效。", exc)


def has_llm_api_key(config: Settings) -> bool:
    """是否已经配置过可用的模型凭证（本地 Ollama 不需要 Key）。"""
    provider = (config.DEFAULT_LLM_PROVIDER or "").strip().lower()
    if provider == "ollama":
        return True
    field = PROVIDER_KEY_FIELDS.get(provider)
    if field is None:
        return False
    return bool((getattr(config, field, None) or "").strip())
