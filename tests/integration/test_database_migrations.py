import sqlite3
from pathlib import Path

from backend.app.db.migrator import apply_migrations, pending_migrations
from backend.app.repositories.database import get_connection, init_db

EXPECTED_TABLES = {
    "schema_migrations",
    "articles",
    "article_observations",
    "article_assessments",
    "briefings",
    "briefing_versions",
    "briefing_articles",
    "collection_runs",
    "collection_run_providers",
    "issues",
    "issue_auto_articles",
    "issue_membership_overrides",
    "cluster_runs",
    "briefing_issues",
    "settings",
    "ai_runs",
    "kesco_press_releases",
    "article_origin_assessments",
    "issue_review_assessments",
    "briefing_report_drafts",
    "ai_selection_runs",
    "weather_collection_runs",
    "weather_run_providers",
    "weather_observations",
    "weather_contexts",
    "weather_risk_signals",
    "briefing_weather",
    "briefing_weather_signals",
    "article_extractions",
    "publisher_extraction_events",
    "briefing_analysis_markdown",
}

EXPECTED_MIGRATIONS = [
    "0001_initial.sql",
    "0002_article_assessment_phase5.sql",
    "0003_issue_clustering_phase6.sql",
    "0004_ai_analysis_phase7.sql",
    "0005_article_body_extraction.sql",
    "0006_article_top_issue_tag.sql",
    "0007_manual_issue_group.sql",
    "0008_query_groups_17.sql",
    "0009_trusted_media.sql",
    "0010_provider_item_key_index.sql",
    "0011_kesco_press_origin.sql",
    "0012_issue_review_priority.sql",
    "0013_briefing_report_draft.sql",
    "0014_ai_article_selection.sql",
    "0015_incident_cause_axes.sql",
    "0016_promote_grouped_article_top_tags.sql",
    "0017_repair_post_deploy_grouped_top_tags.sql",
    "0018_issue_direct_coverage_override.sql",
    "0019_article_direct_coverage_override.sql",
    "0020_top_issue_implies_briefing_selection.sql",
    "0021_weather_briefing.sql",
    "0022_rules_v12_category_reclassification.sql",
    "0023_analysis_markdown_pipeline.sql",
    "0024_publisher_quality_rule_version.sql",
    "0025_analysis_markdown_manifest.sql",
    "0026_issue_evidence_quality.sql",
    "0027_selected_evidence_validation.sql",
]


def test_ai_article_selection_migration_separates_proposal_from_selection(tmp_path):
    connection = get_connection(tmp_path / "ai-selection.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_selection_runs)")}
        assert {
            "briefing_id", "model", "input_signature", "status", "request_json",
            "response_json", "evidence_json", "error_message", "applied_at",
        }.issubset(columns)
    finally:
        connection.close()


def test_review_priority_migration_adds_report_date_relative_issue_assessment(tmp_path):
    connection = get_connection(tmp_path / "review-priority.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(issue_review_assessments)")}
        assert {"briefing_id", "issue_id", "auto_score", "auto_rank", "auto_stars", "editor_stars", "editor_reason", "reasons_json", "scoring_version"}.issubset(columns)
    finally:
        connection.close()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_apply_migrations_creates_expected_tables(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    try:
        applied = apply_migrations(connection)
        assert applied == EXPECTED_MIGRATIONS
        assert EXPECTED_TABLES.issubset(_table_names(connection))
        issue_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(briefing_issues)")
        }
        assert "direct_coverage_override" in issue_columns
        article_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(briefing_articles)")
        }
        assert "direct_coverage_override" in article_columns
        assert pending_migrations(connection) == []
    finally:
        connection.close()


def test_apply_migrations_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    try:
        first = apply_migrations(connection)
        second = apply_migrations(connection)
        assert first == EXPECTED_MIGRATIONS
        assert second == []
        assert EXPECTED_TABLES.issubset(_table_names(connection))
    finally:
        connection.close()


def test_phase5_migration_adds_full_assessment_columns(tmp_path):
    connection = get_connection(tmp_path / "phase5.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(article_assessments)")}
        assert {
            "auto_event_type",
            "auto_relevance_score",
            "auto_severity_score",
            "auto_priority_score",
            "auto_priority",
            "auto_tone",
            "final_category",
            "final_event_type",
            "final_priority",
            "final_tone",
            "manual_override",
        }.issubset(columns)
    finally:
        connection.close()


def test_phase6_migration_adds_issue_override_and_proposal_columns(tmp_path):
    connection = get_connection(tmp_path / "phase6.db")
    try:
        apply_migrations(connection)
        issue_columns = {row[1] for row in connection.execute("PRAGMA table_info(issues)")}
        cluster_columns = {row[1] for row in connection.execute("PRAGMA table_info(cluster_runs)")}
        assert {
            "auto_title", "editor_title", "auto_status", "editor_status",
            "auto_priority", "editor_priority", "spread_score", "needs_review",
            "last_cluster_run_id",
        }.issubset(issue_columns)
        assert {"status", "input_signature", "proposal_json", "diff_json", "applied_at"}.issubset(
            cluster_columns
        )
    finally:
        connection.close()


def test_phase7_migration_adds_ai_run_evidence_and_error_columns(tmp_path):
    connection = get_connection(tmp_path / "phase7.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_runs)")}
        assert {
            "briefing_id", "model", "prompt_version", "input_signature", "status",
            "request_json", "response_json", "evidence_json", "error_message",
            "started_at", "finished_at",
        }.issubset(columns)
    finally:
        connection.close()


def test_article_body_migration_adds_text_status_and_failure_detail(tmp_path):
    connection = get_connection(tmp_path / "body.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(articles)")}
        assert {"body_text", "body_status", "body_fetched_at", "body_error"}.issubset(columns)
    finally:
        connection.close()


def test_article_top_issue_migration_adds_independent_tag(tmp_path):
    connection = get_connection(tmp_path / "top-issue.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(briefing_articles)")}
        assert "top_issue" in columns
    finally:
        connection.close()


def test_post_deploy_grouped_article_top_tag_repair_promotes_tag_to_issue(tmp_path):
    connection = get_connection(tmp_path / "grouped-top-issue.db")
    try:
        apply_migrations(connection)
        now = "2026-07-17T00:00:00Z"
        connection.execute(
            """
            INSERT INTO articles (
                id, content_key, title, first_observed_at, last_observed_at,
                created_at, updated_at
            ) VALUES ('article-1', 'content-1', '군집 기사', ?, ?, ?, ?)
            """,
            (now, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO briefings (id, report_date, created_at, updated_at)
            VALUES ('briefing-1', '2026-07-17', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO cluster_runs (
                id, report_date, status, input_signature, proposal_json, diff_json,
                algorithm_version, created_at, applied_at
            ) VALUES ('run-1', '2026-07-17', 'applied', 'sig', '[]', '{}', 'test', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO issues (
                id, representative_article_id, auto_title, spread_score,
                direct_mention, needs_review, last_cluster_run_id, created_at, updated_at
            ) VALUES ('issue-1', 'article-1', '군집', 0, 0, 0, 'run-1', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO issue_auto_articles (
                issue_id, article_id, cluster_run_id, created_at
            ) VALUES ('issue-1', 'article-1', 'run-1', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO briefing_articles (
                briefing_id, article_id, top_issue, created_at, updated_at
            ) VALUES ('briefing-1', 'article-1', 1, ?, ?)
            """,
            (now, now),
        )

        migration = Path(
            "backend/app/db/migrations/0017_repair_post_deploy_grouped_top_tags.sql"
        ).read_text(encoding="utf-8")
        connection.executescript(migration)

        article_top = connection.execute(
            "SELECT top_issue FROM briefing_articles WHERE briefing_id = 'briefing-1'"
        ).fetchone()[0]
        issue_top = connection.execute(
            "SELECT selected FROM briefing_issues WHERE briefing_id = 'briefing-1'"
        ).fetchone()[0]
        assert article_top == 0
        assert issue_top == 1
    finally:
        connection.close()


def test_manual_issue_group_migration_marks_manual_groups(tmp_path):
    connection = get_connection(tmp_path / "manual-group.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(issues)")}
        assert "manual_group" in columns
    finally:
        connection.close()


def test_direct_coverage_migration_deselects_existing_briefing_and_top_tags(tmp_path):
    connection = get_connection(tmp_path / "direct-coverage.db")
    try:
        apply_migrations(connection)
        now = "2026-07-17T00:00:00Z"
        connection.execute(
            """
            INSERT INTO articles (
                id, content_key, title, first_observed_at, last_observed_at,
                created_at, updated_at
            ) VALUES ('direct-article', 'direct-content', '공사 직접 보도', ?, ?, ?, ?)
            """,
            (now, now, now, now),
        )
        connection.execute(
            "INSERT INTO briefings (id, report_date, created_at, updated_at) "
            "VALUES ('direct-briefing', '2026-07-17', ?, ?)",
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO cluster_runs (
                id, report_date, status, input_signature, proposal_json, diff_json,
                algorithm_version, created_at, applied_at
            ) VALUES ('direct-run', '2026-07-17', 'applied', 'sig', '[]', '{}',
                      'test', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO issues (
                id, representative_article_id, auto_title, spread_score,
                direct_mention, needs_review, last_cluster_run_id, created_at, updated_at
            ) VALUES ('direct-issue', 'direct-article', '공사 직접 보도', 0, 1, 0,
                      'direct-run', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            "INSERT INTO issue_auto_articles "
            "(issue_id, article_id, cluster_run_id, created_at) "
            "VALUES ('direct-issue', 'direct-article', 'direct-run', ?)",
            (now,),
        )
        connection.execute(
            """
            INSERT INTO briefing_articles (
                briefing_id, article_id, selected, top_issue, created_at, updated_at
            ) VALUES ('direct-briefing', 'direct-article', 1, 1, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO briefing_issues (
                briefing_id, issue_id, selected, created_at, updated_at
            ) VALUES ('direct-briefing', 'direct-issue', 1, ?, ?)
            """,
            (now, now),
        )

        migration = Path(
            "backend/app/db/migrations/0018_issue_direct_coverage_override.sql"
        ).read_text(encoding="utf-8")
        repair_sql = migration.split(";", 1)[1]
        connection.executescript(repair_sql)

        article = connection.execute(
            "SELECT selected, top_issue FROM briefing_articles "
            "WHERE briefing_id = 'direct-briefing' AND article_id = 'direct-article'"
        ).fetchone()
        issue = connection.execute(
            "SELECT selected FROM briefing_issues "
            "WHERE briefing_id = 'direct-briefing' AND issue_id = 'direct-issue'"
        ).fetchone()
        assert (article["selected"], article["top_issue"]) == (0, 0)
        assert issue["selected"] == 0
    finally:
        connection.close()


def test_standalone_direct_coverage_migration_deselects_existing_article(tmp_path):
    connection = get_connection(tmp_path / "standalone-direct-coverage.db")
    try:
        apply_migrations(connection)
        now = "2026-07-17T00:00:00Z"
        connection.execute(
            """
            INSERT INTO articles (
                id, content_key, title, category_hint, first_observed_at,
                last_observed_at, created_at, updated_at
            ) VALUES ('standalone-direct', 'standalone-content', '공사 직접 보도',
                      'kesco_direct', ?, ?, ?, ?)
            """,
            (now, now, now, now),
        )
        connection.execute(
            "INSERT INTO briefings (id, report_date, created_at, updated_at) "
            "VALUES ('standalone-briefing', '2026-07-17', ?, ?)",
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO briefing_articles (
                briefing_id, article_id, selected, top_issue, created_at, updated_at
            ) VALUES ('standalone-briefing', 'standalone-direct', 1, 1, ?, ?)
            """,
            (now, now),
        )

        migration = Path(
            "backend/app/db/migrations/0019_article_direct_coverage_override.sql"
        ).read_text(encoding="utf-8")
        repair_sql = migration.split(";", 1)[1]
        connection.executescript(repair_sql)

        article = connection.execute(
            "SELECT selected, top_issue FROM briefing_articles "
            "WHERE briefing_id = 'standalone-briefing' AND article_id = 'standalone-direct'"
        ).fetchone()
        assert (article["selected"], article["top_issue"]) == (0, 0)
    finally:
        connection.close()


def test_top_issue_migration_selects_existing_issue_representative(tmp_path):
    connection = get_connection(tmp_path / "top-implies-selection.db")
    try:
        apply_migrations(connection)
        now = "2026-07-17T00:00:00Z"
        connection.execute(
            """
            INSERT INTO articles (
                id, content_key, title, first_observed_at, last_observed_at,
                created_at, updated_at
            ) VALUES ('top-representative', 'top-representative-content', 'Top 대표 기사',
                      ?, ?, ?, ?)
            """,
            (now, now, now, now),
        )
        connection.execute(
            "INSERT INTO briefings (id, report_date, created_at, updated_at) "
            "VALUES ('top-briefing', '2026-07-17', ?, ?)",
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO issues (
                id, representative_article_id, auto_title, spread_score,
                direct_mention, needs_review, created_at, updated_at
            ) VALUES ('top-issue', 'top-representative', 'Top 이슈', 0, 0, 0, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO briefing_issues (
                briefing_id, issue_id, selected, created_at, updated_at
            ) VALUES ('top-briefing', 'top-issue', 1, ?, ?)
            """,
            (now, now),
        )

        migration = Path(
            "backend/app/db/migrations/0020_top_issue_implies_briefing_selection.sql"
        ).read_text(encoding="utf-8")
        connection.executescript(migration)

        article = connection.execute(
            "SELECT selected, dismissed FROM briefing_articles "
            "WHERE briefing_id = 'top-briefing' AND article_id = 'top-representative'"
        ).fetchone()
        assert (article["selected"], article["dismissed"]) == (1, 0)
    finally:
        connection.close()


def test_query_groups_and_trusted_media_migrations_keep_columns_separate(tmp_path):
    connection = get_connection(tmp_path / "incident.db")
    try:
        apply_migrations(connection)
        assessment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(article_assessments)")
        }
        article_columns = {row[1] for row in connection.execute("PRAGMA table_info(articles)")}
        assert "incident_json" in assessment_columns
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(collection_runs)")}
        assert {"publisher_id", "publisher_allowed"}.issubset(article_columns)
        assert "source_filter_stats_json" in run_columns
    finally:
        connection.close()


def test_kesco_press_origin_migration_keeps_source_lineage_separate(tmp_path):
    connection = get_connection(tmp_path / "kesco-press.db")
    try:
        apply_migrations(connection)
        release_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(kesco_press_releases)")
        }
        origin_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(article_origin_assessments)")
        }
        assert {"bbs_seq", "title", "published_at", "body_text", "canonical_url"}.issubset(
            release_columns
        )
        assert {
            "article_id",
            "auto_origin_type",
            "auto_press_release_id",
            "auto_confidence",
            "final_origin_type",
            "manual_override",
        }.issubset(origin_columns)
    finally:
        connection.close()


def test_selected_evidence_validation_migration_preserves_source_lineage(tmp_path):
    connection = get_connection(tmp_path / "selected-evidence.db")
    try:
        apply_migrations(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(article_extractions)")}
        assert {
            "canonical_url", "page_publisher", "source_domain", "raw_source",
            "normalized_source", "normalization_reason", "validation_errors_json",
        }.issubset(columns)
    finally:
        connection.close()


def test_init_db_backfills_phase4_assessment(tmp_path):
    db_path = tmp_path / "upgrade.db"
    connection = get_connection(db_path)
    try:
        initial_sql = (Path(__file__).parents[2] / "backend/app/db/migrations/0001_initial.sql").read_text(
            encoding="utf-8"
        )
        connection.executescript(initial_sql)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES ('0001_initial.sql', '2026-01-01T00:00:00Z')"
        )
        article_values = (
            "legacy-1", "key-1", "한국전기안전공사 전기화재 예방 점검", "", 0,
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        )
        connection.execute(
            """
            INSERT INTO articles (
                id, content_key, title, description, manual,
                first_observed_at, last_observed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*article_values, "2026-01-01T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO article_assessments (
                article_id, auto_category, auto_risk, auto_risk_score,
                auto_sentiment, auto_reasons_json, classifier_version, updated_at
            ) VALUES ('legacy-1', 'safety', 'watch', 4, 'negative', '[]',
                      'phase3-rules-v1', '2026-01-01T00:00:00Z')
            """
        )
        connection.commit()
    finally:
        connection.close()

    assert init_db(db_path) == [
        "0002_article_assessment_phase5.sql",
        "0003_issue_clustering_phase6.sql",
        "0004_ai_analysis_phase7.sql",
        "0005_article_body_extraction.sql",
        "0006_article_top_issue_tag.sql",
        "0007_manual_issue_group.sql",
        "0008_query_groups_17.sql",
        "0009_trusted_media.sql",
        "0010_provider_item_key_index.sql",
        "0011_kesco_press_origin.sql",
        "0012_issue_review_priority.sql",
        "0013_briefing_report_draft.sql",
        "0014_ai_article_selection.sql",
        "0015_incident_cause_axes.sql",
        "0016_promote_grouped_article_top_tags.sql",
        "0017_repair_post_deploy_grouped_top_tags.sql",
        "0018_issue_direct_coverage_override.sql",
        "0019_article_direct_coverage_override.sql",
            "0020_top_issue_implies_briefing_selection.sql",
            "0021_weather_briefing.sql",
            "0022_rules_v12_category_reclassification.sql",
            "0023_analysis_markdown_pipeline.sql",
            "0024_publisher_quality_rule_version.sql",
            "0025_analysis_markdown_manifest.sql",
            "0026_issue_evidence_quality.sql",
            "0027_selected_evidence_validation.sql",
        ]
    upgraded = get_connection(db_path)
    try:
        row = upgraded.execute(
            "SELECT * FROM article_assessments WHERE article_id = 'legacy-1'"
        ).fetchone()
        assert row["auto_priority"] == "review"
        assert row["auto_relevance_score"] == 100
        assert row["classifier_version"] == "rules-v12"
        assert row["manual_override"] == 0
    finally:
        upgraded.close()


def test_foreign_key_constraints_are_enforced(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    try:
        apply_migrations(connection)
        result = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        assert result == 1
        try:
            connection.execute(
                "INSERT INTO briefing_articles (briefing_id, article_id, created_at, updated_at) "
                "VALUES ('missing-briefing', 'missing-article', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            connection.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised
    finally:
        connection.close()
