# V6 → master 봉합 계획 (data-first 핵심 워크플로 통합)

**문서 상태: 현재 정본** — 이 문서가 봉합 실행의 앵커다. 각 단계는 이 순서대로 실행하며,
단계를 건너뛰거나 범위를 넓히려면 먼저 이 문서를 개정한다. 워크플로 계약의 정본은
`docs/core-workflow.md`이고, 이 문서는 그 계약을 master 실물로 옮기는 **절차**만 소유한다.

## 0. 대원칙

1. **병합 금지.** `lab/ui-reboot`(이 브랜치)를 master 계열에 merge/cherry-pick 하지 않는다.
   봉합은 *계약 추출 → 수직 슬라이스 구현 → UI 이식*이다. (`CLAUDE.md` 기존 규칙과 동일.)
2. **판정은 Python이 지금, JS는 문안만.** 게이트·호환성·선택·검증·계획은 링0/링1 소유.
   JS가 버튼 활성 여부를 재계산하는 순간 이중 진실이 부활한다 — 이건 이 저장소가
   `GateState`/`RunStatus`(RC-23)로 이미 한 번 봉합한 결함류다.
3. **기존 seam 재사용.** `RunViewModel`·`SelectionModel`·`GateState`·`GenerationPlan`·
   `JobController`·`DataZoneMixin`·`DatasetPoolRegistry`는 재구현이 아니라 재사용 대상이다.
   새 스냅샷은 `GateState` 등 기존 dataclass 모양을 **그대로 방출**한다(새 스키마 발명 금지).
4. **계약 게이트 동반 갱신.** DOM·액션·브리지·스냅샷을 바꾸면 해당 정적 계약
   (`test_web_dom_contract.py`, `action_registry.py`, `docs/UI_CONTRACT.md`)과 동적 계약
   (selftest 시나리오)을 같은 변경 단위로 갱신한다. 정적과 동적은 대체 관계가 아니다.
5. **confirm-or-alarm.** 불확실 시 허용 전이는 확정 요구와 시끄러운 실패뿐. 가드 문안은
   실제로 살아남는/사라지는 집합과 정확히 일치해야 한다.

## 1. 워크트리 역할 고정

실존 워크트리는 둘이고, 통합용 하나를 새로 판다. (조언에 있던 `hwpx-filler-ui-v6`
제3 워크트리는 존재하지 않는다 — 이 랩 워크트리가 그 역할이다.)

| 경로 | 브랜치 | 역할 |
|---|---|---|
| `hwpx-filler/` | `master` | Python 백엔드·현재 제품의 정본. 여기서 통합 브랜치를 판다. |
| `hwpx-filler-ui-reboot/` | `lab/ui-reboot` | **읽기 전용 설계 참고본**(동결 후). v6 시안·계약·시안 테스트의 소재지. |
| `hwpx-filler-integration/` (신규) | `feat/data-first-integration` | 실제 봉합 작업. base=master. |

통합 워크트리에서의 세션은 `--add-dir ../hwpx-filler-ui-reboot`로 랩을 참조만 하고,
랩의 파일을 수정하는 계획은 세우지 않는다.

## 2. 단계 0 — 동결 (이 브랜치에서, 다른 무엇보다 먼저)

v6 산출물(`docs/core-workflow-ui-mvp-demo-v6.html`, `docs/core-workflow-prototype/v6.*`,
`docs/core-workflow.md`, `tests/test_core_workflow_v*_prototype.py`, 이 문서)은 현재
**untracked**다. 실수 한 번이면 증발한다.

```powershell
# lab/ui-reboot 에서
git add -A
git commit -m "chore: v6 워크플로 시안·계약·봉합 계획 동결"
git tag prototype-v6-freeze
# master 에서
git worktree add ..\hwpx-filler-integration -b feat/data-first-integration master
```

이후 `lab/ui-reboot`는 참고본으로만 쓴다(추가 실험은 새 시안 id로).

## 3. 단계 1 — 봉합 지도 (구현 전, 분석만)

통합 워크트리 첫 세션은 **구현 금지, 지도 작성만**. 반드시 직접 읽을 것:

- master: `src/hwpxfiller/gui/run_state.py`, `gui/selection_state.py`,
  `webapp/screen_job.py`, `webapp/data_zone.py`, `webapp/action_registry.py`,
  `docs/UI_CONTRACT.md`, `docs/ARCH_UI_SEPARATION.md`, 관련 테스트
- 랩: `docs/core-workflow.md`(계약 정본), `docs/core-workflow-ui-mvp-demo-v6.html`,
  `docs/core-workflow-prototype/v6.js`, `tests/test_core_workflow_v6_prototype.py`
  — **시안 테스트가 곧 추출된 계약의 원재료**다. 이 파일들 자체는 통합 브랜치로
  가져가지 않는다(HTML 목업을 파싱하므로 랩에 남는다).

산출물은 다음 8열 표(파일로 저장, 통합 브랜치 `docs/`):

| 열 | 내용 |
|---|---|
| 1 | 사용자 행동 또는 상태 |
| 2 | 현재 Python 소유자 (모듈·클래스·메서드) |
| 3 | V6 JS 소유자 (함수·상태 키) |
| 4 | 그대로 재사용 가능한 현재 구현 |
| 5 | 제품 결정은 됐지만 아직 없는 구현 (`core-workflow.md` 절 번호로 귀속) |
| 6 | 폐기해야 하는 V6 shadow-backend 코드 |
| 7 | 첫 수직 슬라이스 포함 여부 |
| 8 | **함께 갱신할 계약 게이트** (DOM 계약·action registry·UI_CONTRACT·selftest) |

지도에서 즉시 교정해야 할 신호: 새 거대 ViewModel(예: `DocumentBuildSession`) 제안.
현재 결손은 계층이 아니라 **방향**이다 — 기존은 작업→데이터, v6는 데이터→작업 후보.
JobController가 마운트·선택·게이트·생성 오케스트레이션을 이미 소유하므로
(슬라이스 3에서 RunController를 상위집합이라는 이유로 죽인 전례), 신규분은
아래 §4의 세 조각(링1 둘 + 링2 세션 소유권 재배선)으로 한정한다. 지도가 그보다 큰
결손을 증명하면 이 문서를 먼저 개정한다.

> 단계 1 완료(2026-07-26): 봉합 지도는 통합 브랜치
> `docs/DATA_FIRST_INTEGRATION_MAP.md`. 지도가 증명한 개정분 두 가지가 이 판에 반영됨 —
> ①링2 세 번째 조각(작업 전환 시 데이터·선택 보존, §18.2·§19.10), ②전역 작업 건강 분리
> 계약의 절 번호는 §20이 아니라 **§19.7**.

## 4. 구현 커밋 경계 (통합 브랜치, 직렬)

### 커밋 1 — characterization: 기존 seam 잠금

UI 무변경. 재사용 경계를 테스트로 고정한다:

- 새 데이터 마운트 뒤 선택 0건 / 선택 0건에서 gate 닫힘
- 레코드 선택 순서 보존 (`SelectionModel` 투영)
- 작업 변경이 레코드 선택을 지우지 않음 (`core-workflow.md` §10 항 대응 여부 명시)
- "데이터 없음"과 "호환 작업 없음"의 구분
- 표현 계층이 `GateState.text`를 재조립하지 않음 (기존 테스트 있으면 참조로 갈음)

> 판정(2026-07-26, 지도 §5): **기존 스위트가 재사용 seam을 이미 전부 잠근다** —
> `SelectionModel` 0건 의미론(`test_selection_state.py`), 게이트 선행조건 흡수·데이터
> 없음(`test_run_state.py:92,182,206`), `source_keys` blank 제외·중복제거(`test_job.py:193-219`),
> `template_media` 확장자-단독·미상 loud(`test_job.py:825,838` — v6 §19.1의 기존 구현),
> 링1 위임 불변식(`test_webapp_job.py:607`). 신규 characterization 0건으로 충족.
> 미래 행동(선택 0건 초기화·표시순 투영·전환 보존)의 테스트는 각 행동을 바꾸는 커밋에
> 동반한다(현재와 다른 행동을 "characterization"으로 선작성하지 않는다).

### 커밋 2 — 링1 신규분 두 조각 (Qt-free·DOM-free)

1. **최소 호환성 판정** — v6 `compatibilityFor(workId, runtimeFields)`(§18.4)의 Python 이식.
   계약: *최소 Binding 호환성*(필수 source key ∈ 현재 데이터 fields)만 판정하고,
   실행 완료 가능성은 보장하지 않는다. 권위 판정은 작업 선택 뒤 `RunViewModel.refresh()`.
   전역 작업 건강(`libraryHealthFor`)과 섞지 않는다(§19.7). 배치는 `gui/` 링1 모듈.
2. **후보 열거** — 저장 작업 전체에 1을 적용해 후보 목록(호환/확인 필요/제외)을 내는
   순수 함수까지가 커밋 2다. ~~작업 미선택 상태의 스냅샷~~ → **커밋 3으로 이동**
   (2026-07-26 개정): "데이터는 마운트됐으나 작업 없음" 상태는 세션 소유권 승격 없이는
   존재할 수 없으므로 스냅샷 표현은 재배선과 같은 커밋이 맞다. 데이터 준비 전에는
   후보를 계산하지 않는다(§18.1)는 호출측(컨트롤러) 의무로 커밋 3에서 함께 고정한다.

`v6.js`의 `requestValidation`/`invalidateRunEvidence`/`commitPreparedMount`/
`preview.required·approved`/mock result/localStorage는 **이식하지 않는다** —
전부 Python이 이미 소유하거나(검증·무효화=RunStatus 재계산) 첫 슬라이스 제외 범위다.

### 커밋 3 — 세션 소유권 재배선 + 브리지·스냅샷 배선

> 분할(2026-07-26): **3a** = 세션 데이터 소유권 승격·무선택 스냅샷·후보 동승·초기 선택
> 0건(충돌 A)·가드 재정의 / **3b** = 표시순 투영 실행 순서(충돌 B). 한 커밋에 담기엔
> 계약 개정 폭이 겹치지 않아 분리한다 — 각자 자기 테스트 개정을 동반한다.

**링2 세 번째 조각(지도가 증명한 개정분):** 현재 `_do_select_job`은 작업 전환 시
데이터·선택·필터를 파기한다 — 작업-우선 전제의 산물. data-first에서는 §18.2 보존 계약에
따라 datasource·records·`SelectionModel`·필터를 세션(JobController) 소유로 승격하고,
작업 전환은 `RunViewModel`만 재생성해 데이터를 재주입(`load_data` 재사용)한다.
무효화는 §19.10 규칙(실행 증거만 폐기). 기존 전환 가드 테스트는 삭제가 아니라 재정의
승계한다(무장 시 잃는 것이 "세션 전체"→"실행 증거"로 줄었음을 문안까지 정직하게).

첫 슬라이스의 **양 끝단은 직접 브리지 경로**임을 명시한다(조언의 단일 디스패치 모델은
이 저장소 실물과 다르다):

- 마운트: `pick_data_file`/`load_data_sheet`/`load_data_path` — 직접 브리지 (기존)
- 생성: `generate` — 직접 브리지 (기존)
- 중간(레코드 선택·작업 선택·후보 갱신): `dispatch` 액션 — `action_registry.py` 등록 +
  payload 검증 + `docs/UI_CONTRACT.md` 갱신

스냅샷은 기존 `snapshot()` 확장으로, `gate`는 `GateState` 필드(`enabled/level/text/reason`)
그대로. JS 소비는 `runButton.disabled = !snap.run.gate.enabled` 수준을 넘지 않는다.

### 커밋 4 — V6 화면 골격 이식

이제야 v6 HTML/CSS를 참고한다. **파일 통째 복사가 아니라** 현재 `web/` 구조
(job.js·app.css·디자인 토큰)에 조각을 이식한다.

가져오는 것: 데이터 영역 구조, 레코드 표, 문서 후보 구획 위치, active work 표시,
게이트·실행 버튼 배치, 접근성 패턴.
가져오지 않는 것: `v6.js` 상태 머신 전부(§커밋 2 목록), v6 전용 CSS 체계(토큰은
`design_tokens.json` 단일 출처 유지).

DOM id·화면 루트·script 배선 변경분은 `test_web_dom_contract.py` 갱신을 **선행**하고,
실동작 관여분은 selftest 프로브를 추가한다.

## 5. 첫 PR 범위 (엄격)

**성공 기준: master의 생성 엔진을 그대로 쓰면서, data-first 메인에서 실제 HWPX 생성
1회를 끝낸다.**

포함: 실파일/풀 데이터 마운트 → 선택 0건 초기 상태 → 레코드 선택 → HWPX 저장 작업
후보 → 작업 명시 선택 → `RunViewModel` 검증 → 실제 `GenerationPlan` → 실제 생성 결과.

제외 (후속 슬라이스, 한 PR에 편입 금지): TXT 작업대 / 미리보기 승인(preview approval) /
편집기 deep-link·EditContext / Run override / Template·Binding revision / 즐겨찾기·최근
사용 영속 / 전체 문서 브라우저 복구 경로 / 템플릿 작업 방식 전환.

"첫 PR에서 v6 대부분이 보인다"를 목표로 하면 다시 이중 구현이 된다.

## 6. 단계별 검증 게이트

| 단계 | 게이트 |
|---|---|
| 모든 커밋 | 3종 세트: `ruff` + `pyright` + `pytest` 전부 초록 (`.\test.ps1`) |
| 커밋 3~4 | `test_web_dom_contract.py` + `--extra gui`로 selftest 직접 실행 (gui extra 없으면 **조용히 deselect**됨 — CI에서 처음 잡히게 두지 않는다) |
| 커밋 3 | `action_registry.py` 등록 + `docs/UI_CONTRACT.md` 직접 브리지/액션 목록 갱신 확인 |
| 커버리지 | `scripts/check_package_coverage.py` 플로어 유지 (신규 분기는 테스트 동반) |
| PR | 기존 리뷰 루프(푸시 후 Codex 발화 대기 → 심각도별 라운드) |

## 7. 중단 신호 (즉시 범위 재절단)

- `lab/ui-reboot` merge/cherry-pick 또는 `v6.js`를 제품 JS 디렉터리로 복사
- 새 selection/preflight/gate 엔진 작성, `RunViewModel` 대수술
- JS와 Python 양쪽에서 버튼 활성 여부 계산 (최우선 독버섯 — RC-23 역행)
- 스냅샷에 `GateState`와 다른 모양의 gate 스키마 발명
- §5 제외 목록이 첫 PR에 스며듦
- UI 화면부터 완성한 뒤 Python을 맞추겠다는 제안
- 계약 게이트(DOM 계약·registry·UI_CONTRACT·selftest) 갱신 없는 표면 변경

## 8. 최종 봉합 로드맵 (2026-07-26 확정)

첫 슬라이스(PR #302) 이후의 순서. 각 슬라이스 = 지도 8열 갱신 → 커밋 직렬 →
3종+selftest → PR → 리뷰 루프(§8.1). ⚙=백엔드 확장 수반.

| # | 슬라이스 | 계약 | 백엔드 확장 |
|---|---|---|---|
| 2 | 활성 작업 선정 + 메인 Top 5 | §18.3·§19.3·§19.4 | ⚙ 즐겨찾기 영속 + 사용 기록 링1 |
| 3 | 전체 문서 브라우저·전역 라이브러리 | §19.5·§19.6 | 무확장(기존 재소비) |
| 4 | TXT 작업대 통합 | §19.8 계열 | 기안 배관 재사용 — **중단점 A** |
| 5 | 미리보기 승인 + 무효화 전면 | §18.11·§19.10 | ⚙ RunStatus 상태 기계 확장 |
| 6 | 편집 deep-link + Run override | §4~§13 | ⚙⚙ EditContext·GenerationPlan patch |
| 7 | Template/Binding revision | §5~§7 | ⚙⚙⚙ 링0 저장 모델 — **중단점 B** |
| 8 | 템플릿 작업 방식 전환 | §19.9 | ⚙ Job 가산 필드(dormant)+원자 draft |
| 9 | 최종 정리(구 어법 삭제·존 재편·lab 폐기 판단) | — | 무확장 |

**닫힌 결정(2026-07-26, 사용자 확정):**
- 즐겨찾기 영속 = **Job 가산 필드**(`favorited_at`, version-불변·from_dict 하위호환 —
  tags·last_run_at 관례). 최근 사용 HWPX = 기존 `last_run_at` 재사용.
- 로드맵 순서 = 위 표 그대로(무효화 규칙이 편집·판본의 전제, 저장 모델 확장은 최후).

**슬라이스 2 착수 전 선행 관문 — 이행 완료(2026-07-26):** v6 상태전이 계약 결함 리뷰
보고서 triage 완료. 원문 = `research-private/v6-state-transition-review.md`(비공개 원장),
판정 = 통합 지도 §7. 요지: **첫 슬라이스 직격 결함 없음**(F-02 교정안은 이미 준수 상태),
전 결함이 계약 결함(②)으로 후속 슬라이스 귀속. 로드맵 반영:
- **슬2 스코프 변경(F-02)**: §18.3 "호환 1개 자동 선택" → **추천(suggestedWorkId)**으로
  계약 개정 후 구현. activeWorkId 는 사용자 선택 사건만(예외: preferredWorkId=명시 유래).
  부수 재론 1건 — #53-A 자동 조준 vs 보고서 §7 확인-선행 흐름의 정합.
- **슬5·6 스코프 확대**: 링1 신규 상태 계약 4종(targetAuthority·mutationScope·
  EditDataContext·ReviewRequirement, 보고서 §8) + 신규 절대 불변식 12종(§10)·수용
  시나리오(§11)의 core-workflow.md 흡수.
- **슬4 중단점 A 의제 추가(F-08)**: per-record 검토 = 복사 gate 권위.
- **폐기 목록 추가(F-03)**: dataFamily 추론 이식 금지 명문(지도 §7).

**예정된 중단점(자율 진행이 여기서 멈추고 토의를 요청한다):**
- **A(슬4 직전)**: TXT 작업대 vs 기존 「기안」 화면의 관계(통합/공존) — v6 계약이
  완전히 답하지 않는 제품 구조 결정.
- **B(슬7 직전)**: revision 저장 형식(판본 표현·마이그레이션·하위호환) — 링0 확장이라
  가장 비싼 결정, 슬6까지의 실물을 보고 확정.

### 8.1 리뷰·머지 루프 (사용자 확정)

봉합 PR들은 정본 절차를 자율 적용한다: 푸시 후 코덱스 발화 대기 → P1·P2=픽스 후
다음 라운드, P3 이하만이면 픽스·즉시 머지, 3라운드=근본원인 재분석, 4라운드
미종결=중단·사람 알림. 폴링 창 내 미발화 시 경량 자체 에이전트 리뷰로 대체.

## 9. 원 조언 대비 채택·기각 기록

외부 조언(2026-07-26)에서 채택: 병합 금지·계약 추출 3단 구조, 동결 선행, 커밋 4분할,
첫 슬라이스 범위, 위험 신호 목록. 기각: ①존재하지 않는 제3 워크트리 전제 ②
`DocumentBuildSession` 신설 스케치(죽은 RunController 계층의 부활 위험 — §3) ③영문
CLAUDE.md 신설(규칙의 제2 정본 금지 — 통합 원칙은 기존 CLAUDE.md·UI_CONTRACT 연장)
④발명된 gate 스냅샷 스키마(`GateState` 실물 사용) ⑤세션 4분할(기존 슬라이스 PR 직렬
+리뷰 루프로 갈음; 단 "1세션은 지도만, 구현 금지" 원칙은 유지).
