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

## 6. 원재료

- 계약: lab `docs/core-workflow.md` §2·§18.1-§18.11·§19.1-§19.11 (주의: 전역 건강 분리는
  §19.7이다 — 계획 문서의 "§20" 표기는 이 문서 기준으로 정정)
- 시안 계약 테스트: lab `tests/test_core_workflow_v6_prototype.py` 26건(전부 정적 텍스트
  단언 — 통합 브랜치로 가져오지 않고 계약 추출 원재료로만 소비)
- master seam: `gui/run_state.py`·`gui/selection_state.py`·`webapp/screen_job.py`·
  `webapp/data_zone.py`·`webapp/action_registry.py`·`docs/UI_CONTRACT.md`
