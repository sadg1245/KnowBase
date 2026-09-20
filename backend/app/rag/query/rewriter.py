"""Query Rewrite：默认关闭；开启时只做确定性扩展，不引入额外模型调用。"""

from __future__ import annotations

from app.rag.query.analyzer import QueryAnalysis


def rewrite_queries(analysis: QueryAnalysis, *, enabled: bool = False, limit: int = 3) -> list[str]:
    """返回要检索的查询列表；`enabled=False` 时只有原查询。"""
    queries = [analysis.query]
    if not enabled or not analysis.query:
        return queries
    for entity in analysis.entities[: limit - 1]:
        candidate = entity.strip()
        if candidate and candidate not in queries:
            queries.append(candidate)
    return queries[:limit]

