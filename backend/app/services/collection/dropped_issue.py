"""'이슈 기사 찾아보기' 전용 로직.

수집 때 관련도 미달로 본 파이프라인에서 빠진 기사(dropped_article_pool)를 느슨하게
묶어, 같은 사건을 여러 기사가 다룬 '큰 이슈'만 골라 보여준다. 본 수집·브리핑과 완전히
분리돼 있고 버튼을 눌렀을 때만 계산한다.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.services.deduplication.fuzzy import bigram_similarity

# 같은 사건으로 볼 판단 임계값. 제목 문자 bigram 유사도이거나, 핵심 토큰이 겹치면 묶는다.
_BIGRAM_THRESHOLD = 0.55
_SHARED_TOKEN_MIN = 2
# 노출 정책(담당자 확정값): 같은 사건 5건 이상만 '이슈'로 보고, 큰 순으로 최대 5개까지.
DEFAULT_MIN_ARTICLES = 5
DEFAULT_MAX_ISSUES = 5

# 제목 토큰 중 사건 식별력이 없는 흔한 단어는 겹침 계산에서 제외한다.
_STOPWORDS = frozenset(
    {
        "정부", "발표", "오늘", "내일", "관련", "대책", "예정", "대한", "위해", "통해",
        "이번", "지난", "최근", "종합", "속보", "단독", "기자", "뉴스", "사진", "영상",
        "상황", "이유", "결과", "확인", "공개", "추진", "계획", "방침", "대해", "그룹",
        "국내", "전국", "우리", "한국", "올해", "내년", "가운데", "이날", "당국",
    }
)

# 연예·스포츠 기사는 CEO 브리핑 성격상 이슈에서 제외한다(정치·경제·사회 등은 포함).
_ENTERTAINMENT_SPORTS_TERMS = (
    "아이돌", "걸그룹", "보이그룹", "데뷔", "컴백", "신곡", "음원", "앨범", "뮤직비디오",
    "예능", "드라마", "영화", "배우", "가수", "아티스트", "콘서트", "팬미팅", "열애",
    "결혼설", "이혼", "연예", "출연", "방송인", "아나운서",
    "프로야구", "프로축구", "프로농구", "프로배구", "야구", "축구", "농구", "배구",
    "골프", "월드컵", "올림픽", "국가대표", "홈런", "선발승", "구단", "리그", "선수단",
    "메달", "결승전", "예선", "승부차기",
)

_TOKEN_SPLIT = re.compile(r"[^가-힣a-z0-9]+")
# 한국어 제목 토큰에 붙는 조사를 떼어 '폭발로'와 '폭발', '물류창고서'와 '물류창고'가
# 같은 토큰으로 묶이게 한다.
_JOSA_2 = ("으로", "에서", "에게", "까지", "부터", "한테", "처럼", "보다", "이나")
_JOSA_1 = frozenset("은는이가을를의에서로와과도만나")


def is_entertainment_or_sports(title: str, description: str | None = None) -> bool:
    text = f"{title} {description or ''}".lower()
    return any(term in text for term in _ENTERTAINMENT_SPORTS_TERMS)


def _strip_josa(token: str) -> str:
    if len(token) >= 4 and token.endswith(_JOSA_2):
        return token[:-2]
    if len(token) >= 3 and token[-1] in _JOSA_1:
        return token[:-1]
    return token


def _tokens(title: str) -> frozenset[str]:
    return frozenset(
        stripped
        for token in _TOKEN_SPLIT.split(title.lower())
        if len(token) >= 2 and token not in _STOPWORDS
        for stripped in (_strip_josa(token),)
        if len(stripped) >= 2
    )


def _similar(a_norm: str, a_tokens: frozenset[str], b_norm: str, b_tokens: frozenset[str]) -> bool:
    if a_norm and b_norm and bigram_similarity(a_norm, b_norm) >= _BIGRAM_THRESHOLD:
        return True
    return len(a_tokens & b_tokens) >= _SHARED_TOKEN_MIN


def _clusters_touch(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return any(
        _similar(a["norm"], a["tokens"], b["norm"], b["tokens"])
        for a in left["members"]
        for b in right["members"]
    )


def _merge_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = True
    while merged:
        merged = False
        result: list[dict[str, Any]] = []
        for cluster in clusters:
            for existing in result:
                if _clusters_touch(existing, cluster):
                    existing["members"].extend(cluster["members"])
                    merged = True
                    break
            else:
                result.append({"members": list(cluster["members"])})
        clusters = result
    return clusters


def discover_issues(
    rows: list[dict[str, Any]],
    *,
    min_articles: int = DEFAULT_MIN_ARTICLES,
    max_issues: int = DEFAULT_MAX_ISSUES,
) -> list[dict[str, Any]]:
    """보관된 기사에서 같은 사건 클러스터를 찾아 큰 순으로 상위 이슈를 돌려준다."""
    prepared = []
    seen_keys: set[tuple[str, str]] = set()
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        if is_entertainment_or_sports(title, row.get("description")):
            continue
        norm = str(row.get("normalized_title") or "")
        source = str(row.get("source") or "").strip()
        # 같은 매체가 같은 제목으로 여러 번 들어온 기사는 한 건으로 본다(중복 팽창 방지).
        key = (norm, source.lower())
        if norm and key in seen_keys:
            continue
        seen_keys.add(key)
        prepared.append({"row": row, "norm": norm, "tokens": _tokens(title), "source": source})

    clusters: list[dict[str, Any]] = []
    for item in prepared:
        target = None
        for cluster in clusters:
            if any(
                _similar(item["norm"], item["tokens"], member["norm"], member["tokens"])
                for member in cluster["members"]
            ):
                target = cluster
                break
        if target is None:
            clusters.append({"members": [item]})
        else:
            target["members"].append(item)

    # 단일 패스 그리디는 처리 순서에 따라 같은 사건이 갈라질 수 있으므로, 더 이상 합쳐지지
    # 않을 때까지 서로 겹치는 클러스터를 병합한다.
    clusters = _merge_clusters(clusters)

    issues = []
    for cluster in clusters:
        members = cluster["members"]
        if len(members) < min_articles:
            continue
        sources = {m["source"] for m in members if m["source"]}
        representative = max(
            members, key=lambda m: len(str(m["row"].get("description") or ""))
        )
        issues.append(
            {
                "title": str(representative["row"].get("title") or ""),
                "articleCount": len(members),
                "sourceCount": len(sources),
                "articles": [
                    {
                        "title": str(m["row"].get("title") or ""),
                        "url": m["row"].get("url"),
                        "source": m["row"].get("source"),
                        "publishedAt": m["row"].get("published_at"),
                    }
                    for m in sorted(
                        members,
                        key=lambda m: str(m["row"].get("published_at") or ""),
                        reverse=True,
                    )
                ],
            }
        )

    issues.sort(key=lambda issue: (issue["articleCount"], issue["sourceCount"]), reverse=True)
    return issues[:max_issues]
