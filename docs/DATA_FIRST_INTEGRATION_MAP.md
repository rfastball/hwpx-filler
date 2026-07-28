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

## 7. v6 상태전이 결함 보고서 triage (2026-07-26)

외부 리뷰 보고서(F-01~F-08 + C-01·C-02, 원문은 비공개 원장
`research-private/v6-state-transition-review.md`)의 봉합 관점 3분류. **판정: 첫 슬라이스
(PR #302) 구현 범위(마운트·전환·선택·무효화·후보·prework 게이트) 직격 결함 없음** —
F-02의 교정안(자동 선택 금지)은 #302가 §18.3 자동 선정을 후속으로 미뤄 이미 준수 상태.

| ID | 분류 | 귀속 | 조치 |
|---|---|---|---|
| F-01 새 필드→문서 지목 | ② 계약 | 슬6 | deep-link 권위 규칙(targetAuthority) 계약 개정 후 구현 |
| F-02 유일 호환 자동 선택 | ② 계약 | **슬2 스코프 변경** | §18.3 개정: 자동 선택 삭제 → suggestedWorkId **추천**(카드 강조, activeWorkId는 사용자 선택만). preferredWorkId(명시 사건 유래)만 자동 허용 |
| F-03 dataFamily 추론 분기 | ①mock+② 계약 | 슬6 + §4 폐기 추가 | dataFamily 추론은 **이식 금지 명문**(백엔드 정본에 권위 없음 — 보고서도 확인). 연결 복구/신작업 분기는 identityDecision 사용자 택일로 계약 개정 |
| F-04 라이브러리 편집이 runtime 데이터 차용 | ② 계약 | 슬6 | EditDataContext(문맥 명시 선택) 계약 편입. 현 master 에디터는 명시 로드라 기존 표면 무해 |
| F-05 완료 결과 '이번 생성에 적용' | ② 계약 | 슬5·6 | runPhase·mutationScope 계약 편입 — completed Run 불변, 새 draft/기본 규칙 분기만 |
| F-06 승인 압축 | ② 계약 | **슬5 재정의** | PreviewRequired → ReviewRequirement(위험 분류+증거 정책+fingerprint)로 확장해 구현 |
| F-07 구조 변경을 값 미리보기로 승인 | ② 계약 | 슬8(+슬5) | 구조 검토 요구 편입. master 는 구조 드리프트 danger 게이트가 이미 fail-closed — 승인 표면만 신설 |
| F-08 TXT per-record vs 전역 승인 | ② 계약 | **슬4 중단점 A 의제** | per-record 검토가 복사 gate 권위 — 기안 관계 토의에 편입 |
| C-01 파일명 집합 검증 | 조건부 | 슬5 대조 | master 는 `plan_output_names` 순차 dedupe·`output_conflicts`·미해소 토큰 게이트가 집합 검증 상당 — 충족 여부 슬5에서 확정 |
| C-02 승인 일괄 폐기 | 조건부 | 슬5 | ReviewRequirement fingerprint 도입 시 차등화 |

**로드맵 영향**: 순서 불변. 슬5·6의 스코프가 커진다(링1 신규 상태 계약 4종 —
targetAuthority·mutationScope·EditDataContext·ReviewRequirement, 보고서 §8). 신규 절대
불변식 12종(보고서 §10)과 수용 시나리오(§11)는 해당 슬라이스 계약 개정 시 core-workflow.md
로 흡수한다.

**부수 발견 1건**: 보고서 §7이 안전 반례로 꼽은 "기본 데이터 전환=사용자 확인 선행"과
master #53-A 자동 조준(확인 없음+재진술)이 어긋난다 — 완화 조항(전면 가시성+무반복+틀리면
보이는 추측) 해당 여부를 슬2에서 재론.

## 8. 슬라이스 2 — 활성 작업 선정 + 메인 Top 5

계약 §18.3(F-02 개정)·§18.5·§19.3·§19.4. 백엔드 확장 = 즐겨찾기 영속(Job 가산 필드)
+ 최근 사용 랭킹(기존 `last_run_at` 재소비). 계획 §8 로드맵 2행의 착지.

### 8.1 8열 지도 재판정 (슬라이스 1 표의 갱신분)

| # | 행동/상태 | 현재 Python 소유자 | V6 JS 소유자 (lab) | 재사용 | 결정-미구현 | 폐기 v6 | 슬라이스2 | 갱신 게이트 |
|---|---|---|---|---|---|---|---|---|
| 6' | 후보 **정렬·Top 5** | `candidate_rows` 입력 순서 보존(슬1에서 정렬 유보 명문) | `rankAvailableWorks` v6.js:798 | 후보 판정(`compatibility_for`) 그대로 | §18.5·§19.3 3단 정렬(즐겨찾기→최근 사용→미사용)·전체 상위 5 | mock `work.lastUsedAt`·`favoritedAt` fixture | **포함** | C |
| 7' | 활성 작업 **선정**(자동→추천) | `_do_select_job` 명시 선택만(슬1) | `selectDocumentWork`+자동 선택 | 명시 선택 경로 전부 | §18.3 **개정판**(아래 8.2 ①) — 추천은 강조 표지일 뿐 `job_name` 무변경 | v6 자동 선택 분기 | **포함** | R·U·C·S |
| 11' | 영속: 즐겨찾기·최근 사용 | 즐겨찾기 **부재**, 최근 사용 = `Job.last_run_at`(완주 스탬프, #129) | localStorage `favoritedAt`·`work.lastUsedAt` | `JobRegistry.mutate` 잠긴 읽기-수정-쓰기·`stamp_last_run` 선례 | §19.4 — `Job.favorited_at` 가산 필드(계획 §8 닫힌 결정) | localStorage 4키 | **포함**(즐겨찾기·최근 사용만; 사용 기록 별도 저장소는 없음) | C |
| 12' | 제외 존치 | — | — | — | — | — | 전체 문서 브라우저(슬3)·확인 필요 탭·전역 라이브러리·작업 방식 구획의 **2방식 렌더**(슬4에 txt 합류 전까지 1방식 = 평면 퇴화) | — |

### 8.2 계약 개정·판정 3건 (이 슬라이스에서 확정)

**① §18.3 자동 선택 → 추천 (F-02 반영, 계획 §8 선행 관문).** 개정 규칙:

```text
preferredWorkId(명시 사건 유래)가 새 DataTarget 에서 available  → 활성 선정 허용
기존 activeWorkId 유지                                        → 유지(비호환이어도 내려놓지 않는다)
그 밖에 available 이 정확히 1개                                → suggested(추천 표지)만, 활성은 사용자 클릭
available 0개 또는 2개 이상                                    → 추천 없음
```

- **자동 선택 삭제**: 유일 후보라도 `job_name` 을 앱이 대신 정하지 않는다 — 추천은 카드
  강조 + 「추천」 표지이고 활성 전이는 사용자 클릭 사건뿐이다.
- **preferredWorkId 는 이번 슬라이스에 구현하지 않는다**(명시 사건의 원천인 문서 브라우저
  ·기본 데이터 확인 흐름이 슬3 소관). 규칙만 박제하고 seam 은 비워 둔다 — 없는 기능을
  있는 척하지 않는다.
- **비호환 활성 작업을 비우지 않는다**(v6 원문 "activeWorkId 비움"의 개정): master 는
  소스 누락을 `RunViewModel.refresh` 가 치명 사전검증 + 닫힌 게이트로 **시끄럽게** 말한다
  (`run_state.py:487`). 사용자가 고른 작업을 앱이 조용히 내려놓는 편이 오히려 파괴적이다.

**② §19.4 "부분 성공도 최근 사용" vs master 완주 스탬프 — 충돌 C, master 의미 유지.**
계약 §19.4 는 한 건이라도 성공하면 최근 사용으로 기록하라 하지만, 같은 절이 시안의
`work.lastUsedAt` 은 mock 이며 **백엔드 `Job.last_run_at` 의 성공 실행 의미를 덮어쓰지
않는다**고 못 박는다. 계획 §8 닫힌 결정도 "최근 사용 HWPX = 기존 `last_run_at` 재사용"이다.
그래서 **완주(전건 성공) 스탬프를 그대로 쓴다**: 완주 술어는 세션 가드 무장 해제와 단일
출처이고(#129 결정 7), 부분 성공을 "사용"으로 승격하면 완료의 정의가 둘로 갈라진다.
표면 문안도 "마지막 성공 실행"(§18.5 카드 항목)으로 정직하게 맞춘다. 별도 사용 기록
저장소는 만들지 않는다(제2 정본 금지).

**③ #53-A 자동 조준 재론(지도 §7 부수 발견) — 현행 유지.** 보고서 §7 의 "기본 데이터
전환 = 사용자 확인 선행"은 **이미 데이터가 있는 상태의 전환**을 말한다. master 의 자동
조준은 ⓐ 세션에 데이터가 없을 때만 발동하고(파기 대상 0 — `screen_job.py:644`),
ⓑ 결과를 데이터 라벨 + `data_notice` 로 전면 재진술하며, ⓒ 실패는 조용한 폴백 없이
warn 으로 말한다. 완화 조항(전면 가시성·무반복·틀리면 보이는 추측)의 요건을 충족하므로
확인 왕복을 추가하지 않는다. 슬2 의 추천은 `job_name` 을 바꾸지 않으므로 자동 조준을
유발하지도 않는다(추천 → 자동 로드의 연쇄 없음).

**④ 카드 부제의 작업 방식 텍스트(§19.3 마지막 문장) — 이번 슬라이스에서는 생략.** 계약은
한 방식만 있어 평면 퇴화할 때도 카드 부제에 작업 방식을 남기라 한다. master 는 화면이
매체로 갈라져 있어(「작업」=HWPX·「기안」=TXT, 3부 결정 13) 후보 전원이 자명하게 HWPX 라,
카드 5장에 같은 라벨을 반복하면 밀도만 먹고 정보가 없다(마일스톤 L 세로 밀도). TXT 가 이
구획에 합류하는 슬라이스 4 에서 **구획 헤더와 함께** 들어온다 — 그때가 이 문장이 막으려던
모호함이 실제로 생기는 시점이다.

### 8.3 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(지도·계약 개정 기록) |
| 2 | 링0: `Job.favorited_at` 가산 필드(version 불변·`from_dict` 하위호환·지문 제외·복제 미계승) + `JobRegistry.set_favorite` 잠긴 갱신 |
| 3 | 링1: `work_candidates` 랭킹(§18.5·§19.3)·Top 5·추천(§18.3 개정) 순수 함수 |
| 4 | 링2: 후보 페이로드 확장(정렬·즐겨찾기·최근 사용·추천)·`toggle_favorite` 액션 + registry·UI_CONTRACT |
| 5 | UI: 후보 구획 카드(순위·즐겨찾기 토글·추천 표지·「외 N건」 정직 고지) + DOM 계약·selftest 프로브 |

### 8.4 리뷰 3라운드 근본원인 재분석 (정지 규칙 §8.1)

라운드 1~3의 P2 4건은 서로 다른 파일에서 났지만 한 뿌리를 갖는다: **정렬 축(즐겨찾기)을
새로 도입하면서 그 축의 상태 계약 네 면을 미리 정의하지 않았다.**

| # | 라운드 | 증상 | 미정의였던 면 | 영구 가드 |
|---|---|---|---|---|
| 1 | 1R | 같은 초 즐겨찾기 2건이 동률 → 이름순 추락 | **시각 정밀도** | 전정밀 스탬프 + 같은 초 회귀 |
| 2 | 2R | 상위 5 밖 작업에 별이 없어 승격 불가 | **표시 상한과 무관한 도달성** | 좌 목록 ⋮ 즐겨찾기 + 단일 전이 몸통 DOM 계약 + 순위 밖 승격 회귀 |
| 3 | 3R | 남의 자리를 덮으면 원점 메타가 남의 파일에 이식 | **메타의 주체**(원점 vs 저장 대상) | `_preserved_for_target()` 3갈래 + victim·새 이름 회귀 2건 |
| 4 | 3R | 왕복 중 두 번째 클릭이 멱등 재지정에 삼켜짐 | **지연 왕복 중의 의도** | `FAV_PENDING` 의도 직렬화 + selftest 의도열 프로브 |

5R 은 4R 픽스의 **정리 조건**에서 같은 뿌리(지연 중 의도)의 잔가지를 하나 더 냈다:
값 비교 정리는 같은 값이 다시 큐에 들면 최신 의도를 지운다 → 꼬리 식별로 교체. 여기서
대안 설계 하나를 **검토하고 기각**했다: "왕복 중 별을 비활성"(큐 자체를 없애 세 부품 →
한 부품). 기각 이유 = 5라운드 시점의 설계 교체가 새 결함 창을 열고, 현행 3부품에는
양성대조까지 세운 실행 가능 가드(selftest 발신열 프로브)가 이미 붙었다. 재론 조건: 이
표면에서 같은 뿌리의 결함이 한 번 더 나면 비활성 안으로 되깎는다.

**후속 슬라이스에 적용할 규칙**: 정렬·분류 축(최근 사용 정렬, 태그 facet, 보기 전환 등)을
추가할 때 위 4면 — 정밀도 / 절단과 무관한 도달성 / 상태의 주체 / 지연 중 의도 — 을 구현
전에 계약으로 적고, 각 면에 회귀를 붙인다. 3라운드가 증명한 것은 "축은 값 하나가 아니라
네 개의 계약면"이라는 점이다.

## 9. 슬라이스 3 — 문서 탐색·전역 라이브러리

계약 §18.6·§19.5(현재 데이터 문서 탐색)·§19.6(전역 문서 작업 라이브러리)·§19.7(전역 건강)·
§18.8(ReturnContext). 계획 §8: **무확장**(기존 재소비).

### 9.1 master 실물 대조와 판정

| 계약 | master 실물 | 판정 |
|---|---|---|
| §18.6·§19.5 사용 가능/확인 필요 탭 + 이름 검색 | **부재** — 슬2가 남긴 `more`/`needs` 수치와 「왼쪽 목록에서 고르세요」가 유일 출구 | **신설**(PR-1) — 슬2 고지의 정본 대체 |
| §19.6 browser+detail·보기 4종·모드 필터·group 구획·tag facet | 홈 = 카드 나열 + group-by 렌즈 + facet 칩(`HomeViewModel` 소유) | **개편**(PR-2, 별 PR — 리스크 티어 분리) |
| §19.7 전역 건강 5종 심각도 | 손상 격리(RC-05)·컴파일 배지·템플릿 부재는 있고 **단일 심각도 축은 부재** | 기존 신호의 **번역만**(새 판정 금지 — 무확장) |
| §18.8 ReturnContext | `window.Nav` + `preserve.js`(포커스·스크롤·캐럿) | 탭·검색어는 Python 세션 소유(판정은 Python), 스크롤·포커스는 기존 보존 기제 |

### 9.2 PR-1 확정 사항

- **표면 = `job` 화면 안 전용 시트**(별 라우트 금지): §18.6 이 "문서 만들기의 하위 화면이고
  상단 내비게이션은 계속 문서 만들기 활성"이라 명시한다. master 선례는 `#jobEditHost`(편집)와
  펼침 면(`dataSheet`·`jobConfirmSheet`)이다.
- **탭·검색 판정은 링1**: 탭 건수·필터 결과·검색 일치는 Python 이 내고 JS 는 그린다.
  검색은 **작업 표시 이름만**(§18.6 — 그룹·태그·매체·소스·경로는 대상 아님), 일치 규칙은
  앱 전역과 같은 자모 부분일치(`core.jamo` 재사용 — 별도 검색 어휘 발명 금지).
- **슬2 「확인 필요」 칩 구획은 이 시트로 이사**(삭제는 의무를 상속한다): 후보 줄은 순위 카드와
  「외 N건 · 문서 탐색」 출구만 남긴다.
- **선택은 여전히 명시 사건**: 시트에서 available 행을 누르면 `select_job` 이고, 데이터·선택·
  필터는 세션 소유라 그대로 산다(§18.6 마지막 문단 = §18.2 재확인).

### 9.3 리뷰 3라운드 근본원인 재분석 (PR-1, 정지 규칙 §8.1)

라운드 1~3의 P2 4건은 전부 **새 오버레이 표면의 생명주기**에서 났다. 새 시트를 만들면
네 계약이 딸려온다는 것을 몰라서(=적지 않아서) 하나씩 밟았다:

| # | 라운드 | 증상 | 미정의였던 계약면 | 영구 가드 |
|---|---|---|---|---|
| 1 | 1R | 탭 전환 재렌더에 포커스가 모달 밖으로 | **재렌더를 가로지르는 정체**(안정 id) | 탭·행·출구 id + selftest 포커스 생존 |
| 2 | 1R | 선택 뒤 포커스가 숨은 입력·body 로 | **전이와 왕복의 순서** | 닫기 직후 실 DOM 착지 + DOM 계약 순서 고정 |
| 3 | 2R | 생성 중 탐색 컨트롤이 살아 있음 | **전역 잠금의 범위**(오버레이 루트는 화면 루트 질의 밖) | setBusy 가 시트 루트도 훑음 + busy-lock 표식 3종 |
| 4 | 2R·3R | 실패 경로에서 면이 먼저 닫혀 문맥 상실 / 예약 유령 | **실패 경로의 문맥 보존** | 성사 뒤에만 닫기 + 예약 기제 제거(재유입 금지 계약) |

**후속 슬라이스 규칙**: 새 오버레이·시트·패널을 만들 때 위 4면(정체·잠금 범위·전이 순서·
실패 경로)을 구현 전에 적고 각 면에 회귀를 붙인다. 슬2가 남긴 축 4계약면(§8.4)과 같은
형식의 체크리스트다 — **새 표면도, 새 축도, 계약면 단위로 센다.**

부수 교훈(프로브): 두 프로브가 같은 `Bridge.call` 을 스텁하면 뒤 블록의 복원이 앞 블록의
발신을 삼킨다. 스텁은 **자기 액션만** 가로채고 복원은 "내 스텁일 때만" 해야 한다
([[gate-env-gotchas]] 프로브 교차오염의 새 표본). 또한 프로브가 프로덕션 순서를 흉내 내면
(여기선 Python push 를 대신 밀어 준 것) 실패를 가려 준다 — 리뷰가 그 마스킹을 잡았다.

### 9.4 PR-2b 착수 전 판단 — group-by 렌즈와 §19.6 보기의 충돌

PR-2a(백엔드)가 낸 `library` 투영을 홈 표면이 소비하려면 **기존 작업 브라우저**(group-by
태그 렌즈 + facet 칩, JOB_BROWSER_DESIGN D4·D5·D10)와의 관계를 먼저 정해야 한다. 둘 다
"목록을 나누는 축"이라 같은 화면에 그대로 겹치면 구획이 이중이 된다.

| 후보 | 내용 | 대가 |
|---|---|---|
| **A(권고)** | 보기 4종 = 정렬·구획 축(모든 작업만 **사용자 group** 구획), tag facet = 추가 필터 축(모든 보기와 AND), **group-by 렌즈는 은퇴** | 렌즈가 하던 "태그 축으로 구획" 이 사라진다 — 삭제는 의무를 상속하므로 facet 로 같은 좁히기가 되는지 확인하고 문안으로 고지 |
| B | 렌즈 유지 + 보기는 「모든 작업」에서만 렌즈에 양보 | 같은 화면에 구획 규칙 둘 — 사용자가 왜 어떤 때는 그룹, 어떤 때는 태그로 나뉘는지 설명 불가 |
| C | 렌즈를 보기 5번째 항목으로 흡수 | 축이 섞인다(보기=투영, 렌즈=구획) — §19.2 "화면당 primary grouping 하나" 위반 |

**권고 = A**(§19.2 "화면당 primary grouping 은 하나", §19.6 표의 보기별 투영과 정확히 일치).
은퇴 시 승계 의무: ①facet 칩은 그대로 살아 태그로 좁히기는 계속 가능 ②렌즈 영속값
(`active_group_by`)이 있으면 무시하고 새 축으로 착지 ③퇴화-코퍼스 불변식(태그 0개 = 오늘과
같은 평면)은 그대로.

## 10. 표면 전면 재작성 — 화면·상태 인벤토리와 재작성 슬라이싱

**프레이밍 전환(2026-07-27 사용자 확정)**: "master 표면에 v6 계약 조각을 이식"은 폐기됐다.
홈을 비롯한 화면의 **성격 자체가 바뀌므로** 부분 교체가 아니라 표면 전면 재작성이고, 백엔드는
목업이 요구하는 상태를 내도록 재배치한다. 그래서 무효인 것은 **슬라이싱과 표면 계획**
(계획 §8 로드맵, 이 문서 §9.1~§9.4의 표면 전제)이고, **계약 판정 자체는 전부 유효**하다
(§8.2 4건·§9.2·§7 triage). 자립 핸드오프는 `.claude/v6-surface-rewrite-handoff.md`.

### 10.0 절대 기준 (사용자 확정 2026-07-27)

| 축 | 정본 | 비고 |
|---|---|---|
| 화면 구조·구획·시각 문법 | lab `docs/core-workflow-ui-mvp-demo-v6.html` | 7화면 + 상단 2탭 + 오버레이 19종 |
| 상태·전이·불변식 | lab `docs/core-workflow.md` (§2~§13 v4 본체 + §18 v5 + §19 v6) | 목업과 어긋나면 **계약이 이긴다** — 목업은 계약의 한 렌더 |
| 이미 확정된 개정분 | 이 문서 §7 triage·§8.2 4건 | core-workflow.md 원문보다 **우선**(특히 §18.3 자동선택→추천, §19.4 완주 스탬프 유지) |
| v6.js shadow-backend | — | **이식 금지** 유지(§4) |

인벤토리 범위 = **7화면 전부**(문서 만들기·범위 편집기·문서 탐색·문서 작업 라이브러리·템플릿
바꾸기·편집기·TXT 작업대). 착수 범위와 순서는 §10.5 가 가른다.

### 10.1 v6 표면 인벤토리 (요구 상태·행동)

| # | v6 표면 | 요구 상태 | 사용자 행동·전이 |
|---|---|---|---|
| S1 | `screen-data` 「문서 만들기」(nav 1) | `dataState`(mountedDataRef·runtimeData·pendingMount·loadState·pinnedDataRefs)·`recordRange`·`activeWorkId`·`suggestedWorkId`·validation·preview/approval·result | 데이터 선택·시트 확정·검색·필터·행 선택·표시순서·문서 카드 선택·즐겨찾기·미리보기·생성·결과 닫기 |
| S2 | `screen-record-range` 「처리할 레코드 범위」 | `RecordRangeDraft`(진입 시 깊은 복제)·selected-only 토글·filter chips | 적용(=fingerprint 변화 시에만 증거 폐기)·취소(draft만 버림)·이탈 가드 |
| S3 | `screen-documents` 「현재 데이터에 사용할 문서」 | `documentBrowser{tab,query,scrollY,focusTarget}` + 탭 안 작업 방식 구획 | 탭 전환(←→)·이름 검색·available 선택=`select_job`·needsAction 6분기(§18.7) |
| S4 | `screen-library` 「문서 작업」(nav 2) | `libraryBrowser{view,modeFilter,query,tagFilters,collapsedGroups,selectedWorkId,scrollY,focusTarget}` + `libraryHealth` | 보기 4종·방식 필터·검색·태그 facet·그룹 접힘·행 선택(활성 작업 **불변**)·상세 행동(편집·문서 만들기에서 사용·복제·그룹 이동·태그 편집·삭제) |
| S5 | `screen-transition` 「템플릿 바꾸기」 | `templateTransitionDraft{stage,choice,fromMode,toMode,candidateFields,fieldDiff,dirty}` | 4단계(pick→impact→mapping→review)·fork/convert 택일·원자 커밋·어느 단계든 취소=draft만 폐기 |
| S6 | `screen-editor` 「문서 작업 편집기」 | `EditContext`(work·section·target·entryReason·evidence·returnContext) + `editSession{baseSnapshot,inheritedRunOverrides,patch,dirtySection}` + Template/Binding **판본** | 4탭(템플릿·필드 연결·표시·파일 이름·시험)·주 행동 2분기(이번 생성에 적용 / 기본 규칙으로 저장)·section 이동 시 적용·버리기·머무르기 택일 |
| S7 | `screen-workbench` 「TXT 검토·복사 작업대」 | 진입 시 OrderedSelection 고정 사본·세션 patch·복사 완료 사건 | 작업점 이동·원문/채운 모습 전환·복사(=최근 사용 기록)·자동 다음·기본 규칙으로 저장 |
| O1 | `previewDrawer` 대표 샘플 | 레코드별 값·파일 이름·적용 범위·approval | 레코드 이동·`결과 확인 완료`(승인)·생성 |
| O2 | 데이터 3종 다이얼로그 | `dataPicker`(현재/고정/다른)·`sheetPicker`·`pinData` | 파일 찾아보기·시트 확정(fail-closed)·이 데이터 고정 |
| O3 | 전환·가드 다이얼로그 | `dataSwitchGuard`(손실 열거)·`recordRangeGuard`·`sectionGuard`·`defaultDataSuggestion` | 손실 재진술 후 명시 택일 |
| O4 | 결과 복구 다이얼로그 | `unknownFailure`(증거 dl)·`runtimeFolder`·건별 재시도·레코드 filename override | 성공분 보존 + 실패 1건만 재실행 |
| O5 | `libraryGroupDialog`·`libraryTagDialog`·`objectMenu`·`newWorkDialog`·`workPatchDialog`·`helpDialog`·`deferredDialog`·toast | 각 표면 소유 | — |

### 10.2 8열 대조표 — 현 링1·링2 표면과의 판정

판정 3분류: **재사용**(그대로 쓸 것) / **재배치**(모양만 바꿀 것) / **신설**(새로 만들 것).
게이트열 약어는 §1과 같다(D=DOM 계약, R=action registry, U=UI_CONTRACT, S=selftest 프로브,
C=characterization).

| # | v6 요구 | 현 링2 표면 | 현 링1 소유자 | 판정 | 승계 의무·주의 | 슬라이스 | 게이트 |
|---|---|---|---|---|---|---|---|
| 1 | 상단 nav 2항목(문서 만들기·문서 작업), **새 home 없음**(§19 서문) | 좌 레일 5항목(`home`·`job`·`draft`·`tpl`·`pool`) | — | **신설**(셸 교체) | 5화면 전부 사망하고 2탭만 남는다(결정 1). 사망 시점은 각 승계처가 서는 슬라이스에 묶는다 — `home`=R4·`pool`=R3·`draft`=R6·`tpl`=R8. 그때까지 nav 는 정직하게 임시 4항목 | F2(셸)·F1·F6·F8(개별 사망) | D·U·S |
| 2 | 문서 만들기 2열(좌 현재 데이터 카드+범위 도구+표 / 우 문서 선택기·검증·실행) | `job` 4존(헤더·데이터·본문·완료)+좌 master 작업 목록 | `RunViewModel`·`SelectionModel`·`FilterModel`·`work_candidates` | **재배치** | R1 은 **우 세션 패널만** 2열로 재작성하고 **좌 작업 목록은 존치**한다. 목록 사망은 F2(라이브러리) 소관 — `home` 에 없는 동사가 6개(`rename_job`·`set_group`·`rename_group`·`disband_group`·`toggle_group`·`toggle_favorite`)라 지금 지우면 조용히 사라진다. 특히 목록 ⋮ 즐겨찾기는 「순위 밖 승격 도달성」(§8.4 2행)의 유일 경로다 | R1(패널)·F2(목록) | D·U·S·C |
| 3 | 현재 데이터 카드(파일·시트·행×열·출처·`이 데이터 고정`·`데이터 선택`) | `jobDataLabel`+`등록 데이터…`/`파일 선택…`+`jobDataNotice` | `resolve_file_source`·`source_label`·`DatasetPoolViewModel` | **재배치** | `data_notice`(#53-A 자동 조준 재진술)는 §8.2 ③ 판정대로 **현행 유지** | R1 | D·S |
| 4 | 표시순서 선택기(`sourceDesc`/`sourceAsc`) | 없음 — `_display_indices` 훅이 sourceDesc **고정** | `data_zone._display_indices`(훅 존재) | **신설**(값 1개 → 사용자 축) | 새 정렬 축이므로 §8.4 4계약면(정밀도·절단 무관 도달성·상태 주체·지연 중 의도)을 구현 **전에** 적는다. 순서가 파일명의 함수임(§2 충돌 B)을 표면이 재진술 | F3 | C·S |
| 5 | 검색·열 필터·행 선택·헤더 가산/해제·전체 해제·필터 밖 표본 3+「외 N건」 | `jobFilterSearch`·`jobFilterChips`·`jobSelStrip`·13액션 | `DataZoneMixin` 13액션·`FilterModel` | **재사용** | 표본 3+요약은 이미 `jobSelStrip`이 상시 가시 — 새 표면에서 **가시성 등급을 낮추지 않는다** | R1 | R(기존)·C |
| 6 | 문서 선택기 side-card: Top 5·작업 방식 구획·카드(이름·방식·연결 상태·마지막 성공 실행·즐겨찾기·⋮) | `jobCandsRow`(top·more·needs·suggested 4구획) | `rank_available`·`suggested_work`·`MAIN_TOP_N` | **재배치** | §8.2 ④ 유보 해제 지점: TXT 합류(F6) 전까지 **한 방식 = 헤더 없는 평면**이되 카드 부제의 작업 방식 텍스트는 §19.3대로 유지 | R1(구획)·F6(2방식) | D·C·S |
| 7 | `validationCard`+`run-scope-note`+실행 버튼(`N개 생성`) | `jobGate`+sticky `jobActionBar`+`jobRestate` 재진술+거울 `jobMirror`+`ack_field` | `GateState` 단일 산출·`RunStatus`·`field_states` | **재사용**(배치만 이동) | v6 `renderValidation`의 JS 재계산은 폐기 목록(§4) — 판정은 계속 Python. **거울·재진술은 존치**(결정 3) — side-card 와 병존하는 「본문 확인」 면 | R1 | S·C |
| 8 | 결과 3태(완료/부분/실패)+`결과 닫기`+더보기 | **착지**(F4) — `#jobResult` 3태 구획 + `jobGenLog`=「실행 기록」 | `generate` 반환 dict·`describe_result_error`·`describe_fill_note` | **재배치** | 3태 구획으로 옮길 때 로그 상자가 지금 말하는 것(FillNote 경고·원문 증거)을 잃지 않는다 | F4 | D·S |
| 9 | 부분 실패 복구(건별 재시도·레코드 filename override·`unknownFailure` 증거·외부 폴더 경계) | **착지**(F4) — 증거·성공분 보존·「실패한 N건만 선택」. **재시도 3종은 기각**(§10.14 ④ — 「실패한 N건만 선택」+폴더 변경으로 이미 도달) | `output_conflicts`·`plan_output_names`(집합 검증 상당) | **신설** | §10.2 계약: 성공분 **보존**·원인 미확정은 꾸며내지 않음. 이름 충돌은 master 가 **사전 계획**으로 풀어 실패가 되지 않는다(§10.14 ②) | F4 | D·U·S·C |
| 10 | 전문 범위 편집기(draft 복제·적용/취소·selected-only·이탈 가드) | `dataSheet` 시트(같은 상태 직접 편집 — draft 없음) | `SelectionModel`(index 기반)·`FilterModel` | **재배치+신설** | `RecordRangeState` 정본화(snapshot-local id·`snapshotOrdinal`·`shiftAnchorId` 정리 규칙)가 선행. 적용 시 **fingerprint 변화만** 증거 폐기 | F3 | D·R·U·S·C |
| 11 | 문서 탐색(탭 2·이름 검색·탭 안 작업 방식 구획·needsAction 6분기) | `jobBrowseSheet`(탭·자모 검색·사유 병기) | `browse_candidates` | **재사용+확장** | §19.5 작업 방식 구획과 §18.7 6분기(연결 복구·기본 데이터·재연결·새 작업·Template-only·손상)가 미구현 — 지금은 사유 병기까지 | F1·F6 | R·S·C |
| 12 | 데이터 선택 다이얼로그(현재/고정한/다른 + 파일 찾아보기)·시트 확정·`이 데이터 고정` | `poolModal`(등록 데이터)+네이티브 파일 피커+`sheetModal` | `DatasetPoolViewModel`(등록=고정 상당물) | **재배치** | v6 `pinnedDataRefs`는 별도 저장소를 만들지 않고 **Dataset Pool 재사용**이 계약(§18.2·확장 계약 `reuseBackend`). **`pool` 화면의 흡수처가 여기다**(결정 1) — 등록·보관/활성·삭제·손상 격리가 이 다이얼로그 안에서 전부 도달 가능해야 화면을 죽일 수 있다 | F1 | D·R·S |
| 13 | 데이터 전환 손실 가드(열거)·기본 데이터 전환 확인 | 구 T1 스위치 가드는 데이터-우선 전환으로 **사망**(파괴 소멸) | `_selection_guard` 술어 | **신설** | 데이터 **전환**은 여전히 `RecordRangeState`를 초기화하므로(§18.2) 손실 열거가 필요하다 — 가드 문안은 실제 사라지는 집합과 일치 | F1 | S·C |
| 14 | 전역 라이브러리 browser+detail(2-pane·보기 4·방식 필터·검색·태그 facet·그룹 구획·상세 표) | `home` 카드 나열+`homeBrowser`(group-by 렌즈+facet) | `HomeViewModel.library_*`·`library_health`(PR-2a 완비) | **신설**(표면) | §9.4 A안 승계 의무 3건 그대로: facet 존치·`active_group_by` 무시·퇴화-코퍼스 불변식. 2-pane 치수(≥921px·≥760px)와 상시 행동 고정은 §19.6 명문 | F2 | D·R·U·S·C |
| 15 | 전역 건강 5종 심각도·목록은 최고 1건·상세는 전 원인 | 손상 격리(`homeCorrupt`)·컴파일 배지·템플릿 부재 | `library_health()`(심각도+문구, 커버리지 테스트 동반) | **재사용** | 상세의 "전 원인" 열거는 아직 없다(목록용 1건만) | F2 | C |
| 16 | 미리보기 드로어(레코드별 값·파일 이름·적용 범위·승인) | 없음(문서 만들기 쪽) — 편집기에 값 미리보기 존재 | `MappingModel.preview`·`preview_empties`·`_pattern_preview`·`step_preview` | **재배치**(값 파생) + **신설**(승인 사건) | 승인은 F-06 개정판 `ReviewRequirement`(위험 분류+증거 정책+fingerprint)로 구현 — v6 `preview.required/approved` 게이팅은 폐기(§4) | F5 | D·R·U·S·C |
| 17 | 작업 방식 3값(`hwpx_generate`·`text_review_copy`·`unsupported`)·확장자 파생·fail-closed | `Job.media`(hwpx/txt/"")·`work_candidates` excluded·`library_mode_of` | 존재 | **재사용+어휘 통일** | `library_mode_of`는 **미연결을 hwpx로** 센다(리뷰 P2 근거) — v6 `unsupported`와 어휘가 갈리므로 "미연결"과 "미상 확장자"를 표에서 분리 유지 | F6 | C·U |
| 18 | TXT 문서 만들기 합류(후보 2방식 구획)·작업대 | `draft` 별도 화면(좌 TXT 목록+휘발/저장 세션 4존·`draftMapSheet`) | `DraftSessionMixin`·`TxtQueueModel`·`TxtDraftViewModel`·`MappingModel` | **재배치** | 큐 퇴화 규칙·T3 가드·정렬 린트·확정-비움 의미론은 작업대로 승계. **휘발 기안(붙여넣기 세션)은 v6대로 사망**(결정 2) — 기능 축소이므로 사용자 고지 + 대체 경로(저장 TXT 작업 경유) 명시가 삭제의 조건 | F6 | D·R·U·S·C |
| 19 | §19.4 TXT 복사 완료 = 최근 사용 | 없음(TXT는 `last_run_at` 미기록) | `Job.last_run_at`(완주 스탬프) | **신설** | §8.2 ② 유지: HWPX는 **완주**만. TXT는 복사 완료 1건으로 기록 — 두 매체가 다른 술어를 쓴다는 사실을 표면 문안이 정직하게 말한다 | F6 | C |
| 20 | 편집기 4탭(템플릿·필드 연결·표시·파일 이름·시험) | `jobEditHost` 3분류(템플릿·매핑·저장), 신규=단계/편집=탭 | `MappingModel`·`PartialGate`·`validate_save` | **재배치** | 파일 이름은 현재 **저장 단계에 인라인** — 별도 탭으로 승격. TXT는 파일 이름 탭 없음(§3.2) | F7 | D·R·U·S·C |
| 21 | `EditContext`+`editSession` patch 거래(section 1개·적용/버리기/머무르기)·deep-link·ReturnContext | `editor_entry.js` 착지·`preserve.js` 보존 | 없음 | **신설** | 진입 사유 10종·`evidence`·`returnContext` 6표면. 저장 단위는 effective draft가 아니라 **patch**(§5.2) | F7 | R·U·C |
| 22 | Template/Binding **판본**(revision) + §19.10 무효화 규칙 | 없음 — 저장은 Job 전체 덮어쓰기(`content_fingerprint`) | `content_fingerprint`·`classify_existing` | **신설** | 불변식 §13-6·7이 요구(판본 변경 = 관련 validation·approval 폐기, Run은 사용 판본 고정). 재작성 중 **최대 백엔드 신설** | F7 | U·C |
| 23 | `runOverrides`(이번 생성에 적용·레코드별 filename) | 없음 | — | ~~신설~~ **기각**(§10.14) | override 가 겨눌 실패가 이 제품에 없다(실측 4). §13-14·15 는 전제가 없어 **공허참**. 「master 대응물=없음」이 곧 「다른 층에서 이미 풀림」이던 표본 | ~~F7~~ **사망** | R·U·C |
| 24 | 템플릿 바꾸기 4단계·작업 방식 전환·`dormantFilenamePattern` | `relink_template`(같은 매체 재연결만) | `template_manager_state`(후보 목록) | ~~신설~~ **기각**(§10.16) | 바꿀 대상인 작업 방식이 **생성 시점에 정해져 바뀌지 않는다**(불변식 1의 귀결). convert 의 유일한 정당성인 「이력 유지」가 §19.4 와 충돌해 이력을 위조하고, fork 는 같은 매체 안에서 `clone`+`relink` 로 도달하며 **매체 교차 fork 는 성립 개념이 아니다**(계승할 매핑이 없다 — §10.16.1 ③ 정정, 리뷰 3R P2) | ~~F8~~ **사망** | C·U |
| 25 | 시험 탭(현재 validation·Template r·Binding r·미리보기 생성·승인) | 없음 | — | ~~신설~~ **기각**(§10.17.1) | 5지표 전부가 기존 술어의 **중복 표시**(검증=게이트 fail-closed·판본=편집기 머리 저장 상태줄·생성/승인=F5 드로어+복귀처 게이트)이고, 대표 샘플은 「필드 연결·표시」 탭의 필드별 미리보기 열+레코드 스테퍼가 **상위 호환으로 기존재**. 「없음」 행 리트머스(§10.14.4)의 3번째 적용 표본 | ~~F8~~ **사망** | — |
| 26 | `dataFamily` 추론 분기 | — | — | **이식 금지** | §7 F-03 판정(백엔드 정본에 권위 없음). 연결 복구/신작업 분기는 `identityDecision` 사용자 택일 | — | — |
| 27 | 템플릿 라이브러리 관리(#108 착지분)·데이터 관리(pool 수명) | `tpl` 매체 2밴드·그룹·가져오기·컴파일·검토·TXT 신규 작성 / `pool` 등록·보관·삭제 | `TemplateManagerViewModel`·`template_groups`·`DatasetPoolViewModel` | **화면 사망·기능 흡수**(결정 1) | 두 화면 모두 **두 탭의 상태전이 안으로 흡수**한다. 흡수처는 §10.4.1 표가 항목별로 소유 — 흡수처가 서기 **전에** 화면을 지우지 않는다(그때까지 임시 존치가 정직하다) | F1(pool)·F8(tpl) | U·C |

### 10.3 링1·링0 자산 정산

**그대로 사는 것(재작성 무영향)**: `core/job.py`(`favorited_at`·`last_run_at`·`group`·`tags`·잠긴
writer)·`core/fill_ledger.py`·`batch.py`·`naming.py`·`core/jamo.py`·`gui/run_state.py`(게이트 단일
산출·`GenerationPlan`·`unresolved_name_tokens_for`)·`gui/work_candidates.py`·`gui/home_state.py`
(라이브러리 투영·건강 번역)·`gui/filter_state.py`·`webapp/data_zone.py` 13액션·`gui/mapping_state.py`·
`gui/txt_queue.py`·`gui/dataset_pool_state.py`·`webapp/template_groups.py`.

**확장이 필요한 것**: `SelectionModel`(index → snapshot-local id + draft 복제)·`_display_indices`
(고정 → 사용자 축)·`library_health`(목록 1건 → 상세 전 원인)·`Job`(판본·override 보관).

**신설 백엔드**(모두 링1): `RecordRangeState`/`RecordRangeDraft`·`EditContext`/`editSession`·
Template·Binding 판본·~~`runOverrides`~~(기각 §10.14)·`ReviewRequirement`(F-06)·~~`templateTransitionDraft`~~(기각 §10.16)·
TXT 복사 사건 기록·마운트 참조 세션 복원(`RestoreMountedData`/`SaveMountedDataRef`).

### 10.4 죽는 링2 표면과 승계 의무

**이 표는 후속 항목 목록이지 첫 착지의 조건이 아니다**(§10.5). 화면은 승계처가 실제로 서는
시점에 죽고, 그때 이 표의 의무를 정산한다 — 그전까지는 옛 화면이 그대로 살아 의무를 계속 진다.
「승계처」 열의 S1~S7 은 §10.1 v6 표면 번호다.

| 죽는 것 | 승계처 | 승계 의무(삭제는 의무를 상속한다) |
|---|---|---|
| `home` 화면 전체(`#scr-home`·`screens/home.js` 418줄) | 라이브러리(S4) | 경보 → 건강 「확인 필요」 보기 / 손상 격리 → 심각도 4 / `＋새 작업` → `libraryNewWork` / txt 트랙 → 방식 필터 |
| group-by 렌즈(`set_group_by`·`homeBrowser`) | facet + 그룹 구획 | §9.4 A안 3건(facet 존치·영속값 무시·퇴화 불변식) |
| `job` 좌 master 목록·그룹 관리 ⋮ | 라이브러리 행·상세 관리 행동 | 순위 밖 즐겨찾기 승격 도달성(§8.4 2행)·이름 변경·그룹 이동·복제·삭제 |
| `draft` 화면(`screens/draft.js` 534줄) | 문서 만들기 TXT 구획 + 작업대(S7) | 큐 퇴화 규칙·T3 가드·정렬 린트·확정-비움 의미론 / **휘발 세션은 사망**(결정 2 — 고지 + 대체 경로 명시가 조건) |
| `job` 4존 구조·`jobConfirmSheet`·`dataSheet` | S1 2열 + S2 범위 편집기 | 거울·재진술·ack 게이트 **존치**(결정 3)·`data-preserve-scroll` 보존 계약 |
| `tpl` 화면(`screens/template.js` 417줄)·`pool` 화면(`screens/pool.js` 196줄) | §10.4.1 항목별 흡수처 | 흡수처가 서기 전에 지우지 않는다 |
| 5화면 라우팅(`window.Nav`·`REFRESH_ON_NAV`·레일 접기·`data-scr`) | 상단 2탭 | 테마·글자 크기 토글의 거처, 접힘 영속(`set_rail_collapsed`) |

#### 10.4.1 `tpl`·`pool` 흡수 배치 (결정 1의 이행표)

"두 탭의 상태전이로 흡수"는 기능을 지운다는 뜻이 아니라 **거처를 옮긴다**는 뜻이다. 아래
전 항목이 새 거처에서 도달 가능해짐을 확인한 뒤에야 해당 화면을 삭제한다.

| 현 기능 (액션) | 흡수처 | 슬라이스 |
|---|---|---|
| 등록 데이터 목록·손상 격리 (`pool/refresh`) | `dataPickerDialog` 「고정한 데이터」 구획 + `picker-status` | F1 |
| 데이터 등록 (`register_excel`) | `pinDataDialog` 「이 데이터 고정」 | F1 |
| 보관·활성·삭제 (`archive`·`activate`·`delete`) | 고정 목록 행의 객체 메뉴 | F1 |
| HWPX·TXT 템플릿 목록·그룹 구획·접힘 (`tpl/toggle_group`·`set_group`) | 편집기 「템플릿」 탭 후보 목록 **단독**(~~+ `screen-transition` pick 단계~~ — 그 화면이 §10.16 에서 통째로 기각·사망해 흡수처 절반이 소멸, 재지정 = §10.17.2 판정 A) | F7·F8 |
| 가져오기 (`import_library_template`) | 같은 템플릿 선택 표면의 `가져오기…` — **F7 착지는 절반만 참**(편집기 `import_template_file` 은 hwpx 전용·RAW 거부): hwpx·txt·RAW 수용 통일은 §10.17.2 판정 C | F7·**F8** |
| 새 TXT 템플릿·편집 (`txt_new`·`txt_edit`·`txt_content`) | TXT 작업의 편집기 「템플릿」 탭(원문 편집) | ~~F7~~ **F8**(§10.13.3 말미가 명시 이월) |
| 누름틀 변환·검토 (`compile`·`review`) | 편집기 「템플릿」 탭 — v6 `외부 편집 뒤 변경 확인` + 구조 개요 자리. **v6 에 정확한 대응물이 없는 유일 항목**이므로 문안·행동을 새로 짓되 기능을 줄이지 않는다 | ~~F7~~ **F8**(§10.13.3 말미가 명시 이월) |
| 템플릿 이동·삭제 (`tpl/delete`·`undo_delete`) | 템플릿 선택 표면 행의 객체 메뉴 | F8 |

### 10.5 진행 방식 — 핵심 흐름 먼저, 나머지는 하나씩 (사용자 확정 2026-07-27)

**전 기능을 새 화면으로 옮기지 않는다.** 먼저 핵심 흐름 하나가 새 구조에서 **실제로 작동하게**
만들고, 그 뒤 항목을 하나씩 고쳐 나간다. 그래서 §10.4 의 승계 의무 목록은 **첫 착지의 조건이
아니라 후속 항목 목록**이며, 우선순위는 이 절이 소유한다.

**핵심 흐름의 정본은 계약이다** — 여기 다시 적지 않는다: lab `core-workflow.md` §18 서문 흐름
블록(데이터 선택 → 작업 선택 → 복귀) + §18.10 상태도(`MountedNone → QuickRange → Validated →
HwpxRun`) + §10(성공과 실패). 이 절이 소유하는 것은 흐름의 정의가 아니라 **선별 기준** 하나다:

> 그 계약 흐름을 끝까지 통과하는 데 없으면 끊기는가 — 끊기면 R1, 없어도 끝까지 가면 후속.

**기존 화면은 당분간 그대로 둔다.** `home`·`draft`·`tpl`·`pool` 은 손대지 않고 계속 산다 —
새 표면이 실제로 그 일을 하게 된 뒤에 화면별로 지운다. 병존이 과도기의 정직한 상태다.

#### R1 — 핵심 흐름 (첫 착지)

`job` 화면의 **우 세션 패널**을 v6 `screen-data` 구조로 재작성한다. **백엔드 신설 0, 삭제 0** —
링1 은 전부 그대로 쓰고 바뀌는 것은 링2 배치다. 좌 작업 목록은 그대로 두고 F2 에서 죽는다
(승계처가 서기 전에 지우지 않는다 — §10.4 서문).

| 포함 | 이유 |
|---|---|
| 세션 패널 2열(좌 현재 데이터 카드 + 레코드 표 / 우 side-card 문서 선택기·검증·실행) | 이 형상 전환이 R1 의 본체 |
| 현재 데이터 카드(파일·시트·행×열·`데이터 선택`) | §18 서문 1~3행(선택·시트·마운트) |
| 레코드 표·검색·필터·행 선택·필터 밖 선택 스트립 | §18.10 `QuickRange` — 13액션 그대로 |
| 후보 side-card(top·more·needs·추천) + 문서 탐색 시트 | §18 서문 후보 계산~메인 5개 — 이미 있음, 자리만 이동 |
| 게이트·검증·거울·`ack_field` | **거울이 없으면 빈 값 게이트를 풀 길이 없어 흐름이 끊긴다**(결정 3) |
| 저장 폴더·생성·덮어쓰기 왕복·결과 | §18.10 `HwpxRun` + §10 결과 — 기존 그대로 |

| 제외 (후속) | 흐름이 끊기지 않는 이유 |
|---|---|
| 표시순서 토글 | 현행 `sourceDesc` 고정으로 끝까지 간다 |
| 결과 3태 구획·부분 실패 복구 | 현행 결과 + 로그로 끝까지 간다 |
| 미리보기 드로어·승인 | 계약 §13-2 — 정상 반복 실행에서 미리보기는 **선택** |
| 좌 작업 목록 자체(+관리 동사 6종) | 존치 — F2 에서 라이브러리가 승계할 때 함께 죽는다 |
| 데이터 선택 다이얼로그 통합 | 현행 2버튼(등록 데이터·파일 선택)으로 끝까지 간다 |

#### 후속 항목 — 하나씩 (체감 가치순, 고정 아님)

| 항목 | 내용 | 대조표 행 |
|---|---|---|
| ~~F1~~ **착지** | 데이터 선택 다이얼로그 통합(현재/고정한/다른) + 전환 손실 가드 → `pool` 흡수·**화면 사망** — 계약 §10.7 | 12·13 |
| ~~F2~~ **착지** | 전역 라이브러리 표면(browser+detail) + 상단 2탭 → `home` 흡수·사망 — **PR 2분할**: A(표면·`home` 사망) 계약 §10.8 · PR #309 squash `446e081` / B(셸 교체·좌 목록 사망) 계약 §10.9 | 14·15·1 |
| ~~F3~~ **착지** | 표시순서 축 + 전문 범위 편집기(draft) — PR #312 squash `900aecb` · 계약 §10.11 · 정산 §10.11.6 · 리뷰 5라운드 §10.11.7~§10.11.11 | 4·10 |
| ~~F4~~ **착지** | 결과 3태 + 부분 실패 표면 — **재시도 3종은 기각**(§10.14, 이미 도달 가능) — PR #311 squash `1ea532e` · 계약 §10.10 · 정산 §10.10.5 · 리뷰 4라운드 §10.10.6·8·9 | 8·9 |
| ~~F5~~ **착지** | 미리보기 드로어 + 검토 요구(`ReviewRequirement`) — **구조 검토는 F8 · override 는 기각(§10.14) · 행별 「수정」 deep-link 는 F6 동승** — PR #313 squash `8dcc209` · 계약 §10.12 · 정산 §10.12.4 · 리뷰 5라운드 §10.12.5~§10.12.10 | 16 |
| ~~F6~~ **착지** | TXT 합류 + 작업대 → `draft` 흡수·사망(휘발 세션 폐지 고지) **+ F5 드로어 행별 「수정」 deep-link 동승**(§10.14.3) — **PR 2분할**: ~~A~~(TXT 합류·작업대 신설) PR #315 squash `275dd24` · 계약 §10.15 · 정산 §10.15.4 · 리뷰 9라운드 §10.15.5~§10.15.13 · 결산 §10.15.14 / ~~B~~(`draft` 사망·승계 정산·deep-link·101 트랙 B 재배선) 계약 §10.15.15 · 정산 §10.15.15.4 | 17·18·19 |
| ~~F7~~ **완료** | 편집기 탭 재편 + `EditContext`·patch 거래 + 판본 — **PR-A 착지**(몰입 표면·탭·patch·판본) PR #314 squash `4004723` · 계약 §10.13 · 정산 §10.13.6 · 리뷰 9라운드 §10.13.7~§10.13.15 / **PR-B 기각**(`runOverrides`·재시도 3종) 근거 §10.14 | 20·21·22·~~23~~ |
| F8 | ~~시험 탭~~(**기각** §10.17.1) + `tpl` 흡수·사망 + 셸 2탭 최종 착지 — **템플릿 바꾸기·작업 방식 전환은 기각**(§10.16) — 착수 계약 §10.17 | ~~24~~·~~25~~·27·1 |

F7 의 판본·patch 거래는 다른 항목의 전제가 아니다 — 계약 불변식(§13-6·7)이 요구하지만 핵심
흐름은 그것 없이 오늘도 돈다. 실제로 필요해지는 시점(F5 승인 fingerprint·~~F8 시험 탭~~
— 시험 탭은 기각됐고(§10.17.1) 판본의 표시 자리는 §10.13 판정 O 의 셋이 최종)에 당긴다.

**항목 착수 전 필수 절차**(축적된 교훈의 선행 적용):

- 새 정렬·분류 축(F3 표시순서, F2 보기·facet)은 §8.4 4계약면을 구현 **전에** 적고 각 면에 회귀.
- 새 오버레이·시트·패널(F1 다이얼로그, F3 범위 편집기, F5 드로어)은 §9.3 4계약면
  (재렌더 정체·전역 잠금 범위·전이와 왕복 순서·실패 경로 문맥)을 구현 **전에** 적고 각 면에 회귀.
- 판정 단일 출처: 같은 상태를 두 표면이 다르게 부르면 그게 결함이다(`unresolved_name_tokens_for`
  선례). 새 표면을 추가할 때 기존 술어를 공유하는지 먼저 확인한다.

### 10.6 계약이 답하지 않던 3건 — 사용자 확정 (2026-07-27)

계약과 목업 어느 쪽도 처분을 말하지 않는 자리라 대조 과정에서 남았던 세 건. **확정됨**.

| # | 사안 | 확정 | 파장 |
|---|---|---|---|
| 1 | `tpl`·`pool` 화면의 처분 | **두 탭의 상태전이로 흡수 — 화면 사망**. 별도 자산 축을 만들지 않는다 | 흡수 이행표 = §10.4.1. 사망 시점은 흡수처가 서는 슬라이스(`pool`=F1·`tpl`=F8). 유일 무대응물 = 누름틀 변환·검토 → 편집기 「템플릿」 탭에서 새로 짓되 기능 축소 금지 |
| 2 | 휘발 기안(붙여넣기 → 즉시 채워 복사) | **v6 대로 사망** | 기능 축소이므로 F6 은 삭제와 함께 ①사용자 고지 ②대체 경로(저장 TXT 작업 경유) 재진술을 진다. #148 슬라이스 6a·6b 가 세운 휘발 세션 기계(`DraftSessionMixin` 의 휘발 분기·스태시·「이번 세션」 귀환구)는 저장-세션 경로만 남기고 걷힌다 |
| 3 | 거울(`jobMirror`)·재진술 블록 | **존치** | v6 side-card 와 **병존**하는 「본문 확인」 면으로 이식. 근거 = 계약 §13-2("정상 반복 실행에서 미리보기는 선택")라 미리보기 드로어가 거울을 대체할 수 없고, 거울은 `ack_field` 빈 값 게이트의 표면이라 confirm-or-alarm 본체다 |

### 10.7 F1 착수 계약 — 데이터 선택 다이얼로그 통합 + 전환 손실 가드 (2026-07-27)

대조표 12·13행과 §10.4.1 의 F1 3행(등록 목록·등록·수명 관리)을 한 표면으로 모으고 `pool`
화면을 죽인다. **착수 전 필수 절차**(§10.5)의 이행분이 이 절이다 — 새 오버레이의 §9.3
4계약면과 판정 5건을 구현 **전에** 적는다.

#### 10.7.1 §9.3 4계약면 사전 기입 (새 오버레이 = 데이터 선택 다이얼로그)

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 목록은 `pool` 푸시로 **열려 있는 동안 재렌더**된다(보관·삭제가 같은 면 안에서 일어나므로). 행 id = `data-name`(풀 항목 이름 = 안정 키), 구획·닫기 버튼 id 고정. 재렌더는 `Preserve.around` 로 감싸 포커스가 면 밖으로 떨어지지 않는다 | selftest 프로브: 행 액션 클릭 → 재렌더 뒤 포커스가 다이얼로그 안 |
| **전역 잠금의 범위** | 생성 중(`setBusy`)에는 다이얼로그 루트도 훑어 잠근다 — 오버레이 루트는 화면 루트 질의 밖이라 §9.3 3행과 같은 사각(`jobBrowseSheet` 선례). 로드 중에는 닫기·Escape·추가 클릭을 막고 **그 사실을 표기**한다(`pool_picker.js` C8 승계 — 취소했다면서 화면 데이터가 바뀌는 거짓말 금지) | DOM 계약: 다이얼로그 안 컨트롤에 `data-busy-lock` / 로드 중 Escape 차단 문구 프로브 |
| **전이와 왕복의 순서** | 마운트 성사 시에만 닫는다. 닫힘 직후 포커스는 **여는 트리거**(`데이터 선택` 버튼)로 복귀(Modal 소유). 중첩은 스택으로 — 고정 다이얼로그·확인 다이얼로그·시트 선택이 이 면 **위에** 뜬다(modal.js 스택 계약 재사용, 신설 없음) | 실앱 게이트: 열기→고정→확인 3중첩 뒤 Escape 승계 |
| **실패 경로의 문맥 보존** | 나라 동결·죽은 참조·모호 시트·행 0건·손상 격리는 **다이얼로그 안에서** 재진술하고 면을 닫지 않는다(다른 항목 재선택·취소 가능). 파일 읽기 실패도 같다 — 현재 데이터는 그대로임을 문안이 재진술 | 회귀: 실패 응답에 면이 열린 채 남고 상태줄에 사유 |

#### 10.7.2 판정 5건 (이 슬라이스에서 확정)

**A. 화면은 죽고 컨트롤러는 산다.** 「고정한 데이터」 목록·수명 관리는 `PoolController`
스냅샷(`rows`·`corrupted`·`result`)과 액션(`refresh`·`archive`·`activate`·`delete`·
`register_excel`)을 **그대로** 소비한다 — 백엔드 신설 0, 판정 재구현 0. 죽는 것은
`#scr-pool`·`screens/pool.js`·레일 항목뿐이고, 다이얼로그가 `pool` 푸시의 새 구독자가 된다.

**B. `job`·`draft` 가 같은 다이얼로그를 쓴다.** 데이터 선택 어휘를 둘로 가르지 않는다
(§10.5 "판정 단일 출처"). 그래서 `pool_picker.js`·`#poolModal`·`pool_sources` 액션·
`pool_sources_payload` 는 사망하고, 승계 의무 5건을 새 표면이 진다: ①활성 목록 ②손상 병기
③로드 중 취소·Escape 차단 표기 ④나라 항목 숨김 금지 + 겨눔 시 동결 거절 재진술 ⑤취소=중단
(기본 강등 없음). `draft` 는 F6 에서 죽지만 그전까지 데이터 선택은 한 벌이다.

**C. 「고정한 데이터」는 보관 항목도 싣는다.** `pool_sources_payload` 는 활성만 실었는데,
그 목록이 유일 표면이 되면 **`활성화` 동사에 도달할 길이 사라진다** — §8.4 2행("표시 상한과
무관한 도달성")과 같은 뿌리의 결함이다. 그래서 목록은 `PoolController.rows`(전 상태 + 배지 +
상태별 액션) 그대로다. 보관 항목은 **사용 불가**로 정직하게 비활성이고 `활성화` 를 곁에 둔다.

**D. 가드는 "읽기 직전"에 묻는다.** 계약 §18.2 의 순서는 `inspect → sheet → load → loss guard
→ atomic commit` 이지만, 여기서는 **대상이 확정된 직후·읽기 직전**에 묻는다. 근거: ⓐ 계약이
그 순서로 지키려는 것("성공 전에는 현재 runtime 을 지우지 않는다")은 master 가 이미 만족한다
— `load_data_path` 는 `resolve_file_source` 성공·행 0건 아님을 확인한 **뒤에야** 세션을
대입한다(§18.2 원자 계약). ⓑ 읽은 뒤에 묻는 순서는 실패한 읽기에도 확인 왕복을 물리거나,
성공한 읽기를 버리는 낭비를 만든다. **어긋남을 숨기지 않고 여기 적는다** — 되깎기 조건 =
`pendingMount` 가 실제로 필요해지는 시점(F3 범위 편집기 초안·F5 승인 상태가 손실 목록에
합류할 때) 에 계약 순서로 옮긴다.

**E. 행 수명 관리는 인라인 행동 줄.** §10.4.1 은 "고정 목록 행의 객체 메뉴"라 적었지만,
모달 **안에** 팝오버 생명주기(포커스 트랩·`Popover.closeAll`·좌표)를 새로 들이는 값이
도달성에 비해 크다. 오늘 `pool` 화면이 쓰는 인라인 `tplcard-acts` 를 그대로 옮긴다 — 승계
의무(도달성)는 같고 새 생명주기는 0. 밀도가 문제가 되면 그때 객체 메뉴로 되깎는다.

#### 10.7.3 전환 손실 가드 — 실제 파기 집합 감사 (대조표 13행)

승계 의무는 "가드 문안은 실제 사라지는 집합과 일치"다. `load_data_path`/`load_pool` 이
실제로 파기하는 것을 코드에서 확인해 대조한다.

| 실제 일어나는 일 (코드) | 현 문안 | F1 조치 |
|---|---|---|
| 선택 0건으로 재생성(`SelectionModel(all_selected=False)`) | 실림(무장 시) | 유지 |
| 필터 재생성(`_init_filter` — 검색어·열 조건 전부) | 「필터 정의(N개 조건)」 | 유지 + **재적용 도달성 병기**: `_reapply_available` 3연언은 **소스 일치**를 요구하므로 다른 데이터로 가면 직전 슬롯은 되살릴 수 없다. 문안이 "다시 이 데이터로 돌아오면"을 말한다 |
| 빈 값 확인(`ack_field`)이 `set_acquired` 로 **재평가** | 없음 | 실린 ack 가 있으면 열거에 추가(조용한 소실) |
| 자동 조준 재진술(`data_notice`) 소거 | 없음 | 열거 제외 — 사라지는 게 아니라 **대체**된다(새 데이터가 스스로를 재진술) |
| 생성 결과·로그(웹 소유)는 **남는다** | 없음 | F1 범위 밖(F4 결과 3태) — 남는 것을 "사라진다"고 적지 않는다 |

무장 판정(`_selection_guard`)은 그대로 쓴다 — "재현 불가능한 수작업"만 묻는 술어는 결정 27
이 세운 것이고, v6 `switchLosses` 의 전량 열거로 바꾸면 1클릭 재현 가능한 것까지 확인
왕복을 물려 경보가 싸구려가 된다.

#### 10.7.4 `pool` 화면 사망 조건 점검표

전 항목이 다이얼로그에서 도달 가능함을 확인한 **뒤에만** 화면을 지운다(§10.4 서문).

| # | 도달해야 하는 것 | 새 거처 |
|---|---|---|
| 1 | 등록 데이터 목록(전 상태·배지·참조 요약·메모·로케이트) | 「고정한 데이터」 구획 행 |
| 2 | 데이터 등록(`register_excel`) | 「이 데이터 고정」(현재 데이터 프리필) + 「직접 등록…」(빈 폼) |
| 3 | 보관·활성화·삭제(확인 왕복 포함) | 행 인라인 행동 줄 |
| 4 | 다시 연결(#67 — 끊긴 참조 프리필) | 행 인라인 행동 줄(`참조 끊김` 배지 동반) |
| 5 | 손상 격리 재진술(RC-05) | 목록 아래 상주 danger 카드 |
| 6 | 외부 변경 재스캔(`refresh`) | 구획 헤더 「새로고침」 + 다이얼로그 열 때 1회 |
| 7 | 나라 항목 표시(숨김 금지)·겨눔 시 동결 거절 | 행 표시 + 상태줄 재진술 |

**착지 정산(2026-07-27)**: 7항목 전부 새 거처에서 도달 확인 후 화면 삭제(커밋 `41c042b`).
사망 표면 = `#scr-pool`·`screens/pool.js`·레일 항목·`pool_picker.js`·`#poolModal`·
`pool_sources`(활성-only 페이로드)·죽은 필드 `data_track_path`. 화면 사망이 문안에 남긴
빚도 함께 정산했다 — 「데이터 관리에서 …하세요」로 죽은 화면을 가리키던 사용자 문구
(모호 시트 거절·자동 조준 실패·101 예제·UI_VOCABULARY)를 새 거처 이름으로 바꿨다.

#### 10.7.5 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(4계약면·판정 5건·가드 감사·사망 점검표) |
| 2 | 통합 다이얼로그 표면 + `pool` 화면 사망을 **한 전이로** — `web/js/data_picker.js`·정적 골격·`job`/`draft` 배선 / `pool_picker.js`·`screens/pool.js`·`#poolModal`·`#scr-pool`·레일 항목·`pool_sources` 삭제 / UI_CONTRACT·DOM 계약·selftest 정산 |
| 3 | 전환 손실 가드 열거 정직화(§10.7.3 조치열) |

커밋 2가 신설과 사망을 함께 지는 이유: 등록 모달(`#poolRegModal`)은 두 표면이 공유하는
**한 벌**이라 중간 상태에선 소유자가 둘이 된다(같은 버튼에 리스너 2개 = 클릭 1회에 왕복 2회).
승계처가 서기 전에 지우지 않는다는 규율(§10.4 서문)은 지켜진다 — 같은 커밋 안에서 먼저 서고
그다음 죽는다.

### 10.8 F2 착수 계약 — 전역 라이브러리 표면 + `home` 화면 사망 (2026-07-27)

대조표 14·15행(browser+detail·건강 전 원인)과 1행(셸 교체)을 진다. **착수 전 필수 절차**
(§10.5)의 이행분이 이 절이다 — 새 축의 §8.4 4계약면과 새 표면의 §9.3 4계약면, 판정 8건,
사망 점검표를 구현 **전에** 적는다.

**PR 2분할(사용자 확정 2026-07-27)** — 표면 신설과 셸 교체는 리스크 티어가 다르다.

| PR | 범위 | 착지 뒤 레일 |
|---|---|---|
| **A**(이 절) | 전역 라이브러리 표면(browser+detail) + `home` 화면 사망 + group-by 렌즈 은퇴 + `문서 만들기에서 사용` 3분기 | 4항목 — 작업 · **문서 작업** · 기안 · 템플릿 관리 |
| **B**(후속, 착수 시 §10.9 기입) | 상단 2탭 셸 교체(레일 사망) + 「작업」 좌 master 목록 사망 | 상단 2탭 + 임시 2항목 |

PR-A 가 레일을 유지하는 것은 과도기의 정직한 상태다(§10.5). 「문서 작업」이 실제로 그 일을
하게 된 뒤에 셸을 갈아야 셸 교체가 되돌릴 것 없는 한 방향이 된다.

#### 10.8.1 §8.4 4계약면 사전 기입 (새 축 = 보기 4종 · 작업 방식 필터 · 태그 facet · 그룹 접힘)

| 면 | 이 축들에서의 값 | 회귀 |
|---|---|---|
| **시각 정밀도** | 최근 사용·즐겨찾기 정렬은 슬2가 세운 **전정밀 스탬프**(`last_run_at`·`favorited_at`)를 **그대로 공유**한다 — 라이브러리 전용 정렬 술어를 만들지 않는다. 확인 필요는 심각도 → 이름순이고 동률은 전부 이름순(결정적) | 같은 초 즐겨찾기 2건이 스탬프순을 지키는 회귀(슬2 회귀의 라이브러리 소비처 확장) |
| **절단과 무관한 도달성** | 라이브러리엔 Top N 절단이 없다(전량). 절단자는 **보기·방식 필터·검색·facet** 넷이다. ①탭 건수는 **검색 전** 사실(§19.6 소비처 이미 그렇게 셈) ②고아 활성 facet 표면화는 VM 이 이미 소유 ③빈 결과에는 「필터를 지우고 전체 보기」 출구가 **상주** ④즐겨찾기 토글은 **행 자체**에 있어 모든 보기에서 도달한다 — 이것이 「순위 밖 승격 도달성」(§8.4 2행)의 새 거처다 | 필터로 0건이 된 화면에 출구 버튼 존재 + 확인 필요 보기에서 즐겨찾기 토글 도달 회귀 |
| **상태의 주체** | **세션 소유**(Python 라이브러리 컨트롤러): 보기·방식·검색어·facet·선택 행. **영속 소유**: 그룹 접힘(`settings.job_collapsed_groups` — 기존 키 재사용, 개명 없음). **Job 파일 소유**: group·tags·`favorited_at`. 접힘은 「모든 작업」 보기의 성질이지 Job 속성이 아니다 | 접힘이 보기 전환에 살아남고 Job 저장에 딸려가지 않는 회귀 |
| **지연 왕복 중의 의도** | 즐겨찾기 토글은 슬2의 `FAV_PENDING` 의도 직렬화(꼬리 식별 포함)를 **그대로 옮긴다** — 새 큐를 발명하지 않는다. 검색 입력은 기존 화면들과 같은 디바운스 규약을 쓰고, 왕복 중 도착한 푸시가 입력 캐럿을 되감지 않는다(`Preserve` 계약) | selftest 프로브: 빠른 2연타 즐겨찾기의 발신열이 마지막 의도로 수렴 |

#### 10.8.2 §9.3 4계약면 사전 기입 (새 표면 = 라이브러리 2-pane + 관리 다이얼로그 2종)

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 행 id = **작업 이름**(안정 키, 홈 카드 선례). 보기 탭·방식 칩·facet 칩·그룹 헤더·상세 행동 버튼 id 고정. 목록·상세 재렌더는 `Preserve.around` 로 감싼다. 결과 수는 `role="status"` 로 재진술(§19.6 `libraryCount`) — 필터가 목록을 비웠다는 사실이 조용히 지나가지 않는다 | selftest: 방식 칩 클릭 → 재렌더 뒤 포커스가 그 칩에 생존 |
| **전역 잠금의 범위** | 라이브러리는 화면이라 오버레이 사각이 없지만 **그룹 이동·태그 편집 다이얼로그는 오버레이**다 — `setBusy` 가 그 루트도 훑는다(§9.3 3행 사각의 재발 지점). 더 중요한 잠금은 **타 화면 무장 세션**이다: 삭제·이름 변경·그룹 이동은 「문서 만들기」·「기안」의 무장 세션 가드(`session_guards`, #268)를 지나고 무장이면 `needs_confirm` 재진술로 멈춘다 | DOM 계약: 다이얼로그 컨트롤에 `data-busy-lock` / 무장 세션에서 이름 변경이 확인 왕복을 무는 회귀 |
| **전이와 왕복의 순서** | `문서 만들기에서 사용` 은 **대상 화면 dispatch 로 먼저 겨눈 뒤** 라우팅한다(홈 허브 선례 — 라이브러리는 다른 화면 컨트롤러를 모른다). 겨눔이 실패하면 **화면을 바꾸지 않는다**. 삭제 성사 뒤 포커스는 인접 행, 목록이 비면 목록 제목(§19.8) | 실앱 게이트: 겨눔 실패 시 라이브러리에 남고 사유가 뜬다 |
| **실패 경로의 문맥 보존** | 복제·삭제·개명·그룹 이동 실패는 **라이브러리 안에서** 재진술하고 보기·필터·선택을 유지한다. 편집 저장으로 항목이 「확인 필요」에서 사라지면 보기·필터를 **유지한 채** 재계산하고 성공을 알린다 — 해결된 항목을 결과에 억지로 남기지 않는다(§19.8 명문) | 회귀: 실패 응답 뒤 `library_view`·`library_query`·선택이 불변 |

#### 10.8.3 판정 8건 (이 슬라이스에서 확정)

**A. 화면은 죽고 투영은 산다 — 단, 링2 어휘는 개명한다.** `HomeViewModel` 의 라이브러리
투영·건강 번역·facet 판정(PR-2a 완비)은 **그대로** 소비한다(백엔드 판정 재구현 0). 그러나
링2 는 개명한다: `screen_home.py` → `screen_library.py`, 푸시 채널·액션 registry 키
`home` → `library`. 근거 = `pool` 과 다르다. `pool` 은 도메인 개체 이름(Dataset Pool)이라
화면이 죽어도 어휘가 살지만, `home` 은 **순전히 화면 이름**이라 화면이 죽은 뒤에도 계약
표면(registry·UI_CONTRACT·selftest 프로브)에 남으면 어휘가 갈린다. 링1 `gui/home_state.py`
는 §10.3 이 "그대로 사는 것"으로 배정했으므로 **파일명·클래스명을 바꾸지 않되** 모듈
docstring 이 소유물(홈 화면 아님 · 라이브러리 투영)을 명시한다 — 어휘 빚을 숨기지 않고 적는다.

**B. group-by 렌즈 은퇴 = §9.4 A안 이행.** 죽는 것: `set_group_by` 액션·`homeBrowser` 바·
`effective_group_by`·`grouped_rows`·씨앗 상수 `SEED_GROUP_BY_AXIS`. 승계 의무 3건 중
②는 **실측으로 축소된다** — `active_group_by` 는 설정에 영속되지 않고 씨앗 상수로만 초기화되므로
"영속값 무시"가 아니라 **씨앗 삭제**가 이행분이다(있지도 않은 마이그레이션을 적지 않는다).
①facet 칩은 `facets()`·`_passes_facets` 그대로 살아 태그로 좁히기는 계속 가능하고, ③퇴화-코퍼스
불변식(태그 0개 = 평면)은 `library_sections` 가 이미 진다. VM 함수까지 함께 지우는 이유:
아무도 보지 않는 구획 축이 남으면 제2 정본이 되어 다음 세션이 되살린다.

**C. 상세의 「필드 연결」 표는 저장 키를 보여준다 — 계약과의 어긋남을 적는다.** §19.6 은
"현재 데이터가 준비된 경우에만 원본 열 표시 이름"을 쓰라 하지만 그 전제는 v6 의 **전역
단일 `dataState`** 다. master 에서 현재 데이터는 「문서 만들기」 **세션 소유**라, 라이브러리가
그것을 읽으면 화면 간 결합을 새로 만든다(홈이 다른 화면 컨트롤러를 모른다는 규율의 위반).
그래서 상세는 **항상 저장된 항목 키**를 보여주고 그 사실을 문안이 명시한다. **되깎기 조건** =
전역 `dataState` 가 실제로 서는 시점(PR-B 셸 교체 이후 세션 소유가 탭 위로 올라갈 때).

**D. 판본 열은 만들지 않는다.** §19.6 상세는 판본을 함께 보이라 하지만 Template/Binding
판본은 F7 신설분(대조표 22행)이라 오늘 존재하지 않는다. 빈 자리·「준비 중」 표기도 두지
않는다 — 없는 기능을 있는 척하지 않는다(§8.2 ② 선례). F7 이 판본을 세울 때 이 열이 선다.

**E. 건강은 전 원인이 정본이고 목록 1건은 그 파생이다.** 상세용 `library_health_causes(row)
→ [(심각도, 문구), …]` 를 신설하고, 기존 `library_health` 를 **그 최댓값 파생**으로 재작성한다.
두 술어를 나란히 두지 않는다(판정 단일 출처 — `unresolved_name_tokens_for` 선례). 심각도
표는 §19.7 그대로이고 새 원인을 발명하지 않는다.

**F. 좌 목록 6동사의 거처는 행·그룹 헤더·상세로 갈린다.** PR-B 에서 죽을 「작업」 좌 목록의
관리 동사를 v6 §19.6 상세 목록(복제·그룹 이동·태그 편집·삭제)이 다 받지 못한다. **부재는
금지가 아니므로**(계약이 이기는 것은 *어긋날 때*다) 빠진 것을 아래로 배치한다.

| 동사 | 새 거처 | 근거 |
|---|---|---|
| `toggle_favorite` | **행**(선택 버튼 밖 형제 버튼) | §19.6 "행은 즐겨찾기를 보여준다 · 행 선택 버튼 안에 중첩하지 않는다" |
| `toggle_group` | 「모든 작업」 보기의 **그룹 헤더** | §19.6 `collapsedGroups` 명문 |
| `set_group`(그룹 이동) · `set_tags` · `clone_job` · `delete_job` | **상세 관리 행동** | §19.6 명문 |
| `rename_job` | **상세 관리 행동**(추가) | v6 미언급이나 삭제하면 작업 이름을 바꿀 길이 사라진다 |
| `rename_group` · `disband_group` | **그룹 헤더**의 관리 행동 | 그룹은 행이 아니라 구획이라 상세가 아니라 헤더가 소유 |

**소유(컨트롤러)는 거처(표면)와 다르다 — 착지 시 확정.** 위 표는 *어디서 누를 수 있는가*이고,
*누가 판정하는가*는 이렇게 갈린다: `rename_job`·`set_group`·`rename_group`·`disband_group` 은
열린 세션의 정체(`job_name`·VM)와 결속돼 있어 **「문서 만들기」 컨트롤러가 계속 소유**하고
라이브러리 표면이 교차 화면 dispatch 로 부른다(홈이 대상 화면을 미리 겨누던 선례와 동형).
여기서 재구현하면 라이브러리에서 이름을 바꾼 순간 열린 세션이 없는 이름을 가리킨다. 세션과
무관한 `toggle_favorite`·`clone_job`·`set_tags`·`delete_job` 은 라이브러리가 직접 소유하고,
`toggle_group`(접힘)은 **소유가 라이브러리로 넘어오되** 영속 키(`job_collapsed_groups`)는
그대로 공유한다 — 두 표면이 같은 접힘을 본다(제2 정본 금지).

**G. 상시 행동 2개는 스크롤과 분리해 pane 하단에 고정한다.** `작업 편집`·`문서 만들기에서
사용`(§19.6). 2-pane 치수 계약도 §19.6 명문 그대로 CSS 로 진다 — 넓고(≥921px) 높은(≥760px)
창에서 두 pane 이 뷰포트 높이를 나눠 **각자** 스크롤하고 **페이지는 스크롤하지 않는다**.
그보다 좁거나 낮으면 세로 배치 + 페이지 스크롤로 퇴화한다. 폭 스플리터는 두지 않는다
(§19.6 "공간 배분은 목록 길이에 끌려다니지 않는다" — 고정 비율이 계약).

**H. `문서 만들기에서 사용` 3분기는 ~~링2가~~ **Python 이** 가르고, preferredWorkId 는 이
슬라이스가 채운다.** 착수 시엔 "현재 데이터 준비·호환 상태가 이미 링2 스냅샷에 있으니 웹이
가른다"고 적었지만, **착지에서 되깎았다**: 준비·호환은 링1 술어(`rank_available`·
`compatibility_for`)가 소유한 **판정**이라 표면이 다시 계산하면 같은 상태를 두 곳이 판정하게
된다(§10.5 "판정 단일 출처"). 그래서 「작업」 컨트롤러에 `prefer_work` 액션을 두고 웹은 반환된
`reason` 으로 **라우팅만** 한다.

```text
데이터 ready + 호환   → promoted     : select_job 겨눔(RecordRangeState 는 세션 소유라 생존)
데이터 ready + 비호환 → incompatible : 활성 **불변** + 보관. 표면이 「확인 필요」 탭으로 데려간다
데이터 없음           → no_data      : 보관만. 마운트 시 §18.3 1행이 판정한다
```

비호환에서 활성으로 세우지 않는 이유: 게이트가 닫힌 채 화면이 "이걸 만들 참"이라고 말하게
된다. 계약도 그 경우 선택이 아니라 **사유 표면**으로 보내라 적는다(§19.8).

셋째 갈래의 `preferredWorkId` 는 슬2가 **규칙만 박제하고 seam 을 비워 둔** 자리다(§8.2 ①).
F2 가 그 명시 사건의 유일한 원천이 되므로 여기서 채운다 — 비워 두면 데이터 없는 상태의
버튼이 작업을 겨누지 못한 채 이동하거나 숨어야 한다. 기본 데이터 참조가 있어도 **사용자
확인 없이 데이터를 자동 교체하지 않는다**(§19.8 마지막 줄).

보관분의 수명은 **1회 소비**다(착지 확정): 마운트에서 판정되면 승격이든 거절이든 비운다.
다음 마운트까지 들고 있으면 사용자가 잊은 의도가 나중에 조용히 발화한다 — 지연된 조용한
추측은 이 저장소가 반복해 밟은 결함류다(§8.4 4행 「지연 왕복 중의 의도」와 같은 뿌리).
명시 `select_job` 도 보관분을 소비한다(직접 고른 것이 더 최신 의사). 그리고 **승격하지 못한
경우도 침묵하지 않는다** — 활성 유지(§18.3 2행)·이 데이터로 실행 불가·작업 소실 셋을 갈라
`data_notice` 로 재진술한다. 방금 누른 버튼이 아무 일도 안 한 것처럼 보이는 게 조용한
소실이다.

#### 10.8.4 `home` 화면 사망 조건 점검표

전 항목이 새 거처에서 도달 가능함을 확인한 **뒤에만** 화면을 지운다(§10.4 서문).

| # | 도달해야 하는 것 | 새 거처 |
|---|---|---|
| 1 | 조건부 경보(`homeAlerts`) | 「확인 필요」 보기 + 탭 건수 |
| 2 | 손상 작업 격리·조치(열기·삭제, RC-05) | 목록 위 상주 danger 카드(심각도 4는 §19.7 축에도 동승) |
| 3 | 작업 카드 나열·복제·태그 편집·삭제·복원 | 라이브러리 행 + 상세 관리 행동 |
| 4 | 템플릿 다시 연결(`relink_template`, #67) | 상세 관리 행동(「확인 필요」 사유 동반) |
| 5 | `＋ 새 작업` | `libraryNewWork`(화면 머리) |
| 6 | 작업 브라우저 group-by 렌즈 + facet 칩 | facet 칩만 승계(판정 B — 렌즈는 고지 후 은퇴) |
| 7 | txt 트랙 목록 · `＋ 새 기안` | 레일 임시 「기안」 항목(F6 까지 존치 — 라이브러리 방식 필터가 최종 승계처) |
| 8 | 카드 「편집」 진입(`open_job_in_editor`) | 상세 상시 행동 `작업 편집` |

**착지 정산(2026-07-27)**: 8항목 전부 새 거처에서 도달 확인 후 화면 삭제(커밋 `dd332a2`).
사망 표면 = `#scr-home`·`web/js/screens/home.js`·`homeBrowser`·`.tracks`/`.track`/`.jobbrowser`/
`.tlist` CSS·레일 홈 항목·`set_group_by` 액션·링1 `grouped_rows`/`effective_group_by`/
`active_group_by`/씨앗 축 상수. 6행(group-by 렌즈)의 「문안 고지」 의무는 **실측으로 축소**됐다:
렌즈 값은 설정에 영속된 적이 없고 씨앗 상수로만 초기화됐으므로 사용자가 잃는 **저장 상태가
없다**. 상시 배너 대신 승계처(태그 facet 칩)를 같은 도구줄에 두는 것으로 갈음한다 — 없는
소실을 고지하면 경보가 싸구려가 된다. 화면 사망이 문안·표본에 남긴 빚도 함께 정산했다:
「홈에서 확인하세요」로 죽은 화면을 가리키던 저장 실패 문구, 죽은 클래스(`.kpis`·`.tracks`·
`.tlist`)를 겨눠 스타일 없이 렌더되던 `docs/UI_GALLERY.html` 표본, 홈을 살아 있는 호출자로
적던 주석·JSDoc.

#### 10.8.6 리뷰 3라운드 근본원인 재분석 (정지 규칙 §8.1)

1R·2R·3R 의 결함은 파일이 달랐지만 한 뿌리를 갖는다: **새 표면이 「무엇을 그릴까」(투영)와
「무엇에 대해 행동할까」(정체·목적지)를 한 페이로드로 뭉갰다.** 계약 §19.6 은 `sections`
(투영)와 `selectedWorkId`(정체)를 갈라 두는데, 구현은 링2가 걸러진 목록을 순회해 행동
인자를 조립했다 — 링1이 이미 걸러지지 않은 상세를 내고 있었는데도.

| # | 라운드 | 증상 | 뭉갠 지점 | 영구 가드 |
|---|---|---|---|---|
| 1 | 1R P1 | 필터 밖 선택의 태그가 확인 한 번에 전멸 | 행 페이로드의 `tags` 에서 정체 조립 | 행에서 태그 **삭제**(조립할 원재료 제거) + 정체는 상세에서만 |
| 2 | 1R P2 | 평면 보기에서 이동 도착지 소멸 | 걸러진 구획에서 도착지 조립 | 레지스트리 전역 `group_names` 페이로드 |
| 3 | 2R P2 | TXT 열기가 빈 화면 착지 | 표면이 매체로 목적지 조립 | `detail.primary`(목적지·라벨을 Python 이 낸다) |
| 4 | 2R P2 | 개명 뒤 상세가 닫힘 | 정체의 **수명**이 투영 갱신에 종속 | `refresh(select=)` 승계 + 실패 시 미승계 |
| 5 | 3R P2 | 미연결 작업도 빈 화면 착지 | 3과 **같은 클래스**(표시 정규화 ≠ 실행 판정) | 같은 `detail.primary` — 미연결은 편집기로 |
| 6 | 3R P2 | 그룹 병합 확인이 영영 안 뜸 | 모달 직렬화(`pendingDialog`)를 모른 채 중첩 | prompt 가 풀린 뒤 확정(「작업」 화면과 같은 순서) |
| 7 | 3R P2 | 빠른 2연타가 즐겨찾기 의도를 삼킴 | §8.4 4행 기제를 **새로 안 짜고 안 가져옴** | 기제를 `web/js/intent.js` 공용 몸통으로 — 두 표면이 한 몸통 |

**7이 특히 중요한 신호**: 이 파일 머리말은 처음부터 "의도 직렬화 기제를 그대로 옮긴다"고
적어 놓고 실제로는 DOM 값을 그대로 보냈다 — **계약이 거짓말한 자리**다. §8.4 가 4라운드에
걸쳐 세운 기제가 표면 하나 늘었다고 재발했다는 건, 그 교훈이 *문서에만* 있고 코드에는
없었다는 뜻이다. 그래서 점별 픽스가 아니라 기제를 공용 몸통으로 걷어 두 표면이 물리적으로
한 벌을 쓰게 했다(`grouplist.js`·`popover.js`·`datazone.js` 선례).

**후속 슬라이스에 적용할 규칙**: 새 표면이 목록을 그릴 때 —

1. **행 페이로드에는 그 행이 렌더하는 것만 싣는다.** 안 그리는 값은 조립의 미끼가 된다.
2. **행동의 인자(정체·목적지)는 걸러지지 않은 자리에서 온다.** 상세·전역 목록이 그 자리다.
3. **표시용으로 정규화한 값에서 행동 경로를 파생하지 않는다.** 표시 정규화와 실행 판정은
   목적이 달라 언젠가 갈리고, 그 틈이 곧 "빈 화면 착지"다.
4. **이미 세운 기제는 옮기지 말고 공유한다.** 옮겨 적는 순간 두 벌이 되고 한 벌만 고쳐진다.

#### 10.8.5 커밋 경계 (PR-A, 직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(4계약면 2벌·판정 8건·사망 점검표) |
| 2 | 링1: `library_health_causes` 신설 + `library_health` 를 그 파생으로 재작성 / 상세 투영 원재료(저장 Binding 읽기) / group-by 렌즈 은퇴(`set_group_by`·`effective_group_by`·`grouped_rows`·씨앗 상수 삭제) |
| 3 | 링2+UI 를 **한 전이로** — `screen_home.py`→`screen_library.py` 개명·채널/registry 키 `library`·액션 재편(보기·방식·검색·facet·접힘·선택 + 관리 6동사 + 세션 가드) / `#scr-library` 2-pane + `web/js/screens/library.js` + CSS 치수 계약 / `#scr-home`·`web/js/screens/home.js`·`homeBrowser` 삭제 / 레일 항목 교체 / DOM 계약·UI_CONTRACT·selftest 정산 |
| 4 | `문서 만들기에서 사용` 3분기 + `preferredWorkId` seam 채움(§18.3 개정 규칙의 첫 소비자) |

커밋 3 이 신설과 사망을 함께 지는 이유는 F1 커밋 2 와 같다: 푸시 채널·액션 키를 개명하는
순간 옛 홈 표면은 그 자리에서 죽는다(같은 채널의 구독자가 둘이 될 수 없다). 승계처가 서기
전에 지우지 않는다는 규율은 지켜진다 — 같은 커밋 안에서 먼저 서고 그다음 죽는다.

### 10.9 F2 PR-B 착수 계약 — 상단 2탭 셸 교체 + 「작업」 좌 master 목록 사망 (2026-07-27)

대조표 **1행**(상단 nav 2항목·5화면 라우팅 사망)과 **2행 후단**(좌 작업 목록 사망)을 진다.
PR-A 가 미룬 절반이다 — 「문서 작업」이 실제로 *저장된 작업을 찾는 자리*가 됐으므로 이제 셸을
갈아도 되돌릴 것이 없다(§10.8 서문의 조건이 충족됐다). **백엔드 신설 0**: 링1 은 전혀 손대지
않고, 링2 는 소비처가 사라진 페이로드·액션을 정산하는 삭제만 한다.

#### 10.9.1 §9.3 4계약면 사전 기입 (새 표면 = 상단 셸)

셸은 오버레이가 아니지만 **모든 화면을 감싸는 유일 표면**이라 같은 네 면을 진다. 새 정렬·분류
축은 없으므로 §8.4 4계약면은 이 슬라이스에 해당하지 않는다 — 탭은 라우팅이지 목록 절단자가
아니다(있지도 않은 축의 계약면을 적지 않는다, §10.8 판정 B 와 같은 규율).

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 탭의 `data-scr` 는 **화면 키 그대로**(`job`·`library`·`draft`·`tpl`)고 바뀌는 것은 라벨뿐이다 — 키를 함께 갈면 라우터·프로브·registry 세 계약이 한 커밋에서 동시에 흔들린다. 셸은 푸시 구독자가 아니라 재렌더 자체가 없고(`go()` 가 `aria-current` 만 토글), 테마·글자 크기 라벨은 기존 이벤트 단일 경로(`hwpx:themechange`·`hwpx:personalizationchange`)를 그대로 쓴다 | DOM 계약: `NAV_SCREENS` 4키가 상단 셸에서 전부 발견 + 테마·글자 크기 토글이 `navbtn` **아님**(라우터가 `.navbtn` 전부에 `go(data-scr)` 를 물려 화면을 지우는 회귀 — 기존 회귀 승계) |
| **전역 잠금의 범위** | 셸은 `setBusy` 의 **사각이고 그것이 의도다**: 생성 중에도 탭은 눌린다. 화면 전환은 파괴가 아니다(세션은 컨트롤러 소유, nav 는 CSS 토글이라 DOM 이 살아 있다). 파괴적 전이인 **생성 중 작업 전환**은 계속 Python 이 시끄럽게 거절한다(`_do_select_job` raise) — 잠금은 표면이 아니라 전이에 건다 | 회귀: 생성 중 탭 이동 후 복귀에 진행·결과·로그가 그대로 |
| **전이와 왕복의 순서** | `REFRESH_ON_NAV` 왕복은 화면 전환 **뒤**(현행 유지) — 셸 교체가 순서를 바꾸지 않는다. 교차 화면 이동(라이브러리 `문서 만들기에서 사용`)은 계속 **대상 dispatch 선행 · `Nav.go` 후행**이고 겨눔 실패면 화면 불변(§10.8.2 승계) | 실앱 게이트: 겨눔 실패 시 라이브러리에 남고 사유가 뜬다(기존 회귀 유지) |
| **실패 경로의 문맥 보존** | 좁은 창의 작업 영역 확보 수단이 **레일 접기 → 토바 고정 높이**로 바뀐다. 토바는 64px 한 줄이라 접을 것이 없고(레일 212px 보다 덜 먹는다) 접힘 설정은 표면과 함께 죽는다 — 마이그레이션·고지를 적지 않는다(사용자가 잃는 저장 상태가 「접혀 있었다」 한 비트뿐이고, 그 비트가 가리키던 표면이 없다). `master_width` 는 「기안」 좌 목록이 계속 소비하므로 **생존** | 설정 왕복 회귀에서 `rail_collapsed` 제거·`master_width` 존치, `.master-splitter` 개수 2→1 |

#### 10.9.2 판정 8건 (이 슬라이스에서 확정)

**A. 탭 라벨은 계약 어휘로 개명하고 화면 키는 그대로 둔다.** 「작업」 → **「문서 만들기」**
(§19 서문 "최상위 구조는 `문서 만들기 | 문서 작업`"). 그러나 registry·푸시 채널·프로브 키는
`job` 을 유지한다 — §10.8 판정 A 의 기준을 그대로 적용하면 `home` 은 *순전한 화면 이름*이라
개명했지만 `job` 은 **도메인 개체 이름**(`Job`·`JobRegistry`·`job.py`)이라 `pool` 과 같은
부류다. 화면 이름이 바뀌어도 어휘가 갈리지 않는다. 개명은 사용자가 읽는 자리(탭 라벨·`h1`·
문안)에서만 일어난다.

**B. 임시 2항목은 같은 탭줄 구분선 뒤에 두고, 곧 사라진다고 문안이 말한다**(사용자 확정
2026-07-27). 계약 2탭이 왼쪽, 구분선 뒤에 「기안」·「템플릿 관리」. 도달성 손실 0 이면서 최종
형상(구분선 왼쪽만 남음)이 미리 읽힌다. **제거 예고는 `title` 이 진다** — 상시 배너는 아직
정상 동작하는 화면에 대고 경보를 싸구려로 만든다(§10.8.4 착지 정산의 같은 판단).

**C. 데이터 없는 상태의 작업 선택기는 승계처 없이 사라진다.** 사용자 확정: *"데이터 없이
문서를 보는 그 상태 경로는 「문서 작업」으로 흡수되었다"*. 그래서 후보 side-card 는 §18.1
그대로 데이터 준비 시에만 서고, 데이터·작업이 **둘 다 없을 때만** 그 자리에 흡수처를 가리키는
출구(`「문서 작업」에서 고르기`)가 상주한다. 출구를 두는 이유는 기능 복원이 아니라 **막다른
화면 금지**다 — 흡수했다고 적어 놓고 가는 길을 안 보여 주면 그게 조용한 소실이다. 출구는
화면을 바꾸기만 하고 아무것도 겨누지 않는다(라이브러리에서 명시로 고르는 것이 `prefer_work`).

**D. 편집 → 실행 복귀 어포던스를 신설한다.** 결정 40 은 그 소임을 **좌 목록 행 클릭**에
줬는데(「편집 중 행 클릭 = 실행 복귀」) 그 표면이 죽는다. 기존 작업 편집은 저장해도 제자리에
머무르므로(editor.js `doSave`: "저장은 제자리") 목록이 사라지면 **실행 모드로 돌아갈 길이
없다**. `jobEditResume`(「편집 계속」)의 대칭으로 편집 모드 화면 머리에 「실행으로 돌아가기」를
둔다 — 전이는 기존 `exitEditToRun` 그대로라 비파괴이고 미저장 편집 고지도 그대로 발화한다.
새 전이를 만들지 않고 **기존 전이에 표면만 새로 붙인다**.

**E. 「여는 중」 지연 표지는 후보 카드·탐색 행이 승계한다.** `setJobOpening`(#217 R1 — 클릭
프레임에 즉시 서는 `aria-busy` + 라벨)은 지금 좌 목록 행에만 있다. 작업 선택의 유일 표면이
후보 카드·문서 탐색 행으로 옮겨 가므로 표지도 함께 옮긴다 — 삭제는 의무를 상속한다
([[measurement-litmus]] 의 "삭제된 경보" 클래스). 몸통은 하나로 두고 두 소비처가 쓴다.

**F. 죽는 것과 사는 것 — 액션·스냅샷 키 정산.** 소비처가 사라진 페이로드가 남으면 다음 세션이
그걸 근거로 목록을 되살린다(§10.8 판정 B 와 같은 이유).

| 대상 | 처분 | 근거 |
|---|---|---|
| `job` 스냅샷 `job_rows`·`job_sections`·`job_flat`·`job_group_names` | **사망** | 유일 소비처가 좌 목록·그 이동 다이얼로그다. 「기안」은 자기 스냅샷의 동명 키를 따로 낸다(무관) |
| `job/toggle_group` 액션 + `JobController._collapsed` | **사망** | 접힘 소유는 §10.8 판정 F 로 라이브러리에 넘어갔고 영속 키(`job_collapsed_groups`)는 공유다 — 표면 없는 두 번째 소유자가 남으면 제2 정본 |
| `job/rename_job`·`set_group`·`rename_group`·`disband_group` | **존치** | 표면은 죽어도 **소유는 「문서 만들기」 컨트롤러**다(§10.8 판정 F) — 라이브러리가 교차 화면 dispatch 로 부르는 유일 경로. 접힘 영속의 유령 이름 정리(`_recollapse`)도 여기 남는다: 그룹을 개명·해산하는 동사가 여기 있으므로. 인메모리 사본은 두지 않는다(제2 정본 금지 — 키는 라이브러리와 공유) |
| `job/toggle_favorite` | **존치** | 후보 카드 별이 유일 소비처로 남는다(§8.4 2행 승격은 라이브러리 행이 승계) |
| `job/clone_job`·`delete_job`·`undo_delete_job` | **사망**(착지 정정) | 착수 시엔 "라이브러리·에디터 소비처가 남는다"고 적었으나 **실측에서 되깎았다**: 라이브러리는 복제·삭제·복원을 **자기 채널에서** 소유하고(무장 세션은 `session_guards` 로 「문서 만들기」에 묻는다), 좌 목록이 죽으면 이 셋의 웹 소비처가 0 이다. 표면 없는 파괴 동사를 registry 에 남기는 것은 이 절이 금지한 바로 그 통로다 |
| `#jobListHwpx`·`.job-master`·`jobRowMenu`·`groupMoveModal`·`jobNewBtn`·`jobEmptyNewBtn`·`master-splitter`(job) | **사망** | 승계처: 라이브러리 행·상세·`libraryNewWork`(§10.8.4 3·5행에서 이미 도달 확인) |
| `job_list.build_group_sections`·`grouplist.js` 팩토리 | **존치** | 소비처 3(라이브러리·기안·템플릿 관리)이 남는다 |
| `JobScreen.refreshList` | **존치·재정의** | 에디터 저장 착지가 부르는 seam 이다. 갱신 대상이 좌 목록에서 **후보·탐색 면**으로 바뀐다(저장한 작업이 즉시 후보에 뜨게) |

**G. 토바 64px 은 구조 치수라 라이브러리 2-pane 계산을 다시 맞춘다.** 계약이 리터럴로 허용한
구조 치수다(§19.12: "토바 64px — 라이브러리 2-pane 의 `calc(100vh - 64px)` 가 소비"). 현행
`calc(100vh - 250px)` 은 레일 셸의 실측치라 토바가 생기면 **말없이 어긋난다** — 페이지가 스크롤
하지 않는다는 §19.6 명문이 조용히 깨지는 자리이므로 셸 커밋에서 함께 정산한다.

**H. 문안·주석 빚을 같은 커밋에서 정산한다**(§10.8.4 착지 정산의 선례 — 화면 사망은 자기가
남긴 거짓말을 치운다). 최소 목록: `screen_job.py` 의 「왼쪽 목록에서 직접 고르세요」(죽는 표면을
가리키는 안내 — PR-A 의 「홈에서 확인하세요」와 같은 클래스), selftest 합성 스냅샷의 게이트
문안 「왼쪽에서 작업을 선택하세요」, `index.html`·`app.js`·`job.js`·`editor.js` 의 "좌 레일 5화면
라우팅"·"좌 목록만 갱신" 주석, `UI_CONTRACT.md` 의 레일·`set_rail_collapsed` 항.

**I. 기본 데이터 참조를 가진 작업은 무데이터 상태에서도 연다**(착지 신설). 좌 목록이 살아
있을 땐 목록 클릭이 `select_job` 을 태워 #53-A 자동 조준(작업에 묶인 기본 데이터 자동 연결)이
발화했다. 목록이 죽으면 **무데이터 상태에서 작업을 겨눌 표면이 `prefer_work` 하나뿐**이라,
계약 §19.8 3분기 문면대로 「보관만」 하면 #53-A 가 **도달 불가능**해진다 — 계약이 예상하지
못한 소실이다(v6 에는 작업이 기본 데이터를 갖는다는 개념 자체가 없다). 그래서 `no_data`
갈래를 둘로 가른다: 기본 참조가 **있으면** 열고(자동 조준 발화·`data_notice` 재진술),
없으면 종전대로 보관한다. §19.8 의 "사용자 확인 없이 데이터를 자동 교체하지 않는다"는 계속
참이다 — 교체가 아니라 **빈 자리의 첫 마운트**다.

#### 10.9.3 좌 목록 사망 조건 점검표

전 항목이 새 거처에서 도달 가능함을 확인한 **뒤에만** 지운다(§10.4 서문).

| # | 도달해야 하는 것 | 새 거처 | 상태 |
|---|---|---|---|
| 1 | 작업 선택(행 클릭) | 후보 side-card + 문서 탐색 시트 (데이터 준비 시) | 이미 섬(R1) |
| 2 | 데이터 없는 상태의 작업 선택 | **없음 — 흡수**(판정 C). 출구만 상주 + 기본 데이터 참조를 가진 작업은 `prefer_work` 가 연다(판정 I) | 신설(출구·분기) |
| 3 | `rename_job`·`set_group`·`rename_group`·`disband_group`·`toggle_group`·`toggle_favorite` | 라이브러리 행·그룹 헤더·상세 관리 행동 | 이미 섬(PR-A 판정 F) |
| 4 | 복제·삭제·편집 진입 | 라이브러리 상세 관리 행동·상시 행동 | 이미 섬(PR-A) |
| 5 | `＋ 새 작업`(구획 ＋ · 빈 상태 버튼) | `libraryNewWork`(라이브러리 화면 머리) | 이미 섬(§10.8.4 5행) |
| 6 | 편집 모드 → 실행 복귀 | 편집 머리 「실행으로 돌아가기」 | **신설**(판정 D) |
| 7 | 「여는 중」 지연 표지 | 후보 카드·탐색 행 | **신설**(판정 E) |
| 8 | 순위 밖 작업의 즐겨찾기 승격 | 라이브러리 **행**의 별(절단 없는 표면) | 이미 섬(§10.8.1 도달성 면) |

#### 10.9.4 커밋 경계 (PR-B, 직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(§9.3 4계약면·판정 8건·사망 점검표) |
| 2 | **셸 교체 한 전이로** — `.topbar`(브랜드·탭 4[구분선 뒤 임시 2]·테마·글자 크기) 신설 / `.rail` 전체 삭제 · 접기(`railToggle`·`set_rail_collapsed`·설정 키·`rail-collapsed` CSS) 사망 / `.app` 그리드 재편 + 라이브러리 2-pane `calc` 재정산(판정 G) / 탭 라벨·`h1` 개명(판정 A) / DOM 계약·selftest·UI_CONTRACT·개인화 회귀 정산 |
| 3 | **좌 목록 사망 한 전이로** — `.job-master`·`#jobListHwpx`·`renderMaster`·⋮ 메뉴·인라인 개명·이동 다이얼로그·`jobNewBtn` 삭제 / 승계 3건(무데이터 출구·실행 복귀 버튼·「여는 중」 표지) / 스냅샷 4키·`toggle_group` 정산(판정 F) / 문안·주석 빚(판정 H) / 프로브 정산 |
| 4 | 실앱 순회가 잡은 잔여 2건 — 착지 표면 어긋남 픽스(`landRunMode`) + 판정 I(`prefer_work` 기본 데이터 분기) / 101 하니스 재배선·스크린샷 12컷 재생성·README 2종 |

#### 10.9.5 착지 정산 (2026-07-27)

**커밋 4 가 생긴 이유가 이 슬라이스의 교훈이다**: 커밋 2·3 은 전 테스트를 통과한 채
끝났지만, **실앱을 사람의 순서대로 한 바퀴 돌리자** 두 결함이 즉시 나왔다 — ①저장 직후
「문서 만들기에서 사용」이 편집 호스트에 착지 ②기본 데이터 참조가 있는 작업이 무데이터
상태에서 영영 안 열림. 둘 다 **죽은 표면이 겸하던 정산**(결정 40 의 실행 복귀, 목록 클릭이
태우던 `select_job`)이었고, 단위 계약은 각 조각이 살아 있음만 보므로 잡히지 않았다.
사망 점검표는 *도달 가능한가*를 묻지만 이 둘은 *경로가 이어지는가*의 문제다.

**후속 슬라이스에 적용할 규칙**: 표면을 죽이면 그 표면이 **다른 전이에 곁들여 하던 일**을
따로 세어 본다(그 표면이 유일 진입이던 전이의 목록을 적는다). 그리고 **착지 전에 실앱을
사람 순서로 한 바퀴** 돈다 — 101 자동 캡처 하니스가 그 순회의 기계판이므로, 표면을 죽인
슬라이스는 하니스를 **함께 갱신하고 실행**하는 것을 완료 조건으로 삼는다(이번에 그 하니스
자체가 데이터-우선 슬라이스 이후 stale 이었던 것도 같은 규칙의 부재가 낳은 부채다).

커밋 2 가 신설과 사망을 함께 지는 이유는 F1 커밋 2·PR-A 커밋 3 과 같다: 라우팅 표면은 하나뿐
이라 두 벌이 공존할 수 없다(`.navbtn` 이 두 곳에 있으면 `go()` 가 두 벌의 `aria-current` 를
갈라 쥔다). 같은 커밋 안에서 **먼저 서고 그다음 죽는다**.

### 10.10 F4 계약·정산 — 결과 3태 + 부분 실패 표면 (재시도 제외) (2026-07-27, **머지 `1ea532e`**)

대조표 8행(결과 3태·`결과 닫기`·더보기)과 9행(부분 실패 복구)을 진다. 계약 정본은 lab
`core-workflow.md` §10(성공과 실패)·§15.7(수용 시나리오)·불변식 §13-10·11이다.

**범위 축소(사용자 확정 2026-07-27)** — 9행의 **재시도 3종은 제외**한다: 건별 재시도 ·
레코드 filename override · 다른 폴더에서 재시도. 셋 다 `runOverrides`(F7, 대조표 23행)를
선행 요구하고, 대조표 9행 자신이 그 순서를 이미 적어 뒀다. 그 자리의 도달성은 판정 F
(「실패한 N건만 선택」)가 대신 진다. 이 슬라이스가 지는 것은 **3태 판정과 증거 표면**이다.

| 9행에서 F4 가 지는 것 | F7 로 미루는 것 |
|---|---|
| 성공분 보존 재진술 · 실패 레코드 식별 · 확인 가능한 증거(원문 무손실) · `원인 진단 미연결` 경계 · 외부 폴더 경계 문안 | 건별 재시도 · 레코드 filename override · 실패 1건만 재실행 |

**(후일담)** 미룬 셋은 F7 PR-B 에서 **기각**됐다(§10.14): 이 슬라이스가 착지시킨
「실패한 N건만 선택」 + 저장 폴더 변경이 확정 실패 원인 4종을 이미 전부 덮고, 남은 하나
(레코드 filename override)는 겨눌 실패가 없었다. 축소가 옳았을 뿐 아니라 **그 자리는 애초에
비어 있었다**.

#### 10.10.1 §9.3 4계약면 사전 기입 (새 표면 = 결과 3태 구획 + 접힘 증거)

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 결과는 **웹 소유 세션 상태**라 Python 푸시 재렌더에 갱신되지 않는다(현행과 같다). 구획 id `jobResult` 고정 · 태는 `data-state=completed\|partial\|failed` 로 표기(문안이 아니라 속성이 상태의 정체) · 접힘 증거는 `<details id="jobResultEvidence">` 로 열림 상태를 DOM 이 소유한다. 실패 행 id = `jobResultFail-<index>`(원본 레코드 index = 안정 키) | DOM 계약: 3태 속성값 열거 · selftest: 스냅샷 푸시 뒤 열린 `details` 가 닫히지 않음 |
| **전역 잠금의 범위** | 구획의 행동 4종(`결과 닫기`·`실패한 N건만 선택`·더보기·증거 펼침)은 전부 `data-busy-lock` — 생성 중 결과 구획은 **직전 실행의 결과**를 그리고 있어(판정 G) 그 위의 행동이 새 런과 겹치면 어느 실행 얘기인지 갈린다. 진행 표시는 같은 구획 안에서 태를 `running` 으로 두고 판정 태를 덮지 않는다 | DOM 계약: 구획 안 버튼 4종 `data-busy-lock` 보유 · selftest: 생성 중 클릭 무효 |
| **전이와 왕복의 순서** | 결과는 **선다**(포커스를 뺏지 않는다) — 생성 버튼은 하단 액션바에 있고 결과는 좌 본문 하단이라 포커스 이동은 사용자 의도를 가로챈다. 대신 `aria-live="polite"` + 요약 한 줄이 먼저 읽힌다. `결과 닫기` → 포커스는 생성 버튼으로. 더보기 → 편집 모드 진입(실행 모드 이탈)이지만 결과는 **파기하지 않는다** — 복귀 시 그대로 서 있다(강등 표기는 판정 G 규칙대로) | selftest: 닫기 뒤 포커스 착지 · 편집 왕복 뒤 결과 생존 |
| **실패 경로의 문맥 보존** | 배치가 시작조차 못 한 실패(구조 드리프트·충돌·폴더 오류)도 **구획 안에** 선다(판정 C) — 전역 백스톱으로 새면 결과 자리는 비어 있고 사용자는 "아무 일도 안 일어났다"로 읽는다. 스탬프 실패·취소·미착수는 태를 바꾸지 않고 같은 구획이 병기한다. 저장 폴더 어포던스(열기·복사)는 **실패 태에서도** 남는다 — 실패 진단의 첫 걸음이 그 폴더를 여는 것이다 | 회귀: 배치 예외 3종이 `failed` 태로 착지 · 취소 런이 `partial` 태 |

#### 10.10.2 판정 9건 (이 슬라이스에서 확정)

**A. 3태는 Python 단일 산출이고 `level` 채널과 병존한다.** `status`(`completed` /
`partiallyCompleted` / `failed`)를 신설하되 기존 `level`(ok·warn·danger)을 접지 않는다 —
둘은 다른 축이다. 취소 런은 **네 번째 태가 아니라** `partiallyCompleted` 의 변종
(`cancelled=true` + 미착수 N건 재진술)이고 `level="warn"` 을 유지한다(#278 리뷰가 세운
warn 채널 보존). 전건 실패는 `failed`, 1건이라도 성공하면 `partiallyCompleted` —
불변식 §13-10("일부 성공을 전체 성공으로 표시하지 않는다")이 태 경계를 정한다. JS 는
태를 재계산하지 않는다.

**B. 「원인 진단 미연결」은 힌트 매칭 실패의 함수다.** 계약 §10.3 은 원인을 꾸며내지
말라고만 하지 않고 **미확정임을 표시**하라고 한다. 그런데 지금 `describe_result_error`
는 힌트를 붙였는지 아닌지를 문자열 안에 녹여 버려 표면이 그 경계를 알 수 없다. 반환을
`(text, known)` 짝으로 분해하고, `known=False` 인 실패에만 「원인 진단 미연결」을 붙인다.
**원문 보존 규칙은 불변**(괄호 원문 = 증거) — 분해는 표기 경계를 얻기 위한 것이지
문안 재작성이 아니다. 아는 원인에 미연결을 붙이면 경보가 싸구려가 되고, 모르는 원인을
아는 척하면 조용한 오진이다.

**C. 배치 예외를 결과 구획으로 회수한다.** `generate_batch` 의 예외 3종(구조 드리프트
`ValueError` · `OutputCollisionError` · 폴더 `OSError`)은 지금 `_generate_locked` 를 관통해
브리지 rejection 이 되고 `app.js` unhandledrejection 백스톱이 받는다 — **결과 자리는 빈 채**다.
`failed` 태로 잡아 구획에 세운다(실패 단계 = "생성 시작 전", 영향 레코드 = 계획 전량,
받은 메시지 = 예외 원문). 백스톱은 지우지 않는다 — 최후 방어는 그대로 두고, 알려진
실패류만 앞에서 회수한다.

**D. 로그 상자는 결과만 내주고 산다.** 승계 의무는 "로그가 지금 말하는 것을 잃지 않는다"
인데, 조사해 보니 `log()` 호출부 17곳 중 **결과 사건은 4곳**(요약·실패 원문·FillNote·저장
폴더)이고 나머지 13곳은 데이터 불러옴·검색 실패·작업 열기 실패·탭 전환 실패·중단 요청·
T2 고지·재연결 메시지다 — 상자의 실제 소임은 **이 화면의 유일한 비모달 사건 통보 채널**
이었다. 통째로 죽이면 §10.9.5 가 잡은 결함류("죽는 표면이 곁들여 하던 일")를 그대로
되풀이한다. 그래서 결과 4종만 3태 구획으로 옮기고 상자는 **「실행 기록」으로 개명·역할
축소해 존치**한다(캡션·기본 문안도 그 역할로 정직화). **되깎기 조건**: 비-결과 사건이
상시 표면(토스트·상태줄)을 얻는 슬라이스가 서면 그때 상자를 죽인다.

**E. 실패 행 식별은 링1 단일 출처를 재사용한다.** 실패를 파일명만으로 부르면 "어느
행인가"를 사용자가 표에서 되찾아야 한다. 실패 행은 `identity_summary`(결정 37·A-1-15,
표 「문서」 열과 같은 함수)로 부른다 — 표면은 표현만 입히고 '어느 열로 요약할지'를
재구현하지 않는다. 결과 dict 의 실패 항목은 `{index, identity, filename, reason, known}`
구조를 싣는다(현행 `failures[]` 문자열은 사망).

**F. 「실패한 N건만 선택」은 선택만 바꾼다.** 재시도 자리의 도달성 대체물이다. 누르면
선택이 실패 레코드로 **교체**되고 **생성은 하지 않는다** — 의사표시 2클릭 분리(결정 28
「직전 필터 재적용」 선례: 정의만 복원하고 선택은 불변, 과 같은 격 구분). 성공분 보존은
신설 기제가 아니라 **덮어쓰기 확인 왕복**(RC-02)이 이미 담보한다. 인덱스는 **Python 이
소유**한다(`_last_failed_indices`) — 웹이 들고 있다 되돌려주면 그 사이의 데이터 교체·정렬
변경이 남의 행을 고른다. 데이터 겨눔·작업 전환은 이 목록을 비운다(stale 금지).

**G. 결과는 지문이 갈리면 강등하되 파기하지 않는다.** 판정 F 가 현행과 충돌한다 —
지금은 세션 지문(작업·데이터·폴더·선택 집합)이 바뀌면 `resetGenResult()` 로 결과를 **지운다**
(#28 "오래된 성공 잔존 방지"). 실패분을 선택하는 순간 그 결과가 사라지면 무엇을 다시
만드는지 볼 수 없다. 그래서 규칙을 바꾼다: 지문이 갈리면 결과를 **「직전 실행」으로 표기
강등**하고 남긴다. #28 이 막으려던 것(지금 상태의 결과인 척)은 강등 표기가 막고, 결과가
남는다는 사실은 §10.7.3 감사가 이미 적어 둔 것과 일치한다(데이터 전환 손실 열거에 결과를
넣지 않는 근거). 명시 파기는 `결과 닫기` 하나뿐이다.

**H. 자리는 현행 유지 — v6 와 어긋남을 여기 적는다.** v6 는 `result-panel` 을 화면 상단
(데이터 그리드 위 전폭)에 둔다. 우리는 좌 본문 하단 「생성 결과」 존 자리에 3태를 세운다.
근거: 현 좌열 순서(입력 → 되읽기 → 결과)가 흐름 순서와 같고, `data-preserve-scroll` 계약과
DOM 계약 순서(`jobTableHost < jobMirror < 결과`)를 건드리지 않는다. **되깎기 조건**: 생성
직후 결과가 스크롤 밖이라 못 보고 지나치는 사례가 실앱 순회에서 관측되면 상단으로 옮긴다
(그때 UI_CONTRACT 좌열 순서를 함께 개정).

**I. 더보기(⋯)는 「파일 이름 규칙 수정」 하나다.** v6 와 같다. 편집 진입은 신설하지 않고
`EditorEntry.openGuarded`(미저장 정의 확인 단일 출처)를 재사용한다. 다만 **파일 이름 탭은
아직 없다**(대조표 20행 — F7) — 착지는 현행 저장 단계 인라인이다. 열리는 곳을 실제와 다르게
말하지 않는다(문안이 "저장 단계의 파일 이름 규칙"을 가리킨다). 탭 승격은 F7 이 진다.

#### 10.10.3 로그 상자 승계 정산 (판정 D의 이행표)

| 지금 로그가 나르는 것 | 호출부 | 새 거처 |
|---|---|---|
| 완료 요약(`res.summary`) | `renderResult` | 3태 구획 제목·요약 줄 |
| 실패 원문(`[실패] …`) | `renderResult` | 실패 행 + 접힘 증거(원문은 `<details>` 안, 무손실) |
| 채움 주의(`[주의] …`, FillNote) | `renderResult` | 접힘 「채움 주의 N건」(완료 태에서도 뜬다 — #154 의 시끄러움 등급 유지) |
| 저장 폴더 경로 | `renderResult`·폴더 지정 | 구획 상시 행 + `PathTrack` 어포던스(열기·복사) |
| 생성 요청·취소 요청·취소됨 | `doGenerate`·중단 | 진행 태(`running`) + 취소 변종 재진술(판정 A) |
| 나머지 13종(데이터 불러옴·검색/열기/탭 전환 실패·T2 고지·재연결·편집 상태 확인 실패·폴더 오류) | 각처 | **「실행 기록」 상자 존치**(판정 D) |

#### 10.10.4 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(§9.3 4계약면·판정 9건·로그 승계 정산표) |
| 2 | 링1·컨트롤러 — `status` 3태 산출 · `describe_result_error` `(text, known)` 분해(판정 B) · 실패 항목 구조화(`identity_summary` 결합, 판정 E) · 배치 예외 회수(판정 C) · `select_failed` 액션 + `_last_failed_indices` 수명(판정 F) · 테스트 |
| 3 | 표면 — 3태 구획 재작성 + 접힘 증거 + 「실패한 N건만 선택」 + 결과 강등 표기(판정 G) + 로그 상자 역할 축소(판정 D) / DOM 계약·selftest·UI_CONTRACT·문안 정산 |
| 4 | 101 순회 실행·스크린샷 갱신(§10.9.5 규칙 — 표면이 바뀐 슬라이스는 하니스 실행이 완료 조건) |

커밋 2·3 을 가르는 이유는 F2 PR-B 와 반대다: 여기는 라우팅 표면이 아니라 **한 구획의
페이로드**라 두 벌이 공존해도 충돌하지 않는다(옛 `failures[]` 문자열과 새 구조가 한 커밋
동안 병존해도 표면은 하나만 읽는다). 판정 층을 먼저 세우고 표면이 그것을 소비한다.

#### 10.10.5 착지 정산 (2026-07-27)

계약 대비 **구현이 달라진 3건**과 그 근거다(적어 두지 않으면 계약이 거짓말이 된다).

| 계약 | 실제 | 근거 |
|---|---|---|
| 판정 I 「더보기(⋯)」 | **인라인 버튼** `파일 이름 규칙 수정` | F1 판정 E 와 같은 저울: 항목이 하나뿐인데 팝오버 생명주기(포커스 트랩·`Popover.closeAll`·좌표)를 새로 들이는 값이 도달성에 비해 크다. 밀도가 문제가 되면 그때 메뉴로 되깎는다 |
| 3태 = `[data-state]` 3값 | **5값** — 3태 + `running` + `rejected` | 진행과 "실행 전 거절"은 결과가 아니지만 **같은 자리에 서야 한다**: 거절이 결과 자리를 비워 두면 눌렀는데 아무 일도 없는 것으로 읽힌다. 판정 A 의 "취소는 네 번째 태가 아니다"는 그대로다 — 늘어난 둘은 성공/실패 축이 아니라 **실행 이전·도중**의 표시 상태다 |
| 계약면 3 「닫기 → 생성 버튼」 | 생성 버튼이 `disabled` 면 **구획 자신**(`#jobResultZone`, `tabindex="-1"`) | 게이트가 닫혀 있으면 그 버튼은 focus 를 못 받아 `focus()` 가 조용히 실패하고 body 로 떨어진다(§9.3 #2 결함 클래스의 재발). 착지는 "어느 요소"가 아니라 "실 DOM 안"이 계약이다 |

**실앱 한 바퀴**(§10.9.5 규칙): 101 자동 캡처 하니스를 재실행해 12컷을 갱신했다 —
실 클릭·실 dispatch·실 생성 3건이 새 구획을 통과한다. 101 README 의 결과 단계 문안도
3태 어휘로 갱신했다(문서가 죽은 표면을 가리키지 않게). 실패 경로(부분 실패·미확정 원인·
강등·닫기 착지·거절)는 실앱 게이트 프로브 `job_result` 7항이 실 WebView2 에서 진다.

**되풀이된 결함 클래스 1건**: `display:flex` 가 UA `[hidden]{display:none}` 을 특이도로
이기는 것(부록 B-9)을 또 밟을 뻔했다 — 이번엔 CSS 되돌림과 **계산 스타일 프로브**를 함께
넣었다(속성 존재만 보는 계약은 이 결함을 통과시킨다).

#### 10.10.6 리뷰 1R — P2 2건 조치 (2026-07-27)

둘 다 **드문 갈래에서만 갈라지는 파생**이었다. 정상 경로(레코드 몇 건 성공·몇 건 실패)는
맞게 돌고, 경계 갈래에서만 판정이 어긋난다 — 표본이 정상 경로뿐인 테스트가 통과시킨다.

| # | 증상 | 조치 | 영구 가드 |
|---|---|---|---|
| 1 | 첫 레코드 **전에** 중단한 런이 `failed` 태 — 성공 0·실패 0인데 "중단했습니다 · 0개 완료" 제목 옆에서 태가 없던 실패를 지어낸다. 판정 A 의 "취소는 부분의 변종"이라는 계약을 **구현이 배신**한 자리다 | `_run_status(succeeded, total, cancelled)` — 중단은 성공 수와 무관하게 부분 | 단위: `_run_status(0, 3, True)` + 착지 왕복(미착수 3·실패 0) |
| 2 | 배치 진입 전 실패에서 「실패한 N건만 선택」이 **숨는다** — 노출을 실패 행 목록에서 파생했는데 그 갈래는 레코드별 시도가 없어 행이 0개다. 백엔드는 전량을 들고 있는데 표면에서 복구 경로가 사라진다 | 노출·라벨을 Python 수치 `failed_selectable`(=`len(_last_failed)`)가 소유 | 단위: 예외 런 → 선택 비우고 복구 왕복 / 실앱 프로브: 행 0개에서 버튼 노출 + **없는 행을 지어내지 않음** |

**교훈**: 판정을 Python 이 소유하기로 했으면 그 판정의 **파생 수치까지** 소유해야 한다
(§10.10 판정 F 는 index 만 Python 에 뒀고 개수는 표면이 행에서 셌다 — 그 한 칸의 틈이
결함 2다). 그리고 프로브의 합성 페이로드는 실제 페이로드와 **같은 모양**이어야 한다:
새 키를 더할 때 프로브를 안 고치면 프로브가 옛 계약을 지키게 된다(이번에 실제로 프로브가
먼저 빨개져 그 규율이 작동했다).

#### 10.10.7 실행 기록은 기본 접힘 (사용자 확정 2026-07-27)

「실행 기록」에 쌓이는 대부분은 평시에 볼 일 없는 진행 서사다 — 상시 펼친 상자는
노이즈다. **기본 접힘**으로 바꾸되(`<details>`), 판정 D 가 세운 소임(이 화면의 유일한
비모달 사건 채널)은 그대로여야 하므로 **마지막 기록 한 줄은 접힌 채로도 보인다**
(요약 줄). 접힘은 **노이즈 억제**이지 소음 제거가 아니다 — 작업 열기 실패·폴더 오류가
접힌 상자에 묻히면 그건 조용한 실패다. 펼침은 그 세션의 의사표시라 결과 파기
(`결과 닫기`)에서 다시 접는다. 회귀 = DOM 계약(닫힘 기본 + `log()` 가 요약 줄 갱신) +
실앱 프로브 2항(접힘 상태·거절 사유가 요약 줄에 실림).

#### 10.10.8 리뷰 2R — P2 2건 조치 (2026-07-27)

둘 다 **판정 G(결과 강등)가 연 창**이다. 결과를 살려 두기로 한 순간 "그 결과의 세계"와
"지금 세션의 세계"가 갈라지는데, 그 틈에서 표면의 행동이 **지금 세션**을 겨눴다.

| # | 증상 | 조치 | 영구 가드 |
|---|---|---|---|
| 1 | 작업 A 결과가 강등된 채 남아 있는데 「파일 이름 규칙 수정」이 `LAST.job_name`(=B)을 열어 **남의 작업을 편집**한다 | 결과가 **주체를 진다**(`job_name`) — 세션이 다른 작업이면 행동 2종(편집 진입·실패분 선택)을 걷고 증거는 남긴다. 강등 문구가 어느 작업의 결과인지 밝힌다. 클릭 경로에도 방어적 재확인 | 단위: 결과 dict 의 `job_name`(완주·실패 경로 동형) / 실앱 프로브 4항(행동 2종 걷힘·증거 생존·문구가 주체 명시) |
| 2 | `_do_select_job` 이 `registry.load` **전에** 실패 목록을 비운다 — 삭제·손상된 후보를 클릭하면 세션은 그대로인데(vm·job_name 불변) 화면의 「실패한 N건만 선택」만 0건을 돌려주는 유령 행동이 된다 | 소거를 **전환 성사 뒤로** 이동(명시 해제는 그대로 소거) | 단위: 실패 전환 뒤 복구 대상 불변 → 성사 전환 뒤 소거 |

**교훈**: 상태를 **살려 두는 결정**은 그 상태를 소비하는 모든 행동에 "누구의 것인가"를
묻게 만든다. 강등(판정 G)은 결과를 살렸지만 결과가 **자기 주체를 안 들고 있었다** —
그래서 표면이 "지금 열린 것"으로 대신 채웠다. 곁들여 나온 규칙 하나: 세션 상태를 비우는
문장은 **그 전이가 실패할 수 있는 지점보다 뒤에** 둔다(같은 함수 안 `_last_generated` 는
조기 소거라도 안전 방향=가드 재무장이라 남겼다 — 방향이 다르면 처리도 다르다).

#### 10.10.9 리뷰 3R — 근본원인 재분석 (정지 규칙 §8.1)

3R 의 P2 는 "런 뒤에 작업 이름을 바꾸면 결과가 **남의 것**으로 판정돼 복구 행동이 사라지고
강등 문구가 거짓말한다"였다. 정지 규칙대로 점별 픽스 대신 5건의 궤적을 다시 본다.

| # | 라운드 | 증상 | 미정의였던 것 |
|---|---|---|---|
| 1 | 1R | 중단 전 0건 런이 `failed` 태 | 계약(판정 A)과 구현의 불일치 |
| 2 | 1R | 행 0개 실패에서 복구 행동 소멸 | **파생의 소유자** — 개수를 표면이 행에서 셌다 |
| 3 | 2R | 강등된 결과의 행동이 지금 작업을 겨눔 | **결과가 자기 주체를 모름** |
| 4 | 2R | 전환 실패인데 복구 목록만 소거 | 소거 문장이 실패 가능 지점 앞 |
| 5 | 3R | 이름이 바뀌면 같은 작업이 남처럼 보임 | **정체를 불변 스냅샷에 넣음** |

**같은 뿌리 = 「결과를 살려 두기로 한 결정(판정 G)이 두 세계를 만들었는데, 그 사이의 정합을
표면이 재판정하고 있었다.」** 2·3·5 가 한 줄기다: 판정을 Python 이 소유한다고 적어 놓고
실제로는 표면이 **개수를 세고(2) 정체를 들고(3) 이름을 비교했다(5)**. 결과 payload 는 한 번
찍고 안 변하는 값인데, 정합에 필요한 것들(대상 개수·주체)은 **그 뒤로도 변한다** — 변하는
것을 안 변하는 그릇에 담은 것이 결함의 형태였다.

**근본 조치(구조)**: 정합 판정에 드는 값은 **전부 스냅샷(변하는 것)에서** 온다.

| 무엇 | 어디로 |
|---|---|
| 실패 대상 개수 | `failed_selectable`(1R 조치) — 결과 payload 지만 그 런의 사실이라 안 변한다 |
| 직전 런의 **주체** | `_last_run_job` → 스냅샷 `last_run_job` — 이름 변경이 **같은 전이에서** 추종. 결과 payload 의 `job_name` 은 **삭제**(안 그리는 값을 싣지 않는다, §10.8.6 규칙 ①) |
| 표면의 판정 | `owner === LAST.job_name` — **두 값 모두 Python 산출**. 표면은 정체를 보관하지 않는다 |

곁들여 드러난 계측 결함 하나: `generate` 는 dispatch 밖이라 **자동 push 가 없어** 표면이
런 이전 스냅샷으로 결과 행동을 판정하고 있었다(주체는 물론 완주 스탬프도 다음 왕복까지
안 보였다). 런이 끝나면 스냅샷을 흘린다 — 덮어쓰기 확인 왕복에는 밀지 않는다(모달 중
재렌더는 dispatch 의 무변이 push 생략과 같은 이유로 낭비).

**후속 슬라이스 규칙**: 어떤 상태를 **살려 두기로** 하면(닫지 않고 남기는 결과·초안·세션),
그 상태를 소비하는 모든 행동에 대해 "**누구의 것인가**"와 "**아직 유효한가**"를 누가 답하는지
먼저 적는다. 답을 표면이 문자열 비교로 만들고 있으면 그건 판정이 두 벌이라는 뜻이다.

### 10.11 F3 계약·정산 — 표시순서 축 + 전문 범위 편집기 draft (2026-07-27, **머지 `900aecb`**)

대조표 4행(표시순서 선택기)과 10행(전문 범위 편집기)을 한 슬라이스로 진다. 계약 정본은
lab `core-workflow.md` §18.10(레코드 범위와 OrderedSelection) · 절대 불변식 §18.11-13·14·
18·20·21·27 · 이 문서 §2 충돌 B(표시순서가 파일명의 함수임을 인지·수용한 확정)다.

**사용자 확정 2건(2026-07-27)**:

| 사안 | 확정 | 근거 |
|---|---|---|
| 슬라이스 단위 | **F3 단독 먼저**, F5(미리보기·승인)는 다음 PR | F5 승인이 폐기·강등되는 조건이 「선택 지문 변화」인데 그 지문의 주체(RecordRangeState·draft 적용 경계)를 F3 가 세운다. 역순이면 임시 지문 위에 승인 규칙을 세웠다가 다시 간다 |
| 편집기 형상 | **현행 ⤢ 펼침 면(`dataSheet`) + draft 신설** — 전용 화면 신설 없음 | 마일스톤 L 밀도 라운드의 ⤢ 전용면 확정과 충돌하지 않고, 계약이 요구하는 것은 「별개 화면」이 아니라 **「적용 전 메인 범위를 바꾸지 않는다」는 draft 의미론**(§18.10·불변식 21)이다. 같은 일을 하는 표면을 둘로 만들면 그중 하나는 곧 승계 의무를 남기며 죽는다 |

#### 10.11.1 §8.4 4계약면 사전 기입 (새 축 = 표시순서 `sourceDesc`/`sourceAsc`)

| 면 | 이 축에서의 값 | 회귀 |
|---|---|---|
| **정밀도** | 정렬 키는 `snapshotOrdinal`(= 로드 순서 index)이고 **정수라 동률이 원리적으로 없다** — 즐겨찾기 스탬프(1R)와 달리 2차 정렬 규칙이 필요 없다. 이 면의 답은 "동률 없음"이며, 그래서 두 값의 순서는 서로 **정확한 역**이다 | 전 레코드에 대해 `sourceAsc` 가 `sourceDesc` 의 역순임을 세는 회귀(뒤집기의 항등성) |
| **절단·필터와 무관한 도달성** | 축은 **가시 목록에만** 걸리는 게 아니다. 표는 이미 `_display_indices(view.visible_indices())` 로 투영되지만, **필터 밖 선택 스트립**(`hidden_selected`)은 오늘 원본 순서로 실린다 — 축을 열면 두 목록이 서로 다른 순서를 말한다. 스트립도 같은 투영을 통과시킨다(판정 H). 실행 입력(`_indices`)·거울·파일명 계획은 이미 같은 훅을 소비하므로 자동 추종 | 회귀: 표·스트립·`_indices`·파일명 계획이 한 축을 공유(같은 순서열) |
| **상태의 주체** | `viewOrder` 는 **데이터(스냅샷) 귀속**이다 — 계약이 `recordRange` 안에 두었고, 데이터 전환·시트 교체는 `sourceDesc` 로 리셋한다(판정 J). 개인화 설정(테마·글자 크기 계층)으로 **승격하지 않는다**: 순서가 파일명의 함수라 "지난 데이터에서 쓰던 순서"를 새 데이터가 물고 오면 이름 규칙이 조용히 갈린다 | 회귀: 데이터 전환 뒤 `viewOrder == sourceDesc` · 설정 저장소에 키 없음 |
| **지연 왕복 중의 의도** | 선택기는 왕복 액션이라 **낙관 반영 후 확정**이다. 값이 하나뿐이라 즐겨찾기 같은 의도 큐는 필요 없지만, 왕복 전 도착한 push 가 select 를 옛 값으로 되돌리는 창은 같다 — `preserve.js` 대상에 넣고, 왕복 중 재변경은 **마지막 값이 이긴다**(중간 값은 버린다, 취소 아님) | selftest: 연속 2회 전환 뒤 최종 축이 나중 값 · push 재렌더가 select 를 되돌리지 않음 |

#### 10.11.2 §9.3 4계약면 사전 기입 (새 표면 = ⤢ 면의 draft 거래)

기존 면을 재사용하지만 **거래 의미론이 신설**이라 4면을 다시 적는다 — 지금 이 면은 상태를
직접 편집하고(`SurfaceSheet` 가 실 DOM 을 옮긴다) 닫기 = 그냥 복귀다.

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | draft 는 **Python 소유**(판정 A)이고 스냅샷에 `range_draft{open, dirty, sel_count, view_order, selected_only}` 로 실린다 — 열림 여부가 DOM 클래스가 아니라 상태다. 면이 열린 동안 push 재렌더는 **draft 값을 그린다**(판정 D 경계). 실 DOM 이동이라 행 id·스크롤·앵커 보존은 현행 `SurfaceSheet` 계약을 그대로 상속 | selftest: 면 열린 채 push 왕복 후 draft 선택 수 유지 · DOM 계약: `range_draft` 소비 노드 id 고정 |
| **전역 잠금의 범위** | 생성 중에는 **면 열기·적용·취소 전부 잠근다**(`data-busy-lock`) — draft 적용은 실행 입력을 바꾸는 전이라 진행 중 런과 겹치면 어느 범위로 만든 결과인지 갈린다. 반대로 **draft 가 열려 있는 동안 생성 버튼도 잠근다**(면이 모달이라 물리적으로 못 누르지만, 잠금은 DOM 이 아니라 상태가 진다) | selftest: 생성 중 적용 무효 · 면 열림 중 `generate` 액션 거절 |
| **전이와 왕복의 순서** | **성사 뒤에만 닫는다**(§9.3 4행 상속): 적용은 Python 커밋이 성공한 뒤 닫기, 취소는 draft 폐기 push 뒤 닫기. 포커스 착지는 ⤢ 트리거(`jobDataExpand`) — `SurfaceSheet.trigger` 현행 규약 그대로. 이탈 가드(판정 F)는 **닫기 시도 시점**에 끼어들고, 「머무르기」는 면을 열어 둔 채 아무것도 하지 않는다 | selftest: 적용 실패 시 면 생존 · 닫힌 뒤 포커스 착지 |
| **실패 경로의 문맥 보존** | 적용 시점에 스냅샷이 갈렸으면(데이터 재로드·시트 교체) draft 는 stale 이다 — **적용을 거절하고 사유를 면 안에서 재진술**하며 닫지 않는다. 조용히 커밋하면 남의 스냅샷 index 로 남의 행을 고른다(F4 판정 F 의 「웹이 인덱스를 들고 있다 되돌려주면」과 같은 뿌리) | 회귀: 스냅샷 세대 불일치 적용이 거절 + 메인 범위 불변 |

#### 10.11.3 판정 10건 (이 슬라이스에서 확정)

**A. draft 는 Python 이 소유한다.** 웹은 draft 복제본을 들지 않고 액션만 보낸다. F4 판정 F
(`_last_failed_indices` 는 Python 소유)와 같은 근거 — 웹이 든 인덱스 집합을 되돌려주는 순간
그 사이의 데이터 교체·정렬 변경이 남의 행을 고른다. 면이 열린 동안 13액션은 **같은 이름
그대로** draft 를 향한다(액션을 두 벌로 늘리지 않는다 — 같은 동사가 대상만 바뀐다).

**B. draft 가 덮는 것 = `RecordRangeState` 전부.** 선택 집합 · 검색 · 열 필터 · 표시순서.
계약이 한 그릇에 넣었고(§18.10 `recordRange`), 검색·필터를 committed 에 남겨 두면 "편집기에서
좁혀 고른 뒤 취소했더니 메인 화면 필터만 바뀌어 있다"가 된다. **예외 1건**: `selected_only`
(선택된 항목만 보기)는 draft 안에서만 사는 **보기 상태**라 적용 대상이 아니다 — 적용해도
메인 화면은 selected-only 로 켜지지 않는다(메인엔 그 토글이 없다. v6 도 편집기 도구줄에만 둔다).

**C. 축의 주소지는 둘, 상태는 하나.** 표시순서 선택기는 v6 대로 **메인 캡 줄과 편집기
도구줄 양쪽**에 선다. 상태는 `viewOrder` 하나이고, 면이 열려 있으면 편집기 쪽이 draft 값을,
닫혀 있으면 메인이 committed 값을 편집한다. 한쪽에만 두면(편집기 전용) 축이 절단 뒤에
숨는다(§8.4 2행이 잡은 「상위 5 밖 즐겨찾기」와 같은 도달성 결함).

**D. 스냅샷 이중 소스의 경계를 여기서 긋는다.** 면이 열린 동안:

| 구획 | 소스 | 이유 |
|---|---|---|
| `filter` · `table` · `restate` · 필터 밖 선택 스트립 · 면 footer(`선택 적용: N건`) | **draft** | 편집 중인 것을 그리는 자리 |
| 게이트(`validation`) · 거울 · 후보 side-card · 실행 입력(`_indices`) · `N개 생성` 버튼 수치 · 세션 지문 | **committed** | 불변식 21 — 적용 전 메인 범위·validation·approval·결과를 바꾸지 않는다 |

경계를 코드가 아니라 표로 먼저 적는 이유는 §10.8.6 규칙 ①(행에는 그 행이 렌더하는 것만
싣는다)의 반대 방향 실수 — **한 스냅샷에 두 세계가 실릴 때 어느 소비처가 어느 세계를 읽는지**가
정의되지 않으면 그 틈이 곧 결함이다(F4 3R 의 「두 세계의 정합을 표면이 재판정」).

**E. 적용의 증거 처리는 강등이지 폐기가 아니다.** 계약 §18.10 은 "적용 때 selection
fingerprint 가 바뀐 경우에만 실행 증거를 폐기"라고 쓰지만, **F4 판정 G(§10.10.2)가 이미
개정한 규칙이 우선한다**(§10.0 3행: 확정된 개정분 > 계약 원문): 지문이 갈리면 결과는
「직전 실행」으로 **강등 표기하고 남는다**. 명시 파기는 「결과 닫기」 하나뿐이다. 지문이
같으면(선택 집합·순서 동일) 아무 일도 일어나지 않는다 — 검색·필터만 바꾸고 적용한 경우가
여기다(§18.10 수용 3의 "approval 을 폐기하지 않는다"가 이 자리다).

**F. 이탈 가드는 변경이 있을 때만, 3택으로.** `dirty == false` 면 닫기는 그냥 닫기다(마찰
없음). `dirty` 면 **적용 · 버리기 · 머무르기** 3택 — 에디터 section 가드(`sectionGuard`)와
같은 격이고 문안·기제를 그 선례에서 가져온다. 「버리기」는 draft 만 버린다(불변식 21).

**G. 선택 정체성은 index 를 유지한다 — snapshot-local id 신설을 기각한다.** 계약은
`snapshotRecordId`·`snapshotOrdinal` 을 요구하지만, 우리 `records` 는 **마운트 단위로 통째
교체되고 마운트 직후 선택 0건**(§18.2 확정)이라 index 가 이미 snapshot-local 이며 ordinal 과
같은 값이다. 즉 계약이 막으려는 것("원본 행 번호를 영구 ID 로 쓰기")을 우리는 구조적으로
이미 안 한다 — F2 의 group-by 영속값과 같은 **실측 축소**다. 대신 그 사실을 말로 두지 않고
**불변식 회귀로 못 박는다**: 새 스냅샷 commit 뒤 선택 0건 · 스냅샷 교체가 선택을 index 로
승계하지 않음. **되깎기 조건**: 스냅샷을 갈지 않고 레코드를 부분 갱신하는 경로가 생기면
(재로드 병합 등) 그때 id 를 신설한다.

**H. 필터 밖 선택 스트립도 표시순 투영을 받는다.** 지금은 원본 순서다(`hidden_selected`).
표본 3건이 표와 다른 순서로 나오면 "보이는 것 = 실행되는 것"이 스트립에서만 깨진다.

**I. 표시순서 전환의 파일명 파장은 재진술로 진다 — 확인 왕복을 두지 않는다.** 순서가
`{{seq}}`·동명 꼬리표(`naming._dedupe`)의 함수라는 것은 §2 충돌 B 에서 **인지하고 수용한**
확정이고, 완화는 "미리보기가 같은 투영을 보여주는 것"이다. 우리 표는 이미 행마다
`plan_output_names` 결과를 「문서」 열에 싣고 있어 **전환 즉시 새 이름이 보인다** — 보이는
변화 앞에 확인 왕복을 두면 과경고다(confirm-or-alarm 완화 조항 = 전면 가시성 + 무반복 +
틀리면 보이는 추측, R-flow 결정 31). 선택기 옆 상시 문구가 파일명 연동을 한 줄로 말한다. **되깎기 조건**:
파일명에 순번·꼬리표가 **없는** 작업에서도 경고가 뜨는 식으로 문안이 거짓말하면 조건부로 바꾼다.

**J. 데이터 전환·시트 교체는 축을 리셋하고 draft 를 강제 폐기한다.** `viewOrder = sourceDesc`
(불변식 §18.11-13 "새 스냅샷은 최신 행 먼저로 시작한다"), draft 는 폐기한다 — 스냅샷이 갈리면
draft 가 겨누던 index 는 남의 행이다. 폐기는 **전환 손실 가드 열거에 싣는다**(F1 §10.7.3 이
세운 감사 규칙: 가드 문안은 실제 파기 집합과 대조한다). 단 면이 열린 동안엔 데이터 전환
경로가 모달에 막혀 있어, 이 갈래는 "면 밖에서 전환 → 열려 있던 적 없음"이 정상 경로다.

#### 10.11.4 `dataSheet` 승계 정산 (형상 확정의 이행표)

⤢ 면을 죽이지 않고 **거래를 얹는** 것이므로 사망 점검표가 아니라 「지금 하던 일이 새 의미론
아래서도 그대로 되는가」의 표다.

| 지금 ⤢ 면이 하던 것 | 새 의미론에서 |
|---|---|
| 실 DOM 이동(`jobRecsHead`·`jobFilterChips`·`jobTableHost`·`jobSelStrip`·`jobColPanel`) | 그대로 — 이동 목록 불변, 렌더 소스만 draft |
| 닫기 = 즉시 복귀 | `dirty` 면 3택 가드(판정 F), 아니면 현행과 동일 |
| 열림 중 선택·필터 편집이 **즉시 메인에 반영** | draft 로 격리 — 이것이 이 슬라이스가 바꾸는 유일한 행동 |
| 스크롤·포커스 복원(`data-preserve-scroll`·`trigger`) | 그대로 |
| 열 패널(`jobColPanel`) 안에서의 필터 편집 | draft 대상(판정 B) — 패널은 같은 13액션을 쓴다 |
| footer 없음 | 신설: `선택 적용: N건` · `취소` · `선택된 항목만 보기` 토글 · 표시순서 선택기 |

#### 10.11.5 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(§8.4·§9.3 4계약면 · 판정 10건 · 승계 정산표) |
| 2 | **표시순서 축** — `_display_indices` 를 `viewOrder` 상태의 함수로(훅은 유지) · `set_view_order` 액션 · 스트립 투영(판정 H) · 데이터 전환 리셋(판정 J 전반) · 메인 캡 선택기 + 재진술 문안(판정 I) · 4계약면 회귀 |
| 3 | **draft 층(Python)** — `RecordRangeDraft` 복제·적용·취소·`dirty`·스냅샷 이중 소스 경계(판정 D) · 세대 불일치 거절(§10.11.2 4면) · 13액션 라우팅(판정 A) · 테스트 |
| 4 | **표면** — ⤢ 면 footer(적용·취소·selected-only·축) · 이탈 가드 3택(판정 F) · busy-lock 확장 · DOM 계약·selftest·UI_CONTRACT·문안 정산 |
| 5 | 101 순회 실행·스크린샷 갱신(§10.9.5 규칙 — 표면 변경 슬라이스의 완료 조건) |

커밋 2 를 먼저 두는 이유: 표시순서는 draft 없이도 **혼자 완결**되는 축이고(오늘의 고정값을
사용자 축으로 여는 것뿐), draft 는 그 축을 복제 대상에 포함해야 하므로 순서가 거꾸로면
커밋 3 이 자기 대상 하나를 나중에 얻는다.

#### 10.11.6 착지 정산 (2026-07-27)

커밋 2 `e150594` · 3 `4380598` · 4 `63ab07f` · 5(101). 1969 passed · 실앱 게이트 69 passed ·
101 하니스 13컷 완주.

**되깎은 것 1건 — 판정 F(이탈 가드 3택 → 2택)**. 근거로 든 "에디터 section 가드 선례"가
**master 에 없었다**(확인 모달은 2택뿐이고 3택 기제는 v6·계약 쪽 개념이다). 한 자리를 위해
3택 모달을 신설하는 대신, 「적용」이 이미 면 안의 상시 primary 버튼이라는 사실로 대체한다 —
「계속 편집 → 적용」이 한 클릭이고 파괴 방향(버리고 닫기)은 그대로 명시 확인을 받는다.
되깎기 조건: 3택이 필요한 **두 번째 소비처**가 생기면 그때 기제를 세운다.

**실측 축소 2건**: ①판정 C(축 주소지 2곳) — ⤢ 면이 실 DOM 을 옮기므로 주소지가 둘이 아니라
**같은 요소가 따라간다**(복제 없음 = 상태가 갈릴 자리 없음). 도달성 요구는 그대로 충족.
②판정 H(스트립 투영) — 작업 화면은 이미 표시순 투영을 통과한 실행 입력을 스트립 소재로
넘기고 있었다. 거짓말한 것은 코드가 아니라 주석(「원본 순서」)이었고, 사실로 고치고 회귀를
붙였다.

**판정 D 의 세부 1건을 구현 중에 확정**: 표 「문서」 열의 파일 이름도 **초안 투영으로 다시
계획**한다. 이름이 커밋 기준으로 남으면 편집기 안에서 축을 바꿔도 열이 안 움직여, 판정 I 의
완화("표가 새 이름을 즉시 보여준다")가 하필 그 축을 만지는 자리에서 죽는다.

**경계를 지키느라 갈라야 했던 것 3곳**(판정 D 표의 실제 이행 비용):

| 자리 | 갈래 |
|---|---|
| 순서 투영 | `_display_indices` = **존 표시**(초안 축) / `_indices` = 실행 입력(커밋 축) |
| 가시 집합 | 렌더용(`_zone_visible` — selected-only 가 갈아끼움) / 판정용(`view.visible_indices()`) |
| 세션 가드 | 초안이 열린 동안만 재평가(초안 필터의 가시 집합으로 커밋 선택을 재지 않는다) |

**곁들여 봉합 1건**: `setBusy` 의 잠금 루트에 ⤢ 펼침 면 2종이 빠져 있었다 — 실 DOM 이동이라
잠글 요소가 면 안으로 **옮겨가** 화면 질의에서 빠진다(§9.3 3행이 오버레이 루트에 대해 잡은
결함의 이동 버전).

**교훈 2 — 프로브가 프로브를 오염시키는 두 표본**(계측 리트머스 승계). ⤢ 면 열기가
Python 왕복 뒤로 바뀌자 기존 동기 프로브가 "열리기 전"을 재기 시작했다. 비동기로 떼어 내는
과정에서 ①**앞 프로브의 늦은 push** 가 도착하면 작업 미선택 스냅샷이 내 면을 정당하게 닫고
②`Nav.go('job')` 는 `REFRESH_ON_NAV` 로 실 refresh 를 쏴 같은 일을 한다. 둘 다 프로덕션 결함이
아니라 **프로브가 만든 상태**였다. 규칙으로: 프로브는 ⓐ앞 프로브의 잔여 왕복을 흘려보내고
ⓑ자기 판을 자기가 세우며 ⓒ**실패 경로에서도 연 면을 반드시 닫는다**(열린 채 남기면 뒤
프로브의 계약이 대신 깨진다).

**교훈 1 — 101 한 바퀴가 또 한 건을 잡았다**(§10.9.5 후속 규칙의 두 번째 배당). 하니스에
범위 편집기 한 바퀴를 넣자 「취소」가 곧바로 닫히지 않았다 — 표시순서를 바꿔 초안이 dirty
였고 이탈 가드가 정당하게 끼어든 것이다. 결함이 아니라 **대본이 실물보다 순진했던 것**이고,
사람 순서로 밟지 않았으면 가드가 실앱에서 실제로 뜨는지 아무도 안 봤을 자리다.

#### 10.11.7 리뷰 1R — P1 2건·P2 2건 조치 (2026-07-27)

네 건이 **한 뿌리**다: 초안이라는 두 번째 세계를 만들어 놓고, 그 세계가 새면 안 되는 자리를
경계표(§10.11.3 판정 D)에 **적어 두고도 세 곳에서 새게 두었다.**

| # | 등급 | 증상 | 샌 자리 |
|---|---|---|---|
| 1 | P1 | 재렌더가 축 선택기를 커밋 값으로 되돌려 선택기·표·적용값이 갈림 | 표시(초안) ↔ 선택기(커밋) |
| 2 | P1 | 적용도 안 한 초안 편집이 완료 결과를 「직전 실행」으로 강등, 취소해도 복구 안 됨 | 세션 지문이 **표의 선택 표지**에서 파생 |
| 3 | P2 | 취소가 성사 전에 닫아 느린 브리지에서 초안 기준 렌더·고아 초안 | 적용은 성사 뒤 닫기, 취소만 fire-and-forget |
| 4 | P2 | 축 왕복 미직렬화 — 빠른 두 번 선택이 뒤집혀 커밋되면 순번 파일 이름이 반대로 | 화면 값(`pendingOrder`)만 지키고 **쓰기 순서**는 무방비 |

**근본 조치**: ①·② 는 같은 처방이다 — 값의 출처를 **존 대상 하나**로(축 표시) / **판정
주체 하나**로(`selection_key` = 커밋 실행 입력) 통일한다. F4 3R 이 세운 규칙("정합에 드는
값은 판정 주체가 낸다")의 두 번째 적용이며, ②는 그 규칙을 **적용했어야 할 자리를 F3 가
새로 만들어 놓고 지나친** 사례다. ③은 성사-뒤-닫기 순서의 비대칭, ④는 "이미 세운 기제를
공유한다"(`Intent.chained`)의 미적용이었다.

**후속 규칙**: 두 번째 세계(초안·미리보기·세션 사본)를 도입할 때는 경계표를 적는 것으로
끝내지 말고, **커밋 세계를 소비하는 기존 판정을 전부 열거해** 그것들이 새 payload 의 어느
필드를 읽는지 한 번씩 확인한다 — ②는 경계표에 「세션 지문 = 커밋」이라고 적어 두고도
그 지문의 **재료**가 초안 payload 라는 것을 안 본 결함이다.

**곁들여 프로브 1건**: 닫기가 비동기가 되자 ⤢ 면 프로브가 복귀를 실패로 읽었다 — 프로브는
실물의 **시간 성질**을 따라가야 한다(폴링으로 교체). 또한 축 회귀를 101 하니스에 실을 때
첫 판이 무력했다(클릭 직후를 재 아직 안 온 재렌더를 통과로 읽음) — **양성대조**로 잡았고,
판정 수치가 바뀐 뒤를 재도록 고쳤다.

#### 10.11.8 리뷰 2R — P1 1건·P2 1건 조치 (2026-07-27)

1R 이 "두 세계가 **공간**으로 새는 자리"(어느 payload 를 읽는가)였다면, 2R 은 **시간**으로
새는 자리다: 이미 예약됐거나 날아가는 중인 발신이 초안이 사라진 **뒤에** 착지한다.

| # | 등급 | 증상 | 뿌리 |
|---|---|---|---|
| 1 | P1 | 검색 디바운스(200ms) 안에서 취소를 누르면, 사용자가 **버린 검색어**가 초안 소멸 뒤 도착해 커밋된 필터에 걸린다 | 예약된 발신에 대상 세계가 안 실린다 |
| 2 | P2 | 열기 왕복 중 다른 탭으로 떠나면 전역 펼침 면이 **남의 화면 위에** 열리고, 안 열면 초안만 남아 생성이 잠긴다 | 왕복의 성사 조건에 "그 화면이 아직 여기 있는가"가 없다 |

**근본 조치**: 존의 발신을 **단일 통로**(`datazone.js`의 `call`)로 모으고, 화면이 키를 주면
(`chainKey`) 13액션과 **초안의 적용·취소가 한 체인**을 쓴다 — 순서가 뒤바뀔 여지 자체를
없앤다. 예약분은 출구가 정산(적용: `flushPendingEdits`)하거나 폐기(취소: `dropPendingEdits`)
한다. 열기는 성사 시점에 `#scr-job.on ∧ MODE==='run'` 을 다시 확인하고, 아니면 열지 않고
초안을 거둔다.

**체인이 드러낸 것 2건**(직렬화는 공짜가 아니다):
- **무변이 질의는 체인 밖**이어야 한다. `filter_panel` 을 넣었더니 "응답이 영원히 안 오는
  질의"를 일부러 만드는 기존 프로브가 이후 모든 변이를 막았다 — 순서 보장은 **같은 상태를
  바꾸는 발신들** 사이에서만 뜻이 있다.
- **통로는 요청 시점에 함수로 붙든다**. 객체만 붙들면 큐에서 풀릴 때 그 사이 바뀐 통로로
  나간다(프로브 스텁이 대표 사례 — 요청은 스텁에 걸렸는데 발신은 실물로 샌다). 주석에는
  "요청 시점에 붙든다"고 먼저 적어 놓고 구현이 객체를 붙들고 있었다(§10.8.6 교훈 ②의 재발:
  머리말이 코드보다 앞서간 자리).
- 기존 프로브 하나(#217 R2 낙관 토글)는 "영원히 미결인 promise"로 왕복 미결을 흉내 냈는데,
  직렬화 뒤에는 그것이 둘째 발신을 영영 막는다. 프로브가 재려던 것은 **push 가 오기 전
  재클릭의 값**이지 promise 의 매달림이 아니라, 해소되는 스텁 + 별도 되읽기로 교체했다.

#### 10.11.9 리뷰 3R — 근본원인 재분석과 구조 가드 (정지 규칙 §8.1)

세 라운드의 6건은 **한 가족**이다: 초안이라는 두 번째 세계를 만들고 그 경계를 §10.11.3 판정
D 에 **표로만** 적었다. 표는 사람이 지키는 것이고, 경계는 세 축에서 샜다.

| 축 | 라운드 | 샌 자리 |
|---|---|---|
| **공간**(어느 payload 를 읽는가) | 1R | 세션 지문이 표의 선택 표지에서 파생 · 축 선택기가 커밋 값만 렌더 |
| **시간**(언제 도착하는가) | 2R | 디바운스 예약분이 초안 소멸 뒤 착지 · 열기 왕복 중 화면 이탈 |
| **이름**(같은 이름이 두 세계를 겸함) | 3R | `selected_count` 하나가 표 머리(존)와 게이트 지목(커밋)을 겸함 · 체인 키를 **위젯 단위**로 나눠 축 변경이 취소를 추월 |

**근본 조치 2건**:

1. **체인 키는 상태 단위다.** 축 전용 키(`job:view_order`)를 폐기하고 같은 `recordRange` 를
   바꾸는 발신은 전부 `job:zone` 한 줄에 세운다. 위젯마다 키를 나누면 "직렬화했다"는 말이
   각 줄 안에서만 참이 된다.
2. **경계표를 구조 가드로 승격**(`test_draft_touches_exactly_the_keys_the_boundary_table_names`).
   초안이 열린 채 선택·필터·축을 전부 바꾼 뒤 **움직인 스냅샷 키의 집합**이 경계표와 정확히
   같은지 센다 — 목록에 없는 키가 흔들리면 커밋 세계가 물든 것이고, 있는 키가 안 흔들리면
   편집기가 자기 편집을 안 그리는 것이다. `_SESSION_ATTRS` 구조 가드(PR #308)와 같은 격:
   다음 누락은 사람이 아니라 게이트가 잡는다. 취소 뒤 **전 키 원복**도 같은 테스트가 센다.

**후속 규칙(§10.11.7 규칙의 강화)**: 두 번째 세계를 도입하면 경계를 문서가 아니라 **테스트가
소유**하게 한다 — "이 상태를 소비하는 판정 목록"을 손으로 열거하는 대신, 페이로드가 어느
세계를 따라 움직이는지 기계가 세게 만든다.

#### 10.11.10 리뷰 4R — 세대(epoch)로 시간 축을 닫다 (2026-07-27)

3R 의 근본 조치(구조 가드)는 **공간·이름** 축을 닫았지만 **시간** 축에는 아직 규율이
없었다. 4R P1 이 그 잔여를 정확히 짚었다: 출구(적용·취소)가 느리면 그 뒤에 줄 선 편집이
**초안이 사라진 뒤 실행**돼 커밋 범위에 착지한다. 2R 이 닫은 것은 「예약분」(디바운스)뿐이고,
「이미 큐에 선 발신」은 열려 있었다.

**근본 조치 — 존 변이가 대상 세계를 실어 보낸다.** `zone_epoch` 는 웹이 **발신 시점에 보고
있던** 범위 세계의 세대다. 초안이 열리거나 닫히거나(적용·취소) 데이터가 갈리면 오르고,
세대가 다른 변이는 dispatch 관문에서 `{"stale": true}` 로 **실행되지 않는다**.

| 성질 | 판정 |
|---|---|
| 판정 주체 | **Python**. 웹은 자기가 무엇을 보고 있었는지만 정직하게 나른다(판정 A 의 연장) |
| 조용한 무시 아닌가 | 아니다 — 사용자는 그 세계를 **명시 행동**(취소·적용·데이터 교체)으로 버렸다. 버린 세계의 편집을 지금 세계에 적용하는 쪽이 조용한 파괴다 |
| 세대를 안 싣는 발신 | 무검사 통과. 존을 공유하는 「기안」 화면은 세계가 하나뿐이라 그것이 정답이다 |
| 소속 판정 | **무엇을 바꾸는가**로 정한다 — `set_view_order` 는 화면 전용 액션이지만 같은 `recordRange` 를 바꾸므로 세대 검사 대상이다(체인 키를 상태 단위로 둔 것과 같은 근거) |

**P2 3건**(같은 시간 축의 잔가지): ①이탈 가드가 `dirty`(=푸시가 온 사실)만 보다가 **방금 친
편집**을 못 보고 확인 없이 버렸다 → 대기 중 변이 수를 함께 센다 ②세션 전환이 디바운스
타이머만 끄고 **대기 소재**를 남겨, 나중 정산이 죽은 세션의 열 조건을 새 세션에 보냈다
③축 왕복이 실패하면 스냅샷이 안 와서 선택기만 거절된 값에 머물렀다 → 값을 되돌리고 시끄럽게.

**구조 가드가 즉시 일했다**: `zone_epoch` 를 스냅샷에 싣자마자 §10.11.9 의 경계 가드가
"경계표에 없는 키가 초안에서 움직였다"고 실패했다 — 새 키의 소속(경계 자신의 좌표, 단조
증가라 취소해도 안 되돌아옴)을 선언하게 만든 것이 그 가드의 일이다.

#### 10.11.11 리뷰 5R — 세대 기제가 스스로 연 창 + 데이터-우선 회귀 (2026-07-27)

정지 규칙의 5라운드다. 두 건 모두 **직전 라운드의 조치가 연 창**이고(F2 PR-A 가 이미 잡은
패턴 — "각 라운드가 직전 픽스가 연 창"), 세 번째는 오탐이었다.

| # | 등급 | 증상 | 뿌리 |
|---|---|---|---|
| 1 | P1 | 편집 직후 ⤢ 를 누르면 **그 편집이 사라진다**(커밋에도 초안에도 없음) | 열기가 존 체인 **밖**의 직접 호출이라 큐에 선 편집을 추월 → 세대가 오른 뒤 도착한 편집이 stale 로 거절 |
| 2 | P2 | 작업 미선택 상태(데이터-우선)에서 범위 편집기가 **첫 편집마다 닫힌다** | `syncModeDisplay` 의 강제 닫기가 `edit \|\| !hasJob` 인데, 데이터-우선에선 `!hasJob` 이 정상 상태다 |

**조치**: ①열기도 `flushPendingEdits()` 뒤 **존 체인에 세운다** — 복제되는 범위가 사용자가
보고 있던 그것이 된다 ②강제 닫기의 사유를 **면별로** 가른다: 거울 면은 작업의 것이라
`!hasJob` 에 닫히고, 데이터 면은 데이터-우선에서 작업 없이도 사는 표면이라 **편집 모드**
에서만 닫는다.

**오탐 1건(P2)**: "`set_view_order` 스키마가 `epoch` 를 **required** 로 만들어 selftest 프로브가
거절된다" — 실제로는 `_schema("value", "epoch")` 의 둘째 인자가 **optional** 이고
(`required={'value'}, optional={'epoch'}`), 세대를 안 싣는 발신은 무검사 통과가 계약이다.
실앱 게이트 69건이 그대로 통과하는 것이 반증이다. 지적 자체는 좋은 자리를 짚었다 —
세대를 필수로 만들었다면 정확히 그 결함이 났을 것이고, 그래서 "선택 필드" 판정을
§10.11.10 표에 남겨 둔 것이다.

**5라운드 결산**: P1 5·P2 9 = 14건이 전부 같은 가족(초안↔커밋 경계의 공간·시간·이름 축).
근본 조치 3단(값의 단일 출처 → 구조 가드 → 세대)으로 축을 하나씩 닫았고, 마지막 두 건은
그 조치들이 서로의 사각을 만든 자리였다. 정지 규칙대로 **5라운드에서 멈추고 머지 판단으로
넘긴다** — 다음 라운드가 또 "직전 픽스가 연 창"을 낸다면 그때는 설계 교체를 검토한다.

### 10.12 F5 계약·정산 — 미리보기 드로어 + 검토 요구(승인) (2026-07-27, **머지 `8dcc209`**)

대조표 16행을 진다. 계약 정본은 lab `core-workflow.md` §7(Value preview·Preview approval
정의)·§12(상태와 사건)·절대 불변식 §13-2·3·4·5·6, 그리고 **보고서 F-06 개정판**
(`ReviewRequirement` = 위험 분류 + 증거 정책 + fingerprint)이다 — v6 의
`preview.required`/`approved` 불리언 게이팅은 §4 폐기 목록이라 **이식하지 않는다**.

**사용자 확정 3건(2026-07-27)**:

| 사안 | 확정 | 근거 |
|---|---|---|
| F7 선행분 처분 | **제외** — 값·파일 이름·승인만. 행별 「수정」은 현행 편집기 진입 하나, 적용 범위는 「기본 규칙」 고정 | v6 드로어의 `이번 생성에 적용` 배지·per-field deep-link 는 `runOverrides`·`EditContext`(F7)의 표면이다. 판본 없는 상태에서 override 저장 경계(§13-14·15)를 임시로 세우면 F7 에서 다시 간다 — F4 가 재시도 3종을 뺀 것과 같은 축소 |
| 검토 요구의 기준선 | **영속 기준선 + 세션 승인** — `Job` 가산 필드에 「마지막 완주가 쓴 규칙 지문」을 남기고, 승인 자체는 세션 | §13-2(정상 반복 실행에서 미리보기는 선택)가 **앱 재시작을 넘어** 성립해야 한다. 세션 사건만으로 세우면 어제 규칙을 바꾸고 오늘 열었을 때 요구가 조용히 사라진다. 반대로 승인을 영속시키면 승인만 하고 실행 안 한 채 재시작한 세션이 열린 게이트로 시작한다 — 기준선은 영속, 승인은 휘발이 fail-closed 조합이다 |
| 위험 분류 깊이 | **구조화 지문 3분류**(표시형·의미 연결·파일명 집합) | F-06 이 P0 로 지목한 결함은 "승인 불리언이 어떤 증거에 근거했는지 추적 불가"다. 기준선이 blob 해시면 `changedTargets` 도 `riskClass` 도 계산되지 않아 이름만 `ReviewRequirement` 가 된다. C-02 차등화(선택 변경 시 승인 폐기 범위)도 이 위에서만 가능 |

#### 10.12.1 §9.3 4계약면 사전 기입 (새 오버레이 = 미리보기 드로어)

§10.5 「항목 착수 전 필수 절차」의 이행분. 호스트는 `modal.js` 스택(신설 0) — F1
다이얼로그·`jobBrowseSheet` 와 같은 부류다(실 DOM 을 옮기는 `SurfaceSheet` 가 아니다:
드로어 내용은 이 면에서만 사는 새 DOM 이다).

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 열림 여부·현재 레코드 자리(`index`)는 **Python 소유**(`preview` 스냅샷 구획) — F3 초안이 세운 선례 그대로, DOM 클래스가 아니라 상태다. 자리는 **표시순 투영의 서수**이지 원본 index 가 아니다(판정 M). 면이 열린 동안 push 재렌더는 같은 자리를 다시 그린다 | selftest: 면 열린 채 push 왕복 후 `N / M` 유지 · DOM 계약: `preview` 소비 노드 id 고정 |
| **전역 잠금의 범위** | 생성 중(`setBusy`)에는 드로어 루트도 훑어 잠근다(오버레이 루트는 화면 루트 질의 밖 — §9.3 3행의 사각). **반대 방향도 잠근다**: 범위 초안(⤢)이 열려 있으면 드로어를 열지 않는다 — 미리보기는 **커밋된** 실행 입력의 상이라 초안 세계와 겹치면 어느 범위의 미리보기인지 갈린다(판정 H) | selftest: 생성 중 승인·이동 무효 · 초안 열림 중 `preview_open` 거절 |
| **전이와 왕복의 순서** | 승인은 **Python 커밋이 성공한 뒤** 면이 열린 채 상태만 갱신한다(닫지 않는다 — 승인 후 나머지 레코드를 계속 넘겨볼 수 있어야 한다). 닫힘 시 포커스는 여는 트리거(`jobPreviewOpen`)로 복귀(Modal 소유). 레코드 이동은 왕복 액션이라 **마지막 값이 이긴다**(F3 표시순서 선택기 선례 — 중간 값은 버린다) | 실앱 게이트: 승인 뒤 면 생존 · 닫힌 뒤 포커스 착지 · 연속 이동 뒤 최종 자리 |
| **실패 경로의 문맥 보존** | 값 파생이 실패하는 경로(레코드 0건·작업 미선택·선택 집합이 그 사이 비었다)는 **면 안에서 재진술**하고 닫지 않는다. 승인 거절(세대 불일치·요구 없음)도 같다 — 조용히 승인 상태를 세우지 않는다 | 회귀: 선택 0건 전이 뒤 면이 사유와 함께 생존 · stale 승인 거절 |

#### 10.12.2 판정 13건 (이 슬라이스에서 확정)

**A. 미리보기 값은 파생이지 상태가 아니다 — 백엔드 신설 0의 투영.** 드로어가 그리는 값은
`RunViewModel.mapped_records(indices)` 의 그 레코드 행이고, 파일 이름은 `_record_rows` 가
이미 계산해 표 「문서」 열에 싣는 **바로 그 문자열**을 재사용한다. 한 건만 따로
`make_output_filename` 하면 `{{seq}}` 가 1 로 고정되고 `_dedupe` 꼬리표가 사라져 미리보기가
실행과 다른 이름을 말한다 — 파일 이름은 **배치 전체 계산의 i번째**여야만 참이다. 날짜 토큰
기준 시각도 같은 `_names_now` 를 탄다(RC-02 「확인 대상 = 생성 대상」의 미리보기 확장).

**B. 요구의 기준선은 영속, 승인은 세션.** `Job` 에 가산 필드
`reviewed_rules: dict[str, str]`(대상별 지문) — 마지막 **완주** 런이 쓴 규칙을 적는다.
- 스탬프 시점은 `last_run_at` 과 **같은 전이·같은 술어**(`not cancelled and batch.failed == 0`).
  완료 이벤트가 둘로 갈라지면 이력과 검토 요구가 서로 다른 실행을 완주로 부른다(#129 선례).
- `content_fingerprint` 에서 **제외**한다(`tags`·`last_run_at`·`favorited_at`·`group` 선례):
  검토 메타를 지문에 남기면 실행 한 번이 열어 둔 편집 세션에 「외부 변경을 덮어씁니다」라는
  거짓 파괴 확인을 띄운다.
- **복제 미계승**(`clone_job` — `last_run_at`·`favorited_at` 과 같은 줄): 복사본은 아직 아무
  문서도 만들지 않았으므로 처음부터 검토 요구를 진다.
- 승인은 세션 상태(`_approved_key`)다. 승인만 하고 실행하지 않은 채 재시작하면 요구가
  되돌아온다 — 안전 방향이다.

**C. 대상별 지문 = 4축, 링0 단일 출처.** `core/job.py` 에 `rules_fingerprints(job)` 신설
(`content_fingerprint` 옆 — 두 표면이 복붙하면 그 드리프트가 곧 조용한 오판정):

| 키 | 값 | 바뀌면 |
|---|---|---|
| `template` | 템플릿 경로 | 구조 위험 |
| `filename` | 파일명 패턴 | 파일명 집합 위험 |
| `field:<이름>:source` | 그 필드의 source·type·const·blank | 의미 연결 위험 |
| `field:<이름>:format` | 그 필드의 표시형 코드(`fmt`) | 표시형 위험 |

`changedTargets` = 기준선과 달라진 키. 필드 추가·삭제도 여기서 잡힌다(키의 등장·소멸 =
F-06 표의 「의도적 미사용」 행). 위험 서열은 **구조 > 파일명 > 의미 > 표시형** — 여러 축이
동시에 바뀌면 가장 무거운 것이 `riskClass` 다(증거 정책이 그것을 덮는다).

**D. 없는 증거는 꾸며내지 않는다 — before/after 는 F5 범위 밖이다.** F-06 의 증거 표는
「이전 표시 → 새 표시」·「이전 source → 새 source」를 요구하지만, 우리 기준선은 **지문만
저장하지 값을 저장하지 않는다**. 이전 값을 복원할 원천이 없으므로 증거는 **현재 값 + 변경
대상 이름 + 영향 규모**로 짓는다(§10.3 「원인을 꾸며내지 않는다」와 같은 계열 — 권위 없는
값을 지어내느니 없다고 말한다). **되깎기 조건**: F7 판본이 서면 직전 판본의 값이 실재하므로
그때 before/after 를 채운다. 증거 정책 이행표:

| riskClass | 이 슬라이스가 싣는 증거 | 출처 |
|---|---|---|
| `presentation` | 바뀐 필드의 **현재 표시 값**(이 레코드) + 표시형이 붙었다는 표지 | `mapped_records` · `_formatted_fields` |
| `semantic_binding` | 바뀐 필드의 현재 값 + 선택분 중 **서로 다른 값의 수** + **값이 비는 레코드 수** | `mapped_records` 집계(거울의 `_field_value_display` 와 같은 술어) |
| `filename_set` | 이름이 **수렴해 꼬리표가 붙은 건수** + **경로 길이 초과 건수** + 이 레코드의 실이름 | `plan_output_names` 대조(판정 K) |
| `template_structure` | **승인 대상 아님** — 판정 E | — |

**E. 구조 위험은 승인이 아니라 게이트가 진다(F-07 실측 축소).** master 의 드리프트 게이트는
이미 fail-closed 다: 템플릿 구조가 확정 매핑과 다르면 `danger` 로 **차단**하고 에디터에서
매핑을 다시 확정해야만 풀린다. 즉 「값 미리보기로 구조 변경을 승인」하는 F-07 결함 경로가
master 엔 애초에 없다 — 승인 표면을 새로 만들면 오히려 **게이트를 우회하는 두 번째 권위**가
생긴다. 구조 검토 표면은 계약대로 **F8**(~~템플릿 바꾸기·시험 탭~~) 소관이었으나, F8 착수
실측에서 그 후보 둘이 모두 기각돼(§10.16·§10.17.1) 이 판정의 「구조 위험은 게이트가 진다」가
최종형으로 확정됐다.

**구현 중 되깎기 1건(구멍을 막았다)**: 처음엔 "`template` 축을 `riskClass` 서열에 남기되
승인은 요구하지 않는다"고 적었는데, 그러면 **템플릿과 필드 source 가 같이 바뀐 경우** 서열
1위가 `template_structure` 로 잡혀 승인이 면제되고 **의미 변경이 검토를 통과해 버린다**.
그래서 축을 분리한다: `riskClass` 는 **승인을 요구하는 세 축**(`filename_set` >
`semantic_binding` > `presentation`) 안에서만 정하고, 템플릿 변경은 `structure_changed`
병기 플래그로 문안이 말한다(게이트는 드리프트가 진다). 서열은 면제의 근거가 될 수 없다 —
가장 무거운 축이 가장 약한 처분을 부르면 그건 서열이 아니라 구멍이다.

**F. 게이트 서열에서 검토 요구의 자리 = 전제조건 다음, 열림 직전. level `warn`.**
```
드리프트(danger) > 파일명 미해소 토큰(danger) > 미확인 빈 값(warn)
  > 저장 폴더·선택 0건·이어채우기(warn) > **검토 요구(warn)** > 열림
```
전제조건보다 **뒤**인 이유: 선택 0건에서는 미리보기에 진입하지 않는 것이 불변식
(§18.11-6·§13-26 「첫 레코드를 실행 미리보기로 대신하지 않는다」)이라, 선택이 0인데
"검토하세요"라고 말하면 이행 불가능한 지시가 된다(F2 prework 게이트가 같은 이유로
`available` 만 셌다). `GateState.reason` 에 `review_required` 를 추가한다 — 표시면이 게이트
서열을 재유도하지 않게 하는 축(리뷰 F2 선례).

**G. 드로어는 요구가 없어도 열린다 — 생성과 승인은 다른 사건이다.** 「미리보기」 버튼은
선택 ≥1 이면 상시 열린다(§13-2: 정상 반복 실행에서 미리보기는 **선택**). 승인 버튼은
요구가 있을 때만 나타나고, **면을 열었다는 사실은 승인이 아니다**(불변식 §13-4
`PreviewCreated != PreviewApproved`) — 승인은 명시 클릭 하나뿐이다.

**H. 드로어는 커밋 세계를 그린다(F3 경계표 승계).** 미리보기는 실행 입력의 상이므로
`selection_key`·`_indices`·게이트와 같은 세계다. 범위 초안(⤢)이 열려 있으면 드로어를 열지
않는다(§10.12.1 2행) — 초안 세계의 미리보기를 그리면 "적용도 안 한 편집으로 만든 미리보기를
승인"하게 되고, 그 승인은 불변식 21(적용 전 approval 을 바꾸지 않는다) 위반이다.

**I. 승인의 유효 범위는 위험별로 다르다(C-02 차등화의 이행).** 승인 키:

| riskClass | 승인이 결속되는 값 | 근거 |
|---|---|---|
| `presentation` | `rules_key`(대상별 지문의 해시)**만** | 표시형 증거는 레코드 집합과 무관하다 — 선택을 넓혔다고 「2026. 07. 25. → 2026년 7월 25일」을 다시 확인시키는 건 과경고 |
| `semantic_binding` · `filename_set` | `rules_key` + `selection_key` | 증거가 "선택분 중 몇 건이 달라지나"·"이 배치에서 몇 건이 수렴하나"라 선택·순서가 바뀌면 그 증거 자체가 무효다 |

`selection_key` 는 F3 가 세운 값(선택 집합 + **순서**)이다 — F3 선착지를 확정한 이유가
여기서 회수된다(§10.11 사용자 확정 1행). 규칙이 바뀌면 `rules_key` 가 갈려 승인이 **자동**
무효가 된다: 별도 폐기 코드를 두지 않는다(불변식 §13-6 을 판정 주체 하나로 만족).

**J. 거울과 드로어는 같은 값의 두 축 — 게이트를 겸하지 않는다.** 거울(`jobMirror`)은
**필드축**(선택 전체 집계 · 「외 K개 값」 표본 · `ack_field` 게이트 표면, 결정 3 존치),
드로어는 **레코드축**(레코드 1건의 전 필드 + 그 레코드의 파일 이름). 값은 둘 다
`mapped_records` 단일 출처다. **드로어는 ack 를 다루지 않는다** — 빈 값 확인의 표면이 둘이면
같은 게이트에 권위가 둘이다(§10.5 판정 단일 출처).

**K. C-01 판정 — 조건부 위험의 처분(지도가 「슬5에서 확정」이라 명시한 항목).** 실측:

| C-01 항목 | master 현황 | F5 처분 |
|---|---|---|
| 미해소 토큰(빈 토큰) | `unresolved_name_tokens_for` 가 **danger 차단** | **충족** — 그대로 |
| 디스크 기존 파일 충돌 | `output_conflicts` + 덮어쓰기 확인 | **충족** — 그대로 |
| 배치 내 유일성 | `OutputNamer._dedupe` 가 꼬리표로 보장(파일 소실 없음) | **충족** |
| 서로 다른 레코드가 같은 이름으로 수렴 | 꼬리표가 **조용히** 붙는다 | **증거로 싣되 경보 승격 없음** — 표 「문서」 열이 그 행의 실이름을 이미 보여준다(완화 조항: 전면 가시성 + 틀리면 보이는 추측). 대신 `filename_set` 증거가 "N건이 수렴해 꼬리표가 붙었습니다"로 규모를 말한다 |
| 값이 빈 토큰으로 이름이 무너짐 | 무경보(이름만 짧아진다) | 위와 같다 — 수렴 집계가 이 경로를 함께 잡는다(무너진 이름끼리 겹치므로) |
| 최대 길이 | **무검사** — 생성 시 OSError 로 터진다 | **사전 경보로 승격**(신설): `out_dir` + 이름 길이가 한계를 넘는 건수를 세어 게이트 `warn` + 드로어 증거. 실행하면 확실히 실패하는 것을 실행해서 알게 하는 건 확인-또는-경보 위반이다. 차단이 아니라 경고인 이유 = 확장 경로·`longPathsEnabled` 환경에서 실제로 성공할 수 있어 단정하면 문안이 거짓이 된다 |

**L. 「수정」은 편집기 진입 하나 — deep-link 는 F7.** 행별 버튼은 현행
`openEditForRepair` 경로를 재사용하고 드로어를 닫는다. 돌아와서 규칙이 바뀌었으면 판정 I 에
의해 승인이 자동 무효가 되고 요구가 다시 계산된다 — 복귀 배선을 따로 세우지 않아도 정합이
유지되는 것이 "판정 주체 하나" 설계의 배당금이다.

**M. 레코드 자리는 표시순 서수다.** `‹ N / M ›` 의 N 은 **표시순서 투영의 i번째**(F3 판정 H
가 표·스트립·실행 입력·파일명 계획을 한 축으로 묶은 그 순서)이고 M 은 선택 건수다. 원본
index 로 세면 「보이는 것 = 실행되는 것」이 이 면에서만 깨진다. 자리는 Python 이 서수로
소유하고 웹은 인덱스를 되돌려주지 않는다(F4 판정 F·F3 판정 A 와 같은 뿌리).

**N. 기존 작업의 첫 만남 — 처분은 같고 말이 다르다(구현 중 발견).** 이 기능 이전에
만들어진 작업은 디스크에 기준선이 없다. 그대로 두면 「아직 한 번도 문서를 만들지 않은
작업입니다」가 **수백 번 실행한 작업**에 뜬다 — 거짓 문안이고, 거짓 경보는 경보를
싸구려로 만든다. 그렇다고 조용히 기준선을 찍어 주는 것은 **하지 않은 검토를 했다고
기록하는 것**이라 더 나쁘다. 그래서 요구는 그대로 세우되(불확실 시 허용 전이는 확정
요구뿐) 갈래를 셋으로 둔다:

| 상태 | 문안 머리 |
|---|---|
| 실행 이력 없음 + 기준선 없음 | 「아직 한 번도 문서를 만들지 않은 작업입니다.」 |
| 실행 이력 있음 + 기준선 없음(구 버전 작업) | 「마지막 실행에 쓴 규칙을 확인할 수 없습니다.」 |
| 기준선과 어긋남 | 「규칙이 바뀌었습니다: (대상)」 |

한 번 완주하면 기준선이 서고 그 뒤로는 §13-2 대로 조용하다 — 업그레이드 비용은 작업당
1회다.

**O. 검토 요구는 라이브러리 건강 사유가 **아니다**(PR-2a 커버리지 가드가 물어본 것).**
슬3 PR-2a 가 세운 가드는 "실행 게이트의 데이터-무관 차단 사유를 건강 번역이 빠짐없이
덮는가"를 센다 — `review_required` 를 만들자마자 그 가드가 걸렸다(설계대로다). 판정:
**덮지 않는다.** 계약 §19.7 의 원인 표는 손상·경로 없음·미지원 방식·드리프트·끊어진 참조
뿐인 **결함의 닫힌 목록**이고, 검토 요구는 결함이 아니라 정상 흐름의 한 단계다. 끼우면
새로 만든 모든 작업이 「확인 필요」에 서서 그 구획이 뜻을 잃는다(진짜 고장 난 작업이 새
작업들 사이에 묻히는 경보 인플레이션). 대신 가드에 **배제 선언 표**(`not_health`)를 더해
이빨을 남긴다 — 다음 사유도 번역을 얻든 배제 근거를 적든 **둘 중 하나를 명시적으로** 해야
통과한다. 조용한 무시와 선언된 배제는 다르다.

#### 10.12.3 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(§9.3 4계약면 · 판정 13건 · C-01 처분표) |
| 2 | **검토 요구 판정** — 링0 `rules_fingerprints` · `Job.reviewed_rules`(가산·지문 제외·복제 미계승) · 완주 스탬프 공유 · 링1 `gui/review_state.py`(`ReviewRequirement` 산출: riskClass·changedTargets·증거) · 게이트 서열 편입(판정 F) · 승인 키 차등화(판정 I) · 회귀 |
| 3 | **파일명 집합 증거** — 수렴 집계 + 경로 길이 술어(판정 K) · 게이트 warn · 회귀 |
| 4 | **드로어 표면** — `modal.js` 호스트 · 레코드 이동(표시순 서수) · 값·파일 이름·적용 범위 · 승인 버튼 · 증거 구획 · DOM 계약 · action registry · UI_CONTRACT · selftest 프로브 |
| 5 | **101 하니스 갱신·실행 + 실앱 한 바퀴**(§10.9.5 후속 규칙 2) · 착지 정산 |

#### 10.12.4 착지 정산 (2026-07-27)

**되깎기·실측 발견 3건**(전부 §10.12.2 판정 본문에 박제):
- **판정 E 구멍**(구현 중) — 템플릿 축을 서열 1위로 두고 승인 면제하면 템플릿과 source 가
  같이 바뀔 때 의미 변경이 검토를 통과한다. 서열은 **승인 요구 3축 안에서만** 정한다.
- **판정 N 신설**(구현 중) — 이 기능 이전에 만들어진 작업은 기준선이 없다. 요구는 세우되
  문안을 셋으로 가른다(거짓말 금지). 업그레이드 비용은 작업당 1회.
- **판정 O 신설**(가드가 물었다) — 검토 요구는 §19.7 라이브러리 건강 사유가 **아니다**.
  배제를 **선언**으로 남겨(가드의 `not_health` 표) 조용한 무시와 구분한다.

**프로브·눈검증이 잡은 것 5건**(정적 계약은 전부 통과하고 있었다):

| 어디서 | 무엇 | 왜 정적 계약이 못 봤나 |
|---|---|---|
| 실 창 프로브 | `setBusy` 의 `[data-busy-lock]` **일괄 복원**이 `renderPreview` 가 끈 버튼을 되살려, 마지막 문서에서도 「다음」이 눌렸다 | 배선은 완전하다. 결함은 **두 렌더러의 실행 순서**라 DOM 을 되읽어야 보인다 |
| 실 창 프로브 | 닫힘 뒤 초점이 **비활성** 트리거로 가면 `focus()` 가 조용한 no-op 라 `<body>` 로 떨어진다 | 호출자 규율로는 못 막는다 → **기제 쪽**(modal.js)에서 세웠다: 되돌려 놓고 확인하고, 안 옮겨졌으면 현 화면 루트로. 포커스 가능 규칙을 **재현하지 않는** 것이 요점 — 그 목록이 곧 다음 결함이다 |
| 눈검증 | `.picker-sec>div` 로 넓게 건 CSS 가 구획 **캡션까지** 세로 flex·스크롤 상자로 만들어 가운데로 뭉갰다 | 스타일은 계약이 아니다 |
| 눈검증 | 파일 이름을 증거 행·footer 두 곳이 그려 같은 문자열이 한 면에 두 번 섰다 | 각 구획은 자기 계약을 지켰다. 겹침은 **면 전체**를 봐야 보인다 |
| 눈검증 | 첫 실행인데 증거가 「이름이 모두 서로 다릅니다」만 말해 **묻지 않은 질문에 답했다** | 드로어 안에서는 게이트 문안이 안 보인다 → 왜 묻는지를 면이 스스로 말하게 하고(`reason`), 문장은 게이트와 **공유**한다 |

**101 하니스 갱신·완주**(§10.9.5 후속 규칙 2 이행): 하니스가 모는 것은 **방금 만든 작업**
이라 F5 가 그 첫 실행을 막는다 — 갱신 없이는 그 자리에서 멈춘다. S5a(검토 요구 → 미리보기
→ 결과 확인 완료 → 게이트 열림)를 추가하고 14컷 재생성, README 그림 번호·본문 갱신.
**이 슬라이스는 표면을 죽이지 않지만 게이트를 하나 더 세웠고, 새 게이트도 「경로가
이어지는가」를 물어야 한다** — 하니스 완주가 그 답이다.

**남은 빚**: 증거의 before/after 는 F7 판본이 서면 채운다(판정 D 되깎기 조건). 행별
「수정」 deep-link·`runOverrides` 배지·「이번 생성에만」 범위는 F7 소관이고, 그때 이 면의
footer 와 행이 그 자리를 받는다. **(후일담: 배지·범위는 §10.14 에서 기각 — 말할 상태가
없어졌다. deep-link 만 살아 F6 에 동승한다.)**

#### 10.12.5 리뷰 1R — P1 2건·P2 1건 조치 (2026-07-27)

세 건 다 **같은 뿌리**: 판정을 *스냅샷을 만드는 자리*에만 두고, 그 자리를 거치지 않는
경로를 세지 않았다. F5 는 게이트를 하나 더 세운 슬라이스인데 게이트의 백스톱·기준선·
입력이 각각 한 칸씩 어긋나 있었다.

| # | 급 | 결함 | 조치·영구 가드 |
|---|---|---|---|
| 1 | P1 | **생성 백스톱에 검토가 없다** — `_generate_locked` 는 `validate_generate`·미입력을 방어적으로 재확인하면서 검토 요구는 묻지 않았다. 브리지 `generate` 직접 호출·stale 프론트가 승인 없이 생성한다 | 2-b) 백스톱 신설. 주체는 **이 런의 것**(`run_vm`·`indices`)이라 `_review(vm, indices)` 로 일반화 — 세션은 배치가 도는 사이에도 움직인다(`_stamp_last_run` 이 정체를 인자로 받는 것과 같은 근거). 회귀 2건(직접 호출 거절·승인 뒤 규칙 변경 재차단) |
| 2 | P1 | **기준선을 디스크에서 떴다** — 같은 프로세스의 에디터가 배치 중 저장하면, 완주가 **한 번도 실행·확인된 적 없는 규칙**을 검토받은 것으로 기록한다(조용한 승인) | `stamp_last_run(..., rules=...)` 로 **그 런이 쓴 규칙**을 넘긴다. `None` 은 "무엇을 실행했는지 모른다"이고 그때는 **기준선을 건드리지 않는다** — 디스크 폴백을 남기면 그 폴백이 곧 이 결함의 통로다. 회귀 3건(레이싱 저장 재현 포함) |
| 3 | P2 | **미리보기가 생성과 다른 이름을 승인시킨다** — 확인된 빈칸은 문서에 표식 문자열로 들어가는데, 감사·드로어는 표식 **없는** 값으로 이름·수렴·경로 길이를 계산했다 | 스냅샷이 생성과 **같은 술어**로 표식을 계산해 감사·드로어에 넘긴다(표 「문서」 열도 같이 고쳤다 — 판정 I·K 가 "표가 실이름을 이미 보여준다"에 기대고 있었다). 조건은 **생성이 실제로 붙이는 그것**이다(미입력 게이트 통과 뒤): 느슨히 잡으면 실행되지도 않을 상태의 이름을 말한다. 회귀 3건(미리보기 이름 == 생성물·표식 조건·거울은 여전히 빈 값을 센다) |

**내가 거꾸로 적었던 것**(2번): 착수 시 docstring 에 "호출측 사본으로 찍으면 실행 중 외부
변경을 검토받은 것으로 세운다"고 적었는데, **정확히 반대**였다. 런의 규칙을 찍으면 디스크의
새 규칙과 어긋나 요구가 그대로 서고(안전), 디스크 규칙을 찍으면 미검토 규칙이 통과한다
(불가역). 두 방향 중 어느 쪽이 **조용한 통과**인지를 먼저 묻지 않으면 안전 논증이 뒤집힌다.

**후속 규칙**: 게이트를 새로 세우면 그 게이트의 **백스톱·기준선·입력** 셋을 한 번에 적는다.
표면이 닫는 것은 표면의 사실이고, 계약은 실행 경로가 진다.

#### 10.12.6 리뷰 2R — P1 1건·P2 2건 조치 (2026-07-27)

1R 이 "판정을 스냅샷 자리에만 뒀다"였다면 2R 은 그 **판정이 무엇에 결속되는가**다 —
승인의 범위, 이름의 시각, 휴리스틱의 적용 범위가 각각 한 칸씩 넓거나 좁았다.

| # | 급 | 결함 | 조치·영구 가드 |
|---|---|---|---|
| 1 | P1 | **승인이 데이터 교체를 넘어 되살아난다** — 승인 키가 선택 index 만 담아, A 에서 승인 → B 마운트(선택 0건 리셋) → 같은 index 재선택 시 **같은 키가 재구성**돼 B 의 값·이름을 한 번도 보지 않고 게이트가 열렸다 | `_review_scope_key` 신설 = `snapshot_gen \| selection_key`. `selection_key`(F4 결과 강등)와 **따로 둔다**: 한 문자열이 "지금 실행 입력의 것인가"와 "무엇을 보고 난 승인인가" 두 질문을 겸하면 한쪽 요구가 다른 쪽 의미를 조용히 바꾼다(F3 3R `selected_count` 와 같은 결함류). 회귀 2건 |
| 2 | P2 | **감사와 표가 다른 시각을 찍는다** — `refresh` 의 감사가 자체 `now()`, `_record_rows` 가 별도 `_names_now`. `{{date:SS}}` 가 초 경계를 넘으면 드로어가 승인시킨 이름과 생성물이 갈리고 덮어쓰기 대상 집합까지 바뀐다 | 시각을 **스냅샷당 1회** 캡처해(`snapshot` 머리) 감사·표·드로어·생성이 전부 같은 값을 쓴다. "표시 = 확인 = 생성"(RC-02)의 시간 축. 회귀 2건 |
| 3 | P2 | **휴리스틱이 생성을 막았다** — `MAX_PATH_CHARS=260` 을 전 플랫폼에서 재고 `GateState(False,…)` 로 차단. 확장 경로·`longPathsEnabled`·POSIX 에서 **실제로 성공하는** 사용자가 UI 로는 아예 못 만든다 | 게이트에서 걷어 **사전검증 경고**로 내린다(차단 0). 한계는 `default_max_path()` 로 Windows 에서만 적용하고, 문안도 단정하지 않는다("실패한다" → "실패할 수 있다"). 회귀 4건 |

**내가 내 판정을 어긴 것**(3번): §10.12 판정 K 는 "**차단이 아니라 경고**"라고 적어 놓고
구현은 `enabled=False`(=차단)였다. 표에 옳게 적은 것이 코드에서 지켜졌는지는 **표가 아니라
테스트가** 답해야 한다 — 그래서 회귀가 `gate.enabled is True` 를 직접 센다. 이 슬라이스가
F3 에서 배운 "경계표를 구조 가드로 승격"의 같은 교훈이 문안·심각도 축에서 재발한 자리다.

**후속 규칙**: 세션에 남는 **허가**(승인·확인·무장 해제)는 그 허가가 **무엇을 보고 난
것인지**를 키에 담는다. 대상이 통째로 교체되는 축(데이터 스냅샷·작업 정체)이 키에 없으면,
같은 좌표가 다시 만들어지는 순간 허가가 조용히 부활한다.

#### 10.12.7 리뷰 3R — 근본원인 재분석과 구조 가드 (정지 규칙 §8.1 3항)

3라운드는 점별 픽스로 끝내지 않는다. 두 P2 를 나란히 놓으면 **한 뿌리**다:

> F5 는 상태를 둘 새로 만들었다 — durable 필드(`reviewed_rules`)와 파생값(`_names_now`).
> 둘 다 **누가 소유하고 누가 기대는지**를 적지 않은 채 배선했다. F4 후속 규칙(§10.10.9)이
> "어떤 상태를 살려 두면 그것을 소비하는 모든 행동에 대해 누가 답하는지 먼저 적는다"고
> 세운 그 규칙을, 이 슬라이스가 **두 번** 어겼다.

| # | 급 | 결함 | 조치 |
|---|---|---|---|
| 1 | P2 | **에디터 저장이 기준선을 지웠다** — durable 필드를 더하면서 `_preserved_meta`·저장 재구성에 넣지 않아, 규칙을 하나도 안 바꾸고 저장만 해도 기준선이 비고 다음 실행이 가장 무거운 검토를 다시 요구했다 | 비-편집 메타로 편입(에디터가 소유하는 건 규칙이고, 「마지막 완주가 무엇을 썼는가」는 이력의 일이다). 보존이 **무효화를 막지는 않는다** — 규칙을 바꾸면 기준선은 그대로 남고 요구가 선다 |
| 2 | P2 | **승인한 이름의 시각이 움직였다** — 2R 이 *한 스냅샷 안*의 소비처를 맞췄지만 **스냅샷 사이**는 안 맞췄다. 승인 왕복·면 닫기가 각각 push 를 부르므로 `{{date:SS}}` 가 그 사이 초 경계를 넘으면 생성이 **승인하지 않은 이름**을 쓴다(승인 키는 유효한 채로) | 시각을 **승인의 일부**로 다룬다: 누군가 기대는 동안(면이 열려 있거나 승인이 서 있는 동안) 얼리고, 아무도 안 기대면 새로 찍는다(오래 열어 둔 세션의 날짜가 늙지 않게) |

**근본 조치 = durable 필드 분류의 구조 가드.** 1번은 **두 번째** 재발이다 — 그룹이 조용히
초기화되던 자리(슬라이스 2)와 같은 결함이다. 두 번이면 목록이 아니라 **규율**이 문제이므로
목록을 늘리는 대신 완전성을 테스트가 소유하게 한다: `Job` 의 durable 필드는 에디터 저장이
**다시 짓거나**(`_EDITOR_REBUILDS`) **보존하거나**(`_EDITOR_PRESERVES`) 둘 중 하나로
**선언돼야** 하고, 미분류 필드가 있으면 실패한다(F3 가 초안 경계표를 구조 가드로 승격시킨
것과 같은 기제). 다음 durable 필드의 누락은 사람이 아니라 게이트가 잡는다.

**후속 규칙**: 새 상태를 만들 때 **소유자·수명·기대는 소비처** 셋을 적는다. durable 이면
"저장 경로들이 이 필드를 어떻게 다루는가"가 그 목록에 포함되고, 파생값이면 "이 값이 굳어
있어야 하는 구간이 있는가"가 포함된다. 둘 다 이번에 빠졌고 둘 다 같은 질문의 답이다.

#### 10.12.8 리뷰 4R — 승인 정체의 남은 두 축 (P2×2, 2026-07-27)

3R 근본 조치가 세운 질문("이 승인이 무엇을 보고 난 것인가")의 **답에서 빠져 있던 두 축**.
둘 다 신규·독립이고 이전 픽스의 회귀가 아니다.

| # | 급 | 결함 | 조치 |
|---|---|---|---|
| 1 | P2 | **파일명이 소비하는 필드의 변경이 파일명 위험이 아니었다** — 패턴 문자열이 그대로면 그 필드의 연결·표시형이 바뀌어도 `semantic_binding`·`presentation` 으로 분류돼 ⓐ드로어가 수렴·경로 증거를 건너뛰고 ⓑ표시형 승인은 선택 결속이 아니라 선택을 넓혀도 살아남아 **새로 고른 레코드의 이름 충돌이 검토를 통과**했다 | 위험을 "무엇을 편집했는가"가 아니라 **무엇이 달라지는가**로 정한다: 변경 필드가 `pattern_field_tokens` 에 들면 `filename_set` 으로 승격(선택 결속이 따라온다). 회귀 3건(승격·결속 승계·반대 방향 오승격 금지) |
| 2 | P2 | **표식 상태가 승인 정체 밖에 있었다** — 확인 안 된 빈 값이 있는 채로 승인하면 값은 비어 있고 이름은 표식 없이 계산된다. 면을 닫고 빈 값을 확인하면 실행 입력이 표식으로 바뀌는데 규칙도 선택도 안 바뀌어 **승인이 유효한 채** 남고, 생성이 한 번도 보여준 적 없는 값·이름을 쓴다 | 표식 상태를 `_review_scope_key` 에 넣는다. 되돌리면 되살아난다 — 정체의 일부이지 단조 무효화 신호가 아니다(같은 실행 입력으로 돌아왔으면 이미 확인한 것이 맞다). 표식 판정은 `_run_marker` **단일 술어**로 모아 생성·미리보기·승인이 갈리지 않게 했다. 회귀 2건 |

**승인 정체의 최종 형태** — "이 승인은 무엇을 보고 난 것인가"의 답:

```
rules_key            어느 규칙으로  (판정 C·I)
snapshot_gen         어느 데이터로  (2R P1)
marker               빈 값이 어떻게 채워진 상태로  (4R P2)
selection_key        어느 행을 어느 순서로  (판정 I — 선택 결속 위험만)
```

여기에 **얼린 시각**(3R P2)이 더해져 "승인한 이름 집합"이 생성까지 살아 있다. 넷 중
하나라도 빠지면 그 축으로 실행 입력이 바뀌는 순간 승인이 조용히 재사용된다 — 1R~4R 의
P1·P2 6건이 전부 이 목록의 빈칸이었다.

#### 10.12.9 리뷰 5R — 선택적 미리보기의 시각 (P2×1) · 정지 판정 (2026-07-27)

**결함(P2)**: 3R 이 세운 얼림 규칙("면이 열려 있거나 승인이 서 있는 동안")의 **경계 밖**.
검토 요구가 없는 반복 실행에서도 미리보기는 열린다(§13-2). 그런데 생성 버튼을 누르려면
면을 **닫아야** 하고, 닫는 순간 그 둘이 다 거짓이 되어 시각이 풀린다 — 1초만 들여다봐도
화면이 보여준 것과 다른 이름(그리고 다른 덮어쓰기 대상)이 만들어진다.

**조치**: 얼리는 근거를 셋으로 넓힌다 — ①보는 중 ②승인 서 있음 ③**한 번 본 뒤 아직 그
실행 입력 그대로**(핀). 핀 값은 4R 이 세운 **승인 정체 그대로**(규칙 지문 + 스냅샷 세대 +
표식 + 선택)라 새 축을 만들지 않았고, 생성이 그 시각을 소비하면 놓는다. 회귀 2건.

**내가 그은 경계가 틀렸던 자리**: 3R 에서 "아무도 안 기대면 새로 찍는다"고 적으며 **본
사람**을 기대는 자리에서 뺐다. 승인만 증거라고 본 것인데, §13-2 가 미리보기를 선택으로
만든 이상 **승인 없이 본 것도 본 것**이다. 선택적인 경로일수록 그 경로만의 계약을 따로
묻지 않으면 규칙의 경계가 거기서 새다.

#### 10.12.10 5라운드 결산 — 정지 규칙 §8.1 4항 판정

| 라운드 | 급 | 건수 | 성격 |
|---|---|---|---|
| 1R | P1×2 · P2×1 | 3 | 게이트의 백스톱·기준선·입력 |
| 2R | P1×1 · P2×2 | 3 | 승인의 결속 범위·이름의 시각·휴리스틱의 적용 범위 |
| 3R | P2×2 | 2 | 근본원인 재분석 + durable 필드 분류 **구조 가드** |
| 4R | P2×2 | 2 | 승인 정체의 남은 두 축(파일명 의존 필드·표식 상태) |
| 5R | P2×1 | 1 | 선택적 미리보기의 시각(얼림 근거의 경계) |

**심각도 궤적 P1 3 → P1 1 → 0 → 0 → 0**, 건수 3 → 3 → 2 → 2 → 1. **이전 픽스의 회귀는
0건**이다 — 매 라운드가 신규·독립이었고 전부 당일 조치·게이트 초록. 정지 규칙 4항의
머지 조건(5회차·무회귀)을 충족한다.

**11건의 공통 서사**: F5 는 「무엇을 승인했는가」를 값으로 남기는 슬라이스인데, 그 값이
가리켜야 할 축을 한 번에 다 적지 못했다. 라운드마다 빠진 축이 하나씩 드러났고 최종형은
§10.12.8 의 넷 + 얼린 시각이다. 교훈은 **승인·확인·무장 해제처럼 세션에 남는 허가는
그것이 근거한 입력 전체를 정체에 담아야 하며, 그 목록의 완전성은 산문이 아니라 테스트가
소유해야 한다**는 것 — 3R 근본 조치(durable 필드 분류 가드)가 그 원리를 durable 축에서
먼저 세웠고, 4R·5R 은 같은 원리를 세션 축에서 마저 채운 라운드였다.

### 10.13 F7 PR-A 계약·정산 — 편집기 몰입 표면·탭 + patch 거래 + 판본 (2026-07-27, **머지 `4004723`**)

대조표 20·21·22행을 진다. **23행(`runOverrides`)은 PR-B** — 사용자 확정. 계약 정본은 lab
`core-workflow.md` §3.1(HWPX 탭 구성)·§5(EditContext·patch 거래)·§6(적용 범위)·§8(deep-link
와 복귀)·§12(상태와 사건)·절대 불변식 §13-5·6·7·14·15·16, §19.10(상태 무효화 규칙)이다.

**사용자 확정 2건(2026-07-27)**:

| 사안 | 확정 | 근거 |
|---|---|---|
| 범위 분할 | **PR-A** = 탭 재편 + `EditContext`·patch 거래 + 판본 / **PR-B** = `runOverrides` + 「이번 생성에 적용」 분기 + F4 재시도 3종 + F5 드로어 per-field deep-link·배지 | 판본이 **먼저** 서야 override 저장 경계(§13-14·15)가 참이 된다: "기본 저장은 상속된 Run override 를 포함하지 않는다"는 기본 판본이 실재할 때만 검증 가능한 문장이다. F2 가 쓴 분할(표면 → 셸)과 같은 모양이고, F4·F5 가 미룬 빚은 PR-B 가 한 자리에서 갚는다 |
| 편집기의 거처 | **몰입 표면 승격** — `scr-editor` 부활(상단 2탭 은닉·back = ReturnContext 복귀). 「작업」 화면 안 편집 모드(`jobEditHost`·`MODE`)는 사망 | patch 거래의 이탈 가드(적용·버리기·머무르기)가 성립하려면 **나가는 경로가 셀 수 있어야** 한다. 편집기가 「문서 만들기」 안에 살면 상단 탭·화면 내 다른 컨트롤이 처분 미확정 이탈구가 되고, 그때마다 가드를 따로 걸어야 한다(가드의 완전성이 표면 수에 비례하는 구조 = 조용한 누락의 온상). 진입 사유 10종·복귀 6표면도 한 출구로 모인다 |

#### 10.13.1 §9.3 4계약면 사전 기입 (새 표면 = 몰입 편집기)

§10.5 「항목 착수 전 필수 절차」의 이행분. 호스트는 **화면**이다(오버레이·시트가 아니다) —
F1 다이얼로그·F5 드로어와 다른 부류라 잠금·정체의 값이 갈린다.

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 현재 section·진입 배너·patch dirty 는 **Python 소유**(`editor` 스냅샷) — DOM 클래스가 아니라 상태다(F3·F5 선례). 편집기가 열려 있다는 사실도 화면 키가 아니라 `EditContext` 존재 여부다: 라우팅만으로 열면 부팅·새로고침에 **문맥 없는 편집기**가 선다(진입 사유도 복귀처도 없는 표면 = 나갈 곳이 없다) | selftest: push 왕복 후 section·배너 유지 · 부팅 기본 착지가 편집기가 아님 |
| **전역 잠금의 범위** | 생성 중(`setBusy`)에는 **편집기 진입 자체를 막는다**. 편집기는 화면이라 오버레이 루트 훑기의 대상이 아니고, 실행 중에 규칙을 갈아 끼우면 RC-02 「확인 대상 = 생성 대상」이 깨진다. 역방향은 몰입 승격이 공짜로 준다 — 편집 중에는 생성 표면이 화면 뒤라 눌릴 DOM 이 없다(현행 편집 모드는 같은 화면이라 sticky 액션바를 따로 감췄다) | selftest: 생성 중 편집 진입 거절 · 편집 중 실행 컨트롤 부재 |
| **전이와 왕복의 순서** | 저장은 **Python 커밋이 성공한 뒤** 스냅샷이 새 판본·클린으로 갱신되고 **화면은 머문다**(§6.2 의 「ReturnContext 복원」은 활성 Run 문맥의 복귀 — PR-A 의 주 행동은 「변경 저장」이라 편집기에 머무는 것이 §6 표와 일치). section 전환은 patch 처분이 **성사된 뒤에만** 일어난다(중간 상태로 탭이 먼저 바뀌지 않는다). back 은 복귀처 복원 뒤 포커스를 진입 트리거로 되돌린다 | 실앱 게이트: 저장 뒤 같은 탭 생존·판본 증가 · back 포커스 착지 · 3택 취소 시 탭 불변 |
| **실패 경로의 문맥 보존** | 저장 게이트 차단(미확정 행·이름 없음·패턴 없음)·덮어쓰기 확인·자동등록 게이트·편집 중 외부 변경은 전부 **편집기 안에서 재진술**하고 화면을 닫지 않으며 **patch 를 버리지 않는다**. 실패한 저장이 사용자의 편집을 삼키는 것이 이 표면에서 가장 비싼 조용한 파괴다 | 회귀: 각 차단 뒤 patch·section 생존 |

#### 10.13.2 판정 16건 (이 슬라이스에서 확정)

**A. 탭은 셋이다 — 「시험」은 F8.** 대조표 20행이 「4탭」이라 부르는 넷째(현재 validation·
Template r·Binding r·미리보기 생성·승인)는 **25행이 F8 로 배정한 표면**이다. 빈 탭도
「준비 중」 표기도 두지 않는다(§8.2 ② 선례 — 없는 기능을 있는 척하지 않는다). 대신 탭
목록을 **매체 파생**으로 계산한다: §3.2 가 TXT 에 파일 이름 탭을 주지 않으므로, F6 이 TXT
를 합류시킬 때 목록이 저절로 갈리고 ~~F8 이 「시험」을 한 줄로 더한다~~ **[F8 정정]** 「시험」은
착수 실측에서 기각됐다(§10.17.1) — 탭 목록은 HWPX 3·TXT 2 가 최종형이다.

**B. 어휘는 `section` 하나 — `step` 정수는 사망.** 계약 §5.1 의 section 값
(`template`·`binding`·`filename`·`test`)을 스냅샷·액션·DOM·patch 가 **같은 문자열**로 쓴다.
정수 단계를 남기면 patch 의 section 키와 이중 어휘가 되고("1단계 조건을 채우지 못해"), 같은
상태를 두 표면이 다르게 부르는 순간 그게 결함이다(§10.5 판정 단일 출처).

**C. 「저장」 분류는 사망하고 그 의무를 나눠 상속한다.** 이행표 = §10.13.3. 표의 전 항목이
새 거처에서 도달 가능함을 확인한 뒤에야 분류를 지운다(§10.4 서문과 같은 규율).

**D. 한 진입은 한 section patch(§13-16) — 거래 모델은 링1 신설.**
`editSession = {base_snapshot, patch, dirty_section}` 을 `gui/edit_session.py` 가 소유한다
(`inherited_run_overrides` 자리는 PR-B). 화면이 그리는 유효 초안은 `base_snapshot + patch`
합성이고, **저장 단위는 합성물이 아니라 patch** 다(§5.2). 다른 section 으로 이동하려면
현재 patch 를 **저장·버리기·머무르기** 중 하나로 명시 처분한다.

**E. PR-A 의 주 행동은 「변경 저장」 하나.** §6 표에서 「이번 생성에 적용」은 **활성 Run
문맥**의 주 행동이고 그 저장처가 `runOverrides`(PR-B)다. 판본 없는 상태에서 임시 override
경계를 세우면 F5 가 같은 이유로 미룬 자리를 두 번 짓는다. 그래서 footer 는 「변경 저장」 +
「취소」이고 section 3택은 「저장하고 이동 / 버리고 이동 / 머무르기」다 — v6 의 라디오 3종을
모든 문맥에 나열하지 않는다는 §6 마지막 문장의 이행이기도 하다.

**F. 판본은 2축이고 파일 이름 규칙은 Binding 판본이 진다.** 계약이 고정한 축은 Template·
Binding 둘뿐이다(§13-6·7, v6 시험 탭 지표도 둘). 파일 이름은 문서 **구조**가 아니라 산출물
규칙이라 Binding 쪽이다. F5 의 위험 축이 3분류(`filename_set`·`semantic_binding`·
`presentation`)인 것과 어긋나지 않는다 — **위험 축은 증거 정책의 축, 판본 축은 세대의 축**
이다. 한 축을 다른 축의 이름으로 부르지 않는다(어휘 통일의 반대편 오류: 서로 다른 것을 같게
부르는 것도 드리프트다).

**G. 판본은 지문이 갈릴 때만 오른다 — 저장 횟수가 아니다.** 판정 주체는 F5 가 세운
`rules_fingerprints` 하나이고 새 비교기를 만들지 않는다. 판본이 "저장한 횟수"가 되면
§13-6(판본 변경 = 관련 validation·approval 폐기)이 **아무것도 안 바뀐 저장**에도 승인을
폐기시켜, F5 가 세운 「정상 반복 실행에서 조용함」(§13-2)이 저장 한 번에 깨진다.

**H. 직전 판본은 지문이 아니라 값으로, 1세대만 보관한다 — F5 판정 D 되깎기 조건의 회수.**
F5 는 증거의 before/after 를 "기준선이 지문만 저장하므로 이전 값을 복원할 원천이 없다"는
이유로 비웠고, **F7 판본이 서면 채운다**를 되깎기 조건으로 박제했다. 그 약속을 여기서 갚되
두 규율을 건다:
- **지문을 되파싱하지 않는다.** `rules_fingerprints` 의 source 축은 `\x1f` 로 이어 붙인
  비교용 문자열이다 — 거기서 값을 되뽑으면 「표시용·비교용 정규화 값에서 실체를 파생」하는
  F2 §10.8.6 규칙 ③ 위반이고, 지문 포맷이 바뀌는 날 증거가 조용히 거짓말한다. 직전 판본은
  **구조화 값**(`{template, filename, fields:{이름:{source,type,const,blank,fmt}}}`)으로
  따로 적는다.
- **1세대만.** 증거가 말하는 것은 「직전 판본에선 이랬다」 하나뿐이고, 이력 전체는 아무도
  요구하지 않았다(계약에 판본 이력 표면이 없다). 무한 누적은 durable 파일을 매 저장마다
  불리는 값이라 요구 없이 지불하지 않는다.

증거는 **이전 값을 저장해 되읽는 것이 아니라 이전 규칙으로 지금 레코드를 렌더**해서 짓는다
— 그래야 사용자가 보는 두 값이 **같은 레코드의 두 규칙**이 된다(다른 시점의 다른 데이터를
before 라고 부르면 그게 곧 지어낸 증거다).

**I. Run 은 사용한 판본을 고정한다(§13-7).** 실행 **시작 시점**의 판본 2개를 결과에 실어
완료·부분 실패·원인 미확정 증거가 말한다(§10.3 "사용한 Template·Binding 판본"). 배치가 도는
사이 편집 저장이 착지해도 결과가 말하는 판본은 **그 런이 쓴 것**이다 — `_stamp_last_run` 의
정체 고정(리뷰 P1)과 같은 뿌리이고, 같은 이유로 판본도 완주 시점에 디스크를 다시 읽어
말하지 않는다.

**J. 폐기 규칙에 새 코드를 더하지 않는다(§13-6).** 판본이 올랐다는 것은 지문이 갈렸다는
뜻이고, 갈린 지문은 F5 의 `rules_key` 를 통해 세션 승인을 **자동** 무효로 만든다. 판본 증가를
별도 사건으로 삼아 폐기 훅을 걸면 같은 불변식에 판정 주체가 둘이 된다(F5 판정 I 의 "별도
폐기 코드를 두지 않는다"가 여기서 회수된다).

**K. 진입 사유는 세우는 것만 세우고 나머지는 배제를 선언한다(F5 판정 O 선례).**

| 계약 §5.1 `entryReason` | PR-A 처분 |
|---|---|
| `voluntary` · `library` | **세운다** — 라이브러리 상세·후보 카드의 편집 진입 |
| `document_browser_repair` | **세운다** — 드리프트·파일명 미해소 토큰 수리(현행 `openEditForRepair`) |
| `preview_result` | **세운다** — F5 드로어 「수정」(복귀 시 드로어 재개방) |
| `run_failure` · `output_result` | **세운다** — F4 결과 3태의 수리 진입 |
| `workbench_result` | **배제 선언** — 작업대는 F6 |
| `schema_new_field` · `schema_missing_field` | **배제 선언** — 새 열·필수 누락 제안 표면은 §7 소관이고 아직 없다 |
| `document_browser_new_work` | **배제 선언** — 신규 작업 분기는 F8 `identityDecision` |

배제는 **선언**으로 남긴다: 열거값을 만들어 두고 아무도 쓰지 않으면, 나중에 그 자리에 배선을
빠뜨려도 아무 테스트도 울지 않는다(조용한 무시와 선언된 배제는 다르다).

**L. 데이터 선택은 patch 가 아니다.** Job 에 데이터는 없다(모델 불변식). 편집 세션의 데이터는
미리보기 값의 원천이자 자동등록의 재료일 뿐이라 patch 에 들지 않고 판본을 올리지 않는다.
`default_dataset_ref` 갱신은 저장에 딸려 가되 **조준 힌트**라 `rules_fingerprints` 에 없다 —
판본·검토 요구 어느 쪽도 건드리지 않는 것이 일관된다.

**M. 신규 초안의 전진 게이트는 산다 — F7 이 바꾸는 것은 탭 집합과 거래 모델이다.** v6
편집기는 **저장된 작업**을 여는 표면이라 초안을 모델하지 않는다(§9 는 최소 흐름만 말한다).
템플릿 없이 「필드 연결」 탭을 자유 이동으로 열면 빈 표가 서고 그건 「이행 불가능한 지시」의
표면판이다(F5 판정 F 가 선택 0건에서 검토를 요구하지 않은 것과 같은 계열). 결정 41 의
공개 방식(신규=전진 게이트 / 편집=자유 이동)은 그대로 둔다.

**N. 「편집 계속」·복귀 고지(T2)의 소임은 patch 처분이 승계한다.** 현행 편집 모드는 같은 화면
안이라 실행↔편집 왕복이 비파괴였고, 그래서 「저장하지 않은 편집이 있습니다」 고지와 재진입구
(`jobEditResume`)가 필요했다. 몰입 표면에서는 나가는 경로가 back 하나이고 그때 처분이
확정되므로 **처분 미확정으로 이탈하는 경로 자체가 없다**. 단 **신규 초안**은 patch 가 아니라
세션 전체가 미저장이라 폐기 확인(`EditorEntry.confirmDiscard`)은 그대로 산다. 삭제 조건 =
§10.13.4 점검표.

**O. 판본의 표시 자리는 셋 — 백엔드만 세우지 않는다.** 시험 탭이 F8 이라 v6 의 지표 자리는
아직 없다. 그래도 판본은 ①편집기 page-head 저장 상태(`저장됨 · 연결 r4`) ②실행 결과 증거
(판정 I) ③F5 드로어의 before/after 증거(판정 H) 셋에서 **실제로 읽힌다**. 아무도 안 읽는
durable 필드는 다음 슬라이스에서 조용히 틀려도 아무도 모른다(§10.3 신설 백엔드의 상습 함정).

**P. 신규 초안은 patch 거래 밖이다(구현 중 신설).** 아직 작업이 아니라 비교 대상(base)이
없으므로 「직전 판본과의 차이」가 성립하지 않고, 세션 전체가 하나의 초안이다. 초안에 patch 를
씌우면 첫 저장이 매번 "전 필드가 바뀝니다"를 재진술한다 — 정보가 0인 경보다. 초안의 폐기는
종전대로 **세션 폐기 확인**이 지키고(잃는 것이 이름·데이터·매핑 전부라 성격이 다르다), 탭
이동은 한 초안 안의 이동이라 가드가 없다. 전진 게이트는 그대로 산다(판정 M).

#### 10.13.3 「저장」 분류 사망 승계 정산 (판정 C 의 이행표)

| 현행 저장 단계(step 2) 항목 | 승계처 |
|---|---|
| 작업 이름 입력 | page-head 인라인 이름(v6 `editorTitle`) — 신규 초안의 미입력은 저장 게이트가 이미 시끄럽게 막는다 |
| 파일 이름 패턴 · 라이브 예시(`pattern_preview`) · 토큰 안내 | **「파일 이름」 탭**(승격의 본체, 대조표 20행) |
| 자동등록 데이터 이름 · 동명/충돌/손상 확인 왕복 | 저장 행동의 확인 다이얼로그(현행 `needs_dataset_confirm` 왕복 **그대로** — 판정 로직 불변) |
| 기본 데이터 참조 상태 재진술(#67 `default_dataset`) | 「필드 연결·표시」 탭의 데이터 관문(참조를 실제로 쓰는 자리) |
| 작성 출처 provenance 표시(#53-C) | 「템플릿」 탭(템플릿·필드 어휘의 지문이라 거처가 여기다) |
| 저장 버튼 · 차단 사유 · 덮어쓰기 확인 | footer 주 행동 + 편집기 안 재진술(§10.13.1 4행) |

**§10.4.1 F7 흡수분의 처분**: 템플릿 후보 목록·그룹 구획·`가져오기…` 는 현행 템플릿 분류가
이미 소비 중이라 탭으로 **그대로** 승계된다(추가 신설 0). 새 TXT 템플릿·편집과 누름틀 변환·
검토는 `tpl` 화면이 **아직 살아 있으므로**(사망은 F8) PR-A 가 흡수를 완결할 의무가 없다 —
흡수처가 서기 전에 지우지 않는다는 규율의 반대쪽 적용이다.

#### 10.13.4 편집 모드 사망 조건 점검표 (판정 N)

`jobEditHost`·`jobEditResume`·`jobEditExit`·`jobEditExitNote`·`MODE` 를 지우기 전에 전부 참:

1. back 가드가 dirty patch 에 **세 갈래**(저장하고 나가기·버리고 나가기·머무르기)를 준다.
2. 신규 초안의 세션 폐기 확인이 남아 있다(`EditorEntry.confirmDiscard` 소비처 전부).
3. 편집 진입의 전 소비처(라이브러리 상세·후보 수리·F4 결과·F5 드로어)가 `EditorEntry.land`
   단일 정의를 지나 `scr-editor` 로 착지한다.
4. 저장 직후 「문서 만들기」의 후보·문서 탐색이 갱신된다(현행 `refreshList` 소임의 승계).
5. 생성 중 편집 진입이 거절된다(§10.13.1 2행).

#### 10.13.5 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(§9.3 4계약면 · 판정 15건 · 승계 정산표 · 사망 점검표) |
| 2 | **판본** — 링0 `Job.template_revision`·`binding_revision`·`previous_rules`(가산·하위호환·복제 미계승·`content_fingerprint` 제외) · 증가 술어(판정 G) · Run 고정(판정 I) · 회귀 |
| 3 | **patch 거래** — 링1 `gui/edit_session.py`(`EditContext`·`editSession`·합성·section 처분 판정) · `EditorController` 를 patch 모델로 전환 · 회귀 |
| 4 | **몰입 표면 + 탭 재편** — `scr-editor` 부활·상단 2탭 은닉·back·진입 배너 · 파일 이름 탭 승격 · 저장 분류 사망(§10.13.3) · 편집 모드 사망(§10.13.4) · DOM 계약 · action registry · UI_CONTRACT · selftest 프로브 |
| 5 | **before/after 증거 회수** — F5 판정 D 되깎기 조건 이행(직전 판본으로 같은 레코드 재렌더) · 회귀 |
| 6 | **101 하니스 갱신·실행 + 실앱 한 바퀴**(§10.9.5 후속 규칙 2) · 착지 정산 |

#### 10.13.6 착지 정산 (2026-07-28)

**구현 중 발견 3건**(전부 §10.13.2 본문에 박제):
- **판정 P 신설** — 신규 초안은 patch 거래 **밖**이다. base 가 없으므로 「직전 판본과의
  차이」가 성립하지 않고, 세션 전체가 하나의 초안이다. 초안에 patch 를 씌우면 첫 저장이
  매번 "전 필드가 바뀝니다"를 재진술한다(정보가 0인 경보).
- **잇는 기준은 이름이 아니라 파일 슬롯**(판정 G 본문) — 이름 기준으로 판본을 이으면
  slug 이 같은 이름 변경(`a/b` → `a_b`)이 세대를 1 로 되돌려 열 세대 실행한 작업이
  신참으로 표시된다. `_preserved_for_target`(태그·이력·즐겨찾기가 **대상 파일**의 것으로
  남는다)과 같은 규율로 맞췄다.
- **`blank` 축은 다시 세우지 않는다**(판정 H 이행 중) — `FieldMapping.is_blank` 는
  `type == "blank"` 의 파생이라 이전 판본을 되세울 때 따로 넘기면 두 자리가 어긋날 수 있다.
  지문이 두 축을 다 적는 것은 **비교용**이지 재구성용이 아니다.

**계약이 이긴 자리 1건**: 결정 41 의 「편집 탭은 자유 이동」과 §13-16(한 진입은 한 section
patch)이 부딪혔다 — §10.0 대로 **계약이 이긴다**. 자유 이동은 「깨끗한 세션에서」로
좁혀지고 손댄 patch 가 있으면 처분이 먼저다. 그 회귀를 옛 테스트가 잡았고(자유 이동
단언), 테스트를 새 계약으로 뒤집는 것이 이 라운드의 정직한 처분이었다.

**승계 이행 확인**(§10.13.4 점검표 5항 전부 참):

| 점검 | 이행 |
|---|---|
| back 가드 3택 | `EditorScreen.leaveTo` + `Modal.choose`(신설 골격) — 머무르기가 기본값 |
| 초안 세션 폐기 확인 | `EditorEntry.confirmDiscard` 유지(초안은 patch 가 아니다) |
| 진입 소비처 단일 정의 | 라이브러리·템플릿 관리·수리·드로어·결과 전부 `EditorEntry` 경유, 착지는 `Nav.go("editor")` |
| 저장 뒤 후보·탐색 갱신 | `refreshList` 유지(실패는 이제 **늘 loud** — 화면이 갈려 완료 존 log 가 안 보인다) |
| 생성 중 편집 진입 거절 | 편집기가 화면이라 생성 중에는 「문서 만들기」를 떠나지 않는다 + 진입 버튼이 `data-busy-lock` |

**게이트**: 전체 2102 passed(신규 20 — 판본 8·거래 13·증거 4·3택 1, 갱신분 상쇄) ·
ruff 초록 · 실 WebView2 selftest 71 · **101 하니스 14컷 완주**(실 버튼·실 dispatch·실
생성 3건까지 그대로 — 이것이 §10.9.5 가 요구한 실앱 한 바퀴다).

**PR-B 로 남는 것**: `runOverrides`(대조표 23행) · 「이번 생성에 적용」 분기 · F4 재시도
3종(건별 재시도·레코드 filename override·다른 폴더) · F5 드로어의 per-field deep-link 와
「이번 생성에 적용」 배지. 판본이 섰으므로 §13-14·15(Run-only patch 는 기본 판본을 바꾸지
않는다 / 기본 저장은 상속 override 를 포함하지 않는다)가 이제 **검증 가능한 문장**이다.
**(그 PR-B 는 착수 계약을 쓰던 중 기각됐다 — 근거는 §10.14. 이 문단은 그 시점의 기록이고,
남은 것은 deep-link 하나뿐이다.)**

#### 10.13.7 리뷰 1R — P1 2건·P2 1건 조치 (2026-07-28)

세 건이 **한 뿌리**다: 이 슬라이스가 세운 것은 「단일 정의 seam 을 지나는 흐름」인데,
그 흐름의 **인자와 반환과 약속**을 계약이 세 자리에서 놓쳤다.

| 급 | 증상 | 뿌리 | 영구 가드 |
|---|---|---|---|
| P1 | 「저장하고 이동」·「저장하고 나가기」가 **저장까지만** 하고 멈춘다 | `doSave` 가 성공에 `undefined` 를 돌려줘 가드가 조기 반환 — 배선·문안·판정은 전부 제자리고 **성사 뒤 이어짐**만 끊겼다 | 실 클릭 → 실 3택 모달 → 실 재발신 순서를 밟아 발신 기록을 세는 selftest 프로브(`editor_guard`) + **양성대조**로 검출력 증명 |
| P1 | 진입 문맥이 **전부** 버려진다(배너·복귀처 소실, 결과의 파일 이름 착지 실패) | 공용 seam `EditorEntry.openGuarded` 가 인자를 안 받는데 호출자 넷은 싣고 있었다. 계약은 "호출자가 무엇을 싣는가"만 보고 **"seam 이 흘려보내는가"** 를 안 봤다 | seam 서명·전달 두 줄을 DOM 계약에 명시(`openGuarded(name, context)` · `Bridge.openJobInEditor(name, context`) |
| P2 | 「미리보기로 돌아가기」가 보통의 「문서 만들기」로 데려다 놓는다 | 보낸 표면이 `reopen_drawer` 를 세웠는데 복귀가 **소비하지 않았다** — 라벨이 약속한 자리와 실제 착지가 다르면 그것도 문안 부정직이다 | 복귀가 상태까지 되돌리고(`restoreReturnState`) 여는 절차는 그 화면의 seam 하나가 소유(`JobScreen.openPreview`) + 계약 2줄 |

**교훈**: **단일 정의 seam 은 인자·반환·약속까지 단일이어야 한다.** 「한 곳에서만 정의한다」는
규율은 그 한 곳이 **무엇을 받아 무엇을 돌려주는지**까지 계약에 적어야 완성된다 — 셋 다
"연결은 했는데 흐르지 않는다" 였고, 셋 다 정적 계약이 통과시켰다.

**부수 교훈(프로브)**: 새 프로브가 편집기 화면을 열어 둔 채 끝나 뒤따르는 프로브 6건이
「상단 탭이 사라졌다」로 무너졌다 — 몰입 표면은 셸을 덮으므로 프로브도 **자기 판을 자기가
걷어야** 한다([[gate-env-gotchas]] 교차 오염의 새 표본, 이번엔 화면 축).

#### 10.13.8 리뷰 2R — P1 1건·P2 1건 조치 (2026-07-28)

두 건 다 **판정 L 의 그늘**이다: "이름은 정체이지 규칙이 아니라 어느 section 에도 속하지
않는다"고 옳게 정해 놓고, 그 사실이 **가드와 되돌리기 두 곳에서 각각 반대 방향으로** 샜다.

| 급 | 증상 | 뿌리 | 조치 |
|---|---|---|---|
| P1 | 머리에서 이름만 고치고 나가면 **아무것도 묻지 않고** 그 편집이 사라진다 | 이탈 가드가 `dirty_sections` 만 봤다 — 이름은 section 밖이라 늘 비어 있다. 몰입 표면엔 그 세션으로 되돌아올 길이 없어(구 「편집 계속」 사망) 조용한 파기가 된다 | 가드가 `has_unsaved_work`(세션 손댐 여부, 이미 Python 이 내는 판정)를 함께 본다 — 판정을 다시 만들지 않는다 |
| P2 | 「버리고 이동」이 **세션 전체**를 되돌려 이름까지 원복 | `discard_patch` 가 언제나 `base` 로 전체 복원 — 모달은 「그 탭에서 바꾼 것」을 말하는데 파기 범위가 더 넓었다 | 인자 `section` 을 받아 **그 자리만** 되돌린다(파일 이름=패턴 / 연결=저장 프로파일 재적용 / 템플릿=스키마 동반 재구성하되 이름·데이터 유지). 인자 없는 호출(footer·「버리고 나가기」)은 종전대로 세션 전체 |

**교훈**: **범위를 정한 판정은 그 범위를 소비하는 자리마다 다시 확인해야 한다.** 판정 L 은
"이름은 patch 밖"이라고 한 줄로 옳았지만, 그 한 줄이 **가드에서는 "그러니 안 봐도 된다"로,
되돌리기에서는 "그러니 같이 지워도 된다"로** 읽혔다 — 정확히 반대 방향의 두 오독이다.
경계를 정하면 그 경계의 **양쪽 소비자**를 세는 것이 판정의 완결이다.

**부수 조치**: 부분 되돌리기 뒤 남은 것이 없으면 클린 표지를 되세운다 — 안 그러면 되돌린
직후의 이탈이 잃을 것 없는 확인을 묻는다(과경고).

#### 10.13.9 리뷰 3R — 근본원인 재분석과 구조 가드 (정지 규칙 §8.1 3항, 2026-07-28)

**P2 3건**(회귀 0 — 셋 다 신규·독립):

| 급 | 증상 | 조치 |
|---|---|---|
| P2 | 이름만 고친 세션의 머리가 「저장됨」이라 말하고 footer 에 「변경 버리기」도 없다 | 세션 dirty 를 **Python 스냅샷 `dirty` 하나**로 내고 머리·footer·이탈이 그 값만 읽는다 |
| P2 | 이전 판본이 읽던 열이 지금 데이터에 없으면 `before: ""` 로 실려 **"이전엔 비어 있었다"고 단정** | 소스를 읽는 유형(text·date·amount)에서 그 열이 레코드에 없으면 **뺀다**. 소스가 애초에 없던 필드(미연결)는 그때도 빈 값이 참이라 남긴다 |
| P2 | `previous_rules: null·[]·""·0` 이 「직전 판본 없음」이라는 **정상 상태로 위장**해 로드 통과 | 형상 검사를 falsy 검사 **앞**으로 — 빈 사전만이 「없음」이다 |

**세 라운드를 관통하는 하나**: 이 슬라이스는 **구분을 세우는 슬라이스**였다(section 안과 밖 /
있음과 없음 / 저장될 것과 잃을 것). 그런데 구분은 한 줄로 적히고 **소비자는 여럿**이라,
각 소비자가 그 구분을 자기 방식으로 재조립하는 순간 원래 구분이 사라졌다:

| 라운드 | 재조립한 자리 | 사라진 구분 |
|---|---|---|
| 1R | seam 이 인자·반환을 흘림 | 「문맥을 들고 들어간다」·「성사 뒤 이어진다」 |
| 2R | 가드가 `dirty_sections` 로 세션 dirty 를 유도 / 되돌리기가 base 전체 복원 | 「이름은 section 밖」(양쪽 소비자가 **반대 방향**으로 오독) |
| 3R | 머리·footer 가 같은 유도를 반복 / `value_for` 의 `.get(…, "")` / `not raw` | 같은 구분의 **세 번째 소비자** · 「없음 ≠ 빈 값」 두 자리 |

**근본 조치 = 파생 판정을 표면이 유도하지 못하게 한다.** 값이 아니라 **유도 자체**가 결함의
원천이었다(`length > 0`, `record.get(k, "")`, `not raw` — 셋 다 "없음"을 그럴듯한 값으로
바꾸는 관용구다). 조치 셋:

1. `dirty` 를 스냅샷 필드로 신설하고 **`dirty_sections` 는 탭 표지 전용**으로 못 박았다 —
   구조 가드가 `editor.js` 안의 `dirty_sections` 등장 횟수를 **1** 로 고정하고, 세 소비자
   (머리·footer·이탈)가 `s.dirty` 를 읽는지 각각 센다. 다음 소비자가 늘어도 유도로 돌아갈
   수 없다.
2. 부재를 값으로 바꾸는 두 관용구를 각각 명시 검사로 대체(소스 열 존재 확인 / 형상 우선
   검사)하고 회귀로 고정했다.
3. 실 렌더 프로브가 **손댄 세션의 머리 문안과 되돌리기 버튼**을 함께 읽는다 — 정적 계약은
   "값을 읽는가"까지만 보고 "그래서 화면이 뭐라 말하는가"는 못 본다.

**교훈**: 구분을 세우면 **그 구분을 유도할 수 있는 모든 관용구를 봉쇄**해야 완결된다.
「단일 출처」는 값의 규율이 아니라 **유도 금지**의 규율이다 — 소비자가 재조립할 수 있는
재료(부분 목록·기본값 있는 조회·falsy)를 남겨 두면 언젠가 누군가 그것으로 답을 만든다.

#### 10.13.10 리뷰 4R — 화면이 갈린 뒤의 두 경합 (P1 1건·P2 1건, 2026-07-28)

**둘 다 F7 이 만든 새 왕복에서만 도달 가능한 자리**다 — 편집이 자기 화면으로 나가면서
「저장하고 미리보기로 돌아가기」라는 왕복이 처음 생겼고, 그 왕복이 두 경합을 드러냈다.

| 급 | 증상 | 뿌리 | 조치 |
|---|---|---|---|
| P1 | 편집기에서 저장하고 돌아오면 **옛 규칙으로 미리보고 옛 규칙으로 생성**한다 | `JobController.vm` 은 작업 선택 시점의 인메모리 사본이고 `refresh` 는 **삭제된 작업만** 처리했다. 편집기가 같은 화면 안에 있던 시절엔 저장이 곧 그 화면의 사건이라 드러나지 않던 자리 | `_reload_active_job()` — **지문이 갈릴 때만** VM 을 다시 세우고 세션(데이터·선택·필터·폴더)은 보존. 버리는 것은 계약이 버리라는 것뿐(§19.10 완주 담보·열린 미리보기), 승인은 지문 결속으로 자동 무효 |
| P2 | 이름·패턴을 고치고 **곧바로** back 을 누르면 가드가 안 뜬다 | blur 로 발화하는 `change` 는 아무도 기다리지 않는 발신 — 그 창에서 판정하면 잃을 것이 없다고 읽힌다(F3 이 존 축에서 겪은 「예약 편집이 늦게 착지」의 편집기 판) | 입력 변이를 공용 체인(`intent.js`)에 세우고 이탈·탭 이동이 **정산 뒤** 판정. 정산 뒤에도 스냅샷이 아니라 **컨트롤러에게 묻는다**(push 도착 순서에 기대지 않는다), 질의 실패는 「묻는다」로 fail-safe |

**궤적 정정**: 3R 을 P1 0 으로 읽었지만 4R 이 P1 을 냈다 — [[review-round-stopping-rule]]
의 「싼 리뷰어가 P1 을 잡으면 diff 가 덜 읽혔다는 증거」에 해당한다. 다만 두 건 다
**F7 이 새로 연 왕복**의 것이고 이전 픽스의 회귀는 아니다(신규·독립).

**패턴**: 1R~3R 은 「구분을 소비자가 재조립」이었고, 4R 은 「**화면이 갈리면서 생긴 새 왕복**의
경합」이다. 표면을 나누면 **상태의 주인도 나뉜다** — 규칙의 주인(편집기)과 실행의 주인(문서
만들기)이 갈린 순간, 둘을 잇는 왕복마다 ①누가 최신인가 ②누가 먼저 도착하는가를 다시 묻게
된다. F7 처럼 표면을 분리하는 슬라이스는 그 두 질문을 왕복 목록별로 세는 것이 완결 조건이다.

#### 10.13.11 리뷰 5R — 앞 라운드 조치가 남긴 세 틈 (P1 1건·P2 2건, 2026-07-28)

| 급 | 증상 | 뿌리 | 조치 |
|---|---|---|---|
| P1 | 저장 뒤 복귀에서 드로어가 **옛 규칙을 그리거나 열리자마자 닫힌다** | 4R 이 재적재를 세웠지만 **순서를 세우지 않았다** — `Nav.go` 의 자동 refresh 는 기다려지지 않는 발신이라 재적재와 재개방이 경합한다(규칙이 갈렸으면 재적재가 면을 닫는 것이 옳고, 그 옳은 동작이 순서 때문에 「열리자마자 사라짐」이 된다) | 복귀가 **재적재를 기다린 뒤** 연다. 실패하면 열지 않고 loud — 옛 규칙의 상을 「돌아왔다」며 보여 주는 것이 조용한 거짓이다 |
| P2 | 헤더 토글·확정·되돌리기를 누르고 곧바로 back → 가드가 그 발신보다 먼저 판정 | 4R 이 `change` 만 체인에 세웠다. 클릭 변이는 **자기 핸들러 안에서만** 기다린다 — 정산은 그것을 기다리지 못한다 | 편집기의 브리지 왕복을 **전부** 체인으로(질의 포함 — 대기 중 변이 뒤의 답이라야 참이다). 체인 밖 예외 둘만 선언: 첫 스냅샷 당김·정산 뒤 컨트롤러 직접 질의. 정적 계약이 `Bridge.call(SCREEN` 등장 횟수를 **1** 로 고정 |
| P2 | 데이터를 고른 뒤 부분 되돌리기를 하면 머리가 「저장됨」이라 말하고 이탈이 안 묻는다 | **2R 이 이 줄을 세울 때 이름만 봤다** — 데이터 선택은 저장 시 등록·기본 데이터 연결로 이어지는 미저장 세션 상태라 같은 자리에 든다 | 클린 복원 조건에 세션 데이터 선택을 더한다(section 밖에 사는 것을 빠짐없이 센다) |

**정지 규칙 §8.1 4항 판정**: 5회차 종료. **이전 픽스의 회귀는 0**이다 — 고친 결함이
되살아난 적은 없다. 다만 **직전 조치가 연 창이 2건**(4R 의 재적재가 순서를 안 세움 / 2R 의
클린 복원이 항목을 덜 셈)이라 F3 5R 과 같은 성격이고, 그때와 같이 신규·독립으로 센다.

**5라운드 결산 — 심각도 궤적 P1 2 → P1 1 → 0 → P1 1 → P1 1**, 건수 3 → 2 → 3 → 2 → 3.
P1 이 마지막까지 나온 것은 [[review-round-stopping-rule]] 의 「싼 리뷰어의 P1 = diff 가 덜
읽혔다」 신호에 해당한다. 다만 **다섯 라운드의 P1 4건이 전부 같은 자리**를 가리킨다:
**표면을 나눈 뒤 둘을 잇는 왕복**(문맥 전달 → 성사 뒤 이어짐 → 최신성 → 순서). 이 슬라이스가
한 일이 「편집을 자기 화면으로 내보내기」였으니, 리뷰가 계속 그 이음매를 짚은 것은 diff 를
덜 읽었다기보다 **그 이음매가 이 diff 의 본체**였다는 뜻으로 읽는다.

**남은 판단은 사람 몫**(§8.1 4항 상한 도달): 게이트는 전부 초록이고 회귀는 0이지만, 라운드
상한에서 P1 이 나온 diff 다 — 머지할지, 이음매(왕복 4종)를 한 번 더 훑을지는 사용자가 정한다.

#### 10.13.12 리뷰 6R — 규칙도 실행 입력의 정체다 (P2 1건, 2026-07-28)

**P2 1건**(P1 0 — 상한 뒤 첫 라운드): 편집기에서 규칙을 고치고 결과 화면으로 돌아오면
**다른 규칙으로 만든 결과가 「지금 결과」로 남고** 후속 행동(실패분 선택·파일 이름 수리)까지
열려 있었다. 4R 이 세운 재적재는 Python 쪽 완주 담보만 걷고, 결과 자체는 웹이 든
세션 상태라 지문(`sessionKey`)이 갈리지 않으면 강등되지 않는다(F4 판정 G).

**조치**: 세션 지문에 **규칙 지문**을 더한다(`rules_key` — 검토 요구가 이미 계산한 값을
재사용, 같은 상태를 두 번 세지 않는다). 데이터·선택·폴더만 같으면 결과는 그대로 살고
(과잉 강등 금지), 규칙이 갈리면 강등된다.

**같은 계열의 네 번째**: 「무엇이 이 실행의 정체인가」가 라운드마다 하나씩 늘었다 —
선택(F3) → 순서(F3) → 승인 결속(F5) → **규칙**(6R). 표면을 나누면 정체의 성분도 늘어난다:
규칙의 주인이 다른 화면으로 나간 순간, 규칙은 「저 화면의 값」이 아니라 **이 실행의 정체**가
된다. 다음에 어떤 상태의 주인이 화면 밖으로 나가면 그 값이 지문에 들어야 하는지를 먼저 묻는다.

#### 10.13.13 리뷰 7R + CI 커버리지 플로어 (P2 2건, 2026-07-28)

**CI 적색 1건(사용자 지적)**: `hwpxfiller.webapp` 라인 커버리지 85.98% < 86% — **한 줄**
모자랐다. 4R~6R 이 더한 가드 분기(부분 되돌리기 3갈래·재적재 조기 반환 2갈래)가 테스트 없이
늘어난 탓이다. 플로어를 내리지 않고 **그 분기들에 회귀를 붙여** 메꿨다(86.49%) — 커버리지
플로어는 신규 분기 테스트를 동반한다는 규율([[post-merge-review-sweep-280]])의 이행이다.

**P2 2건 — 둘 다 판본 축**:

| 급 | 증상 | 뿌리 | 조치 |
|---|---|---|---|
| P2 | 연결을 A→B 로 바꿔 두고 **템플릿만** 저장하면, 아직 검토받지 않은 연결 변경의 증거가 「B → B」가 된다 | 직전 판본 스냅샷을 **통째로** 밀었다 — 두 축이 한 스냅샷에 살지만 **각자의 세대**를 가진다 | 직전 판본을 **축별로** 민다(바뀐 축만 갱신) |
| P2 | 규칙이 A→B→A 로 돌아온 저장 뒤 실행하면 결과가 **디스크에 없는 세대**를 자기 근거로 댄다(§13-7) | 재적재 판정이 `content_fingerprint` 만 봤는데, 그 지문은 판본 3필드를 **일부러 뺀다**(거짓 파괴 확인 방지) — 그것만으로는 "지금 것인가"를 답할 수 없다 | 판본 메타·직전 판본까지 대조. 단 규칙이 실제로 갈렸을 때만 증거를 걷는다(과잉 리셋 금지) |

**같은 자리의 다섯 번째**: 「무엇이 이 실행의 정체인가」에 **세대**가 더해졌다(선택 → 순서 →
승인 결속 → 규칙 → 세대). 그리고 이 라운드가 드러낸 것은 그 정체의 **비대칭**이다 —
`content_fingerprint` 는 "편집 세션이 덮어쓸 내용"을 뜻하고 세대는 "실행이 댈 근거"를 뜻하는데,
하나가 다른 하나의 부분집합이 아니다. 지문 하나로 두 질문에 답하려 한 것이 이 결함의 형태다.

#### 10.13.14 리뷰 8R — 라운드가 반복된 원인 진단과 근본 조치 (P1 1 · P2 1, 2026-07-28)

8R 은 **예측된 라운드**다. 7R 직후 여덟 라운드(16건)를 한 화면에 놓고 본 진단이 「다음 라운드가
나올 것」이라 말했고, 그 두 자리가 그대로 나왔다:

| 급 | 증상 | 가족 | 몇 번째 |
|---|---|---|---|
| P1 | 규칙을 고치고 **데이터·결과** 표면으로 돌아오면 화면이 먼저 열리고 재적재는 뒤에 도착한다 — 그 창에서 「만들기」를 누르면 **편집 전 규칙**으로 문서가 나온다 | B(복귀 착지) | 5 |
| P2 | footer 「변경 버리기」·「버리고 나가기」가 「저장된 상태로 되돌린다」고 말하고 **데이터 선택은 남긴다** — 버린 뒤에도 세션이 미저장이라 같은 파기를 다시 묻는다 | A(미저장 열거) | 8 |

**진단 — 왜 여덟 라운드가 반복됐는가**. 16건은 세 가족이고, 각 가족은 이 PR 이 새로 세운
상태 모델 하나에 대응한다: A=patch 거래(section 밖 상태 미열거) · B=몰입 편집기(같은 durable 을
두 화면이 각자 캐시) · C=판본(2축 revision 대 1평면 스냅샷). 라운드가 닫히지 않은 기제는 넷이다.

1. **세 모델을 한 PR에 동시 도입** — 교차면이 3이 아니라 6방향이다. 한 가족을 고치면 교차면이
   다음 라운드의 재료가 된다.
2. **정의 자리가 아니라 리뷰어가 가리킨 호출 자리에서 고침** — 3R 이 출구를 `dirty` 하나로
   모았으나 그 값의 **입구**(무엇이 세션 상태인가)는 판정마다 손으로 다시 쓰여 있었다.
3. **기존 술어를 다른 질문에 재사용** — 7R 의 `content_fingerprint` 가 표본이다(§10.13.13 의
   「비대칭」). 두 질문이 파생 메타에 정반대를 요구하는데 술어는 하나였다.
4. **비동기 경합을 채널 하나씩 봉합** — 4R 이 `change` 만 체인에 태우자 5R 이 click 으로 재현했다.

**근본 조치 — 열거와 착지를 각각 한 자리로**:

- **A**: `EditorController.SESSION_EXTRAS` 가 section 밖 세션 상태의 **전체 목록**이 되고, 저장된
  작업의 미저장 판정은 `dirty_sections() ∪ dirty_extras()` **파생**이 된다. 손으로 켜고 끄던
  클린 표지(`_session_clean`)는 초안에만 남는다 — 파생은 빠질 자리가 없어, 되돌리면 저절로
  깨끗해지고 손대면 저절로 더러워진다. 버리기 두 갈래는 문안과 대칭을 이룬다(탭=extras 보존,
  전체=extras 도 함께). 열거를 세우자 **다섯 번째 값이 즉시 드러났다**: 같은 엑셀의 다른
  시트로 갈아타면 경로도 이름도 그대로인데 시트는 durable 이다(#33) — 리뷰가 아니라 열거가
  잡은 첫 건이고, 이 조치가 작동한다는 증거다.
- **B**: 재당김이 `Nav.refresh` **단일 정의**가 되고, 편집기를 나가는 모든 길이 `landOn` 한
  자리를 지난다 — 목적 화면을 **노출하기 전에** 재적재를 기다리고, 실패하면 나가지 않는다.
  5R 이 미리보기 복귀에만 세운 순서 규율이 그 자리에서 사라진다(두 벌 금지).
- **C**: 7R 이 축별로 분리해 이미 형상이 맞았다 — 추가 조치 없음.

**교훈**: 「같은 결함의 N번째 인스턴스」가 세 라운드 이상 이어지면 그것은 리뷰어의 집요함이
아니라 **정의가 열려 있다는 신호**다. 그때 고칠 것은 리뷰어가 가리킨 줄이 아니라 그 줄이 읽는
열거·술어·착지점이고, 조치가 옳았는지는 **다음 라운드가 아니라 그 조치 자신이 새 인스턴스를
잡는가**로 확인한다(여기선 `data_sheet`).

#### 10.13.15 리뷰 9R — 근본 조치가 닫혔는지의 시험 (P1 1 · P2 1, 2026-07-28)

**8R 근본 조치의 판정 결과: A·B 가족 신규 인스턴스 0건.** §10.13.14 가 "조치가 옳았는지는
다음 라운드가 아니라 그 조치 자신이 새 인스턴스를 잡는가로 확인한다"고 썼고, 이 라운드가
그 시험이었다 — 여덟 라운드 내내 매번 하나씩 나오던 두 가족이 처음으로 침묵했다.

나온 2건은 **새 가족 둘**이다(회귀 아님 — 정지 규칙 4항의 「신규·독립」).

| 급 | 증상 | 가족 | 조치 |
|---|---|---|---|
| P1 | 생성 진행 중에도 상단 탭·라이브러리 컨트롤은 눌린다(`setBusy()` 는 「문서 만들기」 루트 아래만 비활성화) → 편집기를 열어 durable 규칙을 저장하면 진행 중 배치의 결과가 **디스크에 없는 세대**를 근거로 댄다(§13-7) | 실행 경합 | 거절의 **단일 술어**(`raise_if_generating`) + 자물쇠를 **앱이 공유 주입** |
| P2 | 이탈이 화면만 바꿔 초점이 방금 숨겨진 편집기 back 버튼에 남는다 — 키보드 사용자는 보이는 초점 없이 착지 | 초점 복귀 | 진입 seam 이 띄운 자리를 1슬롯 기억, `landOn` 이 `Modal.restoreFocus` 규칙으로 되돌림 |

**P1 은 열거가 스스로 잡은 두 번째 표본**이다. 리뷰는 편집기 진입 하나를 지적했는데, 그
판정을 단일 술어로 세우자 **형제 둘이 함께 드러났다** — 「문서 만들기」 재연결과 라이브러리
재연결도 durable 규칙을 쓰는데 거절이 없었다. 라이브러리 쪽이 특히 구조적이다: 자물쇠가
`JobController` **화면 소유**였으므로, 런을 돌리지 않는 라이브러리는 무엇을 보든 늘 열려
있었다. 그래서 자물쇠를 「진행 중인 런」이라는 **앱 수준의 한 사실**로 올렸다.

**매트릭스 열거의 한계(사용자 질문에 대한 답)**: 행렬화는 **가족 안에서는 닫는다**(A·B 0건이
증거). 그러나 ①행렬을 그리려면 행이 무엇인지 알아야 하는데 그것이 바로 매번 빠지던 것이고
(축 세우기가 곧 발견 수단이다 — `data_sheet`·relink 형제 둘 다 그렇게 나왔다) ②새 **차원**은
리뷰가 도입한다(초점은 어떤 축에도 없었다) ③17,931줄에서 전 곱을 훑는 것은 이 PR 을 다시
쓰는 일에 가깝다. 그래서 정지 규칙 4항이 「신규·독립이면 수렴」으로 끊는 것이 옳다 —
새 가족이 계속 나오면 그것은 열거 실패가 아니라 **PR 이 크다는 신호**이고, 답은 점별 픽스가
아니라 분할이다.

### 10.14 F7 PR-B 기각 — `runOverrides` 는 짓지 않는다 (2026-07-28, 사용자 확정)

대조표 **23행(`runOverrides`)과 9행 잔여분(재시도 3종)을 기각**한다. PR-A 착지 정산(§10.13.6)이
"PR-B 로 남는 것"으로 적어 둔 넷은 **짓지 않고 닫는다** — 착수 계약을 쓰기 전에 실측한 결과
override 가 겨눌 문제가 이 제품에 존재하지 않았다.

**사용자 확정(2026-07-28)**: *"override 로 풀릴 문제면 애초에 풀면 될 문제고, 아니라면
override 가 아니라 **원인 수정**으로 가야 한다."* — override 는 원인 수정의 **대체재**일 때만
값이 있는데, 아래 실측에서 대체할 원인이 남지 않았다.

#### 10.14.1 실측 근거 4

**① 이 앱이 내는 실패 전수 중 규칙으로 풀리는 것은 0건이다.**

| 실패 | 원인 | 실제 처방 |
|---|---|---|
| 배치 **원자 차단** 3종(`batch.py`) | 구조 드리프트 · 산출물 충돌 미확정 · 폴더 오류 | 실행이 시작되지 않는다. 규칙과 무관 |
| 레코드별 실패 — `classify_result_error` 확정 4종 | `WinError 5` 권한 · `WinError 32` 한글에 열려 있음 · `WinError 112` 디스크 공간 · 경로 부재 | 파일 닫기 · 공간 비우기 · 폴더 바꾸기 → **같은 규칙으로 재시도** |
| 원인 미확정(`known=False`) | 아는 패턴 없음 | 증거 표시(F4 §10.10). 규칙을 바꿔서 될 일인지 **알 수 없다** |

**② 계약 §10.2 가 override 를 요구하는 유일한 실패(이름 충돌)는 master 에서 실패가 되지 않는다.**
`plan_output_names` 가 이름을 실행 **전에 전부** 계산하고, 배치 안의 충돌은 `OutputNamer` 가
`_1` 접미로 해소하며, 디스크의 기존 파일은 `OutputCollisionError` 원자 차단 + 덮어쓰기 확인
왕복(RC-02)이 막는다. 즉 master 는 이름 문제를 **사전 계획**으로 푸는 구조이고, v6 계약은
그것을 **런타임 복구**로 푸는 구조다. 전자가 이미 서 있는 자리에 후자를 얹으면 같은 문제에
판정 주체가 둘이 된다(§10.5 판정 단일 출처). F4 판정 D 와 같은 부류 — **조사가 계약의 전제를
뒤집은 두 번째 표본**이다.

**③ 유일하게 남던 후보(경로 길이 초과)도 F5 가 이미 사전에 말한다.** `OutputNameAudit.too_long`
이 게이트 경고와 미리보기 증거로 실행 **전에** 서 있다(§10.12 판정 K). 사후에 그 레코드의 이름만
줄이는 override 는, 사전 경보를 무시하고 실행한 사람을 위한 두 번째 출구일 뿐이다 — 그 자리의
정답은 패턴을 고치거나(기본 저장) 짧은 폴더를 고르는 **원인 수정**이다.

**④ F4 가 미룬 재시도 3종은 실측하면 이미 도달 가능하다.**

| 계약이 요구한 것 | 지금 도달 경로 |
|---|---|
| 건별 재시도 | 「실패한 N건만 선택」(§10.10 판정 F) + 「문서 만들기」 — F4 가 착지시킨 2클릭 |
| 다른 폴더에서 재시도 | 저장 폴더 변경 + 위 2클릭 |
| 레코드 filename override | 겨눌 실패가 ①②③ 에 없다 |

#### 10.14.2 판정

**A. 대조표 23행은 사망한다.** `runOverrides`·「이번 생성에 적용」 분기·합성 3층
(`base + inheritedRunOverrides + patch`)을 짓지 않는다. `EditSession.inherited_run_overrides`
자리는 **비워 두는 것이 최종형**이고, 그 사실을 주석이 말한다(빈 사전으로 세워 두면 §13-15 를
만족하는 척하게 된다던 PR-A 의 규율이 여기서 영구화된다).

**B. §13-14·15 는 폐기가 아니라 공허참이 된다.** "Run-only patch 는 기본 판본을 바꾸지 않는다 /
기본 저장은 상속 override 를 포함하지 않는다"가 금지하는 상태는 **존재할 수 없다** — 상속
override 라는 것이 없기 때문이다. 불변식을 부정하지 않고 그 전제를 짓지 않는 것이므로 계약
우선(§10.0)과 충돌하지 않는다. 같은 이유로 저장 경로에 override 거절 가드를 세우지 않는다
(막을 것이 없는 가드는 다음 사람에게 없는 기능이 있다고 말한다).

**C. §6 적용 범위 표의 「이번 생성에 적용」 행은 이 제품에서 미착지로 선언한다.** 편집기 footer 의
주 행동은 문맥과 무관하게 **「변경 저장」 하나**다(PR-A 판정 E 가 임시 조치로 세운 것이 최종형이
된다). 배제는 **선언**으로 남긴다(PR-A 판정 K 선례) — 열거값을 만들어 두고 아무도 안 쓰면
나중에 배선을 빠뜨려도 아무 테스트도 울지 않는다.

**D. 기각의 진짜 근거는 목적함수다 — 실패 복구를 뺀 뒤 남는 용도가 제품과 어긋난다.**
①②③ 을 걷어내면 override 에 남는 용도는 §6.1 의 **일회성 표시형 변경**뿐인데, 그것은 *파일에
남지 않는 규칙으로 법적 효력 문서를 만드는 층*이다. 산출물의 근거가 Job 에 없어 **같은 문서를
다시 만들 수 없고**(원장에 흔적은 남지만 재현 원천이 아니다), F5 가 "규칙이 갈리면 확인받아라"로
세운 게이트를 우회하는 두 번째 권위가 된다. lab 계약의 예시(급여명세서 지급일 표시형)는 반복
사무문서 도메인의 것이고, 이 제품은 반복성×법적효력의 이상 사분면이다([[positioning-anomalous-quadrant]]).

**E. F7 은 PR-A 로 완료다.** 대조표 20·21·22행은 착지했고 23행은 사망했다. PR-B 로 미뤄 둔 넷
중 셋(override·「이번 생성에 적용」·재시도 3종)이 여기서 닫히고, **하나만 남는다** — 아래.

#### 10.14.3 남는 것 하나 — F5 드로어 행별 「수정」 deep-link (**착지** — F6 PR-B §10.15.15.4)

계약 §8 표(미리보기 필드 → `binding/<fieldId>`, 파일 이름 → `filename/filenamePattern`, 복귀는
같은 `previewIndex` 와 같은 행)는 **override 와 무관하게 성립한다**: 이상한 값을 본 자리에서 그
필드의 탭으로 바로 가고, 고친 뒤 「변경 저장」 하나로 끝난다. `EditContext.target` 한 축과 드로어
행의 행동 줄이 전부라 **F6 에 동승**시킨다(단독 PR 로 올릴 크기가 아니다). 「이번 생성에 적용」
배지는 판정 A 와 함께 사망한다 — 배지가 말할 상태가 없다.

#### 10.14.4 후속 규칙 — 계약 항목을 짓기 전에 「그 문제가 여기서 어떻게 이미 풀리는가」를 센다

이 기각은 착수 계약을 쓰다가 나왔다: §9.3 4계약면을 채우고 판정 10건을 적은 뒤에야 "그런데 이
override 로 풀리는 실패가 실제로 나는가"를 물었고, 답이 0이었다. **v6 계약은 master 가 이미
다르게 푼 문제에 대해서도 자기 해법을 적어 둔다** — 계약이 v6 시안의 세계에서 자족적으로
쓰였기 때문이고, 그 세계엔 사전 이름 계획도 원자 충돌 차단도 없었다. 그래서 대조표의 「master
대응물」 열이 **「없음」인 행일수록 먼저 실측한다**: 정말 없는 것인지, 아니면 **다른 층에서 이미
풀려서 그 이름으로 안 보이는 것**인지. 후자면 지을 것은 새 층이 아니라 이름 하나다.

이 규칙의 이행 비용은 낮다 — 실패 원인 열거(`classify_result_error`)·이름 계획(`naming.py`)·
게이트(`run_state.py`)는 전부 한 자리에 모여 있어 세는 데 20분이 들었고, 지었다면 커밋 5개와
리뷰 라운드 N개가 들었을 자리다.

### 10.15 F6 PR-A 계약·정산 — TXT 합류 + 검토·복사 작업대 (2026-07-28, **머지 `275dd24`**)

대조표 **17·18·19행**을 진다(18행의 `draft` 화면 사망분과 §10.14.3 의 드로어 deep-link 는
**PR-B**). 계약 정본은 lab `core-workflow.md` §3.2(TXT 탭 집합)·§11(작업대 7줄)·
§13-13·17·§18.10~§18.11(고정 사본·OrderedSelection)·§19.1~§19.5(작업 방식·구획·최근 사용
사건), 시안은 `core-workflow-ui-mvp-demo-v6.html` `#screen-workbench`(218~224)다.

**문제의 진술**: TXT 작업은 「문서 만들기」에 들어오지 못한다. `compatibility_for` 가
`media != "hwpx"` 를 후보에서 fail-closed 로 떨어뜨리고, TXT 는 별도 화면 `draft` 에서
**자기만의 데이터 선택·필터·행 선택**을 다시 한다. 같은 일을 두 화면이 다르게 하고 그중
하나는 이미 사망 확정이라(결정 1·2), TXT 사용자는 F1(데이터 선택 통합)·F3(표시순서·범위
편집기)·F5(미리보기)가 세운 것을 **하나도 쓰지 못한다**.

**사용자 확정 4건(2026-07-28)**:

| 사안 | 확정 | 근거 |
|---|---|---|
| 범위 분할 | **PR-A** = TXT 합류 + 작업대 신설 (`draft` 존치) / **PR-B** = `draft` 사망 + 승계 정산 + 드로어 deep-link 동승 | 사망분만 `draft.js` 539 + `draftsession.js` 953 + `screen_draft.py` 644 + `draft_session.py` 1209 줄 + `index.html` 95곳 + 테스트 ~170건으로, F7 PR-A(3619 삽입·리뷰 9라운드)를 넘는다. §10.4 서문의 「승계처가 서기 전에 지우지 않는다」와도 같은 분할이다(F2 선례) |
| 작업대 좌 pane | **인라인 필드 연결 편집 승계** — override 는 짓지 않는다 | 계약 §11(왼쪽 세션 patch → 오른쪽 결과 즉시 반영)이 요구하고 현행 `draft` ② 맞추기 표가 이미 그 일을 한다. 지도가 선언한 사망은 **휘발 세션뿐**이므로 인라인 편집을 걷으면 선언 밖 기능 축소가 된다 |
| TXT 작업 생성 경로 | **편집기 「템플릿」 탭 매체 분기** | 두 매체는 레지스트리·가져오기·그룹까지 이미 대칭이다(`TextTemplateRegistry` 주석: "hwpx 의 템플릿 라이브러리에 대응하는 txt 쪽", tpl 가져오기는 확장자로 매체 라우팅 — 결정 4). 비대칭은 편집기 탭 **한 곳**뿐이고 §10.13.2 판정 A 가 이미 "F6 이 TXT 를 합류시킬 때 목록이 저절로 갈린다"고 배정해 뒀다. **이행은 PR-B**(사망 점검표 4행의 선행 조건) |
| 휘발 폐지 고지 | **화면 문안 + 문서** (PR-B) | 상시 배너·1회 다이얼로그(영속 플래그 신설)를 두지 않고 ①문서 만들기 TXT 구획 빈 상태 ②tpl 화면 TXT 밴드 ③101 README 트랙 B 에서 대체 경로(저장 TXT 작업 경유)를 재진술한다 |

#### 10.15.1 §9.3 4계약면 사전 기입 (새 표면 = 검토·복사 작업대)

§10.5 「항목 착수 전 필수 절차」의 이행분. 호스트는 **화면**이다 — F7 몰입 편집기와 같은
부류이고 F1 다이얼로그·F5 드로어와 다르다(잠금·정체의 값이 갈린다).

| 면 | 이 표면에서의 값 | 회귀 |
|---|---|---|
| **재렌더를 가로지르는 정체** | 세션(고정 사본·작업점·복사 집합·patch dirty)은 **Python 소유**(`workbench` 스냅샷). 작업대가 열려 있다는 사실도 화면 키가 아니라 **세션 존재 여부**다 — 라우팅만으로 열면 부팅·새로고침에 문맥 없는 작업대가 선다(F7 선례). 작업점은 **고정 사본의 서수**이지 원본 index 가 아니고 웹은 이동 **방향**만 보낸다(F5 판정 M·F3 판정 A 와 같은 뿌리) | selftest: push 왕복 후 작업점·복사 수 유지 · 부팅 기본 착지가 작업대가 아님 |
| **전역 잠금의 범위** | 생성 중(`setBusy`)에는 **진입을 막는다** — HWPX 런이 도는 중에 규칙을 갈아 끼우면 RC-02 「확인 대상 = 생성 대상」이 깨진다. 범위 초안(⤢)이 열려 있어도 진입하지 않는다: 작업대는 **커밋된** 실행 입력의 사본을 뜨는 표면이라 초안 세계와 겹치면 어느 범위의 사본인지 갈린다(F5 판정 H 승계). 역방향은 몰입 승격이 공짜로 준다 — 작업 중에는 생성 표면이 화면 뒤라 눌릴 DOM 이 없다 | selftest: 생성 중·초안 열림 중 `open_workbench` 거절 · 작업 중 실행 컨트롤 부재 |
| **전이와 왕복의 순서** | 저장은 **Python 커밋이 성공한 뒤** 스냅샷이 새 판본·클린으로 갱신되고 **작업점은 그대로**(§11 전문). 복사는 **클립보드가 성사된 뒤에만** 큐·최근 사용 스탬프가 움직인다(실패한 복사를 완료로 세지 않는다 — 현행 `copy_clipboard` 순서 그대로). 작업점 이동은 왕복 액션이라 **마지막 값이 이긴다**. back 은 세션 처분이 성사된 뒤에만 일어나고 포커스를 진입 트리거로 되돌린다 | 실앱 게이트: 저장 뒤 같은 작업점·판본 증가 · 복사 실패 시 큐 불변 · back 포커스 착지 |
| **실패 경로의 문맥 보존** | 복사 게이트 차단(빈 값·미치환 토큰)·저장 게이트 차단·스탬프 실패는 전부 **작업대 안에서 재진술**하고 화면을 닫지 않으며 **patch 를 버리지 않는다**. 실패한 저장이 사용자의 편집을 삼키는 것이 이 표면에서도 가장 비싼 조용한 파괴다(F7 4면 승계) | 회귀: 각 차단 뒤 patch·작업점 생존 |

#### 10.15.2 판정 10건 (이 슬라이스에서 확정)

**A. 작업 방식은 3값이고 「연결 상태」는 다른 축이다**(대조표 17행 어휘 통일). 링0에
`work_mode(job)` 신설 — `hwpx_generate`·`text_review_copy`·`unsupported`, `template_path`
확장자에서**만** 파생한다(§19.1·§13-17). **미연결(경로 없음)은 방식의 값이 아니다**:
`library_mode_of` 의 「미연결 → hwpx」는 *필터 귀속 규칙*으로 남기되 방식 파생 함수와 분리해
유지한다(대조표 17행 주의사항 그대로). 어휘 통일의 반대편 오류를 여기서도 피한다 — 같은
것을 다르게 부르는 것도, **다른 것을 같게 부르는 것도** 드리프트다(F7 판정 F 와 같은 규율).
라벨 단일 출처는 `screen_library.MODE_LABELS` 를 링1으로 올려 후보 카드·문서 탐색·라이브러리가
같은 문자열을 쓴다.

**B. 매체 국경이 걷히는 곳은 한 줄이다.** `gui/work_candidates.py` 의
`if media != "hwpx": EXCLUDED` 가 **`unsupported` 만** 남긴다. txt 의
available/needs_action 판정은 hwpx 와 **같은 술어**(필요 필드가 현재 데이터에 있는가)를 탄다 —
매체별로 판정을 갈래 치면 같은 상태를 두 술어가 부른다. 미상 확장자는 그대로
fail-closed(§19.1: 메인 후보 제외·현재 데이터 문서 선택 불가·「확인 필요」에 실제 이유).
`require_hwpx` 백스톱은 **산다**: 후보에 드는 것과 HWPX 생성 경로에 드는 것은 다른 사건이다.
이 한 줄이 `candidate_rows` → `rank_available` → `browse_candidates` → `prework_gate` →
`_candidate_payload`/`_browse_payload` 를 한꺼번에 연다.

**C. 구획은 두 방식이 다 있을 때만 선다**(§19.3). 전체 후보 정렬(즐겨찾기 → 최근 사용 →
미사용) → 상위 `MAIN_TOP_N` → **그 결과를** 방식으로 구획한다. 방식별 최소 자리 보장도
방식별 5개도 없다. 한 방식만 있으면 헤더 없는 평면으로 퇴화하되 **카드 부제의 방식 텍스트는
유지**한다 — §8.2 ④ 의 유보가 여기서 풀린다. 구획 순서 = 각 구획에 든 항목 중 가장 높은
전역 순위의 위치. 문서 탐색 시트도 탭 **안에서** 같은 규칙(§19.5)이고 탭(사용 가능/확인
필요)이 primary 다.

**D. 실행 버튼은 매체 파생 2분기이고 판정은 Python 이 낸다.** HWPX 「N개 생성」 /
TXT 「검토·복사 시작 · N건」. 스냅샷이 라벨과 행동 키를 싣고 웹은 그리기만 한다(F3 판정 A·
F4 판정 F 와 같은 뿌리). 표면이 매체를 다시 읽어 분기하면 같은 판정이 두 곳에 산다.

**E. 작업대는 몰입 화면이다** — F7 편집기 승격과 **같은 근거**. 세션 patch 의 이탈 처분이
성립하려면 **나가는 경로가 셀 수 있어야** 한다. 작업대가 「문서 만들기」 안에 살면 상단 탭·
화면 내 다른 컨트롤이 처분 미확정 이탈구가 되고 가드의 완전성이 표면 수에 비례한다.
`scr-workbench`·상단 2탭 은닉·back = 문서 만들기. 열기는 **성사 뒤**다(선택 0건·미상 방식·
생성 중·초안 열림이면 열지 않는다 — F3 초안 선례).

그리고 **`workbench_result` 진입 사유는 F6 이 와도 서지 않는다** — F7 판정 K 가 "작업대는
F6" 으로 미뤄 둔 자리의 처분이다. 계약 §8 표에서 작업대 결과 토큰의 복귀처는 편집기가 아니라
**같은 화면의 규칙 행**이다(오른쪽 결과를 누르면 왼쪽 소유 규칙 행을 강조 — §11 2줄). 즉
작업대는 편집기로 나가는 deep-link 를 갖지 않고 화면 안에서 겨눈다. 배제 선언을 **유지**하되
사유를 「후속 미구현」에서 「계약이 화면 안 겨눔으로 정했다」로 고쳐 적는다 — 미뤄 둔 것과
짓지 않기로 한 것은 다르다.

**F. 세션은 진입 시 고정 사본이다**(§13-13·§18.11-25). F3 표시순 투영을 통과한
OrderedSelection 의 복사본을 뜨고, 이후 문서 만들기의 검색·필터·정렬·선택 변화가 현재 작업점
순서를 바꾸지 않는다. **작업대에 데이터 존은 없다** — `draft` 의 ① 데이터 존과 13 액션·
필터·`zone_epoch` 는 TXT 에서 사라지고 그 일은 문서 만들기가 한다. HWPX 와 TXT 가 같은
OrderedSelection 을 소비한다는 불변식(§18.11-24)이 여기서 참이 된다.

**G. 승계 4종은 거처만 옮긴다 — 판정 소유자는 그대로다**(대조표 18행이 명시).

| 승계물 | 판정 소유자(불변) | 새 거처 |
|---|---|---|
| 큐 퇴화 규칙(선택 1건 = 점·◀▶·자동 다음 숨김) | `TxtQueueModel` + `queue_degenerate` 술어 | 작업대 footer·readout |
| T3 가드(복사 진행 중 이탈·데이터 교체) | `_guard_state`·`_leave_guard` | 작업대 이탈 가드 |
| 정렬 린트(전각·공백 연쇄) | `_aligned` — 카드와 클립보드가 **같은 값** | 작업대 우 pane |
| 확정-비움 의미론 | `MappingModel.declared_blank_fields` | 작업대 좌 pane + 편집기 |

**H. 좌 pane 은 미저장 변경이지 override 가 아니다.** v6 배지 「이번 작업에만 적용 중」은
§10.14 판정 A·C 와 함께 **사망**한다 — 말할 상태가 없다. 문안은 「저장하지 않은 변경 N건」이고
착지점은 **「기본 규칙으로 저장…」 하나**다. 거래 모델은 F7 `gui/edit_session.py` 를
**재사용**한다(section = `binding` 하나) — patch 를 두 벌 지으면 같은 상태에 어휘가 둘이 된다
([[contract-item-litmus]] 의 이행: 그 문제가 여기서 이미 어떻게 풀리는가를 먼저 셌다).
저장 = dirty 전 필드 열거 확인 → Binding 판본 상승 → 재검증 → **같은 작업점 유지** → 이미
복사한 레코드는 「다시 확인 필요」로 되돌림(§11 전문 그대로).

**I. 복사 완료 = 최근 사용**(대조표 19행). `JobRegistry.stamp_last_run` 을 **재사용**한다 —
같은 잠금 왕복, 새 writer 없음(`test_architecture.py` 가 지키는 「durable Job 쓰기는
`mutate`·`stamp_last_run` 만」 규율). 세션의 **첫 복사 1건**에서 찍고 이후는 무동작(§19.4:
"한 레코드라도 복사 완료", 작업대 진입만으로는 기록하지 않는다). HWPX 는 완주
(`not cancelled and failed == 0`), TXT 는 복사 1건 — **두 술어가 다르다는 사실을 문안이
말한다**: 후보 카드가 매체별로 「마지막 성공 실행」/「마지막 복사」를 가른다. `reviewed_rules`
는 **넘기지 않는다**(판정 J 의 따름정리) — 짓지 않은 축의 기준선을 찍으면 하지 않은 검토를
했다고 기록하는 것이다(F5 판정 N 의 규율).

**J. TXT 는 검토 요구·미리보기 드로어를 지지 않는다 — 배제 선언.** 드로어는 값 + **파일
이름** + 승인의 면인데 TXT 엔 파일 이름 축이 없고(§3.2), 작업대가 이미 레코드 전수를 채운
모습으로 보여 주는 검토 표면이다. TXT 에 `review_required` 를 세우면 작업대에서 눈으로 본
것을 문서 만들기에서 또 확인하라는 **이중 권위**가 된다(§10.5 판정 단일 출처). 배제는
**선언**으로 남긴다 — F5 판정 O 가 건강 번역에 세운 `not_health` 표와 같은 자리에 검토
요구의 매체 배제를 적어, 다음 사람이 배선을 빠뜨리면 가드가 울게 한다. 조용한 무시와
선언된 배제는 다르다.

#### 10.15.3 커밋 경계 (PR-A, 직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(§9.3 4계약면 · 판정 10건) |
| 2 | **어휘 통일** — 링0 `work_mode` · 라벨 단일 출처 · `compatibility_for` 방식 국경 해제 · 고정 테스트 2건 뒤집기(둘 다 "F6 이 오면 시끄럽게 알린다" 주석 보유) · 회귀 |
| 3 | **TXT 세션 분기 + 작업대 표면 — 한 전이로** · `scr-workbench` · 고정 사본 세션 · 좌 필드 연결(`EditSession` section=binding) · 우 원문/채운 모습 + 검토 상태 · footer(작업점·자동 다음·복사) · 「기본 규칙으로 저장…」 · 이탈 가드 · 몰입 표면 목록 일반화 · action registry · UI_CONTRACT · selftest 프로브 |
| 4 | **후보·탐색 방식 구획** — Top 5 결과의 방식 구획(1방식 평면 퇴화) · 카드 부제 방식 텍스트 · 매체별 최근 사용 문안 · 탐색 시트 탭 안 구획 · DOM 계약 |
| 5 | **복사 = 최근 사용** — `stamp_last_run` 재사용(첫 복사 1회) · 매체별 술어 문안 · 검토 요구 배제 선언 · 회귀 |

#### 10.15.4 착지 정산 — PR-A (2026-07-28)

**실앱 한 바퀴가 잡은 것 1건**(§10.9.5 후속 규칙의 배당금). 헤드리스 2170건과 실 WebView2
프로브 72건이 전부 통과한 뒤, 사람 순서로 한 바퀴 돌리자 **작업점 표기가 진입부터
「2 / 3」**이었다. 뿌리는 `TxtQueueModel.position_of` 의 의미를 잘못 빌린 것이다 — 그 값은
*미처리 큐* 안의 **1-기반** 순번이라 ①표면이 +1 하면 진입부터 어긋나고 ②복사할 때마다 번호가
**다시 매겨지며** 복사한 카드는 `None` 이 된다. 이 화면의 부제가 「선택 당시 표시순서로 고정된
항목」이라고 말하므로, 사람이 읽는 숫자도 그 고정 순서를 따라야 참이다(§13-13). 자리를
**고정 사본의 서수**로 바꿨다.

이 결함이 단위 계약을 통과한 이유가 교훈이다: 테스트가 `position` 을 `position_of` 와
**같은 함수로** 대조했기 때문이다 — 산출과 기대가 같은 술어를 쓰면 그 술어의 의미가 틀려도
둘이 나란히 틀린다. 회귀는 이제 *사람이 읽는 숫자*를 직접 못박는다(진입 = 1번째, 복사 뒤에도
그 카드의 자리는 불변).

**실앱 순회 결과**(임시 홈 · TXT 작업 1건 · 3행): 후보 카드에 방식 부제·「복사한 적 없음」 →
실행 버튼 「검토·복사 시작 · 3건」 → 작업대 몰입 진입(상단 탭 은닉) → 작업점 1/3, 카드 채움·
〈빈 값〉 표지 → 이동 2/3 → 인라인 편집 「저장하지 않은 변경 1건」 → **실 클립보드 복사**
「2행을 복사했습니다」·「복사 완료」 + 디스크 `last_run_at` 기록 → 이탈 가드가 세 줄(복사 진행
1/3 · 미저장 연결 1건 · 미확정 편집)을 열거 → 복귀 후 카드가 「마지막 복사 2026-07-28」.
101 하니스도 14컷 무변경 완주(트랙 B 는 아직 「기안」 화면 — PR-B 에서 재배선한다).

**게이트**: 2176 passed(신규 40) · 실 WebView2 selftest 72 · ruff·pyright 초록 · 커버리지
플로어 8구획 PASS.

**PR-B 로 남는 것**: `draft` 화면 사망과 그 승계 정산(TXT 작업 생성 = 편집기 템플릿 탭 매체
분기 · 라이브러리 `primary_action` 재배선 · 휘발 폐지 고지) · 드로어 행별 「수정」 deep-link ·
101 하니스 재배선.

#### 10.15.5 리뷰 1R — 근본원인 재분석과 구조 조치 (P1 2 · P2 2, 2026-07-28)

**4건이 아니라 두 가족이었다.** 개별 수리 대신 뿌리를 닫는 쪽을 택한 이유가 이 절이다
(사용자 확정: "근본 조치 4건 전부").

**가족 A — 확인 프로토콜을 새로 발명했다**(P1 2건).

| 증상 | |
|---|---|
| P1 | `save_rules` 스키마가 `confirm_drift` 를 모른다 → `validate_dispatch` 가 거절 → 실 브리지에서 「기본 규칙으로 저장」이 **한 번도 성사되지 않았다** |
| P1 | 클라이언트가 `{confirm, confirm_drift}` 를 한 번에 보낸다 → Python 의 드리프트 분기는 **도달 불가능한 죽은 코드**, 외부 변경은 무확인 덮어쓰기 |

둘은 결정 하나에서 나왔다: 2단 확인을 **불리언 두 개**로 설계한 것. 이 저장소엔 이미 그
문제를 푸는 관용구가 있다 — **`confirmed_text`**(클라이언트가 *보여 준 문안 그대로*를
되돌려주고 Python 이 잠금 안에서 문안을 **다시 지어** 대조; `screen_draft._do_save_job`·
`screen_editor._overwrite_gate`). 그 관용구가 구조적으로 드리프트-안전한 이유가 정확히
P1-2 가 놓친 지점이다: **불리언은 「사용자가 *이* 상황을 확인했다」와 「*어떤* 상황을
확인했다」를 구별하지 못한다.** 저장소는 이 교훈을 더 세게 배운 적도 있다(리뷰 5c 6R P1
/ #273 — 이름만 든 문안은 버전 불가지라 내용 다이제스트까지 못박았다).

즉 [[contract-item-litmus]]("그 문제가 여기서 이미 어떻게 풀리는가")를 **기능에는 적용하고
프로토콜에는 적용하지 않았다.** P1-1(스키마 누락)은 그 발명의 부산물이다 — 새 어휘를
만들었으니 등록할 자리가 하나 더 생겼고 그걸 빠뜨렸다.

**조치**: 불리언 폐기 → `confirmed_text` 왕복으로 교체(문안을 잠금 안에서 성형·대조,
외부 변경 시 버전 다이제스트를 문안에 못박음). 새 어휘가 없으니 등록할 자리도 없다.

**가족 B — 같은 사실의 두 번째 소유자를 세웠다**(P2 2건).

`txt_job: Job` 은 durable 사실의 **제2 정본**이었다. 그 순간 `vm.job` 을 유지하던 모든 자리
(`_reload_active_job`·`_do_rename_job`·`_do_relink_template`)가 조용한 구멍이 됐다 — 이름을
바꾸면 세션이 없는 이름을 가리키고, 다른 곳에서 저장한 규칙은 재진입에도 stale 이었다.
이 저장소는 같은 규칙을 이미 명문으로 적어 뒀다: *"메모리 사본을 들지 않고 영속 키를
그때그때 읽고 쓴다 — 표면 없는 두 번째 인메모리 소유자가 남으면 … 그게 제2 정본이다"*
(`_recollapse`). P2-2(창 종료 가드가 화면 이름 셋을 손으로 셈)는 그 가족의 열거판이다.

**조치**: ①`txt_job` **삭제** — 매체는 파생 플래그(`job_is_txt`, §13-17 로 불변)만 남기고
Job 은 **쓰는 순간** 읽는다. 「지금 열어 둔 작업인가」도 `vm.job.name` 이 아니라 `job_name`
으로 묻는다(매체 불가지). 세 경로는 **고칠 것이 없어졌다** — 그게 요점이다. ②창 종료
가드를 **프로토콜 순회**로: 컨트롤러가 `close_guard_reason()` 을 구현하면 자동 참여하고,
세션을 든 컨트롤러가 빠지면 테스트가 운다(배제는 사유와 함께 선언).

**검출이 실패한 공통 이유** — 새로 만든 이음매를 **전부 한쪽에서만** 검증했다:

| 이음매 | 테스트가 들어간 자리 | 놓친 것 |
|---|---|---|
| dispatch 스키마 | `ctrl.dispatch()` **직접**(관문 아래) | P1-1 |
| 확인 왕복 순서 | 테스트가 실 클라이언트와 **다른 조합**을 보냄 | P1-2 |
| 작업대 실 발신 | selftest 프로브가 `Bridge.call` **스텁** | P1-1·2 |
| 창 종료 | 이탈 가드를 컨트롤러 메서드로 직접 호출 | P2-2 |

착지 정산의 작업점 결함(*"산출과 기대가 같은 술어를 쓰면 나란히 틀린다"*)과 **같은 부류의
2·3번째 발생**이다. 그래서 개별 수리가 아니라 관문을 옮겼다: ①이 스위트의 모든 발신은
`validate_dispatch` 를 **먼저** 지나는 `_send()` 헬퍼를 쓴다 ②정적 가드
`tests/test_dispatch_payload_contract.py` 신설 — 프런트 리터럴 호출의 **페이로드 키**를
전 화면에서 스키마와 대조한다(양성대조 확인: `confirm_drift` 를 되살리면 울고, 되돌리면
통과) ③로컬 `call()` 래퍼 폐기 — 래퍼가 있으면 리터럴 추출이 그 화면을 **공허하게 통과**한다.

**실 브리지 왕복으로 확인**: 실앱 순회에 저장 단계를 더해 확인 문안(「비고」 나열) → 저장
성사 → 연결 r2 → dirty 해소 → 디스크 반영까지 실물로 밟았다.

**게이트**: 2182 passed(신규 6) · 실 WebView2 selftest 72 · ruff·pyright 초록.

#### 10.15.6 리뷰 2R — 사건에 고정하지 말고 조건을 재라 (P1 1 · P2 3, 2026-07-28)

**1R 조치가 절반만 갔다.** 1R 에서 durable 사실의 **사본**(`txt_job: Job`)을 지웠는데 같은
자리에 **래치**(`job_is_txt`)를 남겼고, 2R 의 P1·P2 셋이 전부 그 가족이었다 — F3·F5 에서
반복된 「각 라운드가 직전 픽스가 연 창」 패턴의 이번 판이다.

**가족: 파생 가능한 값을 사건 시점에 고정하고, 그 사건 밖의 변화를 못 본다.**

| # | 래치한 것 | 못 본 변화 | 증상 |
|---|---|---|---|
| P1 | 표시 서수 하나로 **두 질문**에 답(자리 + 순회 경계) | 복사가 카드를 큐 후미로 보냄 | 복사 직후 「다음」은 눌리는데 무동작, 「이전」은 비활성 — **그 카드에 갇힌다** |
| P2 | 매체를 **작업 선택** 사건에 고정 | 재연결이 매체를 갈아 끼움(파일 필터에 「모든 파일」) | TXT→HWPX 는 실행 버튼이 계속 작업대를 광고, HWPX→TXT 는 재적재가 `RunViewModel` 을 세우려다 터짐 |
| P2 | 복사 상태를 **저장** 사건에 고정 | 그냥 매핑을 고친 것 | 카드는 이미 다른 문장인데 배지는 「복사 완료」 — 다시 복사해야 할 행을 건너뛴다 |

셋의 처방도 하나다: **래치를 지우고 파생으로 바꾼다.**

- 순회 경계는 **큐 상대 위치**에서 파생해 Python 이 `can_prev`/`can_next` 로 낸다. 표시
  서수는 고정 사본의 자리로 남는다 — 한 값으로 두 질문에 답하면 그중 하나는 반드시 틀린다.
- 매체와 실행뷰를 **한 함수**(`_seat_active_job`)가 함께 세우고, 재적재가 매체 변화를 보면
  다시 앉힌다. 두 값이 갈라질 자리 자체가 없어진다(세션 데이터 주입도 같은 자리로 모았다 —
  vm 을 세우는 곳과 그 vm 이 볼 데이터를 싣는 곳이 갈리면 한쪽만 부르는 경로가 빈 실행뷰가
  된다. 실제로 재적재가 그랬다).
- 복사 상태는 **복사 시점의 규칙 지문**과 지금 지문의 차이에서 파생한다. 저장은 규칙을
  바꾸지 않고 영속시킬 뿐이므로 저장 경로에서 재확인 집합을 칠하지 않는다 — §11 의 「이미
  복사한 레코드는 다시 확인 필요」도 이 파생이 자연히 만족한다. 지문에 **전각 치환 여부**를
  담는 이유도 같다: 그것도 복사되는 문자열을 바꾼다.

**네 번째(P2)는 다른 뿌리 — 승계가 표지만 옮기고 행동을 두고 왔다.** 판정 G 는 정렬 린트를
「거처만 옮긴다」고 했는데, 옮긴 것은 경고 문안뿐이고 그 **처방**(전각 치환 버튼)이 없었다.
백엔드 `set_fullwidth` 는 살아 있는데 그것을 부르는 DOM 이 없어, 사용자는 문제를 통보받고
손잡이는 없는 상태였다 — 「승계는 의무를 상속한다」가 행동까지를 뜻한다는 확인이다.

**게이트**: 2187 passed(신규 5) · 실 WebView2 selftest 72(프로브에 경계·린트 행동 추가) ·
실앱 순회 재완주(저장 왕복 포함).

#### 10.15.7 리뷰 3R — 근본원인 재분석: 승계는 판정이 아니라 **동사**다 (정지 규칙 §8.1 3항)

3라운드다. 개별 수리 전에 세 건의 공통 뿌리를 물었고, 답은 **판정 G 의 「거처」를 너무 좁게
읽었다**였다.

| 등급 | 증상 | 실측 |
|---|---|---|
| P2 | `set_map_fmt` 가 **이름 API 에 행 index** 를 넘긴다 | 작업대의 표시형 변경이 **전부** `ValueError: 매핑에 없는 토큰: 0` |
| P2 | `revert_map` 이 스니핑 유형을 안 넘긴다 | 일반명 필드에 결속된 금액 열이 되돌릴 때 **text 로** 떨어짐 |
| — | (리뷰 미지적, 이관 중 드러남) `set_source` 에 덮어쓰기 확인이 없다 | 직접 입력한 값이 **무확인으로** 사라짐 |

셋 다 「기안」의 같은 동사를 **손으로 다시 짜면서** 호출 규약과 그에 딸린 게이트를 함께
옮기지 않은 자리다 — 6개 중 2개가 파손, 1개가 게이트 누락이었다. 판정 G 는 승계를 「거처만
옮긴다」고 했는데, *거처* 에는 **동사의 호출 규약과 게이트**가 포함된다. 2R 의 네 번째 건
(린트의 **행동**을 두고 옴)이 같은 오독의 앞선 표본이었고, 3R 에서 세 번 반복됐다.

**근본 조치 — 동사를 한 벌로 만든다.** `webapp/mapping_verbs.py` 의 `MappingVerbsMixin` 이
맞추기 동사 6종을 소유하고 「기안」·작업대가 **함께** 상속한다. 이관 방향은 **작업대가
「기안」의 구현을 채택**하는 쪽이다(그쪽이 정본이고 141건이 지킨다) — 다시 파생하지 않고
옮겼다. 정체는 **토큰 이름**으로 통일했다: 행 index 는 템플릿을 다시 읽으면 흔들리지만
이름은 그 표의 안정 식별자이고, 없는 이름은 `index_of` 가 시끄럽게 거절한다. PR-B 에서
「기안」이 죽으면 이 모듈의 소비자는 작업대 하나가 된다.

PR-A 가 「한시적 중복」으로 허용했던 자리가 바로 여기다 — #94 가 남긴 교훈("한시적 중복은
한시적이지 않다")을 이 PR 이 세 라운드에 걸쳐 다시 확인했다.

**P1 — 확인 대상 = 복사 대상.** 복사를 빠르게 두 번 누르면 둘 다 **같은 카드**로 사전확인을
통과하는데, 첫 복사가 자동 전진으로 작업점을 옮겨 두 번째가 **확인하지 않은 카드**를
클립보드에 쓴다(이동도 같은 틈을 만든다). 잠금으로 풀지 않고 **결속**으로 풀었다:
`copy_precheck` 가 그 카드의 정체(작업점 + 지금 규칙)를 토큰으로 돌려주고 브리지가 쓰기 전에
대조한다 — 어긋나면 쓰지 않고 stale 로 재진술한다. `confirmed_text` 와 같은 규율이고, 잠금은
DOM 이 지므로 상태로 푸는 쪽이 이 저장소의 문법이다(RC-02 「확인 대상 = 생성 대상」의 복사 판).

**게이트**: 2189 passed(신규 8) · 실 WebView2 selftest 72 · 실앱 순회 재완주 · 확인 원장
+1(수기 값 덮어쓰기 — 공용 동사를 채택하며 **따라온** 게이트라 순증이 아니라 회수다).

**3라운드 결산**: 1R·2R·3R 의 P1·P2 10건이 전부 한 줄기였다 — **정본이 아닌 것을 들었다**.
1R 은 Job **사본**, 2R 은 파생값의 **래치**, 3R 은 동사의 **손복사**. 매 라운드 그 층을 하나씩
지웠고, 남은 것은 정본(레지스트리·파생·공용 동사)뿐이다. 4라운드가 또 같은 줄기를 내면
그때는 설계 교체를 검토한다(정지 규칙 §8.1 4항).

#### 10.15.8 리뷰 4R — 등록만 되고 아무도 못 부르는 seam (P2 3건, P1 0)

3R 의 거울상이다. 3R 은 **소비자가 있는데 규약이 틀린** 자리였고, 4R 은 **규약이 있는데
소비자가 없는** 자리다 — 둘 다 「표면과 백엔드가 한 벌로 옮겨지지 않았다」의 두 방향이다.

| 등록된 것 | 소비자 | 결과 |
|---|---|---|
| `last_copy.stamp_error`(스냅샷 키) | 없음 | 복사는 됐는데 최근 사용 기록이 실패해도 **무조건 성공 문안** |
| `workbench/set_target_font` | 없음(「기안」에만 있음) | 정렬 린트가 **그 선언**으로 비례폭을 판정하는데 이 화면에서 고칠 수 없다 |
| `workbench/set_current` | 없음 | 순차 이동만 남아 **아는 행으로 바로 갈 길이 없다** |

F7 판정 K 가 이미 같은 말을 해 뒀다: *"열거값을 만들어 두고 아무도 안 쓰면, 나중에 그 자리에
배선을 빠뜨려도 아무 테스트도 울지 않는다."* 그때는 진입 사유의 **배제 선언**으로 그 규율을
지켰는데, F6 은 세 자리에서 그 반대(배선 없이 등록)를 했다.

**근본 조치 — 가드의 반대 방향을 세운다.** 1R 이 세운 정적 가드는 *프런트가 보내는 것*이
스키마와 맞는지를 봤다(3R 결함류). 여기에 *등록된 것을 프런트가 부르는지*를 더해 짝을
맞춘다(`test_every_registered_action_has_a_frontend_consumer`). 적용 범위는 **자기 화면
파일 하나가 자기 액션을 전부 부르는 화면**(현재 작업대)으로 좁혔다 — 나머지는 공용
팩토리가 화면을 **변수**로 받아 정적 귀속이 성립하지 않고, 거기까지 억지로 세면 거짓
실패가 쏟아져 가드가 무뎌진다. 대신 그 범위 안에서는 **예외를 두지 않는다**(양성대조 확인:
배선 한 줄을 떼면 운다).

`stamp_error` 는 액션이 아니라 스냅샷 키라 같은 가드로 잡히지 않는다 — 회귀로 못박았다.

**게이트**: 2192 passed(신규 5) · 실 WebView2 selftest 72(글꼴 값·큐 색인 되읽기 추가) ·
실앱 순회 재완주.

**정지 규칙 §8.1 4항 판정**: 4라운드다. 다만 **심각도는 단조 감소**했고(P1 2→1→1→**0**)
이번 3건은 전부 「도달 못 하는 손잡이」이지 **잘못된 거동이 아니다**. 1R~3R 이 지운 것은
정본이 아닌 층(사본·래치·손복사)이었고 그 줄기는 4R 에서 재발하지 않았다. 그래서 설계
교체가 아니라 **가드 보강 + 머지 판단**으로 넘긴다 — 사람 확인 사항으로 올린다.

#### 10.15.9 리뷰 5R — 정체를 묶어도 시간을 안 묶으면 창이 남는다 (P1 1 · P2 3)

**P1 은 3R 픽스가 연 창이다.** 3R 은 「확인 대상 = 복사 대상」을 토큰으로 묶었지만 대조와
쓰기 **사이를 잠그지 않았다**: 브리지가 「대조 → 렌더 → 쓰기 → 전진」을 네 걸음으로 밟는
동안 두 호출이 겹치면 둘 다 같은 토큰으로 통과하고, 앞선 호출이 자동 전진으로 작업점을 옮긴
뒤 뒤선 호출이 **새 카드**를 복사한다. 정체(공간·이름)를 닫아도 **시간** 축은 따로 닫아야
한다 — F3 4R 이 존 세대(`zone_epoch`)에서 배운 것과 같은 축이고, 이 PR 에서 두 번째다.

**근본 조치 — 거래의 소유권을 옮겼다**(패치가 아니라 설계 교체). 복사는 이제 컨트롤러의
`copy_to(token, write)` **한 임계구역**이다: 대조·렌더·OS 쓰기·큐 전진이 한 잠금 안에서
일어나고, 브리지는 클립보드 쓰기 **함수만** 건넨다. 겹친 두 번째 호출은 잠금에서 기다렸다가
바뀐 작업점 때문에 토큰 대조에서 걸린다. 뿌리는 「브리지가 상태 있는 컨트롤러를 가로질러
read-modify-write 를 네 걸음으로 밟았다」였고, 그건 저장 경로에서 이미 `registry.write_lock()`
으로 닫아 둔 것과 **같은 부류**다 — 복사만 그 규율 밖에 있었다.

**P2 3건**:

- **확정은 복사되는 문자열의 축이기도 하다.** 무결속·미확정 행은 `live_profile` 에서 빠져
  토큰이 `{{이름}}` 그대로 복사되고, 확정하면 확정-비움이 되어 빈 문자열이 된다. 2R 에서
  "확정을 켜도 문장은 그대로"라고 **단정**한 것이 틀렸다 — 계약(`live_profile` 문서)이 반대로
  적고 있었는데 읽지 않고 추론했다. 지문에 `confirmed` 를 담는다.
- **템플릿이 사라지면 버튼이 먼저 정직해야 한다.** 진입 게이트가 데이터·선택만 세서, 삭제된
  템플릿에도 「검토·복사 시작」이 열린 채였고 누르면 `read_text` 예외가 `.then` 밖으로 나가
  **아무 설명 없이 아무 일도 안 난 것처럼** 보였다. 게이트에 템플릿 가용성을 더하고, 진입
  실패도 예외 대신 사유를 돌려준다(둘 다 필요하다 — 판정과 진입 사이에도 파일은 사라진다).
- **다시 확인 대기도 미완이다.** 전건 복사 뒤 규칙을 고쳐 저장하면 복사 진행도(전건이라)
  미저장 변경도(저장했으므로) 없어 이탈 가드가 침묵했다. 그 문서들은 지금 규칙의 산출물이
  아니므로 가드가 그 건수를 센다.

**게이트**: 2197 passed(신규 5, 양성대조 2 — 잠금을 떼면 겹침 테스트가 운다) · 실 WebView2
selftest 72 · 실앱 순회 재완주.

**커밋 3·4 는 계획서의 순서를 뒤집었다** — 커밋 2 가 TXT 를 후보로 만드는 순간
`RunViewModel` 진입 가드(hwpx 전용)에 부딪히기 때문이다. 즉 **세션 분기가 구획보다 먼저
서야** 중간 상태가 정직하다: 후보에 뜨는데 고르면 터지는 커밋을 남기지 않는다. 표면 신설과
세션 분기를 한 커밋에 묶는 것도 같은 이유다(F1 커밋 2·F2 PR-B 커밋 2 선례 — 두 벌이 공존할
수 없는 자리는 한 전이 안에서 먼저 서고 그다음 죽는다).

#### 10.15.10 리뷰 6R — 매체가 다른데 같은 문장을 쓰면 화면이 거짓말한다 (P1 10)

**한 라운드 최다(10건)이고, 전부 「TXT 를 합류시켰다」의 미완이다.** 두 축이었다.

**① TXT 가 hwpx 스냅샷 형상을 매체 분기 없이 물려받았다.** 파일을 만들지 않는 작업에
「문서 N건 생성 · 저장 폴더」가 서고, 폴더 피커가 살아 있고, 본문 거울은 행을 다 고른 뒤에도
「행을 선택하면 …」이라 말하고, 복사 1건이 라이브러리에서 「최근 실행」으로 집계됐다.
**조치의 축은 「어디서 갈리는가」다** — 분기 근거를 Python 이 낸 `run_action.key` 하나로 모아
표면이 매체를 다시 읽지 않게 하고, 최근 사용 문구는 `last_use_label` 단일 출처로 되돌렸다.
판정 A(작업 방식 3값)를 링0에 세워 두고도 **표면이 자기 눈으로 매체를 다시 본 자리**가
남아 있었다는 뜻이다.

**② 작업대 컨트롤러의 세션 위생이 미완이었다.** 원문 보기에서 복사하면 채운 문장이 나갔고
(보이는 것 ≠ 복사되는 것), 템플릿에서 사라진 토큰의 저장 매핑이 사용자가 한 적 없는
「저장하지 않은 변경」으로 서서 저장하면 진짜로 지워졌고, 복사 완료 노트·저장 성공 배너를
아무도 지우지 않아 다른 카드·다른 상태 위에 남았고, `dispatch` 가 자기 핸들러의
`is_query`·`is_no_push` 표식을 안 읽어 **그 표식을 붙인 자리가 죽어 있었다**(4R 의 「등록만
되고 아무도 못 부르는 seam」과 같은 부류가 다른 층에서 재발).

나머지 둘은 **경로 축의 값 열거**였다: 비-UTF-8 템플릿의 `UnicodeDecodeError` 가 5R 이 세운
화면 내 오류 안내를 `except OSError` 밖으로 빠져나갔고, hwpx 도 txt 도 아닌 경로가 된 활성
작업에서 `RunViewModel` 이 재적재·재연결 밖으로 터졌다 → `_seat_kinds` 로 세 값 축을 한
자리에서 센다.

**게이트**: 2206 passed · ruff·pyright 0 · 커버리지 플로어 전 구획 PASS.

#### 10.15.11 리뷰 7R — 잠그는 것은 「복사」가 아니라 세션의 상태 전이다 (P1 1)

**같은 결함이 세 번째다**(3R 토큰 결속 · 5R 복사 거래 원자화 · 7R). 세 번 다 **복사 경로만**
넓혔다 — §10.13.14(F7 PR-A 8R)가 이름 붙인 신호 그대로, 정의가 열려 있다는 뜻이다.

**잠금은 잠금을 잡는 쪽끼리만 배제한다.** `copy_to` 혼자 잠그면 pywebview 의 다른 스레드에서
온 「다음」·매핑 편집·이탈이 렌더와 `note_copied` 사이로 **그대로** 들어온다: 옛 카드로 만든
문자열을 쓰고 새 작업점을 복사 완료로 찍거나, `_do_close` 가 비운 `mapping` 위에서 이미
성공한 복사가 assert 로 터진다(**사용자는 복사를 받았는데 앱은 실패했다고 말한다**).

**조치는 봉합이 아니라 정의 확장**이다: `_copy_lock` → `_state_lock`(RLock). 잠그는 것은
「복사 거래」가 아니라 **이 세션의 상태를 바꾸는 모든 것**이다 — `dispatch`(질의 포함, 전이
중간을 읽지 않게)·`open`·`close`·`copy_to`·`close_guard_reason`(창 종료 훅은 다른 스레드다)이
한 잠금에 참여한다. 잠금 순서는 언제나 `_state_lock` → `registry.write_lock()` 이고 역순
경로는 없다. 회귀 2건은 **실제로 스레드를 띄워** 쓰기 도중 `set_current`·`close` 를 밀어
넣는다(양성대조: dispatch 의 잠금을 빼면 둘 다 떨어진다).

**게이트**: 2208 passed · ruff·pyright 0 · 커버리지 플로어 전 구획 PASS.

#### 10.15.12 리뷰 8R — 순서는 쏘는 쪽에서만 정해진다 (P1 1 · 전 화면 일괄)

**네 번째다**(3R·5R·7R·8R). 앞의 셋은 전부 필요했지만 **끝낼 수 없는 층**이었다 — 잠금은
겹치지 않게 할 뿐 **누가 먼저인지**는 정하지 않는다(먼저 잡는 쪽이 이긴다). pywebview 는
호출마다 별도 스레드라, 한 사용자 동작이 호출 둘로 쪼개지면(blur 가 편집을 쏘고 클릭이
커밋을 쏜다) 순서는 **쏘는 쪽에서만** 정할 수 있다. 증상은 값을 치고 곧바로 복사·이탈할 때
이전 값이 클립보드로 나가거나 편집이 가드에 안 잡힌 채 사라지는 것.

**전수 조사가 규약 부재를 드러냈다**: 작업대 = 체인 0·발신 12개 전부 fire-and-forget ·
「기안」 = `editChain`·`editTargets`·`flushDeb` 를 **다 지어 놓고** 소비자가 `openSaveTpl`
하나뿐(자기 주석이 "복사=전 대상 최신성"이라 적어 둔 그 복사가 안 부른다) · 「문서 만들기」 =
존 변이는 `ZONE_CHAIN` 인데 생성·작업대 진입이 그 체인 밖 · template·data_picker = 변이가
이산적이라 **지금은** 무해(규약이 없어서 안전한 것). 즉 규약을 세운 자리가 없어 화면마다
각자 발명했고 새 화면은 아무것도 승계하지 않았다.

**조치 5단**: ①`Intent.settle(key)` — 「합류하지 않고 큐를 정산한다」를 계약면으로 명명하고
규약을 한 문장으로 세운다 = **같은 상태를 바꾸는 발신은 한 체인, 그 상태를 읽는 커밋은 그
체인을 먼저 정산한다** ②작업대 변이 14자리를 `WB_CHAIN` 하나에 태우고 복사·저장·이탈이
정산 후 진행(래퍼가 아니라 **호출 자리마다** — dispatch 리터럴 가드가 계속 보게, 1R 교훈)
③「기안」 `copyCard`·`confirmNewDraftIfArmed` 가 `flushDeb()` 를 await ④「문서 만들기」
`doGenerate`·작업대 진입이 `ZONE_CHAIN` 정산 ⑤**정적 가드 2종**(핵심) — 커밋이 첫 발신보다
앞에서 정산하는지 · 작업대 변이가 체인 밖으로 새지 않는지. 관문을 지우고 돌려 둘 다 떨어지는
것을 확인했다. **다음 화면이 빠뜨리면 리뷰 라운드가 아니라 이 게이트가 잡는다.**

**게이트**: 2210 passed · ruff·pyright 0 · WebView2 실앱 셀프테스트 72.

#### 10.15.13 리뷰 9R — 계약 미이행 하나와, 여덟 라운드 동안 죽어 있던 게이트 (P2 1)

**P2 1건은 이 PR 이 스스로 정한 판정 E 의 미이행이었다**(§10.15.2 E · 계약 §11): 「작업대는
편집기로 나가는 deep-link 를 갖지 않고 **화면 안에서** 겨눈다」. 그런데 `SegView` 가 토큰
이름을 버리고 칠했고 wbCard 에는 핸들러가 없었다 — 카드도 표도 멀쩡하고 정적 계약은 초록인데
**둘을 잇는 길만 없어** 사용자가 소유 행을 손으로 찾는 상태.

- `segview.js`: 토큰 세그먼트(fill·blank·missing)가 `data-token` 으로 **신원을 지고 나간다**.
  literal 엔 붙이지 않는다(템플릿 원문에는 소유 규칙이 없다). 신원만 싣고 용도는 소비 화면이
  정한다 — 「기안」에서는 무해한 표식.
- `workbench.js`: 행이 안정 id + `tabindex="-1"` 로 **착지점**이 되고, wbCard 위임 클릭이 그
  행을 포커스·스크롤한다. 발신은 없다(어느 조각이 어느 행 소유인지는 세그먼트가 이미 말한다).
- **강조는 포커스 파생**이다: `#wbMapPanel tbody tr:focus` 가 표지를 내므로 표면이 「지금 겨눈
  토큰」을 변수로 들지 않는다. 스냅샷 푸시가 표를 다시 그려도 `Preserve` 가 같은 id 로 포커스를
  되찾고, 포커스가 떠나면 강조도 사라진다 — **늘 참인 파생이라 무효화할 스킴이 아예 없다**
  (`MUTABLE_MODULE_STATE_BUDGET` 의 작업대 몫을 늘리지 않고 끝냈다).

**곁들여 드러난 것 둘**(리뷰가 아니라 조치 중에 나왔다):

1. **작업대 실앱 게이트가 한 번도 돌지 않았다.** `test_workbench_is_immersive_and_the_queue_
   degenerates` 가 앞 모듈 함수 본문 **안에** 들여쓰여 있어 pytest 가 수집하지 않았다 —
   8라운드 동안 몰입 셸·큐 퇴화·이탈 순서를 지킨다고 믿은 가드가 죽은 코드였다.
   **초록은 「지켰다」가 아니라 「묻지 않았다」였다**([[measurement-litmus]] 네 번째 표본).
2. **좌 pane 표가 스타일시트에 없는 클래스였다**(`maptable`). 「기안」과 같은 열·같은 동사·같은
   행 마크업을 쓰면서 클래스만 갈라 둬서 테두리·sticky 머리·`{{}}` 표기·확정-비움 행 표지를
   하나도 못 받고 있었다 — 그 파일 첫 주석이 경고한 드리프트의 실물. `dmap` 으로 통일.

**게이트도 그 규율로 짓는다**: 신원(`data-token` 수)·착지(포커스한 행)·표지(**계산된**
box-shadow) 셋을 실 WebView2 에서 되읽는다. 하나만 빠져도 정적으로는 초록이고, 특히 표지는
클래스↔스타일시트 어긋남을 **계산까지 가 봐야** 잡는다.

#### 10.15.14 9라운드 결산과 착지 표기 (머지 `275dd24`, 2026-07-28)

PR #315 squash **`275dd24`** — 사용자 승인. F5·F3·F4 선례대로 다음 슬라이스에 동승시킬
착지 표기는 이 절 자신이다(6R~9R 정산이 밀려 있던 것을 F6 PR-B 착수 전에 회수).

**라운드별 건수**(실측 — 커밋 제목 기준):

| R | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 계 |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 2 | 1 | 1 | 0 | 1 | **10** | 1 | 1 | 0 | **17** |
| P2 | 2 | 3 | 2 | 3 | 3 | 0 | 0 | 0 | 1 | **14** |

합 **31건**(+ 리뷰 밖에서 우리가 잡은 죽은 게이트 1). 정지 규칙 §8.1 상한(5라운드)을 넘겨
계속한 근거는 F7 PR-A 와 같다 — **6R 이후는 앞 라운드의 재게시가 아니라 신규·독립 결함이었고**,
매 라운드 조치가 다음 라운드에서 같은 가족을 침묵시켰다.

**이 PR 의 서사는 한 축이다**(§10.15.7 이 3R 에서 이미 이름 붙였고, 8R 이 층을 바꿔 닫았다):
P1 다섯 중 넷(3R·5R·7R·8R)이 **「복사되는 것과 확인한 것이 같은가」의 시간 축**이었다.
궤적이 진단을 말한다 — 정체를 묶고(3R) → 거래를 원자화하고(5R) → 잠금을 세션 전이로 넓혔지만
(7R) 셋 다 **백엔드 층**이었고, 백엔드로는 **순서를 정할 수 없다**(8R). 답은 발신 쪽 규약이었다.
이것이 [[bridge-call-ordering-contract]] 로 승격된 규약이고, 지금은 정적 가드 2종이 지킨다.

**남은 두 라운드가 성격이 달랐던 것도 기록해 둔다**: 6R(P1 10)은 **합류의 미완**이었다 —
TXT 를 후보에 넣었지만 화면이 hwpx 형상을 그대로 물려받아 「파일을 만들지 않는 작업」에
생성 어휘가 서 있었다. 9R 은 **우리가 적은 계약의 미이행**이었다(판정 E). 즉 라운드가
길어진 원인은 셋으로 갈린다: ①정의가 열린 축(3·5·7·8R) ②새 매체가 여는 어휘 면(6R)
③계약을 적고 배선을 빠뜨린 자리(9R). ①만 근본 조치로 닫히고, ②는 열거로, ③은 게이트로 닫힌다.

**게이트 최종**: 2211 passed · 실 WebView2 selftest 72 · ruff·pyright 초록 · 커버리지 플로어
8구획 PASS · 101 하니스 14컷 완주.

**F6 PR-B 로 넘어가는 것**(§10.15.4 말미와 동일 — 여기서 다시 못박는다): `draft` 화면 사망과
승계 정산(TXT 작업 생성 = 편집기 「템플릿」 탭 매체 분기 · 라이브러리 `primary_action`
재배선 · 휘발 폐지 고지 3자리) · F5 드로어 행별 「수정」 deep-link(§10.14.3) · 101 하니스
트랙 B 재배선.

### 10.15.15 F6 PR-B 계약 — `draft` 사망·승계 정산 + 드로어 deep-link + 101 트랙 B (2026-07-28)

§10.15.14 말미의 5항목을 진다. 착수 전 실측 하나가 계약의 형상을 정한다: **승계 4종은 이미
작업대에 착지해 있다** — 큐 퇴화(`screen_workbench.py` `queue_degenerate = total <= 1`) ·
T3 가드(`leave_guard`/`close_guard_reason` 의 사유 열거) · 정렬 린트+처방(`lint` 스냅샷 +
`_do_set_fullwidth`·`set_target_font`) · 확정-비움(`gate_empty_fields` + 공용
`mapping_verbs._do_set_confirmed`). 그러므로 PR-B 에 이식은 없고, 지어야 하는 것은
**생성 경로 하나**(편집기 「템플릿」 탭 매체 분기 — 점검표 1행이자 유일한 선행 조건)와
**deep-link 한 축**, 그리고 사망 자체다.

#### 10.15.15.1 `draft` 화면 사망 조건 점검표

전 항목이 새 거처에서 도달 가능함을 확인한 **뒤에만** 화면을 지운다(§10.4 서문).

| # | 도달해야 하는 것 | 새 거처 |
|---|---|---|
| 1 | TXT 작업 생성(템플릿 고르기→매핑→저장) | 편집기 「템플릿」 탭 TXT 밴드(매체 분기) — 행 클릭은 기존 `use_library_template` 재사용, 신규 액션 0 |
| 2 | 저장 TXT 작업 열기 | 라이브러리 `primary_action` = 「문서 만들기에서 사용」 → `job` → 작업대(실행 버튼 2분기는 판정 D 가 이미 진다) |
| 3 | 승계 4종(큐 퇴화·T3 가드·정렬 린트·확정-비움) | 작업대 — PR-A 착지 실측(위 서문 좌표) 확인만 |
| 4 | TXT 작업 목록(구 좌 목록) | 라이브러리 방식 필터 「온나라 기안」(§10.8.4 7행의 최종 승계처 — 기존재) |
| 5 | TXT 작업 편집(매핑·확정-비움 수정) | 편집기 binding 탭(`open_job_in_editor` 가 txt Job 을 받는다 — 1행의 매체 분기에 포함) |
| 6 | 휘발 세션(저장 없이 채워 복사) | **사망**(결정 2) — 고지 3자리(①문서 만들기 TXT 구획 빈 상태 ②tpl TXT 밴드 ③101 트랙 B)가 대체 경로(저장 TXT 작업 경유)를 재진술하는 것이 조건 |
| 7 | 「템플릿으로 저장」 승격(`save_template`·`promote_info`) | tpl `txt_new` 존치(F8 전까지) — 문안이 그리 가리킨다 |

#### 10.15.15.2 판정

| # | 사안 | 판정 |
|---|---|---|
| A | 고지 ① 표시 술어 | **txt 템플릿 有 ∧ txt 방식 작업 0건**일 때만 문서 만들기 후보에 빈 「온나라 기안」 구획을 세운다. 순수 HWPX 사용자·이미 TXT 작업을 가진 사용자에게 0 소음, 휘발-기안만 쓰던 사용자에게 정확히 발화. 영속 플래그 없음 — 매 스냅샷 파생(3태 회귀로 양단 고정) |
| B | deep-link 축 | `EditContext.target` 하나: `""` · `binding/<fieldId>` · `filename/filenamePattern` 만, 그 외 fail-closed. 복귀 행 정체성도 이 축에서 파생(`return_context` 에 둘째 축을 만들지 않는다). 착지점은 「변경 저장」 하나 — 「이번 생성에 적용」 배지는 짓지 않는다(§10.14.3) |
| C | `preview_open {at}` — 판정 M carve-out | 드로어 복귀가 같은 `previewIndex` 로 서려면 인덱스가 왕복해야 한다. 방향-only(판정 M)의 예외가 아니라 동류다: `at` 의 출처는 **Python 자신이 push 한 스냅샷 값**(`preview.pos`)의 왕복이고, Python 이 클램프해 권위를 유지한다. 값을 프런트가 짓지 않는다 |
| D | `workbench_result` 배제 | 거절 유지 — 사유 문안만 「F6 소관」에서 **영구 배제**(판정 E: 작업대는 인라인 필드 연결 편집을 승계했으므로 편집기로 나가는 deep-link 를 갖지 않는다)로 갱신 |
| E | `TargetFontSetting` 거처 | `draft_session.py` 사망 시 유일 생존 소비자인 `screen_workbench.py` 로 이동. 영속 키 `draft_target_font` 는 **그대로**(개명 = 마이그레이션 비용만 사고 얻는 게 없다) |
| F | `toggle_library_group` | 편집기 라이브러리가 매체 2밴드가 되므로 `_schema("group")` → `_schema("group", "media")` 확장 — 신규 액션 대신 기존 액션의 키 확장 |

#### 10.15.15.3 커밋 경계 (직렬)

| 커밋 | 내용 |
|---|---|
| 1 | 이 절(사망 점검표·판정 6건) |
| 2 | 편집기 「템플릿」 탭 TXT 매체 분기(점검표 1·5행) + selftest 프로브 |
| 3 | 라이브러리 `primary_action` 재배선(점검표 2행) — 이후에도 `draft` 는 레일로 도달 가능한 병존 과도기 |
| 4 | 휘발 폐지 고지 ①②(판정 A) |
| 5 | F5 드로어 행별 「수정」 deep-link(판정 B·C·D) |
| 6 | 101 트랙 B 재배선 + README(고지 ③) — 재촬영과 README 는 같은 커밋(1:1 게이트) |
| 7 | `draft` 사망을 **한 전이로** — 이주(판정 E·`job_list` 축소·`copy_clipboard` 단일화) 먼저, 삭제 그다음 / 게이트·계약 문서 정산 동반. 잔존 참조 grep 0건이 커밋 조건 |
| 8 | 점검표 전 행 「도달 확인」 기입 + 최종 게이트 |

101 게이트 파손 창이 없도록 사망(7)은 트랙 B 재배선(6) **뒤에만** 온다 — 하니스는 오늘
「기안」 화면을 몬다(§10.15.4).

#### 10.15.15.4 착지 정산 (2026-07-28)

**사망 점검표 7행 전부 도달 확인 후 화면 삭제**(§10.4 서문 이행):

| # | 도달 확인 |
|---|---|
| 1 | 편집기 TXT 밴드 → `use_library_template` → 2탭 세션 → 저장(실앱 selftest `editor_txt_band` + 101 S8 실촬영) |
| 2 | 라이브러리 `primary_action` = 「문서 만들기에서 사용」 → 판정 D 「검토·복사 시작 · N건」 → 작업대(101 S9 실촬영) |
| 3 | 승계 4종 실물 좌표 확인 — 서문 표 그대로(이식 0) + **카드가 `wc-render`·`f-*` 를 실제로 입도록 마감**: 종전 작업대 카드는 대상 글꼴 선언을 받기만 하고 입지 않아 정렬 린트가 선언 기준으로 판정하는데 카드는 다른 글꼴로 그려졌다(선언≠실제 — 이 정산에서 봉합) |
| 4 | 라이브러리 방식 필터 「온나라 기안」 기존재(F6 PR-A) — 도달 확인만 |
| 5 | `open_job_in_editor` 가 txt Job 을 받는다(`test_txt_draft_saves_without_pattern_gate_and_reopens_with_two_tabs`) |
| 6 | 고지 3자리 실재(①`_txt_onboarding_note` 3태 회귀 ②tpl `txt["notice"]` ③101 README 트랙 B) — 상시 배너·다이얼로그·영속 플래그 없음 |
| 7 | tpl `txt_new` 존치·TXT 카드 ⋮ 는 「이 서식으로 새 작업」(makeJob 매체 무관)으로 재배선 — 구 「기안 시작」(휘발)은 화면과 함께 사망 |

**사망 표면**: `screens/draft.js`·`draftsession.js`·`screen_draft.py`·`draft_session.py`·
`gui/txt_state.py`·레일 임시 항목·`#scr-draft`·기안 모달 5종(paste/move/saveTpl/mapSheet/
rowMenu)·draft CSS·테스트 3파일(148건). 잔존 참조 grep 0건(가짜 양성 허용 = `range_draft`
범위 초안·`is_draft`/`_draft_job` 편집 초안·에디터 프로브 JS 변수명).

**이주**(같은 전이 안, 삭제보다 먼저): `TargetFontSetting` → `screen_workbench`(판정 E,
영속 키 불변) · `job_list` → `drift_note` 만 존치 · `copy_clipboard` 비-원자 폴백 걷음
(소비자 0 — `copy_to` 단일 거래, 무거래 화면 호출은 loud) · `draft_collapsed_groups` 삭제.
`mapping_verbs` 소비자 = 작업대 하나(§10.15.10 3R 이 예고한 상태).

**화면이 곁들여 하던 정산**(교훈 §10.9.5 의 이행 — 따로 세었다): ①패키징 `--selfcheck`
스모크가 DraftController 를 몰았다 → 편집기 TXT 분기로 재겨눔(릴리스 스모크 ImportError 를
테스트가 선행 적발) ②selftest 프로브 5계열 재배선(모달 표적 → `txtEditModal` · 실화면
스크롤 e2e → `#editor-body` · 워크카드 재질 → `wbCard` · 15px 역할 표본 → tpl 밴드 머리 ·
`data_picker` 사어 버튼 제거) ③DOM 계약·datazone 원장을 job 단독으로 재작성 ④dispatch
payload 정적 가드 최소 판독 수 40→**71**(실측 — draft.js 소실분보다 편집기·작업대 증가분이
컸다) ⑤101 재촬영(기안 탭 없는 최종 상단바).

**게이트 최종**: 2055 passed · 실 WebView2 selftest **70** · ruff·pyright 초록 · 커버리지
플로어 8구획 PASS(webapp 86.50/86 — 예고했던 출렁을 WU-1 신규 분기 커버가 완충) ·
101 하니스 14컷 완주. deep-link(§10.14.3)는 판정 B·C 대로 착지(EditContext.target 한 축·
`preview_open {at}` 클램프)했고 작업대 배제 선언(판정 E 문안 영구화)은 정적 핀이 지킨다.

### 10.16 매체 전환 기각 — 템플릿 선택이 곧 경로 선택이다 (2026-07-28, 사용자 확정)

대조표 **24행**(템플릿 바꾸기 4단계·작업 방식 전환·`dormantFilenamePattern`)과 그 근거인
계약 **§19.9 매체 전환분·§19.11 불변식 16~18·S5 `screen-transition` 화면**을 **기각**한다.
F8 착수 계약을 쓰기 전에 실측한 결과, 전환이 겨눌 시나리오가 이 제품에 존재하지 않았고
전환이 약속한 값(이력 유지)이 오히려 이력을 거짓으로 만들었다. §10.14 와 같은 형태의
기각이며, 같은 리트머스([[contract-item-litmus]])의 두 번째 적용이다.

**사용자 확정(2026-07-28)**: *"잘못 만들었다는 걸 인지하면, 당초 선택 실수이므로 삭제하고
다시 만들라는 것. 친절한 방향은 아니지만 가끔 있는 일을 위한 배려로는 구현 비용이 너무 크다."*

#### 10.16.1 실측 근거 4

**① 「업무 형식이 바뀐다」는 시나리오가 없다**(사용자 확정). 전환이 겨눌 수 있는 상황은 셋뿐이다:

| 시나리오 | 실재 | 답 |
|---|---|---|
| A 실수 복구(템플릿을 잘못 골랐다) | 있음 | 아직 이력이 없다 — 삭제 후 재생성으로 족하다 |
| B 같은 데이터로 두 산출물(공고서 + 기안) | 있음 | **전환이 아니라 두 작업**이다. 둘 다 계속 살아야 한다 |
| C 업무 형식 자체가 바뀜(hwpx 서식 → 온나라 기안) | **없음** | — |

**② convert 의 유일한 정당성(이력 유지)이 이력을 위조한다.** `Job.last_run_at` 은 저장 필드가
하나이고 **그 뜻은 현재 매체가 정한다**(`gui/work_mode.last_use_label` — HWPX=생성 완주 /
TXT=복사 완료 1건). 매체를 바꾸면 100건 생성 완주가 「마지막 복사」로 표시되고, 역방향에선
복사 이력이 「마지막 성공 실행」이 된다. 후자는 §19.4 최근 사용 순위와 F5 검토 기준선이
소비하므로 **추천 순위까지 오염**된다. 즉 계약 §19.9 convert 행(「이력 유지」)이 §19.4(매체마다
술어가 다르다)와 정면으로 부딪친다 — **계약 내부의 모순**이고, §10.15.10(6R P1 10건 「매체가
다른데 같은 문장을 쓰면 화면이 거짓말한다」)과 같은 가족이다.

**③ fork 는 이미 있다 — 새 기제가 아니라 기존 두 동사의 합성이다.**

| 계약 「새 작업으로 만들기」 | `JobRegistry.clone` |
|---|---|
| 새 work identity 생성 | ✅ `'<이름> (복사본)'` 유일 이름 |
| group·tags 복사 | ✅ 계승 |
| 즐겨찾기·`last_run_at` 미복사 | ✅ `favorited_at`·`last_run_at` 초기화(+F5 `reviewed_rules` 도) |
| 기존 작업·Binding 불변 | ✅ 원본 무변경 |

계약이 요구한 형상이 한 항목도 어긋나지 않는다. fork = `clone` + `relink` 이고, 그 규율은
이미 코드 주석이 적어 두었다 — *"복사본은 아직 실행된 적도 사용자가 고른 적도 없다는 사실을
그대로 말하게(조용한 이력·우선순위 위조 금지)"*.

**정정(리뷰 3R P2)** — 이 합성은 판정 C 게이트 이후 **같은 매체 안에서만** 성립한다(clone 은
`template_path` 를 보존하고 교차 relink 는 거절되므로 clone(HWPX)→relink(.txt) 경로는 없다).
그리고 그거면 된다: 시나리오 B 의 둘째 산출물은 fork 가 아니라 **그 매체의 템플릿으로 새 작업
생성**이 정도다 — 매핑은 매체를 못 넘는다(매핑의 키가 템플릿 필드인데 hwpx 필드명과 txt
`{{토큰}}` 은 다른 이름 공간이고, 설령 실어 가도 드리프트 게이트가 전면 재확정을 요구해
계승분이 0 이다). 계승할 실물은 데이터 참조뿐이고 그것은 새 작업 생성 경로가 이미 준다.
fork 의 실사용처는 같은 매체 안 재사용(서식 변형·다음 회차)이고 그 경로는 게이트 후에도
온전하다. **매체 전환은 복제와 같은 부류다** — 어느 쪽도 새 기제를 정당화하지 않는다.

**④ 남는 A(실수 복구)에는 이력이 없다.** 잘못 고른 직후는 `last_run_at == ""` 이라 ②의 위조가
발생하지 않고, 잃을 매핑도 거의 없다. 가끔 있는 실수를 위해 4단계 마법사·`templateTransitionDraft`·
`dormantFilenamePattern`·전용 무효화 규칙을 짓는 것은 ROI 가 서지 않는다.

#### 10.16.2 판정 5건

**A. 작업 방식은 생성 시점에 정해지고 바뀌지 않는다.**

> **템플릿 선택이 곧 경로 선택이다. 같은 길 안에서는 서식을 바꿀 수 있고, 길을 바꾸려면
> 작업을 다시 시작한다.**

이는 새 규칙이 아니라 **링0 불변식 1**(작업 방식은 `template_path` 확장자에서**만** 파생)의
UI 층 귀결이다. `Job.media` 는 저장 필드가 아니라 파생 속성인데 `relink` 만 그 파생의 **원천**을
사후에 갈아치울 수 있게 열려 있었다 — 결함의 뿌리는 「기능 미구현」이 아니라 **모델과 어긋난
구멍**이었다. 그래서 조치는 신설이 아니라 **좁힘**이다.

**B. 대조표 24행·S5 화면·§19.9 매체 전환분·불변식 16~18 은 사망한다.** 불변식 15(다른 작업
방식의 템플릿은 안내와 명시적 선택 없이 적용되지 않는다)는 기각이 **아니라 더 강하게 이행**된다
— 안내 + 명시적 선택보다 차단이 상위다.

**C. 게이트는 3분기다** — 「템플릿을 못 바꾼다」가 아니다.

| 상황 | `template_path` | 판정 |
|---|---|---|
| 미연결 작업의 첫 연결 | `""` | **허용** — 아직 길을 고르지 않았다(`require_hwpx` 의 「빈 경로 = 통과」와 같은 규율) |
| 같은 매체 재연결 | `.hwpx` → `.hwpx` | **허용** — #67 의 「파일 이동·삭제로 끊긴 연결 복구」. 길은 그대로고 서식만 바뀐다 |
| 매체 교차 | `.hwpx` → `.txt` | **거절** — 다른 길이다. 문안이 「삭제 후 새로 만들기」를 지목한다 |

이로써 `relink` 의 의미가 **「복구 동사」 하나로 좁아진다**. 종전엔 복구와 작업 방식 변경을
겸했고, 그 겸직이 이력 위조·재착석 방어 코드·`dormantFilenamePattern` 요구의 공통 뿌리였다.

**D. 매체 교차 경로는 둘이고, 둘째는 F6 PR-B 가 열었다.**

| 경로 | 오늘 거동 |
|---|---|
| ① `relink_template` | 파일 필터의 「모든 파일」로 `.txt` 선택 가능. 확인 문안이 **매체 변화를 한 글자도 말하지 않는다** |
| ② 편집기 저장의 **「남의 자리 덮어쓰기」** | TXT 초안을 기존 HWPX 작업 이름으로 저장하면 `_preserved_for_target` 이 **victim 의 `last_run_at`·`favorited_at`·`reviewed_rules` 를 보존** → 같은 위조가 재현. 저장 경로에 매체 검사가 없다 |

②는 PR-B 이전엔 편집기가 hwpx 만 만들어 **불가능했던 경로**다. 규칙으로 적으면:
**새 매체를 한 표면에 들이면 그 표면의 기존 동사들이 품고 있던 매체 가정도 함께 세어야 한다**
(§10.15.10 6R 이 화면 문안에서 밟은 것의 저장 경로 판).

**E. 되깎기 — 열린 문이 낳은 방어 코드를 함께 회수한다.** 「매체 교차가 가능하다」는 전제 하나가
코드·docstring·아키텍처 등재·회귀에 퍼져 있었고, 전제를 지우면 넷이 같이 걷힌다.

| 자리 | 조치 |
|---|---|
| `screen_job._reload_active_job` 매체 교차 재착석 분기 | ~~삭제~~ → **역할 좁힘 존치**(리뷰 1R P2 정정): 옛 역할(교차 방어)은 게이트가 원천 차단해 죽었지만, 게이트가 **허용**하는 복구 전이(미상 `.docx` → 라이브러리 relink 로 기지 매체)가 같은 분기를 실물로 쓴다 — 지우면 화면이 유효해진 템플릿을 재선택 전까지 unsupported 로 주장한다. 지문 대조는 unsupported 세션(vm 없음)을 못 보므로 대체 불가 |
| `core/job.require_hwpx` docstring 「매체 교차 relink 는 예외」 | 삭제 — 예외 없는 가드 |
| `test_architecture` 허용 소비자 등재 사유 | 「매체 교차 재확인」 → 「같은 매체 드리프트 재확인」 |
| `test_webapp_job.test_cross_media_relink_reseats_the_active_session` | **반전** — 「갈리면 재착석한다」 → 「교차는 거절된다」(자리 불변). 재착석 쪽 회귀는 복구 전이 판으로 존치(`test_recovery_relink_reseats_the_active_session`) |

정정의 교훈(1R): 「죽은 코드」 판정은 그 코드가 받치던 전이 목록에서 **이번 변경이 새로
연 전이**(미상 구작업 복구 — 게이트 3분기의 통과 갈래)까지 세어야 한다 — 같은 커밋이
문을 좁히면서 열어 준 갈래가 그 방어 코드의 새 소비자가 된다.

#### 10.16.3 후속 규칙 — 파생의 원천을 바꾸는 동사는 그 파생이 결정한 전부를 바꾼다

`media`·`work_mode` 처럼 **파생 속성**이 화면 분기·문안·순위·게이트를 결정하는 자리에서,
그 파생의 원천(`template_path`)을 바꾸는 동사를 열어 둘 때는 「원천이 바뀌면 무엇이 거짓이
되는가」를 **먼저** 센다. 답이 이력·순위·문안처럼 **되돌릴 수 없는 기록**이면, 동사를 좁히는
쪽이 방어 코드를 얹는 쪽보다 싸다 — 이 슬라이스에서 좁힘 한 번이 방어 코드 4곳과 미구현
기능 3종(마법사·draft 상태·dormant 패턴)을 동시에 없앴다.

### 10.17 F8 착수 계약 — `tpl` 흡수·사망 + 셸 2탭 최종 착지 (2026-07-29)

마지막 슬라이스. 착수 실측에서 대조표 25행(시험 탭)이 기각돼(§10.17.1) 범위는 **한 주제**로
좁아졌다: `tpl` 화면의 흡수 완결과 사망, 그리고 그 사망이 완성하는 셸 2탭 최종 형상. 기반
`02471c3`, 단일 PR, 화면 사망 양식은 §10.15.15(F6 PR-B)를 따른다.

#### 10.17.1 대조표 25행 「시험 탭」 기각 — 「없음」 행 리트머스 3번째 적용 (사용자 확정 2026-07-29)

> *"Template r / Binding r 은 있을 이유가 없어보이고 (변경 회수로는 변경 내용을 복원할 수
> 없음), 미리보기 생성·승인도 마찬가지. 어차피 돌아가서 확인할 것."* — 이 잣대를 다섯 지표에
> 일관 적용하고 실측한 결과, **전체 기각**.

§10.14.4 후속 규칙(「master 대응물=없음」 행일수록 먼저 실측한다)의 3번째 적용 표본이다
(1번째 = 23행 `runOverrides`, 2번째 = 24행 템플릿 바꾸기). v6 시험 탭의 여섯 성분 전부가
다른 층에서 이미 풀려 있었고, 이번엔 지을 이름조차 남지 않았다:

| v6 성분 | master 의 실제 소유자 | 판정 |
|---|---|---|
| 현재 validation | 게이트(`GateState`·`RunStatus`) — fail-closed, 복귀 착지점이 표시 | 편집기 거울은 run-context 판정의 **두 번째 표시 자리**만 만든다(§10.12 판정 E 의 경고 그대로) |
| Template r / Binding r | 편집기 page-head 저장 상태줄·실행 증거·F5 드로어(§10.13 판정 O 의 셋) | 회수 숫자 단독으로는 변경 내용을 복원할 수 없다 — 무엇과 병치될 때만 정보이고 그 병치 자리는 이미 셋 있다 |
| 미리보기 생성·승인 | F5 드로어 세션 상태 + `ReviewRequirement`(게이트 서열 warn) | 승인 무효화는 게이트가 시끄럽게 잡는다 — 어차피 돌아가서 확인한다 |
| 대표 샘플 | 「필드 연결·표시」 탭 필드별 미리보기 열 + 레코드 스테퍼(`editor.js` mappingStage) + 파일 이름 `pattern_preview` | v6 샘플 한 줄(이름·날짜·파일명)의 **상위 호환이 편집 자리 인라인**에 기존재 |
| 「이 변경으로 미리보기 만들기」 | — | 저장 없이 실제 생성하는 경로는 §10.14 가 기각한 override 출구의 부활이고, 저장 후 생성은 job 화면에서 이미 도달 가능(F4 재시도 기각과 같은 논리) |

v6 가 시험 탭 하나에 담은 것을 master 는 이미 해체 흡수했다 — **앞을 보는 정보(초안의
효과)는 각 section 탭이 편집 자리에서 직접, 뒤를 보는 상태(검증·승인)는 복귀처 게이트가
경보로**. 계약 §3.1/§3.2 의 탭 목록(HWPX 4·TXT 3)과 달라지는 자리이나, §10.0 의 규칙대로
이미 확정된 개정분(§10.14 의 override 기각·§10.12 판정 E)이 계약 원문보다 우선한다 —
최종형은 HWPX 3탭(템플릿·필드 연결·표시·파일 이름)·TXT 2탭이다.

**죽은 예약의 정산**(빈 자리를 남기지 않는다): `gui/edit_session.py` `SECTION_TEST` 상수와
"F8 소관" 주석, `web/js/screens/editor.js` `SECTION_TITLES` 의 `test` 라벨과 예고 주석 —
F7 이 파 둔 홈이므로 F8 이 걷는다. §10.13 판정 A·§10.12 판정 E·§10.5 후속 항목표·대조표
25행은 취소선 + 이 절 지목으로 정정했다.

#### 10.17.2 판정 (착수 확정 5건)

**A. §10.4.1 406행 흡수처 재지정 — 편집기 「템플릿」 탭 단독.** 원표가 지목한 흡수처 절반
(`screen-transition` pick 단계)은 §10.16 이 화면째 기각·사망시켰다. 남는 실물 흡수처는
편집기 「템플릿」 탭 후보 목록 하나이고, 그 목록은 이미 tpl 과 **같은 그룹 모델·같은 링1
인스턴스**(`app.py` 가 `tpl_ctrl.vm`·`hwpx_groups`·`txt_groups` 를 편집기에 공유 주입)를
소비 중이다 — 옮길 데이터 축은 없고 세울 것은 관리 동사의 어포던스뿐이다.

**B. 채널·소유권 — F1 선례(화면은 죽고 `tpl` 채널·컨트롤러·12액션 생존).**
`TemplateController` 의 실질은 잠금 규율(`_import_lock`·`write_lock` 임계구역)·경로 검증
(`_live_paths`)·30일 휴지통·그룹 모델 소유다. EditorController 로 이전하면
`test_webapp_template.py` 와 이 규율 전부가 이사하고 얻는 것은 이름 하나 — §10.14.4
리트머스 탈락. F2 PR-B(표면 없는 파괴 동사는 채널에서 사망)와 다른 점: 여기선 흡수 표면이
실재하므로 동사는 산다. 프런트는 editor.js 가 **명시 리터럴** `Bridge.call("tpl", …)` 로
호출(F1 의 data_picker→pool 동형)하고 `Bridge.onPush("tpl", …)` 를 구독한다 — 핸들러는
①`result` 캐시(결과 재진술 줄) ②`Bridge.initial("editor")` 재당김. **목록의 정본은 계속
editor 스냅샷이다**(성형 두 벌 금지); tpl 스냅샷에서 소비하는 것은 `result` 하나. tpl
스냅샷 중 고지②(`txt["notice"]` — 소스가 스스로 F8 사망을 명시)만 생산·소비·게이트 동반
사망하고, 고지①(job `txt_note`)·close_guard 배제 표·selftest 액션군 왕복
`['template','tpl','refresh']`·`test_webapp_template.py` 는 존치한다.

**C. 가져오기 통일 — 이 슬라이스의 유일한 의미 변경.** 가져오기는 이원화돼 있었다: 편집기
`import_template_file` 은 `_TEMPLATE_FILTERS`(hwpx 전용) + RAW 선거부, tpl
`import_library_template` 은 `_LIBRARY_IMPORT_FILTERS`(hwpx·txt) + RAW 수용. §10.4.1
407행의 "F7 착지"는 절반만 참이었다. 통일: 편집기 「가져오기…」가 `_LIBRARY_IMPORT_FILTERS`
를 쓰고 **복사 권위는 `TemplateController.import_into_library` 하나로**(잠금·충돌 접미
유지). 사본이 세션 시작 가능하면(hwpx 누름틀 有 / txt 판독 가능) 곧바로
`new_job_session`(F7 거동 보존), 아니면(RAW·손상) 목록 추가 + notice 가 수선 경로를
지목한다("행 ⋮ → 누름틀로 변환"). 편집기의 종전 RAW 선거부 근거(인앱 삭제 어포던스 부재 →
영구 오류 행)는 이 슬라이스가 행 ⋮ 삭제를 들이면서 **소멸**한다 — 근거가 죽으면 가드도
걷는다. `import_library_template` 브리지 메서드는 소비자 0 이 되므로 js_api·bridge.js 에서
제거한다(표면 없는 통로 금지 — F2 PR-B `set_rail_collapsed` 선례).

**D. 흡수 형상 — 선택 전용 피커를 완전한 라이브러리 관리 표면으로.**
- 상단 행동 줄(`.tpl-libbar` 승계): `[가져오기…] [새 TXT 템플릿…] ─ [새로고침]`.
- 행 ⋮ 메뉴(`GroupList.createMenu`·`#tplRowMenu` **재사용, 이식 아님** — F2 교훈 ④):
  HWPX 행 = 링1 상태 동사(`compile`·`review`, 라벨은 `_STATE_ACTIONS` 소유, `make_job`·
  `preview` 제외) → 그룹 이동 → 삭제(danger). TXT 행 = 내용 편집 → 그룹 이동 → 삭제.
  오류·손상 행에도 ⋮(삭제 도달성 — F1 ⓒ와 같은 뿌리). **소비 동사는 ⋮ 에 넣지 않는다** —
  행 「이 템플릿으로」 버튼이 이미 소유, 같은 동사 2벌 금지(§10.5 판정 단일 출처).
- 그룹 헤더 ⋮(명명 그룹만): 이름 변경(병합 확인 왕복)·해산(확인 왕복). ＋그룹지정 칩은
  「그룹 없음」 행에만 → `createMoveDialog`(`#tplMoveModal` 재사용).
- `_library_snapshot` 확장: 밴드별 `group_names`·`count`·`dir`, hwpx 행 `actions`·
  `fill_warns`(#154 가시성 유지), 결과 재진술 줄(`#tplResult` 승계).
- TXT 저작: `#txtEditModal` DOM 은 셸 레벨 생존, 소유 JS(template.js 의 열기·dirty 가드·
  제출)만 editor.js 로 이전 — selftest Escape·커스텀 모달 프로브 표적이라 DOM 이동 금지.
- **「이 템플릿으로」의 의미는 불변**: 항상 새 초안 세션(`use_library_template` →
  `confirmNewSessionIfUnsaved` 확인), in-place 교체 아님. §10.16 게이트와 충돌 없음(교차
  게이트는 relink·저장 덮어쓰기에 이미 산다) — **신규 게이트 0, 신규 세션 액션 0**.

**E. 셸 최종 형상 — 임시 탭 제도 자체의 은퇴.** `NAV_SCREENS` 3→2(`library`·`job`),
`TEMP_NAV_SCREENS` 는 빈 튜플이 아니라 **기제째 은퇴**: 임시 표지 강제 테스트는 「`.nav-sep`
0개·`.temp` navbtn 0개·계약 2탭 무예고」의 최종 형상 고정판으로 재작성한다(과도기 기제가
공회전으로 남으면 그게 다음 부활 통로다). `REFRESH_ON_NAV` 에서 `tpl` 제거 — 편집기는 몰입
표면이라 nav 재당김 대상이 아니고, 템플릿 탭 재진입 재스캔이 그 역할을 이미 진다.

#### 10.17.3 `tpl` 사망 조건 점검표 — 전 행 도달 확인 후에만 지운다

| # | 도달해야 하는 것 | 새 거처 | 도달 확인 |
|---|---|---|---|
| 1 | HWPX·TXT 목록·그룹 구획·접힘 영속 | 편집기 템플릿 탭 2밴드(기존재) | ✓ 기존재(F7·F6) + 프로브 `grp_heads`·`rows_visible` 실렌더 |
| 2 | 가져오기(유효 HWPX·RAW·TXT) | 「가져오기…」 통일(판정 C — RAW·TXT 수용 신설) | ✓ 커밋 4 — 채택 3분기 헤드리스(`test_adopt_defers_raw…` 등 3건) |
| 3 | 새 TXT 저작·내용 편집 | 새 TXT 버튼 + 행 ⋮ 내용 편집 + `txtEditModal`(소유 이전) | ✓ 커밋 4 — 프로브 `toolbar`·`txt_menu_items` + opener 가드 병존 검증 |
| 4 | 누름틀 변환 2단계·검토 + 결과 재진술 | 행 ⋮ 상태 동사(링1 라벨) + 결과 줄 | ✓ 커밋 3·4 — 프로브 `hwpx_menu_items`·`result_line` + danger 계약 재겨눔 |
| 5 | 그룹 지정·이동·개명(병합 확인)·해산(확인) | 행 ⋮·칩·그룹 헤더 ⋮(팩토리 공유) | ✓ 커밋 3 — 프로브 `group_menu_items`·`move_shown_after_chip` + 정적 배선 가드 |
| 6 | 삭제(경로 검증·30일 휴지통)·복원 1건 | 행 ⋮ 삭제 + UndoToast | ✓ 커밋 3 — forgiveness 계약 재겨눔(사전 확인 없음 + UndoToast) |
| 7 | 새로고침(외부 FS 재스캔) | 상단 행동 줄 + 탭 재진입 자동 재스캔(기존재) | ✓ 커밋 4 — `lib-refresh` + r3_pool 수동 버튼 계약 재겨눔 |
| 8 | 「이 서식으로 새 작업」(매체 무관) | 행 「이 템플릿으로」(기존재) | ✓ 기존재(F7 `use-library` + `confirmNewSessionIfUnsaved`) — 판정 D 로 의미 확정 |
| 9 | `fill_warns`(#154)·배지 가시성 | 행 배지 title + warn 줄(스냅샷 확장) | ✓ 커밋 3 — 프로브 `fill_warn` 실렌더 |
| 10 | 라이브러리 폴더 경로 표시 | 밴드 캡션 옆 muted mono(스냅샷 `dir`) | ✓ 커밋 3 — 프로브 `band_caption`(개수·경로) |

#### 10.17.4 사망이 곁들여 하던 정산 (§10.9.5 규칙의 전수)

- **15px 구획 타이포 역할 표본**: DOM 계약·프로브가 `.tpl-band .tb-t` 를 표본으로 씀 —
  생존 멤버 `.modal-card h3`(정적 DOM)로 재겨눔(F6 PR-B 가 draft→tpl 로 재겨눴던 그 표본의
  두 번째 이사).
- **selftest 프로브**: ①`_TPL_LIST_GROUP_PROBE_JS` 는 폐기가 아니라 **재작성** — 검증
  대상(그룹 헤더·접힘 뷰 제외·⋮ 구성·칩·이동 다이얼로그 개폐·퇴화 평면)이 전부 편집기로
  살아 이주하므로 합성 editor 스냅샷 기반 `_EDITOR_LIBRARY_MANAGE_PROBE_JS` 로 교체
  ②③Escape·커스텀 모달 프로브 표적 `txtEditModal` 은 DOM 생존이라 재겨눔 불필요(소유 이전
  이력만 주석 추기) ④액션군 왕복 존치(판정 B) ⑤milestone-H 카드 프로브 `.tplcard`→`.jcard`
  재겨눔, H-04(매체 sunken 2면) 은퇴 — 승계 표면인 편집기 밴드는 `.grp` 문법이고 그 시각
  계약은 새 프로브 ①이 잰다.
- **DOM 계약**: `SCREEN_ROOTS` 에서 `scr-tpl` 제거, `NAV_SCREENS=("library","job")`,
  임시 표지 테스트 최종 형상 고정판 재작성(판정 E), 고지② 게이트 ② 절반 삭제,
  `.tplcard` 계약 정리, preserve 상태 원장 editor.js 수치 재실측.
- **CSS**: 사망 = `.tpl-libbar`·`.tpl-medium`·`.tpl-band*`·`.tpl-banddir`·`.tplcard*`.
  생존 = `.tpl-grp-rows`·`.tpl-assign`(칩 이주)·`.ctx-menu`·`#tplRowMenu`·`#tplMoveModal`.
  죽은 CSS 를 남기지 않는다(부활 통로).
- **정적 목록류 테스트**: r3_js·modal_system·interaction_responsiveness·forgiveness·
  danger_confirm(compile 확인·그룹 해산 → editor.js 재겨눔)·ux_copy_round(사망 표에 tpl
  추가)·dispatch_payload(SCREEN_OF_FILE 행 삭제 + 최소 판독 수 재실측)·r3_pool
  (REFRESH_ON_NAV·refresh 가드 재겨눔)·dispatch_wiring(`SCREEN_JS` tpl 행 삭제,
  `CONTROLLERS` 존치).
- **문안 빚**: 셸 title 의 죽은 「템플릿 바꾸기」 지목(탭째 삭제로 해소), 편집기 빈 밴드
  문안("템플릿 관리에서" → 탭 내 실 버튼 지목), `screen_editor.py` RAW 거부 사유문(판정 C 로
  소멸), `docs/UI_CONTRACT.md` 의 `import_library_template` 등재 해제.
- **101 하니스**: tpl 컷은 없으나 상단바 3탭이 전 컷에 찍힌다 — 사망 뒤 전 컷 재촬영·완주가
  완료 조건(§10.9.5).

#### 10.17.5 커밋 경계

| # | 내용 | 게이트 |
|---|---|---|
| 1 | 지도 정산(이 절 + 25행 기각 + §10.4.1 재지정 + 문안 정정 4곳) | 문서 대조 |
| 2 | 시험 탭 죽은 예약 정산(`SECTION_TEST`·`test` 라벨) | grep 0건 + 편집기 pytest |
| 3 | 흡수 1 — 관리 기계(⋮·칩·이동·tpl push 구독·결과 줄·스냅샷 확장) + 헤드리스 테스트 동반 | 헤드리스 + ruff/pyright |
| 4 | 흡수 2 — 저작·상태 동사·가져오기 통일(판정 C) + 문안 | 헤드리스(RAW/TXT 분기) + 전체 pytest |
| 5 | selftest 재배선(프로브 교체·표본 재겨눔) — tpl 병존 시점이라 파손 창 0 | 실 WebView2 selftest 완주 |
| 6 | `tpl` 화면 사망 **한 전이**(DOM·JS·CSS·셸·테스트 일괄) | 잔존 grep 0건 + 전체 pytest |
| 7 | 101 재촬영·README | 하니스 완주 |
| 8 | 점검표 전 행 도달 확인 기입 + 착지 정산 + 최종 게이트 | pytest·selftest·ruff·pyright·커버 8구획·101 |

커버리지 완충(F6 PR-B 결산의 경고 이행): 착수 선실측 = webapp 86%(selftest 게이트 제외
기준), `screen_template.py` 93%·`screen_editor.py` 93%, 삭제 예정 고지②는 커버 라인이라
영향 소폭, 편집기 가져오기 미커버(788·794·805-808)는 커밋 4 재작성이 테스트를 동반해 상승
방향. 신규 파이썬 분기는 같은 커밋에 헤드리스 테스트 동반이 규율.

#### 10.17.6 착지 정산 (2026-07-29 — 커밋 8)

**커밋 실물**: 1=지도 정산 · 2=시험 탭 죽은 예약 · 3=관리 기계(⋮·칩·이동·구독·결과 줄·
스냅샷 확장) · 4=저작·상태 동사·가져오기 통일 · 5=selftest 재배선 · 6=사망 한 전이
(25파일, +160/−765) · 7=101 재촬영+⋮ 노출 회수 · 8=이 정산.

**사망 표면 열거**: `#scr-tpl` DOM·`screens/template.js`(파일)·임시 탭·`.nav-sep`(기제째)·
tpl 전용 CSS(`.tpl-libbar`·`.tpl-medium`·`.tpl-band*`·`.tpl-banddir`·`.tpl-catalogs`·
`.tplcard-more`)·고지②·`empty_hint`·`import_library_template`·`load_template_into_editor`
(둘 다 소비자 0 통로)·`test_template_wayfinding.py`(계약은 승계 표면 테스트가 소유)·
UI_GALLERY 의 `.tpl-medium` 표본·상태 원장 `screens/template.js` 행.

**실측이 착수 계약을 정정한 자리 3**(교훈 — 사망 목록도 소비자 실측이 정본이다):
① `.tplcard` 계열·`.tpllist` 는 **데이터 피커(F1 재사용)가 살아있는 소비자**라 생존 —
"tplcard 전체 사망" 계획을 되깎았다(죽은 것은 tpl 전용 부속 `.tplcard-more` 뿐).
② `Bridge.onPush` 가 **단일 슬롯(덮어쓰기)** 이었다 — 병존 기간 editor 의 tpl 구독이
template.js 렌더러를 조용히 밀어낼 뻔한 자리. 기제 쪽(bridge.js)에서 복수 구독으로 확장
(호출자 규율 아닌 기제 불변식 — F2 교훈 ①).
③ `#txtEditModal` OK·취소의 **이중 배선 경합**: 병존 기간 양쪽 화면이 정적 버튼을 함께
물어, opener 가드(editor `txtEdit`≠null / template `editOwned`) 없이는 남이 연 모달의
클릭에 빈 이름 `txt_new` 가 이중 디스패치됐다.

**눈검증 회수 1건**(101 컷 — §10.9.5 순회의 산물): 행 ⋮ 는 `.job-more` 기본 hidden 인데
`.libselrow` 계열 호버 노출 규칙이 없어 **영영 은닉**이었다 — selftest 프로브의 프로그램적
`click()` 은 hidden 요소를 통과해 못 잡는다(F2 PR-B 1R 「실물이 없던 자리」·관측자 한계
동류). 노출 규칙 + 정적 CSS 가드로 회수.

**곁들인 정산**: R-copy 금지어 표에 「템플릿 관리」 행 추가(죽은 표면 지시 CI 차단 — F1
교훈 이행) · `TXT_RAW_BLOCK` 처방 재지정(행 ⋮ 내용 편집) · 15px 역할 표본 `.modal-card h3`
재겨눔 · 카드 상태 표본 `.jcard` 이주 · `aria-label` 「템플릿 관리」→「항목 관리」.

**게이트 최종**(CI 동형 전체 완주): pytest **2065 passed · 1 failed** — 유일 실패는
**환경성**(selftest short viewport, 모달 높이 0.2px 초과)으로 **순정 `02471c3` 에서 동일
재현 증명**(코드 무관 — F6 의 `test_job_process_topology` 와 같은 부류). 같은 부류였던
workbench `aim_marked` 는 완주 런에서 통과(간헐 — 창 포커스 조건 의존). 커버리지 플로어
**8구획 전부 PASS**(webapp 87.21/86 — 착수 86, 완충 상승) · dispatch payload 최소 판독
**70**(template.js 몫이 editor.js 리터럴로 승계된 뒤 실측) · 101 하니스 **14컷 완주**
(계약 2탭 최종 형상) · ruff·pyright 클린.

**실앱 순회**: 101 하니스 트랙 A·B(실 클릭·실 dispatch·실 생성 3건·실 클립보드)가 사람
순서의 기계판을 완주했고, 관리 동사 면은 editor_lib_manage 실렌더 프로브 + 액션군 왕복
(`['template','tpl','refresh']`)이 실 WebView2 로 덮는다.

## 6. 원재료

- 계약: lab `docs/core-workflow.md` §2·§18.1-§18.11·§19.1-§19.11 (주의: 전역 건강 분리는
  §19.7이다 — 계획 문서의 "§20" 표기는 이 문서 기준으로 정정)
- 시안 계약 테스트: lab `tests/test_core_workflow_v6_prototype.py` 26건(전부 정적 텍스트
  단언 — 통합 브랜치로 가져오지 않고 계약 추출 원재료로만 소비)
- master seam: `gui/run_state.py`·`gui/selection_state.py`·`webapp/screen_job.py`·
  `webapp/data_zone.py`·`webapp/action_registry.py`·`docs/UI_CONTRACT.md`
