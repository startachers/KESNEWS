from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.repositories import settings_repository as settings_repo
from backend.app.repositories.database import get_connection

BASE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "collection_settings.json"


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    query: str = Field(min_length=1, max_length=2000)
    naverQueries: list[str] = Field(default_factory=list, max_length=3)
    maxRecords: int | None = Field(default=None, ge=20, le=100)

    @field_validator("naverQueries")
    @classmethod
    def validate_naver_queries(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(values):
            raise ValueError("naverQueries에는 빈 검색어를 넣을 수 없습니다.")
        return cleaned


class CollectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settingsVersion: int = Field(default=11, ge=1)
    lookback: int = Field(default=24, ge=1, le=24)
    maxRecords: int = Field(default=50, ge=20, le=100)
    collectionLimit: int = Field(default=400, ge=1, le=2000)
    enableYonhap: bool = True
    enableOpmPress: bool = True
    enableMePress: bool = True
    queries: list[SearchQuery] = Field(default_factory=list, max_length=100)
    coreKeywords: list[str] = Field(default_factory=list, min_length=1, max_length=100)
    riskKeywords: list[str] = Field(default_factory=list, max_length=200)
    positiveKeywords: list[str] = Field(default_factory=list, max_length=200)
    excludeKeywords: list[str] = Field(default_factory=list, max_length=200)
    endpoint: str = Field(default="", max_length=2000)

    @field_validator("queries")
    @classmethod
    def validate_query_ids(cls, queries: list[SearchQuery]) -> list[SearchQuery]:
        ids = [query.id for query in queries]
        if len(ids) != len(set(ids)):
            raise ValueError("검색 그룹 ID는 중복될 수 없습니다.")
        return queries

    @field_validator(
        "coreKeywords", "riskKeywords", "positiveKeywords", "excludeKeywords"
    )
    @classmethod
    def validate_keywords(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(values):
            raise ValueError("키워드에는 빈 값을 넣을 수 없습니다.")
        return cleaned


def _config_path() -> Path:
    configured = os.environ.get("KESCO_COLLECTION_SETTINGS_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_CONFIG_PATH


@lru_cache(maxsize=8)
def _load_defaults_from_path(path_string: str) -> CollectionSettings:
    path = Path(path_string)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CollectionSettings.model_validate(payload)


def load_default_settings() -> CollectionSettings:
    return _load_defaults_from_path(str(_config_path().resolve()))


def get_effective_settings() -> tuple[CollectionSettings, dict[str, Any]]:
    defaults = load_default_settings()
    connection = get_connection()
    try:
        override, updated_at = settings_repo.get_override(connection)
    finally:
        connection.close()
    if override and int(override.get("settingsVersion") or 0) < defaults.settingsVersion:
        # 새 버전에 추가된 검색군만 보충하고, 담당자가 수정·비활성화한 기존 검색군과
        # 수집 상한·키워드 등 나머지 override 값은 그대로 보존한다.
        existing_ids = {
            str(query.get("id") or "")
            for query in override.get("queries", [])
            if isinstance(query, dict)
        }
        effective_payload = {
            **override,
            "settingsVersion": defaults.settingsVersion,
            "queries": [
                *override.get("queries", []),
                *[
                    query.model_dump(exclude_none=True)
                    for query in defaults.queries
                    if query.id not in existing_ids
                ],
            ],
        }
        effective = CollectionSettings.model_validate(effective_payload)
    else:
        effective = CollectionSettings.model_validate(override) if override else defaults
    return effective, {
        "hasOverride": override is not None,
        "updatedAt": updated_at,
        "defaultSource": "config/collection_settings.json",
    }


def get_category_labels() -> dict[str, str]:
    """Return stable labels for both built-in and user-defined categories."""
    defaults = load_default_settings()
    effective, _ = get_effective_settings()
    labels = {query.id: query.label for query in defaults.queries}
    labels.update({query.id: query.label for query in effective.queries})
    return labels


def save_settings(settings: CollectionSettings) -> tuple[CollectionSettings, dict[str, Any]]:
    value = settings.model_dump()
    connection = get_connection()
    try:
        with connection:
            updated_at = settings_repo.put_override(connection, value)
    finally:
        connection.close()
    return settings, {
        "hasOverride": True,
        "updatedAt": updated_at,
        "defaultSource": "config/collection_settings.json",
    }


def reset_settings() -> tuple[CollectionSettings, dict[str, Any]]:
    connection = get_connection()
    try:
        with connection:
            settings_repo.delete_override(connection)
    finally:
        connection.close()
    return load_default_settings(), {
        "hasOverride": False,
        "updatedAt": None,
        "defaultSource": "config/collection_settings.json",
    }


def collection_payload(
    settings: CollectionSettings,
    report_date: str | None,
    lookback_hours: int,
    *,
    scope: str = "all",
) -> dict[str, Any]:
    payload = {
        "reportDate": report_date,
        "lookbackHours": min(24, lookback_hours),
        "maxRecordsPerQuery": settings.maxRecords,
        "collectionLimit": settings.collectionLimit,
        "enableYonhap": settings.enableYonhap,
        "enableOpmPress": settings.enableOpmPress,
        "enableMePress": settings.enableMePress,
        "queries": [
            query.model_dump(exclude_none=True)
            for query in settings.queries
            if query.enabled and query.query.strip()
        ],
        "coreKeywords": settings.coreKeywords,
        "riskKeywords": settings.riskKeywords,
        "positiveKeywords": settings.positiveKeywords,
        "excludeKeywords": settings.excludeKeywords,
        "endpoint": settings.endpoint,
    }
    if scope == "article":
        payload.update(
            {
                "enablePolicyBriefing": False,
                "enableMediaFallback": True,
            }
        )
    elif scope == "government":
        payload.update(
            {
                "enableYonhap": False,
                "enableOpmPress": False,
                "enableMePress": False,
                "enablePolicyBriefing": True,
                "enableMediaFallback": False,
                "queries": [],
            }
        )
    return payload
