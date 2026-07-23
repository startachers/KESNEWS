from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.ids import make_id
from backend.app.services.normalization.title import normalized_article_title

# 한 수집 실행에서 보관할 최대 기사 수. 이슈 탐색은 참고용이므로 상한을 둬 저장량을 제한한다.
MAX_POOL_PER_RUN = 2500
# 보고일 기준 이 일수보다 오래된 임시 풀은 정리한다.
RETENTION_DAYS = 14


def replace_for_run(
    connection: sqlite3.Connection,
    *,
    collection_run_id: str,
    report_date: str,
    articles: list[dict[str, Any]],
) -> int:
    """보고일의 기존 임시 풀을 지우고 이번 수집분으로 교체한다. 저장한 행 수를 반환한다.

    같은 보고일을 재수집하면 최신 실행분만 남기고, 오래된 보고일은 함께 정리한다.
    """
    connection.execute(
        "DELETE FROM dropped_article_pool WHERE report_date = ?", (report_date,)
    )
    connection.execute(
        "DELETE FROM dropped_article_pool WHERE report_date < date(?, ?)",
        (report_date, f"-{RETENTION_DAYS} days"),
    )
    created_at = now_iso()
    stored = 0
    for article in articles[:MAX_POOL_PER_RUN]:
        title = str(article.get("title") or "").strip()
        if not title:
            continue
        connection.execute(
            """
            INSERT INTO dropped_article_pool (
                id, collection_run_id, report_date, title, normalized_title,
                url, source, published_at, description, category, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                make_id(),
                collection_run_id,
                report_date,
                title,
                normalized_article_title(title),
                article.get("url"),
                article.get("source"),
                article.get("pubDate"),
                article.get("description"),
                article.get("category"),
                created_at,
            ),
        )
        stored += 1
    return stored


def list_for_report_date(
    connection: sqlite3.Connection, report_date: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, title, normalized_title, url, source, published_at, description, category
        FROM dropped_article_pool
        WHERE report_date = ?
        ORDER BY created_at, id
        """,
        (report_date,),
    ).fetchall()
    return [dict(row) for row in rows]
