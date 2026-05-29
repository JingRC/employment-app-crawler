from __future__ import annotations

from typing import Any

from app.core.company_normalizer import build_job_dedup_key
from app.core.database import get_connection


def compute_cross_source_dedup_key(
    source_code: str,
    company_name: str,
    title: str,
    city_name: str,
) -> str:
    return build_job_dedup_key(source_code, company_name, title, city_name)


def check_cross_source_exists(
    source_code: str,
    company_name: str,
    title: str,
    city_name: str,
    *,
    exclude_job_id: int | None = None,
) -> dict[str, Any] | None:
    key = compute_cross_source_dedup_key(source_code, company_name, title, city_name)
    with get_connection() as conn:
        cond = "cross_source_dedup_key = ? AND source_code != ? AND status = 'active'"
        params: list[Any] = [key, source_code]
        if exclude_job_id is not None:
            cond += " AND id != ?"
            params.append(exclude_job_id)
        row = conn.execute(
            f"SELECT id, company_name, title, city_name, source_code, source_url FROM jobs WHERE {cond} LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["id"],
            "company_name": row["company_name"],
            "title": row["title"],
            "city_name": row["city_name"],
            "source_code": row["source_code"],
            "source_url": row["source_url"],
            "dedup_key": key,
        }


def backfill_cross_source_dedup_keys(batch_size: int = 500) -> dict[str, int]:
    from app.core.job_sources import get_source_name

    updated = 0
    skipped = 0
    errors = 0

    with get_connection() as conn:
        while True:
            rows = conn.execute(
                "SELECT id, source_code, company_name, title, city_name FROM jobs WHERE cross_source_dedup_key IS NULL OR cross_source_dedup_key = '' LIMIT ?",
                (batch_size,),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                try:
                    key = compute_cross_source_dedup_key(
                        str(row["source_code"] or ""),
                        str(row["company_name"] or ""),
                        str(row["title"] or ""),
                        str(row["city_name"] or ""),
                    )
                    conn.execute(
                        "UPDATE jobs SET cross_source_dedup_key = ? WHERE id = ?",
                        (key, row["id"]),
                    )
                    updated += 1
                except Exception:
                    errors += 1
            conn.commit()

    return {"updated": updated, "skipped": skipped, "errors": errors}
