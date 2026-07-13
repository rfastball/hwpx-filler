# 표준 관행 리뷰 — 발견 원장 (ST-01~ST-35)

> **성격**: 직전 UI 디자인 라운드([REVIEW_UI_FINDINGS.md](REVIEW_UI_FINDINGS.md), UD-01~45)의
> 후속·별개 트랙. UI 라운드는 **저장소 자체 ADR/계약을 ground truth** 로 내부 일관성
> 결함만 잡았다(취향≠결함, 목업 대조 금지). 이 라운드는 그 사각지대 —
> **외부 표준**(Nielsen 10 휴리스틱 · WCAG 2.1/2.2 AA · Windows·데스크톱 플랫폼 관행) 대비
> **관행 이탈** 을 잡는다. 설계서 = [REVIEW_STD_ORCHESTRATOR.md](REVIEW_STD_ORCHESTRATOR.md).
>
> **실행(2026-07-13)**: 병렬 오케스트레이션(에이전트 47) — 리뷰어 10(전역 3: nav·IA /
> WCAG 접근성 / Windows 플랫폼 + 화면 7: Nielsen 휴리스틱, 앱 A 포함) → 원발견 83 →
> 상관 병합 35 → 적대 검증(반증 4축) → **확정 23 · ADR정당화 2 · 기각 10**.
> 대상: 앱 B(`src/hwpxfiller/gui/`) 전 화면 + 앱 A(`src/hwpxdiff/`).
>
> **조치 완료(2026-07-13): 착지 20 · 후속 1(ST-01 셸) · 보류 1(ST-14) · 재분류 1(ST-33).**
> 유닛 U1~U8 · 6스테이지 직렬 착지(각 스테이지 ruff·pyright·pytest 통과, 최종 821 passed).
> 착지 기록은 아래 "스테이지 착지 기록" 절.

---

## 추적 표 (조치 착지 시 이 표를 원장으로 갱신)

| ID | 판정 | 심각도 | 차원 | 화면 | 표준 근거 | 제목 | 상태 |
|---|---|---|---|---|---|---|---|
| ST-03 | 확정 | **높음** | a11y | 전역 QSS | WCAG 2.4.7 | 포커스 표시가 QLineEdit/QPlainTextEdit 에만 — 버튼·체크박스·콤보·라디오·리스트 포커스 비가시 | 착지(b46fbf4) |
| ST-04 | 확정 | **높음** | a11y | 전 화면 | WCAG 1.4.3 | MUTED(#7a7f87) 소형 텍스트 대비 4.0/3.76:1 — 4.5:1 미달 (systemic) | 착지(b46fbf4) |
| ST-08 | 확정 | **높음** | heuristic | 저작 위저드 | Nielsen H5/H3 | 위저드 닫기(X/취소/Esc)가 진행 중 저작을 무확인 폐기 | 착지(2a9a864) |
| ST-09 | 확정 | **높음** | heuristic | 데이터 풀 | Nielsen H5·confirm-or-alarm | 풀 등록이 동명 데이터셋을 무확인·무경고 덮어쓰기 | 착지(7d5a810) |
| ST-01 | 확정 | 중간 | nav-ia | 전역 창 모델 | Nielsen H3/H4·Fluent | 능력마다 별도 최상위 창 — 인-윈도 네비게이션 부재 | 후속(셸 라운드) |
| ST-06 | 확정 | 중간 | a11y | txt 기안 | WCAG 4.1.2/1.1.1 | 아이콘 전용 ◀/▶ 버튼 접근가능 이름 부재 | 착지(7838c96) |
| ST-07 | 확정 | 중간 | a11y | 저장·txt·나라 | WCAG 1.3.1/4.1.2/3.3.2 | 폼 라벨-입력 프로그램적 연결(setBuddy) 누락 (systemic) | 착지(7838c96) |
| ST-10 | 확정 | 중간 | nav-ia | 전역 라우팅 | Nielsen H4·Windows | 중복 창 무제한 생성 + 동일 제목 + 편집기 저장 경합 | 착지(7ba56dd) |
| ST-15 | 확정 | 중간 | a11y | 레코드·매핑 체크박스 | WCAG 2.5.8 | 체크박스 클릭 타깃 15px — 24px 최소 미달 | 착지(b46fbf4) |
| ST-16 | 확정 | 중간 | heuristic | 홈·위저드·템플릿·파이프라인 | Nielsen H1 | 장시간 동기 IO 가 UI 스레드 무피드백 실행 → 프리즈 (systemic) | 착지(7b3e68c) |
| ST-05 | 확정 | 낮음 | a11y | 레코드 체크박스 | WCAG 1.4.11 | 인디케이터 테두리(#adb3bb) 대비 2.1:1 — 3:1 미달 | 착지(b46fbf4) |
| ST-11 | 확정 | 낮음 | platform | 전 최상위 창 | Windows·H4 | 창 크기·위치·최대화 세션 간 미지속 (systemic) | 착지(2a9a864) |
| ST-12 | 확정 | 낮음 | a11y | 전 화면 | WCAG 2.1.1·H7 | 키보드 니모닉·가속기·기본버튼 전무 (systemic) | 착지(7ba56dd) |
| ST-14 | 확정 | 낮음 | platform | 전역 QSS | Windows·WCAG 1.4.3 | 고정 hex 팔레트가 Windows 고대비(Forced Colors) 무시 | 보류(헤드리스 검증불가·리스크) |
| ST-17 | 확정 | 낮음 | heuristic | 나라·풀 복원 | Nielsen H1 | 백그라운드 네트워크 중 진행 인디케이터 부재 | 착지(7b3e68c) |
| ST-18 | 확정 | 낮음 | a11y | 나라·매트릭스·풀·txt | WCAG 4.1.3 | 동적 상태 메시지가 보조기술에 미통지 (systemic) | 착지(7838c96) |
| ST-20 | 확정 | 낮음 | heuristic | 위저드·템플릿·txt·diff | Nielsen H9·WCAG 3.3.3 | 오류 다이얼로그가 원시 예외 str(exc) 노출 (systemic) | 착지(6f209fc) |
| ST-21 | 확정 | 낮음 | heuristic | 실행·매트릭스 | Nielsen H3/H5 | 생성 진행 중 창 닫기 확인·취소 가드 없음 | 착지(2a9a864) |
| ST-22 | 확정 | 낮음 | heuristic | 실행 게이트 | Nielsen H2 | 사용자 대면 문구에 개발자 용어 '드리프트' 노출 | 착지(6f209fc) |
| ST-26 | 확정 | 낮음 | heuristic | 전 화면 | Nielsen H10 | 도메인 용어·복잡 개념에 도움말·툴팁·진입점 부재 (systemic) | 착지(6f209fc) |
| ST-30 | 확정 | 낮음 | heuristic | 나라 취득 | Nielsen H8 | '다시 시도'가 '가져오기'와 동일 동작 — 중복 컨트롤 | 착지(6f209fc) |
| ST-33 | 확정→재분류 | 낮음 | heuristic | diff 판본 선택 | Nielsen H5 | 구판=신판 동일 파일 선택 가드 없음 | 재분류(RC-32 충돌·부록 D) |
| ST-34 | 확정 | 낮음 | heuristic | diff 최근 비교 | Nielsen H6 | 최근 비교가 basename 만 표시 — 동명 파일 구별 불가 | 착지(6f209fc) |
| ST-27 | **ADR정당화** | (low) | heuristic | 삭제·제자리 변환 | Nielsen H3 → ADR-E | 파괴적 삭제·변환에 undo/휴지통 없이 확인 게이트만 | 제외(부록) |
| ST-28 | **ADR정당화** | (low) | heuristic | 실행 사전검증 | Nielsen H9 → ADR-L | 비차단 조건(missing_columns)에 '[치명]' 어휘 | 제외(부록) |
| ST-02 | 기각 | — | nav-ia | 자식 창 exit | — | 상시 home 앵커라 창닫기=비파괴 복귀; 잔여=죽은 back_requested(코드위생) | 기각 |
| ST-13 | 기각 | — | nav-ia | 홈 목적지 분산 | — | 단일 비스크롤 화면·공유 어휘 '관리'·공간 군집으로 그룹 이미 표명 | 기각 |
| ST-19 | 기각 | — | a11y | 매핑 행 상태색 | — | 미매칭이 '데이터 항목'=(비움)·빈 미리보기로 텍스트 재진술(1.4.1 미성립) | 기각 |
| ST-23 | 기각 | — | heuristic | 나라 기간 검증 | — | validate_range 가 네트워크 이전 fail-closed — '왕복 후 거부' 피해 부재 | 기각 |
| ST-24 | 기각 | — | platform | 메뉴·툴바·상태바 | — | H7 오귀속·Fluent는 메뉴바 폐기 관행·X 종료 존재 (ADR-I 발명 금지) | 기각 |
| ST-25 | 기각 | — | a11y | 목록 Enter·탭순서 | — | 카드 버튼이 탭체인 포함·Enter/Space 활성 — 2.1.1 충족 | 기각 |
| ST-29 | 기각 | — | heuristic | 파이프라인 스텝 | — | 'inner/left'는 선택 시 본 콤보 라벨 글로스 토큰 + 헤딩 레전드 | 기각 |
| ST-31 | 기각 | — | heuristic | txt 초기 상태 | — | 부제·3버튼·안내노트·빨간 배지 공존; 빈 상태 CTA는 ADR-E/H 반대 | 기각 |
| ST-32 | 기각 | — | heuristic | diff 판본 선택 | — | 결과가 `old→new` 쌍·방향 재진술; drift 는 읽기전용 비파괴 | 기각 |
| ST-35 | 기각 | — | heuristic | diff 스플리터 | — | QSplitterHandle 이 hover SplitHCursor 어포던스 제공(캡처 미검증) | 기각 |

**확정 23** (높음 4 · 중간 6 · 낮음 13) · **ADR정당화 2** · **기각 10** · critical 0.

---

## 스테이지 착지 기록 (2026-07-13)

앞선 두 라운드(U1~U12, V1~V15)의 방식 계승 — 직교 유닛 · 유닛별 커밋 · 스테이지별 통합
게이트. 기존 안전 패턴(`confirm_destructive`·`QProgressBar`·`QFormLayout` 버디·
`design_tokens` 단일출처)의 수평 전개가 처방 골자. **최종 게이트 821 passed**(직전 809 대비
+12 신규 회귀 테스트).

| 유닛 | 커밋 | 착지 | 요지 |
|---|---|---|---|
| U1 시각/토큰 | `b46fbf4` | ST-03·04·05·15 | :focus outline · MUTED/테두리 대비 · 인디케이터 24px. 신규 대비 계약 가드 |
| U2 풀 게이트 | `7d5a810` | ST-09 | 풀 등록 exists→confirm_destructive(파이프라인 게이트 복제) |
| U3 창 수명 | `2a9a864` | ST-08·11·21 | 창당 단일 closeEvent(가드→지오메트리). QSettings INI(HWPXFILLER_HOME 격리) |
| U4 접근성 | `7838c96` | ST-06·07·18 | accessibleName·setBuddy·announce_status(QAccessible Alert) |
| U5 재사용·키보드 | `7ba56dd` | ST-10·12 | 능력별 싱글턴 · F5/Ctrl+Return/니모닉 |
| U6 상태 가시성 | `7b3e68c` | ST-16·17 | busy_cursor 컨텍스트 · 나라 불확정 진행바 |
| U7/U8 마감 | `6f209fc` | ST-20·22·26·30·34 | describe_exception/show_error · 용어 · 툴팁 · 재시도 컨텍스트 · diff 경로 툴팁 |

**보류·후속·재분류(3):**
- **ST-01**(중간) — 다중창→단일창 셸 리팩터는 **별도 전용 라운드**(설계부터). 이 라운드가
  창 수명(U3)·재사용(U5)을 먼저 마감해 셸 리팩터 표면을 줄였다.
- **ST-14**(낮음) — 고대비/Forced Colors 정확 처리는 **헤드리스 검증 불가 + 리스크**이고
  기본 팔레트가 이미 AA(검증 시 low 강등)라 이 라운드에서 보류. 재개 시 취약 토큰
  (MUTED·테두리)부터 palette 경로 최소 도입.
- **ST-33**(낮음) — 아래 부록 D 참조.

---

## 총평 (executive summary)

이 앱은 파괴적 작업 **일부**(파이프라인 저장·매트릭스 덮어쓰기·`apply_fieldize` 2단계
dry-run·삭제)에서 confirm-or-alarm 원칙과 ADR-E 확인 패턴을 성실히 구현하고,
`ManualRecordDialog` 의 `QFormLayout` 버디 자동연결, 매트릭스의 `QProgressBar`, diff앱의
`QSettings` 최근비교, `design_tokens.json` 단일출처 토큰 파이프라인 등 **외부 표준에
부합하는 지점을 이미 갖추고 있다.** 문제는 이 좋은 관행들이 **화면·경로마다 비대칭적으로만
적용**되어, 표준을 아는 코드베이스가 같은 표준을 이웃 화면에서 반복적으로 놓친다는 데 있다.

따라서 핵심 처방은 **새 역량 추가가 아니라, 이미 저장소에 존재하는 패턴**
(`confirm_destructive` 게이트 · `QProgressBar` · `QFormLayout` 버디 · `design_tokens`
단일출처)을 **비대칭 화면으로 수평 전개**하는 것이다.

---

## 확정 발견 — 테마별 상세

### T1. 다중창 셸 부재 & 창 관리 크롬 〔높음〕 — ST-01, ST-10, ST-11
능력마다 별도 `QMainWindow`/`QWizard` 를 생성하는 다중창 모델에 인-윈도 네비게이션·현재
위치 노출·창 재사용(싱글턴)·세션 간 지오메트리 지속이 모두 없다.

- **ST-01** 〔중간〕 *Nielsen H3/H4·Fluent NavigationView.* `AppController` 의 7개 `_open_*`
  가 각각 새 창 생성 후 `win.show()`(`app.py:81-243`). 인-윈도 전환·복귀·위치표지 없음.
  `app.py:8` 주석이 임베드를 "후속 리팩터"로 자인 — 코드-코멘트 이연이지 ADR 아님.
  → 홈을 셸로 `QStackedWidget`/네비 레일 임베드, 또는 자식 창에 공통 네비 크롬 부여.
  (검증 보정: OS 창관리로 완화돼 high→**medium**.)
- **ST-10** 〔중간〕 *Nielsen H4·Windows.* 기존 창 검사 없이 매번 `show()`(`setModal` 0건).
  동일 능력 재클릭이 동일 제목 창 무제한 복제 → Alt+Tab 구별 불가. **같은 작업을 두
  편집기로 열면 last-save-wins 로 조용히 충돌**(핵심 원칙 위배). → 관리형 능력 싱글턴
  (`_children` raise), 편집기 동일 작업 중복 억제.
- **ST-11** 〔낮음〕 *Windows 창 상태 지속.* `saveGeometry`/`restoreGeometry`/`QSettings`
  (지오메트리) 0건 — 전 창 하드코딩 `resize`. → `closeEvent saveGeometry` + 생성자
  `restoreGeometry` 공용 헬퍼.

### T2. 무확인 파괴적 전이 — confirm-or-alarm 비대칭 〔높음〕 — ST-08, ST-09, ST-21
파이프라인·매트릭스·삭제는 게이트를 갖췄으나 이웃 화면이 원칙을 위반한다.

- **ST-08** 〔높음〕 *Nielsen H5/H3.* `JobEditorWizard` 에 `closeEvent`/`reject` 오버라이드
  0건 — X/Cancel/Esc 가 다스텝 매핑 확정을 침묵 폐기, undo 불가. 동종 형제
  `pipeline_builder`(UD-45)는 이미 봉합됨. → 확정 행 존재 시 `reject`/`closeEvent` 에
  `confirm_destructive` 게이트.
- **ST-09** 〔높음〕 *Nielsen H5·confirm-or-alarm.* `register_excel`/`register_nara` 가
  `exists()` 검사 없이 `registry.save`(`dataset_pool_state.py:186,219`) — 동명 durable
  참조 무통보 소실. 대조: `pipeline_builder._on_save` 는 `exists`+`confirm_destructive`.
  → 등록 전 `exists` 검사 후 동일 게이트 재사용.
- **ST-21** 〔낮음〕 *Nielsen H3/H5.* 실행/매트릭스 생성 진행 중 창을 닫아도 스레드가 조용히
  계속 돈다(파이프라인 이탈 가드와 비대칭). → `_running` 시 `closeEvent` 확인 후
  `request_cancel`·teardown.

### T3. QSS 전면 재스타일이 플랫폼 접근성 기본을 억제 〔높음〕 — ST-03, ST-04, ST-05, ST-14
`BASE_QSS` 가 위젯을 고정 hex 로 전면 재스타일하며 네이티브 접근성 기본을 억제한다.

- **ST-03** 〔높음〕 *WCAG 2.4.7 Focus Visible.* `:focus` 규칙이 `QLineEdit`/
  `QPlainTextEdit` 에만(`style.py:99`). 버튼(primary는 `border:none`)·체크박스·콤보·
  라디오·리스트 포커스 비가시 → 키보드/확대 사용자가 **파괴적 삭제** 버튼 포커스도 추적
  불가. → 전 조작 컴포넌트에 `:focus` outline(3:1↑, 레이아웃 불변).
- **ST-04** 〔높음〕 *WCAG 1.4.3 Contrast.* `MUTED=#7a7f87` — 흰 배경 4.03:1·창 배경
  3.76:1·pill[muted] 3.53:1. KPI 라벨·게이트 사유·빈값 마커 등 **상태 판단 필수 텍스트**에
  전역 적용(merged 9). 코드 자기입증: `ContrastProgressBar` docstring 이 "3.5:1 도 AA
  미달"을 명시하고 진행바만 국소 우회. → `design_tokens.json` 에서 MUTED 를 #656a72 이하로
  하향, 재유입 가드와 함께 재생성(diff앱 사본 동조정).
- **ST-05** 〔낮음〕 *WCAG 1.4.11 Non-text Contrast.* 체크박스 인디케이터 테두리(#adb3bb)
  흰 배경 대비 2.11:1. (체크 상태는 PRIMARY 채움으로 구별되므로 low.) → 테두리 3:1 상향.
- **ST-14** 〔낮음〕 *Windows Forced Colors.* 전역 QSS 고정 hex 가 `QPalette` 미참조 →
  고대비 모드 무시. (기본 팔레트는 AA 튜닝돼 판독 실패는 아님 → low.) → 고대비 감지 시
  취약 토큰(MUTED·테두리)부터 palette 경로.

### T4. 프로그램적 접근성 시맨틱 부재 〔중간〕 — ST-06, ST-07, ST-18
`setAccessibleName` 이 저장소 0건. 보조기술이 이름·라벨·상태를 얻지 못한다.

- **ST-06** 〔중간〕 *WCAG 4.1.2/1.1.1.* 글리프 전용 `◀`/`▶` 레코드 이동 버튼에 접근가능
  이름·툴팁 없음(`txt_view.py:112-119`). → `setAccessibleName`+`setToolTip`.
- **ST-07** 〔중간〕 *WCAG 1.3.1/4.1.2/3.3.2.* SaveJobPage·txt 컨트롤 줄·나라 ServiceKey 가
  라벨-입력 인접 배치만, `setBuddy` 없음. ServiceKey 는 placeholder 의존이라 채우면 라벨
  소멸. (대조: `ManualRecordDialog` 은 `QFormLayout.addRow` 로 정상.) → `addRow`/`setBuddy`.
- **ST-18** 〔낮음〕 *WCAG 4.1.3 Status Messages.* 취득 결과·잠금 사유·완료 요약 등 동적
  라벨이 보조기술에 미통지. → 갱신 시 `QAccessibleEvent(Alert)` 발신(live-region 상당).

### T5. 키보드·포인터 조작성 〔중간〕 — ST-12, ST-15
- **ST-12** 〔낮음〕 *WCAG 2.1.1·Nielsen H7·Windows 니모닉.* `setShortcut`/`&`니모닉/
  `setDefault` 전무 → Enter 로 주 액션 실행 불가, F5 미배선. (기본 키보드 조작은 Tab+Space
  로 가능하므로 접근성 배제가 아닌 효율 손실 → low.) → 핵심 액션 니모닉·`QShortcut`·
  `setDefault`(파괴 확인은 취소 기본 유지).
- **ST-15** 〔중간〕 *WCAG 2.5.8 Target Size.* 레코드 체크박스 인디케이터 15px<24px, 매핑
  확정 체크박스 기본(더 작음) — 3표면 계통적. → 인디케이터 확대 또는 아이템 클릭=행 토글.

### T6. 시스템 상태 가시성 — UI 프리즈 〔중간〕 — ST-16, ST-17
- **ST-16** 〔중간〕 *Nielsen H1.* `WaitCursor`/`setOverrideCursor` 0건. 스키마 추출·데이터
  로드·컴파일·드리프트·풀 새로고침·미리보기(나라 서브소스 네트워크 포함)가 UI 스레드
  무피드백 실행 → 프리즈. (RC-12 `TaskWorker` 패턴 기존 존재.) → WaitCursor 래핑 또는
  `TaskWorker`+`QThread` 오프로드.
- **ST-17** 〔낮음〕 *Nielsen H1.* 나라 취득·풀 복원 네트워크 중 버튼 비활성/한 줄 라벨뿐
  (매트릭스는 `QProgressBar` — 내부 비대칭). → 매트릭스 진행바 위젯 재사용.

### T7. 오류 처리·용어·도움말 〔중간〕 — ST-20, ST-22, ST-26
- **ST-20** 〔낮음〕 *Nielsen H9·WCAG 3.3.3.* 실패 다이얼로그가 `str(exc)`
  (PermissionError/BadZipFile/WinError) 를 복구 안내 없이 노출. → VM에서 유형별 문구+조치로
  성형, 원시 exc 는 `setDetailedText` 접기(RC-16 번역층 GUI 확장).
- **ST-22** 〔낮음〕 *Nielsen H2.* 실행 게이트만 개발자 용어 '드리프트' 노출(preflight·배지와
  3표면 불일치). → "템플릿 구조가 확정 매핑과 달라졌습니다"로 치환.
- **ST-26** 〔낮음〕 *Nielsen H10.* 매핑 프로파일·누름틀·PARTIAL·조인·ServiceKey 발급 등
  도메인 용어에 도움말·툴팁·진입점 전무. → 개념 툴팁 + 헤더 도움말/키 발급 링크.

### T8. diff앱·나라 소소한 예방·인식 결함 〔낮음〕 — ST-30, ST-33, ST-34
- **ST-30** 〔낮음〕 *Nielsen H8.* 나라 '다시 시도'가 '가져오기'와 동일 동작(중복 컨트롤).
- **ST-33** 〔낮음〕 *Nielsen H5.* diff 구판=신판 동일 파일 비교 미차단 → 무의미 비교가
  '변경 없음'으로 정상 결론처럼 확정.
- **ST-34** 〔낮음〕 *Nielsen H6.* 최근 비교가 basename 만 표시 → 다른 폴더 동명 파일 구별
  불가(전체 경로 툴팁 없음).

---

## 권장 조치 시퀀스 (임팩트/비용 비율순)

1. **1단계 — 저비용·고임팩트(단일출처·QSS 국소 편집):** ST-04 MUTED 하향 + ST-05 인디케이터
   테두리 상향(재생성 1회) · ST-03 `:focus` outline · ST-22 용어 치환 · ST-06 접근가능 이름.
2. **2단계 — 기존 패턴 수평 전개(데이터 손실 방지):** ST-08 위저드 닫기 게이트 · ST-09 풀
   등록 exists 게이트 · ST-21 실행 중 닫기 가드 (모두 `confirm_destructive` 재사용).
3. **3단계 — 상태 가시성:** ST-16 동기 IO WaitCursor/오프로드 · ST-17 네트워크 진행바 ·
   ST-07 폼 버디 연결 · ST-18 상태 라벨 Alert (공용 헬퍼로 systemic 적용).
4. **4단계 — 창 관리(중비용):** ST-10 싱글턴/중복 억제 · ST-11 지오메트리 지속 헬퍼 ·
   ST-12 니모닉·QShortcut·setDefault.
5. **5단계 — 구조 리팩터(고비용, 마지막):** ST-01 셸 창 전환 — 다른 결함 마감 후 착수.
6. **6단계 — 저심각 마감:** ST-15 · ST-14 · ST-20 · ST-26 · ST-30 · ST-33 · ST-34.

---

## 부록 A — ADR 정당화로 제외 (재발견 방지)

다음 2건은 관찰은 사실이나 **ADR이 의도적·방어 가능하게 정한 정책**이라 결함 아님. 다음
라운드가 재발견하면 여기를 참조해 기각한다.

- **ST-27** — 파괴적 삭제·`apply_fieldize` 제자리 변환에 undo/휴지통 없이 확인 게이트만.
  → **ADR-E**(차단 모달=진짜 비가역 작업에만; default=취소·명시 라벨) + confirm-or-alarm
  (허용 전이=확정요구·실패표시 둘뿐). `apply_fieldize` 는 `scan_preview`→`apply` 2단계
  dry-run 을 추가로 가짐. 잔여 저비용 개선: 결과 문구에 복구 경로 안내(권고, 정책 불변).
- **ST-28** — 비차단 조건 `missing_columns` 에 '[치명]' 어휘.
  → **ADR-L**(구조 드리프트 차등 처방: 소스-구조 드리프트는 loud 하되 실행-스코프, 처방은
  MISSING_MARKER; 템플릿-구조만 하드게이트) + confirm-or-alarm('시끄럽게 알려라' 분기).
  두 메시지가 결과를 텍스트로 구별하므로 H9 충족.

## 부록 B — 기각 10건 (반증 사유 요약)

ST-02·ST-13·ST-19·ST-23·ST-24·ST-25·ST-29·ST-31·ST-32·ST-35. 상세 반증은 추적 표의
제목 열 참조. 공통 패턴: ① 멀티윈도 모델 오독(상시 home 앵커 미인지 — ST-02), ② 이미
존재하는 텍스트/어휘/커서 신호 미인지(ST-13·19·29·32·35), ③ 외부 표준 오귀속(H7↔발견성,
Fluent 메뉴바 관행 — ST-24·25), ④ 네트워크 이전 fail-closed 검증 미인지(ST-23), ⑤ ADR
반대 처방(ST-31: 빈 상태 CTA 가 ADR-E/H loud-missing 은폐).

## 부록 C — ST-33 재분류 (조치 중 발견)

**ST-33**(diff 구판=신판 동일 파일 가드)은 조치 착수 시 **RC-32 와 충돌**함이 드러나
재분류했다(반영 커밋 `6f209fc`). 동일 파일 비교를 차단하는 경고 모달을 넣었으나,
`hwpxdiff` 는 이미 **RC-32** 로 변경 0건을 `NO_CHANGES_MESSAGE`(명시 문장)+KPI(0/0/0/0)로
**정직하게 확정**한다(조용한 오도 없음 — 회귀 테스트 `test_diff_zero_changes_shows_shared_
no_changes_copy` 가 같은 파일 비교의 이 흐름을 고정). 즉 발견이 우려한 '무의미 비교가 조용히
확정'은 RC-32 가 이미 완화했고, 별도 차단 가드는 그 의도된 zero-changes 흐름과 정면 충돌한다.
→ 가드 철회, 발견을 **기각 계열(기존 설계로 완화)** 로 재분류. ST-34(최근 비교 경로 툴팁)는
충돌 없어 착지. **교훈**: 소스 기반 리뷰가 놓친 인접 결정(RC-32)은 조치 착수(코드 접촉) 시
드러난다 — 검증 단계에 회귀 코퍼스 대조를 더 실으면 조기 포착 가능.
