"""无第三方依赖的密码哈希与签名会话令牌。

令牌的 `sub` 保存用户 ID。仅验证签名和有效期不足以授权，
认证依赖必须随后从数据库加载有效用户。
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.config import settings


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ROUNDS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ROUNDS)
    return (
        f"{PASSWORD_ALGORITHM}${PASSWORD_ROUNDS}"
        f"${base64.urlsafe_b64encode(salt).decode()}"
        f"${base64.urlsafe_b64encode(derived).decode()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    """常量时间校验密码；任何解析失败都视为校验失败。"""
    if not password or not encoded:
        return False
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    candidate = base64.urlsafe_b64encode(derived).decode()
    return hmac.compare_digest(candidate, expected)


def create_token(subject: str) -> str:
    payload = {"sub": subject, "exp": int(time.time()) + settings.SESSION_DAYS * 86400}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def decode_token(token: str) -> dict[str, Any] | None:
    """校验签名与有效期并返回声明；失败返回 None。"""
    try:
        body, signature = token.split(".", 1)
        expected = base64.urlsafe_b64encode(hmac.new(settings.JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        if not payload.get("sub"):
            return None
        return payload
    except (ValueError, TypeError, KeyError):
        return None


def verify_token(token: str) -> bool:
    """兼容旧调用点：仅表示签名与有效期是否有效。"""
    return decode_token(token) is not None
