from backend.app.services.classification.origin import assess_kesco_origin
from backend.app.services.collection.kesco_press import _parse_detail, _parse_list


def test_kesco_press_list_and_detail_parser_extract_stable_fields():
    list_html = """
    <table><tr>
      <td>1033</td><td>[뉴스]</td><td class="tbl_tit">
        <a href="#" onclick="fnDetail('171545', ''); return false;">
          “복지 사각지대도 전기안전 지킨다”… 한국전기안전공사 협력
        </a>
      </td><td class="tbl_date">2026.07.16</td>
    </tr></table>
    """
    detail_html = """
    <div class="board_view"><h4 class="tit1">복지 사각지대도 전기안전 지킨다</h4>
      <div class="editor_view" id="cn"><span>한국전기안전공사는</span>
        <div><span>취약계층 전기안전 점검을 실시한다.</span></div>
      </div>
    </div>
    """

    items = _parse_list(list_html)
    assert items == [
        {
            "id": "kesco:171545",
            "bbsSeq": "171545",
            "title": "“복지 사각지대도 전기안전 지킨다”… 한국전기안전공사 협력",
            "publishedAt": "2026-07-16T00:00:00Z",
            "url": "https://www.kesco.or.kr/bbs/pr/selectBbs.do?bbs_code=MKB00002&bbs_seq=171545",
        }
    ]
    assert _parse_detail(detail_html) == (
        "복지 사각지대도 전기안전 지킨다",
        "한국전기안전공사는 취약계층 전기안전 점검을 실시한다.",
    )


def test_origin_matcher_identifies_republication_but_not_unrelated_direct_mention():
    releases = [
        {
            "id": "kesco:171545",
            "title": "복지 사각지대도 전기안전 지킨다 한국전기안전공사 협력",
            "publishedAt": "2026-07-15T15:00:00Z",
            "bodyText": "한국사회복지협의회와 업무협약을 체결하고 취약계층 무료 전기안전 점검을 실시한다.",
        }
    ]
    copied = {
        "title": "복지 사각지대도 전기안전 지킨다…전기안전공사 협력",
        "description": "한국사회복지협의회와 업무협약을 체결해 취약계층 무료 전기안전 점검을 실시한다.",
        "pubDate": "2026-07-16T01:00:00Z",
    }
    independent = {
        "title": "국정감사, 한국전기안전공사 검사 제도 개선 주문",
        "description": "국회가 별도 조사 결과를 공개했다.",
        "pubDate": "2026-07-16T01:00:00Z",
    }

    match = assess_kesco_origin(copied, releases)
    assert match is not None
    assert match["originType"] == "kesco_republication"
    assert match["pressReleaseId"] == "kesco:171545"
    assert assess_kesco_origin(independent, releases) is None
