"""Snapshot-keyed AI learning suggestions that never obscure deterministic reports."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import ReportSuggestion
from app.services import report_service
from app.services.assessment_ai import _provider


class ReportAIError(RuntimeError):
    """The suggestion provider failed; the deterministic report remains available."""


def _view(row: ReportSuggestion) -> dict:
    return {
        "id": row.id, "status": row.status, "suggestion": row.suggestion,
        "model": row.model, "error_message": row.error_message,
        "stats_hash": row.stats_hash,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


def canonical_snapshot(report: dict) -> dict:
    return {
        "period": report["period"],
        "metrics": {key: value["value"] for key, value in report["metrics"].items()},
        "comparisons": report["comparisons"],
        "pending_grading_count": report["pending_grading_count"],
    }


def snapshot_hash(snapshot: dict) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _prompt(snapshot: dict) -> str:
    return (
        "你是学习教练。请根据以下学习报告统计，给出三条简洁、具体、可执行的中文建议。"
        "不要编造未提供的学习事实，不要使用 Markdown 表格。\n"
        + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    )


async def _default_completion(settings, prompt: str) -> tuple[str, str]:
    import litellm

    model, api_key, api_base = _provider(settings)
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 600,
        "api_key": api_key,
        "timeout": 60,
    }
    if api_base:
        kwargs["api_base"] = api_base
    response = litellm.acompletion(**kwargs)
    if inspect.isawaitable(response):
        response = await response
    content = response.choices[0].message.content
    return content, model


async def generate_suggestion(
    db: AsyncSession,
    settings,
    period_type: str,
    anchor_date: date,
    *,
    completion=None,
) -> dict:
    now = datetime.now(timezone.utc)
    report = await report_service.build_report(db, period_type, anchor_date, now=now)
    snapshot = canonical_snapshot(report)
    digest = snapshot_hash(snapshot)
    period_start = datetime.fromisoformat(report["period"]["utc_start"])
    row = await db.scalar(select(ReportSuggestion).where(
        ReportSuggestion.period_type == period_type,
        ReportSuggestion.period_start == period_start,
        ReportSuggestion.timezone_name == report["period"]["timezone_name"],
        ReportSuggestion.stats_hash == digest,
    ))
    if row is not None and row.status == "ready":
        return _view(row)
    owns_generation = False
    if row is None:
        values = dict(
            period_type=period_type,
            period_start=period_start,
            period_end=datetime.fromisoformat(report["period"]["utc_end"]),
            timezone_name=report["period"]["timezone_name"],
            stats_hash=digest,
            stats_snapshot=snapshot,
            status="pending",
        )
        if db.bind and db.bind.dialect.name in {"sqlite", "postgresql"}:
            if db.bind.dialect.name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                from sqlalchemy.dialects.postgresql import insert
            inserted = await db.execute(insert(ReportSuggestion).values(**values).on_conflict_do_nothing())
            owns_generation = inserted.rowcount == 1
            row = await db.scalar(select(ReportSuggestion).where(
                ReportSuggestion.period_type == period_type,
                ReportSuggestion.period_start == period_start,
                ReportSuggestion.timezone_name == report["period"]["timezone_name"],
                ReportSuggestion.stats_hash == digest,
            ))
        else:
            row = ReportSuggestion(**values)
            db.add(row)
            owns_generation = True
    else:
        claimed = await db.execute(update(ReportSuggestion).where(
            ReportSuggestion.id == row.id,
            or_(
                ReportSuggestion.status == "failed",
                (ReportSuggestion.status == "pending")
                & (ReportSuggestion.updated_at < now - timedelta(minutes=2)),
            ),
        ).values(status="pending", error_message=None, updated_at=now))
        owns_generation = claimed.rowcount == 1
        await db.refresh(row)
    if not owns_generation:
        return _view(row)
    # This endpoint is the transaction boundary: persist the in-flight state before
    # making a slow provider call so a process interruption remains observable.
    await db.commit()
    try:
        response = completion(_prompt(snapshot)) if completion else _default_completion(settings, _prompt(snapshot))
        if inspect.isawaitable(response):
            response = await response
        text, model = response
        if not isinstance(text, str) or not text.strip():
            raise ValueError("provider returned an empty suggestion")
        row.suggestion = text.strip()[:1200]
        row.model = model
        row.status = "ready"
        row.generated_at = now
        row.error_message = None
        await db.commit()
        return _view(row)
    except Exception as exc:
        row.status = "failed"
        row.error_message = str(exc)[:1000]
        row.generated_at = None
        await db.commit()
        raise ReportAIError(str(exc)) from exc


async def get_cached_suggestion(db: AsyncSession, report: dict) -> dict | None:
    snapshot = canonical_snapshot(report)
    row = await db.scalar(select(ReportSuggestion).where(
        ReportSuggestion.period_type == report["period"]["type"],
        ReportSuggestion.period_start == datetime.fromisoformat(report["period"]["utc_start"]),
        ReportSuggestion.timezone_name == report["period"]["timezone_name"],
        ReportSuggestion.stats_hash == snapshot_hash(snapshot),
    ))
    return _view(row) if row else None
