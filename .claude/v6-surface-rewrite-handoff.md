# 핸드오프 — v6 표면 전면 재작성 (신규 세션용 자립 프롬프트)

이 파일 하나만 읽고 시작할 수 있게 썼다. 아래 「첫 과업」 전에는 코드를 고치지 않는다.

## 0. 무엇을 하는 일인가 (프레이밍 — 2026-07-27 사용자 확정)

**v6 목업과 상태전이를 사양으로 삼아, 그에 맞는 백엔드로 제품을 다시 구현한다.**

지금까지(슬라이스 1~3)는 "master 표면에 v6 계약 조각을 이식"하는 방식이었다. 그 전제는
**폐기됐다**. 홈을 비롯한 화면의 성격 자체가 바뀌므로 부분 교체가 아니라 표면 전면
재작성이고, 백엔드는 목업이 요구하는 상태를 내도록 재배치한다.

직전 세션이 이 전환 직전에 홈 카드 레이아웃 위에 축(보기·필터·검색)을 얹는 작업을 하다가
사용자 지적으로 중단했다 — 그 브랜치(`feat/slice3-library-surface`)는 **삭제됐다**. 같은
실수를 반복하지 않는다: 죽을 구조 위에서 시각을 다듬지 않는다.

## 1. 절대 기준 문서 (읽기 전용 lab 워크트리)

경로: `C:\Users\rfast\Desktop\PYTHON_Projects\hwpx-filler-ui-reboot` (브랜치 `lab/ui-reboot`,
동결 태그 `prototype-v6-freeze`)

- `docs/core-workflow.md` — 워크플로 계약 정본. §2·§18.1~§18.11·§19.1~§19.12 가 이번 사양의
  본체(데이터 선택·문서 탐색·메인 순위·라이브러리·건강·무효화 규칙·시각 문법).
- `docs/core-workflow-ui-mvp-demo-v6.html` — v6 시안(화면 구조·구획·문법).
- `docs/core-workflow-prototype/v6.js` — 시안 동작. **이식 금지 목록**은 통합 지도 §4
  (shadow-backend: 검증·무효화 재계산, mock 실행/결과, localStorage, dataFamily 추론 등).
- `research-private/v6-state-transition-review.md` (integration 워크트리, git-ignored) —
  상태전이 결함 리뷰. triage 결과는 지도 §7.

**착수 전 사용자에게 확인할 것**: 위 셋 중 무엇을 절대 기준으로 삼는지(목업 단독인지,
`core-workflow.md` 상태전이와 함께인지). 직전 세션에서 이 질문에 답을 받지 못했다.

## 2. 워크트리 3역할

| 경로 | 브랜치 | 역할 |
|---|---|---|
| `hwpx-filler/` | `master` | 제품 정본(사용자가 직접 쓰는 체크아웃) |
| `hwpx-filler-ui-reboot/` | `lab/ui-reboot` | v6 시안·계약 **읽기 전용 참고본** |
| `hwpx-filler-integration/` | 작업 브랜치 | 실제 작업. 여기서 `origin/master` 기반 새 브랜치를 판다 |

lab 은 수정하지 않는다. 통합 지도는 `docs/DATA_FIRST_INTEGRATION_MAP.md`(integration).

## 3. 현재 코드 상태 (전부 master 에 머지됨, 2026-07-27)

| 커밋 | 내용 |
|---|---|
| `9652f20` | 슬1 — 데이터-우선 첫 수직 슬라이스(무작업 마운트·후보 구획·prework 게이트·전환 보존) |
| `c0aad27` | 슬2 — 활성 작업 선정 + 메인 Top 5(즐겨찾기 영속·순위·§18.3 추천) |
| `d8a0c18`·`81105be` | 슬3 PR-1 — 현재 데이터 문서 탐색(job 화면 하위 시트) + 스윕 |
| `fb4f064`·`f3f1fbb` | 슬3 PR-2a — 전역 라이브러리 **백엔드**(보기 4종·방식 필터·검색·§19.7 건강 번역+심각도) |

### 재작성에서도 살아남는 자산 (링0·링1)

- `core/job.py` — Job 모델(`favorited_at`·`last_run_at`·`group`·`tags`), 잠긴 writer 전부
- `core/fill_ledger.py`·`batch.py`·`naming.py` — 생성·드리프트·파일명 계약
- `gui/run_state.py` — `RunViewModel`(사전검증·`GateState` 단일 산출·`GenerationPlan`),
  `unresolved_name_tokens_for(job)`(실행 게이트와 건강 보기가 공유하는 술어)
- `gui/work_candidates.py` — 호환성 판정(§18.4)·순위(§18.5·§19.3)·추천(§18.3 개정)·
  문서 탐색 탭·prework 게이트
- `gui/home_state.py` — 라이브러리 투영(`library_sections`·`library_counts`·`library_mode_of`)
  + §19.7 건강 번역(`library_health`, (심각도, 문구) 쌍)
- `gui/selection_state.py`·`gui/filter_state.py`·`webapp/data_zone.py` — 선택·필터 13액션

### 죽는 것 (링2 표면)

현 5화면 라우팅(`home`·`job`·`draft`·`tpl`·`pool`)의 DOM·JS 구조, 홈 카드/바, 그 위의
정적 DOM 계약 일부. 무엇이 죽는지는 인벤토리 대조 결과가 정한다.

## 4. 무효가 된 전제

- lab `docs/core-workflow-integration-plan.md` §8 로드맵(슬라이스 4~9의 자르는 축)
- 통합 지도 §9.1~§9.4(슬3 PR-2/2b 계획, group-by 렌즈 은퇴 A안 등 표면 전제)

계약 판정 자체(§8.2 4건, §9.2 확정)는 유효하다 — 무효인 것은 **슬라이싱과 표면 계획**이다.

## 5. 첫 과업 (구현 금지 — 지도 먼저)

슬라이스 1에서 통했던 절차의 재적용:

1. v6 목업 + `core-workflow.md` 를 읽어 **화면·상태 인벤토리**를 뜬다(화면, 그 화면이
   요구하는 상태, 사용자 행동, 전이).
2. 각 항목을 현 링1 표면과 대조해 **그대로 쓸 것 / 모양만 바꿀 것 / 새로 만들 것**로 분류한다
   (슬라이스 1의 8열 지도와 같은 형식).
3. 그 대조표를 근거로 **재작성 슬라이싱**을 제안한다(각 슬라이스 = 수직으로 완결되는 사용자
   가치 + 계약 게이트 갱신 단위).
4. 지도(`docs/DATA_FIRST_INTEGRATION_MAP.md`)에 새 절로 쓰고 사용자 확정을 받은 뒤 착수.

## 6. 작업 규율 (이 저장소의 확립된 관례)

- **게이트 3종**: `uv run ruff check src tests` + `uv run pyright src` +
  `uv run --extra gui pytest -q` (gui extra 없으면 실앱 selftest 가 **조용히 deselect** 된다).
  커버리지 플로어: `scripts/check_package_coverage.py coverage.xml --config docs/package_coverage_floors.toml`.
  실창에서만 도는 코드를 늘리면 플로어가 깎인다(프로브 회수는 `_probe_late` 헬퍼로 접을 것).
- **계약 게이트 동반 갱신**: 정적 DOM 계약(`tests/test_web_dom_contract.py`),
  action registry, `docs/UI_CONTRACT.md`, 실 WebView2 selftest 프로브
  (`src/hwpxfiller/webapp/app.py` 의 `_*_PROBE_JS` + `tests/test_web_selftest_gate.py`).
- **리뷰 루프**: 푸시 후 Codex 자동 리뷰 대기(3~6분) → P1·P2 픽스 후 다음 라운드,
  3라운드=근본원인 재분석, 최대 5라운드·무회귀면 머지. 머지 후 도착분은 스윕 PR.
- **눈검증**: 실앱 캡처 스크립트 패턴은 세션 스크래치패드의 `shot_*.py`
  (`scripts/capture_101_screenshots.py` 의 `_find_hwnd`·`_capture_window` 재사용,
  `--selftest` 부팅에 `_selftest_drive` 치환). 합성 스냅샷을 `window.__push` 로 밀어 캡처.
- **confirm-or-alarm**: 불확실 시 허용 전이는 확정 요구·시끄러운 실패뿐. 가드 문안은 실제로
  살아남는/사라지는 집합과 일치해야 한다.

## 7. 축적된 교훈 (재작성에서 먼저 적고 들어갈 체크리스트)

- **정렬·분류 축의 4계약면**(지도 §8.4): 시각 정밀도 / 절단과 무관한 도달성 / 상태의 주체 /
  지연 왕복 중의 의도. 새 정렬·필터 축을 만들 때 구현 **전에** 넷을 적고 각각 회귀를 붙인다.
- **새 오버레이·표면의 생명주기 4계약면**(지도 §9.3): 재렌더를 가로지르는 정체(안정 id) /
  전역 잠금의 범위(오버레이는 화면 루트 질의 밖) / 전이와 왕복의 순서 / 실패 경로의 문맥 보존.
- **프로브 함정**: 두 프로브가 같은 `Bridge.call` 을 스텁하면 뒤 블록의 복원이 앞 블록의
  발신을 삼킨다(자기 액션만 가로채고 "내 스텁일 때만" 복원). 전이 뒤에 일어나는 일을 즉시
  읽으면 **거짓 통과**한다(관측 시점을 전이 종료 뒤로). 체인 링에서 `return tail` 은 프로미스
  순환이라 영영 안 끝난다.
- **판정 단일 출처**: 같은 상태를 두 표면이 다르게 부르면 그게 곧 결함이다(실행 게이트와
  건강 보기가 `unresolved_name_tokens_for` 를 공유하게 만든 이유).

## 8. 관련 메모리

`data-first-integration`(진행 원장) · `review-round-stopping-rule` · `gate-env-gotchas` ·
`confirm-or-alarm-principle` · `measurement-litmus` · `ux-101-first-user-round`(제로베이스
재설계 결정) · `no-artifact-publishing`.
