from __future__ import annotations

import re
from typing import Any, Iterable

from backend.app.services.ai.jurisdiction import load_jurisdiction_policy
from backend.app.services.ai.schemas import AnalysisBasisItem, AnalysisResult

NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])\d[\d,.]*(?:\s*(?:%|％|퍼센트|년|월|일|시|분|초|건|명|개|곳|대|"
    r"억원|조원|만원|원|kV|KV|MW|GW|kW|㎾|℃|도))?"
)
SENTENCE_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?|[^\n]+$")
INVESTIGATION_RE = re.compile(
    r"추정|의심|조사\s*중|가능성|원인\s*(?:미상|불명|확인되지|밝혀지지)|"
    r"원인.{0,12}(?:조사|확인)\s*중"
)
HEDGE_RE = re.compile(
    r"추정|의심|조사\s*중|가능성|잠정|확인\s*중|원인\s*(?:미상|불명)|"
    r"단정하기 어렵|판단하기 어렵|확인(?:된 바|되지)"
)
CAUSE_ASSERTION_RE = re.compile(
    r"원인(?:은|이|으로|로).{0,30}(?:이다|이었다|이었|였다|확정|밝혀졌|발생)|"
    r"(?:때문에|탓에|으로 인해|로 인해|하지\s*않아).{0,30}(?:발생|불이|사고가|인명\s*피해)"
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
ELECTRICAL_RE = re.compile(r"전기|배선|누전|합선|아크|전선|전기설비|전기공사")
INSPECTION_CHANGE_RE = re.compile(
    r"(?:검사|점검|진단).{0,16}(?:항목|기준|체계|절차).{0,16}(?:세분화|개정|변경|강화|구축|반영)|"
    r"(?:항목|기준|체계|절차).{0,16}(?:세분화|개정|변경|강화|구축|반영)"
)
DIRECTIVE_RE = re.compile(r"해야|한다|추진|강화|개정|변경|의무화|단속|구축|반영|세분화")
CONFIRMATION_RE = re.compile(r"확정|확인됐|밝혀졌|원인이다|원인이었다|초래했|야기했|때문에")
LATIN_NAME_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9.-]{1,}(?![A-Za-z0-9])")
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


def _all_input_text(evidence_input: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(article.get(key) or "")
        for article in evidence_input
        for key in ("title", "source", "publishedAt", "content", "editorNote")
    )


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
    all_input: str = "",
    check_action_language: bool = True,
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

    policy = load_jurisdiction_policy()
    for concept, aliases in policy["blocked_if_absent"].items():
        if any(alias in text for alias in aliases) and not any(alias in all_input for alias in aliases):
            warnings.append(
                _warning(
                    "UNSUPPORTED_CONCEPT",
                    f"입력 기사와 메모에 없는 사고 세부사항·설비·정책명: {concept}",
                    article_ids=article_ids,
                    field=field,
                    text=text,
                )
            )

    input_latin_names = set(LATIN_NAME_RE.findall(all_input))
    unsupported_names = sorted(
        name for name in set(LATIN_NAME_RE.findall(text))
        if name not in input_latin_names and name not in {"KESCO", "DIRECT", "COLLABORATIVE"}
    )
    if unsupported_names:
        warnings.append(
            _warning(
                "UNSUPPORTED_NAMED_ENTITY",
                f"입력에 없는 영문 고유명사·설비명: {', '.join(unsupported_names)}",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )

    mentioned_oos = [term for term in policy["out_of_scope"] if term in text]
    if check_action_language and mentioned_oos and DIRECTIVE_RE.search(text):
        warnings.append(
            _warning(
                "OUT_OF_SCOPE_RECOMMENDATION",
                f"비소관 요소를 공사 조치로 제안했습니다: {', '.join(mentioned_oos)}",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    if (
        check_action_language
        and INVESTIGATION_RE.search(corpus)
        and INSPECTION_CHANGE_RE.search(text)
    ):
        warnings.append(
            _warning(
                "UNCONFIRMED_ELECTRICAL_ACTION",
                "원인 미상·조사 중 기사에서 검사·점검체계 변경을 직접 제안했습니다.",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    authority_phrases = [phrase for phrase in policy["authority_only_phrases"] if phrase in text]
    if (
        check_action_language
        and authority_phrases
        and not re.search(r"관계기관|협의|의견|개정\s*동향", text)
    ):
        warnings.append(
            _warning(
                "KESCO_AUTHORITY_OVERREACH",
                f"공사 권한 밖의 기준·단속 조치를 직접 지시했습니다: {', '.join(authority_phrases)}",
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


def _classification_warnings(
    *,
    text: str,
    corpus: str,
    article_ids: list[str],
    field: str,
    certainty: str,
    electrical_status: str,
    jurisdiction: str,
    action_level: str,
    owner_type: str,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    policy = load_jurisdiction_policy()

    expected_levels = {
        "DIRECT": {"internal_review", "interagency_coordination"},
        "COLLABORATIVE": {"interagency_coordination"},
        "MONITORING": {"policy_monitoring"},
        "OUT_OF_SCOPE": {"exclude"},
    }
    if action_level not in expected_levels[jurisdiction]:
        warnings.append(
            _warning(
                "JURISDICTION_ACTION_MISMATCH",
                "소관 등급과 조치 수준이 일치하지 않습니다.",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    if owner_type == "EXTERNAL_AGENCY" and text.strip():
        warnings.append(
            _warning(
                "EXTERNAL_ACTION_AS_KESCO",
                "외부기관 소관 조치를 KESCO 직접 조치로 출력할 수 없습니다.",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    if certainty in {"suspected", "unknown"} and CONFIRMATION_RE.search(text) and not HEDGE_RE.search(text):
        warnings.append(
            _warning(
                "UNCERTAINTY_OVERSTATED",
                "suspected 또는 unknown 사실을 확정형으로 표현했습니다.",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    if electrical_status == "not_confirmed" and INSPECTION_CHANGE_RE.search(text):
        warnings.append(
            _warning(
                "UNCONFIRMED_ELECTRICAL_ACTION",
                "전기적 원인이 확인되지 않았는데 검사·점검체계 변경을 직접 제안했습니다.",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    if electrical_status == "confirmed" and not ELECTRICAL_RE.search(corpus):
        warnings.append(
            _warning(
                "ELECTRICAL_CAUSE_UNSUPPORTED",
                "근거 기사에 전기적 원인 확인 내용이 없습니다.",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    if jurisdiction in {"DIRECT", "COLLABORATIVE"}:
        mentioned_oos = [term for term in policy["out_of_scope"] if term in text]
        if mentioned_oos and DIRECTIVE_RE.search(text):
            warnings.append(
                _warning(
                    "OUT_OF_SCOPE_RECOMMENDATION",
                    f"비소관 요소를 공사 조치로 제안했습니다: {', '.join(mentioned_oos)}",
                    article_ids=article_ids,
                    field=field,
                    text=text,
                )
            )
    monitoring_terms = [term for term in policy["monitoring"] if term in text or term in corpus]
    if monitoring_terms and jurisdiction == "DIRECT" and DIRECTIVE_RE.search(text):
        warnings.append(
            _warning(
                "MONITORING_AS_DIRECT",
                f"정책·산업 동향을 공사 직접 소관으로 과장했습니다: {', '.join(monitoring_terms)}",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    authority_phrases = [phrase for phrase in policy["authority_only_phrases"] if phrase in text]
    if authority_phrases and action_level == "internal_review":
        warnings.append(
            _warning(
                "KESCO_AUTHORITY_OVERREACH",
                f"법령·기준 또는 타 기관 권한을 공사 내부 조치로 표현했습니다: {', '.join(authority_phrases)}",
                article_ids=article_ids,
                field=field,
                text=text,
            )
        )
    return warnings


def validate_basis_items(
    items: list[AnalysisBasisItem], evidence_input: list[dict[str, Any]]
) -> tuple[list[AnalysisBasisItem], list[dict[str, Any]]]:
    articles_by_id = {str(item.get("id")): item for item in evidence_input}
    accepted: list[AnalysisBasisItem] = []
    warnings: list[dict[str, Any]] = []
    all_input = _all_input_text(evidence_input)
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
                    all_input=all_input,
                    check_action_language=field in {"kescoInterpretation", "managementRecommendation"},
                )
            )
        item_warnings.extend(
            _classification_warnings(
                text=item.managementRecommendation,
                corpus=corpus,
                article_ids=item.articleIds,
                field=f"items[{index}]",
                certainty=item.certainty,
                electrical_status=item.electricalCauseStatus,
                jurisdiction=item.kescoJurisdiction,
                action_level=item.actionLevel,
                owner_type=item.ownerType,
            )
        )
        for quote in item.evidenceQuotes:
            quote_corpus = _corpus(articles_by_id, [quote.articleId])
            item_warnings.extend(
                _text_warnings(
                    quote.fact,
                    field=f"items[{index}].evidenceQuotes",
                    article_ids=[quote.articleId],
                    corpus=quote_corpus,
                    all_input=all_input,
                    check_action_language=False,
                )
            )
            if quote.articleId not in item.articleIds:
                item_warnings.append(
                    _warning(
                        "EVIDENCE_QUOTE_ID_MISMATCH",
                        "evidenceQuotes의 기사 ID가 항목 articleIds에 없습니다.",
                        article_ids=item.articleIds,
                        field=f"items[{index}].evidenceQuotes",
                        text=quote.fact,
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
    all_input = _all_input_text(evidence_input)
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
        (f"keyIssues[{index}].recommendation", item.recommendation, item.articleIds)
        for index, item in enumerate(result.keyIssues)
        if item.recommendation.strip()
    )
    fields.extend(
        (f"decisionPoints[{index}].text", item.text, item.articleIds)
        for index, item in enumerate(result.decisionPoints)
    )
    fields.extend(
        (
            f"actionItems[{index}].action",
            item.action,
            item.articleIds,
        )
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
                all_input=all_input,
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
    basis_by_id = {
        article_id: item
        for item in basis_items
        for article_id in item.articleIds
    }
    for index, item in enumerate(result.keyIssues):
        item_text = " ".join(
            (item.title, item.summary, item.managementImpact, item.recommendation)
        )
        warnings.extend(
            _classification_warnings(
                text=item_text,
                corpus=_corpus(articles_by_id, item.articleIds),
                article_ids=item.articleIds,
                field=f"keyIssues[{index}]",
                certainty=item.certainty,
                electrical_status=item.electricalCauseStatus,
                jurisdiction=item.kescoJurisdiction,
                action_level=item.actionLevel,
                owner_type="UNDETERMINED",
            )
        )
        linked_scopes = {
            basis_by_id[article_id].kescoJurisdiction
            for article_id in item.articleIds
            if article_id in basis_by_id
        }
        if linked_scopes and item.kescoJurisdiction not in linked_scopes:
            warnings.append(
                _warning(
                    "FINAL_BASIS_SCOPE_MISMATCH",
                    "최종 이슈의 KESCO 소관 등급이 검증된 중간 분석과 다릅니다.",
                    article_ids=item.articleIds,
                    field=f"keyIssues[{index}].kescoJurisdiction",
                    text=item.kescoJurisdiction,
                )
            )
        for quote in item.evidenceQuotes:
            warnings.extend(
                _text_warnings(
                    quote.fact,
                    field=f"keyIssues[{index}].evidenceQuotes",
                    article_ids=[quote.articleId],
                    corpus=_corpus(articles_by_id, [quote.articleId]),
                    all_input=all_input,
                    check_action_language=False,
                )
            )
            if quote.articleId not in item.articleIds:
                warnings.append(
                    _warning(
                        "EVIDENCE_QUOTE_ID_MISMATCH",
                        "evidenceQuotes의 기사 ID가 이슈 articleIds에 없습니다.",
                        article_ids=item.articleIds,
                        field=f"keyIssues[{index}].evidenceQuotes",
                        text=quote.fact,
                    )
                )
    for index, item in enumerate(result.actionItems):
        basis = next((basis_by_id.get(article_id) for article_id in item.articleIds if article_id in basis_by_id), None)
        electrical_status = basis.electricalCauseStatus if basis else "not_applicable"
        warnings.extend(
            _classification_warnings(
                text=item.action,
                corpus=_corpus(articles_by_id, item.articleIds),
                article_ids=item.articleIds,
                field=f"actionItems[{index}].action",
                certainty=item.uncertainty,
                electrical_status=electrical_status,
                jurisdiction=item.kescoJurisdiction,
                action_level=item.actionLevel,
                owner_type=item.ownerType,
            )
        )
        if basis is not None and item.kescoJurisdiction != basis.kescoJurisdiction:
            warnings.append(
                _warning(
                    "FINAL_BASIS_SCOPE_MISMATCH",
                    "최종 조치의 KESCO 소관 등급이 검증된 중간 분석과 다릅니다.",
                    article_ids=item.articleIds,
                    field=f"actionItems[{index}].kescoJurisdiction",
                    text=item.action,
                )
            )
    return warnings
