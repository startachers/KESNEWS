# CEO 브리핑 자동선정 품질 개선 회귀 기록 — 2026-07-17

## 범위

- 전체 브리핑 선정 상한을 20건에서 12건으로 변경
- 추천 1~6위를 핵심 선정, 7~12위를 추가 참고로 구분
- Top Issues 합산 상한을 5개에서 6개로 변경
- 추천 적용 시 기존 수동 Top 태그를 보존하고 빈 Top Issues 자리만 추천 순위순으로 채움
- 추천 기사가 군집에 속하면 기사 태그 대신 해당 군집의 Top 태그를 활성화
- 구버전의 숨은 기사 Top 태그를 군집 Top 태그로 승격하는 migration 및 화면 fallback
- 공사 직접성·법정업무 연관성을 사회적 심각성보다 우선
- 전기·설비·검사·점검·안전관리 연결이 없는 일반 화재 제외
- 국내 정책·기준·대응 또는 공사 해외사업과 연결되지 않는 해외 사고 제외
- 동일 이슈 후보를 대표 1건으로 제한
- 정부부처·경제·AI 분야 강제를 공사 직접 연관 후보가 있을 때만 적용
- 기사 설명을 기사 사실·공사 연관성·선정 이유로 분리

## 자동 검증

```text
.venv/bin/python -m pytest -q
269 passed, 3 warnings

.venv/bin/ruff check .
All checks passed!

node --check frontend/js/app.js
node --check frontend/js/features/auto-selection.js
node --check frontend/js/features/issues.js
node --check frontend/js/features/articles.js
node --check frontend/js/ui/renderers.js
성공

git diff --check
성공
```

단위 테스트에서 일반 화재 제외, 해외 사고의 국내 연결 조건, 동일 이슈 대표 1건 압축,
조건부 분야 요구를 확인했다. 통합 테스트에서 명시적 적용 전 무변경, 12건 선정, Top Issues
6칸을 추천 중요도 1~6위 순서로 채움, 추천 기사의 군집 Top 태그 활성화, 군집이 없는 기사의
개별 Top 태그 fallback, 기존 수동 선정·메모·중요·Top 태그 보존, 7번째 Top 태그 거부를
확인했다. 모든
테스트는 외부 Ollama와 언론사 네트워크를 호출하지 않는다.

## 수동 회귀

현재 실행 세션에 브라우저 자동화 연결이 제공되지 않아 다음 항목은 미실행으로 남긴다.

- [ ] 실제 화면에서 Top Issues 카드 6칸 배치 확인
- [ ] 실제 Gemma 추천 모달에서 핵심/참고 구분과 3단 설명 확인
- [ ] 추천 적용 뒤 기사 선택·해제, 중요 표시, 메모 저장 확인
- [ ] 날짜 변경, 요약 직접 수정, JSON·CSV 내보내기 확인
- [ ] 인쇄 미리보기와 개발자도구 Console 신규 오류 확인

정적 화면 파일 응답은 통합 테스트로, 변경 JavaScript의 구문은 `node --check`로 확인했다.

## 남은 위험

- 전기안전 연관성은 명시적 단어 규칙과 Gemma 재평가를 함께 사용하므로 기사 본문이 없고
  제목·RSS 요약도 짧은 경우 관련 기사를 놓칠 수 있다.
- 기존 군집 품질이 낮으면 동일 이슈 대표 1건 제한이 완전하게 작동하지 않을 수 있다.
- Top Issues 자동 채움은 담당자가 추천 결과를 명시적으로 적용한 경우에만 발생한다.
- 앱 재시작 시 migration 0016이 적용되며, 적용 전 DB는 자동 백업된다.
