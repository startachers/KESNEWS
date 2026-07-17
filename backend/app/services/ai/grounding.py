from __future__ import annotations

import re
from typing import Any, Iterable

from backend.app.services.ai.schemas import AnalysisBasisItem, AnalysisResult

NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])\d[\d,.]*(?:\s*(?:%|％|퍼센트|년|월|일|시|분|초|건|명|개|곳|대|"
    r"억원|조원|만원|원|kV|KV|MW|GW|kW|㎾|℃|도))?"
)
SENTENCE_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?|[^\n]+$")
INVESTIGATION_RE = re.compile(r"추정|조사\s*중|가능성|원인.{0,12}(?:조사|확인)\s*중")
HEDGE_RE = re.compile(r"추정|조사\s*중|가능성|잠정|확인\s*중|단정하기 어렵")
CAUSE_ASSERTION_RE = re.compile(
    r"원인(?:은|이|으로|로).{0,30}(?:이다|이었다|이었|였다|확정|밝혀졌|발생)|"
    r"(?:때문에|탓에|으로 인해|로 인해).{0,24}(?:발생|불이|사고가)"
)
ATTRIBUTION_RE = re.compile(
    r"언론|보도|전문가|관계자|당국|기관|업계|연구진|(?:에|은|는|이|가)\s*따르면|"
    r"지적|주장|평가|분석|전망|설명|밝혔|말했"
)
ROLE_RE = re.compile(
    r"송전망\s*(?:구축|건설)|전력\s*(?:공급|판매)|발전\s*사업|계통\s*(?:운영|제어)"
)
ROLE_NEGATION_RE = re.compile(r"주체가\s*아니|담당하지\s*않|소관이\s*아니|권한이\s*없")
REFERENCE_SCOPE_RE = re.compile(
    r"예산|재무|회계|결산|보안|정보보호|개인정보|인사|채용|노무|노사|계약|조달|감사|"
    r"경영평가|경영공시|거버넌스|이사회|윤리|청렴|내부통제"
)
TOKEN_RE = re.compile(r"[가-힣]{2,}")
STOPWORDS = {
    "공사는",
    "공사의",
    "관련",
    "대한",
    "기사",
    "보도",
    "필요",
    "있다",
    "있습니다",
    "것으로",
    "대해",
}


def _warning(
    code: str,
    message: str,
    *,
    article_ids: list[str],
    field: str,
    text: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "articleIds": article_ids,
        "field": field,
        "text": text,
    }


def _corpus(articles_by_id: dict[str, dict[str, Any]], article_ids: Iterable[str]) -> str:
    parts: list[str] = []
    for article_id in article_ids:
        article = articles_by_id.get(article_id) or {}
        parts.extend(
            str(article.get(key) or "")
            for key in ("title", "source", "publishedAt", "content")
        )
    return "\n".join(parts)


def _normalize_number(value: str) -> str:
    return re.sub(r"[\s,％]", "", value).lower().replace("퍼센트", "%")


def _sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text) if match.group(0).strip()]


def _text_warnings(
    text: str,
    *,
    field: str,
    article_ids: list[str],
    corpus: str,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    corpus_numbers = {_normalize_number(value) for value in NUMBER_RE.findall(corpus)}
    unsupported = sorted(
        {
            value
            for value in NUMBER_RE.findall(text)
            if _normalize_number(value) not in corpus_numbers
        }
    )
    if unsupported:
        warnings.append(
            _warning(
                "UNSUPPORTED_NUMBER",
                f"근거 기사에서 확인되지 않은 숫자·날짜·단위: {', '.join(unsupported)}",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )

    for sentence in _sentences(text):
        if "공사" in sentence and ROLE_RE.search(sentence) and not ROLE_NEGATION_RE.search(sentence):
            warnings.append(
                _warning(
                    "KESCO_ROLE_CONFUSION",
                    "공사를 송전망 구축·전력 공급·발전사업·계통 운영 주체로 읽을 수 있습니다.",
                    article_ids=article_ids,
                    field=field,
                    text=sentence,
                )
            )
        if (
            INVESTIGATION_RE.search(corpus)
            and CAUSE_ASSERTION_RE.search(sentence)
            and not HEDGE_RE.search(sentence)
        ):
            warnings.append(
                _warning(
                    "INVESTIGATION_OVERSTATED",
                    "원문은 원인을 추정·조사 중으로 표현하지만 결과문은 원인을 확정합니다.",
                    article_ids=article_ids,
                    field=field,
                    text=sentence,
                )
            )
    return warnings


def validate_basis_items(
    items: list[AnalysisBasisItem], evidence_input: list[dict[str, Any]]
) -> tuple[list[AnalysisBasisItem], list[dict[str, Any]]]:
    articles_by_id = {str(item.get("id")): item for item in evidence_input}
    accepted: list[AnalysisBasisItem] = []
    warnings: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        item_warnings: list[dict[str, Any]] = []
        corpus = _corpus(articles_by_id, item.articleIds)
        values = {
            "articleFact": item.articleFact,
            "attributedClaim": item.attributedClaim,
            "kescoInterpretation": item.kescoInterpretation,
            "managementRecommendation": item.managementRecommendation,
        }
        for field, text in values.items():
            item_warnings.extend(
                _text_warnings(
                    text,
                    field=f"items[{index}].{field}",
                    article_ids=item.articleIds,
                    corpus=corpus,
                )
            )
        if item.attributedClaim.strip() and not ATTRIBUTION_RE.search(item.attributedClaim):
            item_warnings.append(
                _warning(
                    "UNATTRIBUTED_CLAIM",
                    "언론·전문가 주장의 주체나 출처가 표시되지 않았습니다.",
                    article_ids=item.articleIds,
                    field=f"items[{index}].attributedClaim",
                    text=item.attributedClaim,
                )
            )
        if item.section == "reference" and not REFERENCE_SCOPE_RE.search(corpus):
            item_warnings.append(
                _warning(
                    "REFERENCE_SCOPE_INVALID",
                    "참고 동향 근거가 내부 경영관리 범위와 직접 연결되지 않습니다.",
                    article_ids=item.articleIds,
                    field=f"items[{index}].section",
                    text=item.articleFact,
                )
            )
        if item_warnings:
            warnings.extend(item_warnings)
        else:
            accepted.append(item)
    return accepted, warnings


def _tokens(text: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(text) if token not in STOPWORDS}


def _resembles_unattributed_claim(sentence: str, claims: list[str]) -> bool:
    if ATTRIBUTION_RE.search(sentence):
        return False
    sentence_tokens = _tokens(sentence)
    for claim in claims:
        claim_tokens = _tokens(claim)
        if len(claim_tokens) < 2:
            continue
        overlap = sentence_tokens & claim_tokens
        if len(overlap) >= 2 and len(overlap) / len(claim_tokens) >= 0.45:
            return True
    return False


def validate_final_result(
    result: AnalysisResult,
    evidence_input: list[dict[str, Any]],
    basis_items: list[AnalysisBasisItem],
) -> list[dict[str, Any]]:
    articles_by_id = {str(item.get("id")): item for item in evidence_input}
    attributed_claims = [item.attributedClaim for item in basis_items if item.attributedClaim.strip()]
    fields: list[tuple[str, str, list[str]]] = [
        ("managementMessage.text", result.managementMessage.text, result.managementMessage.articleIds),
        ("situationSummary.text", result.situationSummary.text, result.situationSummary.articleIds),
        ("riskOutlook.text", result.riskOutlook.text, result.riskOutlook.articleIds),
    ]
    fields.extend(
        (
            f"keyIssues[{index}]",
            " ".join((item.title, item.summary, item.managementImpact)),
            item.articleIds,
        )
        for index, item in enumerate(result.keyIssues)
    )
    fields.extend(
        (f"decisionPoints[{index}].text", item.text, item.articleIds)
        for index, item in enumerate(result.decisionPoints)
    )
    fields.extend(
        (f"actionItems[{index}].action", item.action, item.articleIds)
        for index, item in enumerate(result.actionItems)
    )

    warnings: list[dict[str, Any]] = []
    for field, text, article_ids in fields:
        warnings.extend(
            _text_warnings(
                text,
                field=field,
                article_ids=article_ids,
                corpus=_corpus(articles_by_id, article_ids),
            )
        )
        for sentence in _sentences(text):
            if _resembles_unattributed_claim(sentence, attributed_claims):
                warnings.append(
                    _warning(
                        "UNATTRIBUTED_CLAIM",
                        "중간 분석의 언론·전문가 주장이 최종문에서 객관적 사실처럼 표현됐습니다.",
                        article_ids=article_ids,
                        field=field,
                        text=sentence,
                    )
                )
    return warnings
