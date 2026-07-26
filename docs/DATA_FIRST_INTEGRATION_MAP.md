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
| 8 | 결과 3태(완료/부분/실패)+`결과 닫기`+더보기 | `jobGenResult`+`jobGenLog`(로그 상자) | `generate` 반환 dict·`describe_result_error`·`describe_fill_note` | **재배치** | 3태 구획으로 옮길 때 로그 상자가 지금 말하는 것(FillNote 경고·원문 증거)을 잃지 않는다 | F4 | D·S |
| 9 | 부분 실패 복구(건별 재시도·레코드 filename override·`unknownFailure` 증거·외부 폴더 경계) | 없음 — 실패는 결과 dict + 로그 | `output_conflicts`·`plan_output_names`(집합 검증 상당) | **신설** | §10.2 계약: 성공분 **보존**·원인 미확정은 꾸며내지 않음. `runOverrides` 선행(F7) | F4 | D·U·S·C |
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
| 23 | `runOverrides`(이번 생성에 적용·레코드별 filename) | 없음 | — | **신설** | 기본 저장은 상속 override를 **포함하지 않는다**(§13-15) | F7 | R·U·C |
| 24 | 템플릿 바꾸기 4단계·작업 방식 전환·`dormantFilenamePattern` | `relink_template`(같은 매체 재연결만) | `template_manager_state`(후보 목록) | **신설** | 커밋 전 기존 작업 **전혀 불변**(§19.11-16)·취소는 draft만 폐기·TXT 전환 시 파일명 규칙 삭제 금지 | F8 | D·R·U·S·C |
| 25 | 시험 탭(현재 validation·Template r·Binding r·미리보기 생성·승인) | 없음 | — | **신설** | 판본(22)·승인(16) 선행 | F8 | D·S |
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
Template·Binding 판본·`runOverrides`·`ReviewRequirement`(F-06)·`templateTransitionDraft`·
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
| HWPX·TXT 템플릿 목록·그룹 구획·접힘 (`tpl/toggle_group`·`set_group`) | 편집기 「템플릿」 탭 후보 목록 + `screen-transition` pick 단계(둘 다 이미 그룹 구획 스냅샷 소비 — #108 슬3) | F7·F8 |
| 가져오기 (`import_library_template`) | 같은 템플릿 선택 표면의 `가져오기…` | F7 |
| 새 TXT 템플릿·편집 (`txt_new`·`txt_edit`·`txt_content`) | TXT 작업의 편집기 「템플릿」 탭(원문 편집) | F7 |
| 누름틀 변환·검토 (`compile`·`review`) | 편집기 「템플릿」 탭 — v6 `외부 편집 뒤 변경 확인` + 구조 개요 자리. **v6 에 정확한 대응물이 없는 유일 항목**이므로 문안·행동을 새로 짓되 기능을 줄이지 않는다 | F7 |
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
| F1 | 데이터 선택 다이얼로그 통합(현재/고정한/다른) + 전환 손실 가드 → `pool` 흡수·사망 | 12·13 |
| F2 | 전역 라이브러리 표면(browser+detail) + 상단 2탭 → `home` 흡수·사망 | 14·15·1 |
| F3 | 표시순서 축 + 전문 범위 편집기(`RecordRangeState` 정본) | 4·10 |
| F4 | 결과 3태 + 부분 실패 복구 | 8·9 |
| F5 | 미리보기 드로어 + 검토 요구(승인) | 16 |
| F6 | TXT 합류 + 작업대 → `draft` 흡수·사망(휘발 세션 폐지 고지) | 17·18·19 |
| F7 | 편집기 4탭 + `EditContext`·patch 거래 + 판본 + `runOverrides` | 20·21·22·23 |
| F8 | 템플릿 바꾸기 + 시험 탭 → `tpl` 흡수·사망 | 24·25 |

F7 의 판본·patch 거래는 다른 항목의 전제가 아니다 — 계약 불변식(§13-6·7)이 요구하지만 핵심
흐름은 그것 없이 오늘도 돈다. 실제로 필요해지는 시점(F5 승인 fingerprint·F8 원자 전환)에 당긴다.

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

## 6. 원재료

- 계약: lab `docs/core-workflow.md` §2·§18.1-§18.11·§19.1-§19.11 (주의: 전역 건강 분리는
  §19.7이다 — 계획 문서의 "§20" 표기는 이 문서 기준으로 정정)
- 시안 계약 테스트: lab `tests/test_core_workflow_v6_prototype.py` 26건(전부 정적 텍스트
  단언 — 통합 브랜치로 가져오지 않고 계약 추출 원재료로만 소비)
- master seam: `gui/run_state.py`·`gui/selection_state.py`·`webapp/screen_job.py`·
  `webapp/data_zone.py`·`webapp/action_registry.py`·`docs/UI_CONTRACT.md`
