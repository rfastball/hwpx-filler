# data-first 봉합 지도 (V6 → master)

**문서 상태: 현재 정본** — `lab/ui-reboot`의 `docs/core-workflow-integration-plan.md`(봉합 계획)
단계 1 산출물. 워크플로 계약 정본은 랩의 `docs/core-workflow.md`(태그 `prototype-v6-freeze`),
이 문서는 그 계약과 master 실물 사이의 **소유권 대조표**만 소유한다. 인용의 `lab:`은
동결 시점 랩 워크트리, 무접두는 이 브랜치(master 계열) 기준이다.

## 0. 총괄 판정

1. **방향 반전이 봉합의 본질이다.** master는 작업-우선이다 — `RunViewModel(job)`이
   생성자에서 job을 요구하고(`run_state.py:203-207`), 작업 전환(`_do_select_job`,
   `screen_job.py:536`)이 데이터·선택·필터를 **파기**한다(`:554-566`). v6는 데이터-우선이다 —
   데이터가 세션 소유이고 작업 전환에도 보존된다(계약 §18.2 보존 목록·§19.10 무효화 규칙).
2. **계획의 "링1 두 조각" 가정은 유지되나 세 번째 링2 조각이 추가로 필요하다**:
   세션 데이터 소유권 승격(작업 전환에서 데이터·선택 생존). 계획 §4가 이에 맞게 개정됐다.
3. **기존 characterization과의 계약 충돌 2건** — 초기 선택(전체→0건), 표시·실행 순서
   (원본 오름차순→최신 행 먼저 + 표시순 투영). 둘 다 v6 계약 채택으로 확정
   (충돌 B는 파일명 순서 의존 귀결까지 인지한 사용자 확정, 2026-07-26 — §2 상세).
   기존 테스트 개정은 각 행동을 바꾸는 커밋에 동반한다.
4. 그 외는 재사용이 지배한다: 게이트(`GateState`/`RunStatus`), 필터·행선택
   (`DataZoneMixin` 13액션), 생성(`generate`+`GenerationPlan`+덮어쓰기 왕복), 풀 마운트,
   세션 가드. **v6 shadow-backend는 전량 폐기**(§4).

## 1. 8열 봉합 지도

약어: 게이트열의 D=`test_web_dom_contract.py`, R=`action_registry.py`, U=`docs/UI_CONTRACT.md`,
S=selftest 프로브, C=characterization(기존 테스트 개정/신규).

| # | 행동/상태 | 현재 Python 소유자 | V6 JS 소유자 (lab) | 재사용 | 결정-미구현 (계약 §) | 폐기 v6 | 슬라이스1 | 갱신 게이트 |
|---|---|---|---|---|---|---|---|---|
| 1 | 파일 inspect·시트 확정·마운트 | 직접 브리지 `pick_data_file`→`JobController.load_data_path` `screen_job.py:475`→`RunViewModel.load_data` `run_state.py:249`→`resolve_file_source` `:162`; 시트 `load_data_sheet` | `inspectFile` v6.js:2197, `loadCandidate`:2181, `commitPreparedMount`:2144 | 브리지·리졸버·다중시트 확정 게이트 전부 | §18.2 원자 전환(성공 전 현재 runtime 미파기 — 현 구현 대조 확인), commit 뒤 초기화 규칙 | `commitPreparedMount`류 인메모리 배선 :2136-2226 | **포함** | U·S·C |
| 2 | 풀 항목 마운트 | dispatch `load_pool` → `RunViewModel.load_pool_item` `run_state.py:261`, `_after_pool_load` `screen_job.py:789` | localStorage `DATASET_POOL_KEY` v6.js:2064 | 전부 | — | localStorage 참조 저장 :2086 | **포함** | C |
| 3 | 마운트 직후 초기 상태 | `SelectionModel(count, all_selected=True)` `selection_state.py:14` — **전체선택** | `emptyRecordRange` v6.js:234 — **0건**·`sourceDesc` | `SelectionModel(count, all_selected=False)` 인자 이미 존재 | §18.2 commit 뒤 선택 0·최신 행 먼저 — **충돌 A, v6 채택** | `resetDataOwnedState`:2136 | **포함** | C (`test_webapp_job.py:95` 개정) |
| 4 | 레코드 검색·필터·행 선택 | `DataZoneMixin` 13액션 `data_zone.py:70-218` (자모 부분일치·엑셀식 필터) | `filteredRecordIds`:382, `setRecordSelection`:458, `headerSelectionState`:405 | 13액션 전부 | §18.10 잔여 대조: 헤더 체크=가시결과만 가산/해제, 필터 밖 선택 표본 3+«외 N건» 고지(침묵 금지) | 필터·선택 JS 재계산 전부 | **포함** (표본 고지는 대조 후 판단) | R(기존)·C |
| 5 | OrderedSelection (실행 입력 순서) | `SelectionModel.selected_indices` `selection_state.py:32` — **원본 오름차순** | `orderedSelectedRecords` v6.js:398 — **전체 표시순서 투영** | 모델 골격 | §2·§18.10 — **충돌 B, v6 채택**: 실행 입력=표시순 투영, 기본 `sourceDesc`(최신 먼저) | — | **포함** | C (`test_selection_state.py:37` 개정) |
| 6 | 작업 후보 계산 (호환성) | **부재** — 역방향 산출 코드 0. 유사물은 정방향 `default_dataset_ref`(`_auto_aim_default` `screen_job.py:581`)와 media 필터뿐 | `compatibilityFor` v6.js:521-542, `compatibleWorks`:574, Top5 `rankAvailableWorks`:798 | `job.source_keys()` 소비처 재사용 | **§18.4** 단일 출처(required만 검사·선택필드/새 열 무해), **§18.1** 데이터 준비 전 계산 금지, §18.4 available≠실행 보장, **§19.1** mode=확장자만·unsupported fail-closed, §19.7 전역 건강과 분리 | mock fixture `works`/`fieldDefs` :11-215, `libraryHealthFor` 구동 플래그 | **포함** (최소판: HWPX+required⊆fields; Top5 랭킹·전역 건강은 후속) | C·U |
| 7 | active work 명시 선택·전환 | `_do_select_job` `screen_job.py:536` — 전환=데이터·선택·필터 **파기** + 무장 시 confirm 왕복 `:547-550` | `selectDocumentWork` v6.js:963 — 데이터 보존, 실행 증거만 무효화 | confirm 왕복 골격, `vm is None` 분기 `:405-415` | **§18.2 보존 계약 + §19.10 무효화 규칙 — 신규 링2 조각**: 데이터·선택을 세션 소유로 승격, `RunViewModel` 재생성 시 datasource·records 재주입(`load_data` 재사용); §18.3 마운트 후 활성 선정(호환 1개 자동 등)은 후속 | `invalidateRunEvidence`:437, `requestValidation`:954 | **포함** (명시 선택만; §18.3 자동 선정 후속) | R(액션 재정의)·U·C·S |
| 8 | 게이트·검증·필드 배지 | `RunViewModel.refresh`→`RunStatus` `run_state.py:367-395`, `_compose_gate`:436, 스냅샷 `{enabled,level,text}` `screen_job.py:463-467` | `renderValidation` v6.js:920-931 — **JS가 disabled 재계산 (독버섯)** | `GateState`/`RunStatus` 전부, 스냅샷 모양 그대로 | 무작업+데이터有 상태의 게이트 문안(무선택/무작업/비호환 3구분, §18.4) — `vm is None` 분기 확장 | `renderValidation` 판정 로직 전부 (문안 3구분만 계약으로 이식) | **포함** | C·S |
| 9 | 생성 실행·덮어쓰기 | 직접 브리지 `generate` `screen_job.py:835`, `build_generation_plan` `run_state.py:595`, `output_conflicts`:576 + `needs_overwrite` 왕복 | `runCurrent` v6.js:1909 + `mock-backend.js:173-231` | 전부 그대로 | — | mock 실행 전부 | **포함** | U(기존)·S |
| 10 | 결과 표시 | `generate` 반환 dict `screen_job.py:954-970` (스냅샷 밖, 브리지 반환값 렌더) | `renderResult` v6.js:1924 (완료/부분/실패 3태), `retryOne`:1939 | 반환 dict 전부 | 3태 구획 표현은 커밋 4에서 v6 골격 참조 | mock 결과 모양, `retryOne`(단건 재시도=후속) | **포함** (재시도 제외) | D·S |
| 11 | 영속: 즐겨찾기·최근 사용·마운트 참조 | 즐겨찾기·사용기록 상당물 부재; 데이터 참조는 `default_dataset_ref` 존재 | localStorage 4키 v6.js:2063-2067, `markWorkUsed`:985 (§19.4 결과 사건만 기록) | — | §19.4는 결정 완료·구현은 후속 슬라이스 | localStorage 전부 | 제외 | — |
| 12 | 제외군: TXT 작업대(`setupWorkbench`:1954)·preview approval(:239,1879-1905)·편집 deep-link/EditContext(:589,1754)·revision(:1823)·문서 브라우저/라이브러리(:855,1087)·템플릿 전환(:1397-1636) | (해당 없음/기존 화면 유지) | 좌표는 좌측 | — | 각 §14~§19 결정은 유효, 구현은 후속 | preview.required/approved 게이팅 | **제외** (계획 §5 목록) | — |

## 2. 계약 충돌 2건 — 채택 판정과 파장

**충돌 A — 마운트 직후 선택 상태.** 현재: 전체선택(`test_webapp_job.py:95`,
`test_selection_state.py:8`). v6 §18.2: 선택 0건. **v6 채택**(계획 §5 첫 슬라이스 정의에
이미 포함). 파장: `load_data_path:490`·`_after_pool_load:793`의 `SelectionModel(len(records))`
호출에 `all_selected=False` 명시 + 기존 테스트 2곳 개정. "선택 0건 → 게이트 닫힘"은
기존 `test_select_none_closes_record_gate:538`이 이미 고정하므로 초기 상태 쪽만 추가.

**충돌 B — 표시·실행 순서.** 현재: 원본 오름차순 고정(`selected_indices`
`selection_state.py:32`, `test_selected_records_preserves_order:37`). v6 §18.10·§2:
기본 표시 순서 `sourceDesc`(최신 행 먼저), OrderedSelection=**전체 표시순서에 선택 투영**
= 실행 입력 순서가 표시 순서를 따른다.

**사용자 확정(2026-07-26): v6 계약 채택 — 실행 결과는 스냅샷을 SoT로 하여 보이는
정렬순으로 출력한다.** 화면=실행 일치(WYSIWYG)가 목업 작성 판단과 일치.
**인지하고 수용한 귀결**: 파일명이 순서의 함수다 — 순번 토큰(`naming.py:66 _fmt_seq`)과
동명 꼬리표(`naming.py:115 _dedupe`, `_1`·`_2` 레코드 순서대로 부여)가 실행 순서를 따르므로,
같은 선택 집합이라도 실행 시점의 정렬 상태에 따라 파일명·결과 나열·원장 기록 순서가
달라진다. 완화 의무: 결과·미리보기 표면이 실행 순서를 그대로 보여줘 사용자가 순서를
화면에서 확인한 것이 곧 확정이 되게 한다(confirm-or-alarm — 보이는 것=실행되는 것).
구현: `SelectionModel` 투영에 표시 순서 주입(또는 컨트롤러가 표시순 인덱스열을 계획에
전달), `GenerationPlan.indices`가 표시순을 운반.

**(비충돌) 작업 전환 시 데이터 파기 → 보존.** 현재 계약(전환=세션 파기+무장 confirm,
`test_guard_blocks_job_switch_until_confirmed:1082`)은 작업-우선 전제의 산물이다.
data-first에서는 §18.2가 보존을 명하므로 전환은 **RunViewModel만 재생성**하고
데이터·선택·필터는 세션이 보유한다. 무효화는 §19.10 규칙(실행 증거만 폐기)로 대체.
기존 가드 테스트는 삭제가 아니라 **재정의 승계**한다(삭제는 의무를 상속한다 —
무장 상태에서 잃는 것이 "세션 전체"에서 "실행 증거"로 줄었음을 문안까지 정직하게).

## 3. 신규 구현 목록 (계획 §4 커밋 배정)

| 조각 | 내용 | 커밋 |
|---|---|---|
| 링1-1 | 최소 호환성 판정: `compatibility_for(job, fields)` — §18.4 이식, required source ⊆ 현재 fields, txt·unsupported 제외(§19.1), 데이터 미준비 시 미계산(§18.1). 배치 `gui/` 신규 모듈 | 커밋 2 |
| 링1-2 | 작업 미선택 스냅샷: 데이터 마운트됨+active work 없음 상태의 후보 목록·게이트 문안(무선택/무작업/비호환 3구분) | 커밋 2 |
| 링2-3 | **세션 데이터 소유권 승격**: datasource·records·`SelectionModel`·필터를 작업 전환에서 생존시키는 `JobController` 재배선 + `RunViewModel` 재생성 시 재주입 | 커밋 3 |
| 배선 | 신규/재정의 dispatch 액션(작업 선택 의미 변경, 후보는 스냅샷 동승) + registry·UI_CONTRACT 갱신 | 커밋 3 |
| UI | v6 골격 이식(데이터 영역·레코드 표·후보 구획·active work·게이트·결과 3태) — job.js·app.css 조각 이식, 토큰 단일 출처 유지 | 커밋 4 |

## 4. 폐기 목록 (v6 shadow-backend — 이식 금지)

`requestValidation`(954)·`invalidateRunEvidence`(437)·`finishRunInputMutation`(444),
`commitPreparedMount` 인메모리 배선(2136-2226), `preview.required/approved` 게이팅(239),
mock 실행·결과(`runCurrent` 1909 이후, `mock-backend.js` 전체), localStorage 4키(2063-2067),
`renderValidation`의 disabled 재계산(920-931), fixture `dataFiles`/`works`/`fieldDefs`(11-215),
`testScenarios`(253)·성능 하니스(2297-2306). — 정책 문장만 계약으로 살아남고 코드는 죽는다.

## 5. characterization 현황 (커밋 1 원재료)

**이미 고정됨(재사용)**: 선택 0건 게이트 닫힘(`test_webapp_job.py:538`), 데이터 없음
게이트(`test_run_state.py:182`·`test_webapp_job.py:70,600`), GenerationPlan 불변(`:278`),
덮어쓰기 조회(`:259`), 링1 위임 불변식(`test_webapp_job.py:607` + #87 아키텍처 가드),
무선택 작업 스냅샷(`:551`).

**개정 필요(충돌 A·B·전환 보존)**: `test_webapp_job.py:95`(전체선택→0건),
`test_selection_state.py:8,37`(기본값·순서), `test_guard_blocks_job_switch_until_confirmed:1082`
(파기→보존+증거 무효화로 재정의 승계).

**신규 필요**: "데이터 없음"과 "호환 작업 없음"의 구분, 작업 전환 시 데이터·선택 생존,
호환성 판정 경계(선택 필드 미연결·새 열 무해), 표시순 투영 실행 순서.

## 6. 원재료

- 계약: lab `docs/core-workflow.md` §2·§18.1-§18.11·§19.1-§19.11 (주의: 전역 건강 분리는
  §19.7이다 — 계획 문서의 "§20" 표기는 이 문서 기준으로 정정)
- 시안 계약 테스트: lab `tests/test_core_workflow_v6_prototype.py` 26건(전부 정적 텍스트
  단언 — 통합 브랜치로 가져오지 않고 계약 추출 원재료로만 소비)
- master seam: `gui/run_state.py`·`gui/selection_state.py`·`webapp/screen_job.py`·
  `webapp/data_zone.py`·`webapp/action_registry.py`·`docs/UI_CONTRACT.md`
