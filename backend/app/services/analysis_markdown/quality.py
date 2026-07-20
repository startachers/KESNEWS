from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.ids import make_id


def record_event(connection: sqlite3.Connection, article: dict, extraction: dict) -> None:
    existing = connection.execute(
        """SELECT 1 FROM publisher_extraction_events
           WHERE article_id = ? AND extraction_status = ?
             AND analysis_eligible = ? AND COALESCE(failure_reason, '') = ?
             AND cleaning_rule_version = ?
           LIMIT 1""",
        (
            article["id"], extraction["status"], int(extraction["analysisEligible"]),
            extraction.get("failureReason") or "", extraction["cleaningRuleVersion"],
        ),
    ).fetchone()
    if existing:
        return
    connection.execute(
        """INSERT INTO publisher_extraction_events (
               id, article_id, publisher_id, publisher_name, extraction_status,
               analysis_eligible, noise_detected, ai_content_detected, access_blocked,
               failure_reason, attempted_at, cleaning_rule_version
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            make_id(), article["id"], article.get("publisherId"), article.get("source"),
            extraction["status"], int(extraction["analysisEligible"]),
            int(extraction.get("noiseDetected", False)),
            int(extraction.get("aiContentDetected", False)),
            int(extraction.get("failureReason") == "access_blocked"),
            extraction.get("failureReason") or None, now_iso(), extraction["cleaningRuleVersion"],
        ),
    )


def publisher_statistics(connection: sqlite3.Connection, config: dict) -> list[dict[str, Any]]:
    window = int(config["publisher_quality"]["evaluation_window"])
    rows = connection.execute(
        """SELECT * FROM publisher_extraction_events
           WHERE cleaning_rule_version = ?
           ORDER BY COALESCE(publisher_id, publisher_name), attempted_at DESC""",
        (config["cleaning_rule_version"],),
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        key = row["publisher_id"] or row["publisher_name"] or "unknown"
        if len(grouped.setdefault(key, [])) < window:
            grouped[key].append(row)
    disabled = set(config.get("disabled_publishers") or [])
    quality = config["publisher_quality"]
    result = []
    for publisher, events in sorted(grouped.items()):
        attempts = len(events)
        full = sum(row["extraction_status"] == "success_full" for row in events)
        summaries = sum(row["extraction_status"] == "success_summary" for row in events)
        eligible = sum(bool(row["analysis_eligible"]) for row in events)
        failed = sum(row["extraction_status"] == "failed" for row in events)
        eligible_rate = eligible / attempts if attempts else 0.0
        if publisher in disabled:
            status = "disabled"
        elif attempts >= int(quality["minimum_attempts_for_quarantine"]) and eligible_rate < float(quality["quarantine_success_rate"]):
            status = "quarantine"
        elif attempts < int(quality["minimum_attempts_for_quarantine"]) or eligible_rate < float(quality["warning_success_rate"]):
            status = "warning"
        else:
            status = "active"
        result.append({
            "publisherId": publisher,
            "publisherName": events[0]["publisher_name"],
            "attempts": attempts,
            "fullSuccesses": full,
            "summarySuccesses": summaries,
            "failures": failed,
            "fullSuccessRate": full / attempts if attempts else 0.0,
            "eligibleSuccessRate": eligible_rate,
            "noiseDetectionRate": sum(bool(row["noise_detected"]) for row in events) / attempts,
            "aiContentRate": sum(bool(row["ai_content_detected"]) for row in events) / attempts,
            "accessBlockedRate": sum(bool(row["access_blocked"]) for row in events) / attempts,
            "lastSuccessAt": next((row["attempted_at"] for row in events if row["analysis_eligible"]), None),
            "lastFailureReason": next((row["failure_reason"] for row in events if row["failure_reason"]), None),
            "status": status,
        })
    return result
