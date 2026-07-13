# 표준 관행 리뷰 오케스트레이터 — 설계서

> **용도**: 코드 리뷰 라운드1([REVIEW_ORCHESTRATOR.md](REVIEW_ORCHESTRATOR.md), RC-)과 UI
> 디자인 라운드([REVIEW_UI_ORCHESTRATOR.md](REVIEW_UI_ORCHESTRATOR.md), UD-)에 이은 **세 번째
> 리뷰 트랙**. 발견 원장 = [REVIEW_STD_FINDINGS.md](REVIEW_STD_FINDINGS.md)(ST- 번호).

---

## 1. 이 라운드의 정체성 — 왜 별개 트랙인가

앞선 두 라운드는 **저장소 자체를 ground truth** 로 삼았다:
- 라운드1: 엔지니어링(결합·실패흐름·명명) — 내부 코드 계약.
- UI 라운드: 시각·상태·어포던스 — **저장소 ADR/목업/자기 규율**. 명시적으로 "취향≠결함",
  "목업 대조 금지", 판정은 ADR 조항 위반 여부.

그 결과 **"어떤 ADR도 위반하지 않지만 외부 표준과 어긋난"** 항목은 구조적으로 통과했다.
이 라운드는 정확히 그 사각지대를 **외부 표준을 ground truth 로** 메운다:

| 축 | 외부 표준 |
|---|---|
| 사용성 휴리스틱 | **Nielsen 10 Usability Heuristics** (H1~H10) |
| 접근성 | **WCAG 2.1 / 2.2 Level AA** (SC 단위 인용) |
| 플랫폼 | **Windows 데스크톱 · Fluent/WinUI 관행** (창 상태·크롬·니모닉·고대비) |

**성립 요건**: 모든 발견은 `external_basis` 에 **구체적 표준 조항**(예: "WCAG 2.1 SC 4.1.2",
"Nielsen H5 Error prevention")을 인용해야 한다. 인용 못 하면 취향 → 기각.

## 2. 스코프

- **앱 B**(`src/hwpxfiller/gui/`) 전 화면 + **앱 A**(`src/hwpxdiff/`) — UI 라운드가 앱 A를
  제외했던 것과 달리 이 라운드는 포함(플랫폼·휴리스틱은 앱 무관).
- **소스 기반 라운드**: UI 라운드와 달리 캡처 뱅크를 짓지 않았다. 창 모델·접근성 API·
  플랫폼 크롬·대부분의 휴리스틱은 **코드에서 직접 판정** 가능(grep `setAccessibleName`/
  `QSettings`/`setShortcut`/`menuBar`, 색 상수 대비 계산 등). 픽셀에만 의존하는 시각 주장은
  `confidence≤0.4` + "(캡처 필요)" 표기 후 대개 기각(예: ST-35).

## 3. 차원·렌즈

- **전역 3(앱 전체 아키텍처 스윕):** ① nav-ia(창 모델·IA·발견성) ② accessibility(WCAG 전수)
  ③ platform(창 상태·메뉴·니모닉·고대비·다이얼로그).
- **화면 7(Nielsen 휴리스틱 적용):** 홈 · 저작 위저드 · 실행 · 데이터 계열(풀/나라/파이프
  라인/매트릭스/어휘) · txt · 템플릿 관리 · **앱 A(diff)**. 각 화면에 H1~H10 적용 + 화면
  국소 a11y/platform 증상.
- 의도된 중복(전역 systemic vs 화면 국소)은 상관 단계가 병합.

## 4. 파이프라인 (배리어는 상관 앞 1곳)

```text
Review  : parallel(전역 3 + 화면 7 = 리뷰어 10)
  → [배리어] Correlate : 근본원인 병합 + ADR 대조 태깅 + UD/RC dedup (단일 편집자)
  → Verify  : parallel(발견별 적대 반증 4축)
  → Synthesize : 테마 그룹핑 + 심각도 + 조치 시퀀스
```

**ADR 대조 태깅(상관 단계 핵심)**: 일부 이탈은 ADR이 의도적으로 정한 것일 수 있다(ADR-C
인앱 미리보기 없음, ADR-E 모달 강등, ADR-L 드리프트 차등). 리뷰어는 자기검열 없이 **일단
보고**하고 `possible_adr_justification` 만 표기 → 상관·검증이 `UI_DESIGN_DECISIONS.md`
원문으로 최종 판정. 이로써 "정당한 이탈"과 "진짜 공백"이 갈린다(ST-27·28 = 정당화, 나머지
= 공백).

**적대 반증 4축(Verifier)**: ① 표준 오적용?(조항 실재·정확 적용) ② ADR 정당화?(원문 대조)
③ 실마찰 입증?(구체 태스크의 배제·오류·손실) ④ 코드 재확인?(file:line 사실 확인). 2축 이상
반증 시 기각. **심각도는 검증이 보정**(리뷰어 severity ≠ 최종) — 예: ST-01 high→medium
(OS 창관리 완화), ST-04 high 유지(코드 자기입증 강화), ST-12 medium→low(기본 키보드 조작
존재).

## 5. UD 스키마 대비 — 발견 스키마 차이

`external_basis`(구체 표준 조항, 필수) · `dimension`(nav-ia/accessibility/platform/
heuristic) · `possible_adr_justification` · `related_prior`(UD/RC 연결). 심각도 기준:
critical=데이터 오류·손실 오도 / high=상태 오전달·확인-또는-경보 시각 위반 / medium=태스크
마찰·systemic / low=비차단 폴리시.

## 6. 실행 기록

- **실행 완료 (2026-07-13)**: 병렬 오케스트레이션(`Workflow`, 에이전트 47 · 오류 0 ·
  ~22분 · 서브에이전트 토큰 2.9M). 리뷰어 10 → 원발견 83 → 상관 병합 35(기각 없음, dedup:
  geometry 6·mnemonic 9·muted대비 9·raw예외 5·help 5·동기프리즈 4·상태통지 3·setBuddy 3을
  각 1건 systemic 통합) → 적대 검증 35 투입 → **확정 23 · ADR정당화 2 · 기각 10**(critical 0).
- **결과 박제**: [REVIEW_STD_FINDINGS.md](REVIEW_STD_FINDINGS.md) — 추적 표(ST-01~35) +
  테마 8개(T1~T8) 상세 + 조치 시퀀스 + ADR정당화·기각 부록. **조치는 전건 대기.**
- **핵심 소견**: 코드베이스가 표준을 아는데(confirm_destructive·QProgressBar·QFormLayout
  버디·design_tokens 단일출처) **화면마다 비대칭 적용** — 처방은 신규 역량이 아니라 기존
  패턴의 수평 전개. 3대 systemic 층: 접근성(QSS 재스타일이 포커스·대비·시맨틱 억제) · 창
  모델(다중창·미지속·중복) · 확인/상태(무확인 폐기·프리즈).

## 7. 조치 착지 (2026-07-13)

- **완료: 착지 20/22** — 유닛 U1~U8·6스테이지 직렬. 착지 표·유닛 커밋은
  [REVIEW_STD_FINDINGS.md](REVIEW_STD_FINDINGS.md) "스테이지 착지 기록" 절이 원장.
  최종 게이트 821 passed(직전 809 대비 +12 회귀 테스트).
- 처방 골자대로 **기존 패턴 수평 전개** — 신규 공용 헬퍼는 전부 `gui/view_helpers.py`에
  단일 소유(지오메트리·접근성 통지·단축키·대기 커서·오류 성형).
- **후속/보류/재분류**: ST-01(셸 리팩터=별도 전용 라운드) · ST-14(고대비=헤드리스 검증불가·
  리스크 보류) · ST-33(RC-32 zero-changes 흐름과 충돌 → 가드 철회·재분류, FINDINGS 부록 C).
- 착지 방식(계승): 유닛별 커밋 · 스테이지별 통합 게이트(ruff·pyright·pytest, 깨끗한
  basetemp) · 적대 검증(대비 계약 가드·게이트 monkeypatch·지오메트리 왕복 등 신규 회귀).
- 조치 교훈: 모달 `box.exec()`는 offscreen 테스트를 hang → `QMessageBox.critical`(테스트가
  patch하는 정적 이음새)로 통일. 소스 리뷰가 놓친 인접 결정(RC-32)은 코드 접촉 시 드러남.
