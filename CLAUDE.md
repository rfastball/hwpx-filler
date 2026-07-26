# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

문서·주석·커밋 메시지·사용자 문안은 한국어다. 기술 식별자는 `hwpx-filler`(`hwpxfiller`)
계열, 사용자에게 보이는 제품명은 **문서나르미**다.

## 이 워크트리의 성격

여기는 `hwpx-filler` 저장소의 **워크트리**이며 브랜치는 `lab/ui-reboot`다 (`.git`은 파일).
제품 코드를 개선하는 곳이 아니라, 검증된 백엔드 배관 위에서 핵심 워크플로 UI를 백지부터
비교·시연하는 실험장이다. 경계는 `docs/ui-lab/README.md`가 정본이고, 프론트엔드 작업 규칙은
`AGENTS.md` → `docs/FRONTEND_WORKFLOW_PROTOTYPE_RULES.md`가 강제한다(생략 금지).

- `web/` = 기존 제품 표면. **비교 기준이므로 이 브랜치에서 수정하지 않는다.**
- `web-minimal/variants/<id>/` = 실험 시안. 공통 부팅·토큰은 `web-minimal/shared/` 한 벌.
  시안 등록은 `web-minimal/variants.json`, 비교 상태는 `web-minimal/scenarios/*.json`.
- `docs/core-workflow*.html` + `docs/core-workflow-prototype/` = 클릭형 워크플로 시안.
  계약 정본은 `docs/core-workflow.md`, 시안별 정적 계약 테스트는
  `tests/test_core_workflow_v*_prototype.py`(HTML/JS/CSS를 파싱해 계약을 단언).
- 선정 시안은 이 브랜치를 통째로 머지하지 않는다. `master`에서 새 브랜치를 파고 필요한
  배관과 시안만 옮긴다.

## 명령

```powershell
# 최초 1회 (uv 설치 후)
uv python install 3.13
uv sync --locked --all-extras --group dev --group build

.\test.ps1                          # ruff → pyright → pytest + coverage (전체 게이트)
.\test.ps1 -q -x                    # 추가 인자는 그대로 pytest 로 전달
.\test.ps1 tests\test_engine.py
.\test.ps1 -k core_workflow_v6      # 단일 테스트 파일/이름 선택

.\run-filler.ps1                    # 제품 GUI (= python -m hwpxfiller.webapp)
.\run-filler.ps1 -Cli --help        # CLI
.\run-diff.ps1                      # 자매 제품 hwpxdiff

# UI 랩 — 같은 백엔드로 실험 시안/기존 표면을 번갈아 실행
.\run-ui-surface.ps1 -Surface Lab -Variant blank -Scenario blank
.\run-ui-surface.ps1 -Surface Lab -Variant blank -Scenario blank -ValidateOnly
.\run-ui-surface.ps1 -Surface Legacy

.\build.ps1                         # PyInstaller onedir 포터블 (canonical: packaging\build.ps1 -Target all)
```

`test.ps1` 의 ruff 대상은 `src tests conftest.py` 지만 CI(`quality.yml`)는 `src tests scripts`
를 검사한다. `scripts/` 를 건드렸으면 푸시 전에
`uv run --no-sync ruff check src tests scripts` 를 따로 돌린다.

의존성을 바꿨으면 `uv lock` + `uv sync` 후 `uv.lock` 을 함께 커밋한다(CI는 `--locked`).

## 아키텍처

공통 파서 `hwpxcore` 위에 두 제품이 서고 의존은 아래로만 흐른다:
`hwpxfiller → hwpxcore ← hwpxdiff`. 두 제품 간 직접 import 금지이며
`tests/test_architecture.py` 가 이를 차단한다.

`hwpxfiller` 는 3링 레이어링이다(정본: `docs/ARCH_UI_SEPARATION.md`, `docs/UI_CONTRACT.md`).

- **링0 도메인** `core/`, `data/` — 문서 생성·저장 모델·데이터 소스. UI 런타임을 모른다.
  (`fields.py` 누름틀 주입, `schema.py`, `authoring.py` 평문→누름틀 컴파일, `job.py`,
  `dataset_pool.py`, `fill_ledger.py`, `engine.py`/`batch.py`)
- **링1 ViewModel** `gui/*_state.py` — Qt-free·DOM-free 상태·명령·게이트. JSON-safe 값을 낸다.
- **링2 웹 프레젠테이션** `webapp/` + `web/` — 링1을 호출해 스냅샷으로 바꾸고 DOM에 렌더한다.

**링2가 링0/링1의 정책을 복제하지 않는다.** 게이트 판정(`gate`), 미러, 드리프트, 재진술,
빈값 표식 같은 판단은 Python 소유이고 JS는 문안과 표현만 맡는다. 새 UI 시안도 이 경계를
지켜 스냅샷을 다르게 *그리기만* 한다.

### 웹↔Python 두 경로

1. **디스패치 경로** — `WebFrontend.initial(screen)` / `dispatch(screen, action, payload)`.
   허용 화면·액션·payload 키는 `webapp/action_registry.py` 의 `validate_dispatch` 가 검증한다.
2. **직접 브리지 경로** — 네이티브 자원이 관여하는 호출(파일 피커, `generate`,
   `import_template_file`, 클립보드, 테마·설정, `load_data_sheet` 등)은 `web/js/bridge.js` 가
   `WebFrontend` 공개 메서드를 직접 부른다. **action registry 밖**이라 새 직접 메서드를
   추가하면 `docs/UI_CONTRACT.md` 목록과 메서드 본문의 payload 검증을 함께 갱신한다.

Python→웹 갱신은 `window.__push(screen, snapshot)`. 파괴 전이의 `needs_confirm` 왕복은
네이티브 다이얼로그가 아니라 `web/js/modal.js` 의 `Modal.confirm` 이 구현한다.

라우팅 화면은 `home` `job` `draft` `tpl` `pool` 다섯이며 `editor` 는 `job` 안의 편집 호스트다.
화면을 추가·삭제·개명할 때는 DOM 루트, 화면 JS의 `SCREEN`, Python 컨트롤러 `name`,
`WebFrontend.controllers`, action registry 를 **한 계약 변경으로** 갱신한다.

### 단일 출처

- 디자인 토큰: `src/hwpxfiller/gui/design_tokens.json` → `scripts/gen_design_tokens.py` 가
  `web/css/tokens.css` 와 동결 목업 생성 구간을 만든다(생성물도 커밋). 드리프트는
  `tests/test_design_tokens.py` 가 막는다.
- 레이아웃·컴포넌트 CSS: `web/css/app.css`.
- 제품 버전: `pyproject.toml` 의 `project.version` (릴리스 태그 `vX.Y.Z` 와 일치해야 한다).

### 환경 seam

- `HWPXFILLER_HOME` — 앱 홈(설정·템플릿 그룹·영속). 테스트는 `tests/conftest.py` 의 autouse
  픽스처가 임시 폴더로 못박는다. **실 사용자 홈을 읽거나 쓰는 테스트를 만들지 않는다** —
  템플릿 그룹 `reconcile` 이 빈 스냅샷에서 실 지정을 삭제·영속한 전례가 있다.
- `HWPXFILLER_WEB_DIR` — 정적 웹 자산 루트 교체(UI 랩이 이걸로 시안을 띄운다).
- `HWPX_SKIP_GUI_TESTS=1` — 데스크톱 세션 없는 환경에서 실 WebView2 게이트 옵트아웃.
- 루트 `conftest.py` 는 저장소 안을 가리키는 `--basetemp` 를 감시받지 않는 시스템 임시
  폴더로 돌린다(OneDrive/인덱서가 걸어 놓는 삭제 보류 → `WinError 5` 회피). 그 우회를
  없애지 말 것.

## 검증 계층

정적과 동적은 대체 관계가 아니다. 둘 다 갱신한다.

| 게이트 | 무엇을 잡나 |
|---|---|
| `tests/test_web_dom_contract.py` | 실제 배포 자산의 id 유일성·화면 루트·script 배선·접근성 참조 |
| `tests/test_web_selftest_gate.py` (`python -m hwpxfiller.webapp --selftest`) | 실 WebView2 창을 띄워 렌더·클릭·브리지 왕복을 DOM 되읽기로 단언 |
| `tests/test_core_workflow_v*_prototype.py` | HTML 시안의 워크플로·capability·접근성 계약 |
| `scripts/check_package_coverage.py` + `docs/package_coverage_floors.toml` | 패키지별 line/branch 하한 |

DOM `id`·`data-*`·script 순서·화면 루트를 바꾸면 정적 DOM 계약을 먼저 갱신하고, 실제 동작이
관여하면 selftest 시나리오도 갱신한다. GUI extra 없이 pytest 를 돌리면 실앱 게이트가 조용히
deselect 되므로 DOM 변경 시에는 `--extra gui` 로 직접 확인한다.

HTML 시안의 실클릭 검증은 설치된 Chrome 을 쓴다:
`uv run --with playwright python ...` + `channel="chrome"` 으로 `file://` 을 열고 결과를
UTF-8 리포트 파일로 남긴다.

## 제품 규율

**"묻고 확정하게 하라, 아니면 시끄럽게 알려라."** 법적 효력이 있는 문서를 만드는 도구라
불확실할 때 허용되는 전이는 확정 요구와 실패 표시뿐이고 조용한 추측은 없다. 빈 값은 생성을
잠그고, 확인하고 진행한 빈 값은 `〘미입력·필드명〙` 표식으로 문서에 남으며, 데이터에 없는
토큰은 미리보기에 그대로 빨갛게 남는다. 가드 문안은 **실제로 살아남는/사라지는 집합과
정확히 일치**해야 한다(과경고=거짓말, 과소경고=조용한 소실).

- 사용자 문안: `docs/COPY_STYLE_GUIDE.md`, 용어: `docs/UI_VOCABULARY.md` 가 계약이다.
- 문서 배치: 서사·원칙·설계는 `docs/`, 이산 조치는 GitHub 이슈. `docs/` 에 TODO 를 두지 않는다.
  각 문서 머리의 **문서 상태**(현재 정본 / 유효 결정 / 부분 대체 / 역사 기록 / 동결 시안)를
  먼저 보고, 탐색 순서는 `docs/README.md` 가 정본이다.
- 삭제는 의무를 상속한다 — 화면·모듈을 지울 때 어포던스·테스트 커버리지·경보 문안이 조용히
  같이 사라지지 않게 승계한다.
