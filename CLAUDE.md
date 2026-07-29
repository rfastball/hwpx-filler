# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 이 저장소가 담은 것

파서 `hwpxcore` 위에 제품 `hwpxfiller` 가 서는 저장소다. 의존은 아래로만 흐른다:
`hwpxfiller → hwpxcore`. 코어에 제품 로직을 두지 않는다(`tests/test_architecture.py` 가 강제).

- `hwpxfiller` — 누름틀 HWPX 템플릿 + 엑셀/CSV 데이터로 문서 일괄 생성. 사용자 대면
  제품명은 **문서나르미**, 기술 식별자는 `hwpx-filler`/`hwpxfiller` 계열.
- HWP 프로그램·COM 자동화를 쓰지 않는다. `zipfile` + `lxml` 로 OCF ZIP 을 직접 읽고 쓴다.

자매 제품 `hwpxdiff`(두 판본 HWPX 의 의미 기반 비교)는 2026-07-29 에 별도 저장소
[rfastball/hwpx-diff](https://github.com/rfastball/hwpx-diff) 로 분리됐다. 그쪽이 `hwpxcore`
**사본**을 들고 있어 자동 동기화되지 않는다 — 파서를 고칠 때 저쪽에도 필요한 변경인지
판단하고, 필요하면 각각 반영한다.

Windows 전용(pywebview 6.x + WebView2). Python 은 `.python-version` 의 3.13 고정이고
환경은 전부 `uv` 가 소유한다 — 시스템 Python·수동 venv 를 만들지 않는다.

## 명령

```powershell
uv python install 3.13
uv sync --locked --all-extras --group dev --group build   # 최초 1회

.\test.ps1                        # Ruff → Pyright → pytest + coverage (전체 게이트)
.\test.ps1 tests\test_engine.py -x   # 인자는 그대로 pytest 로 전달
.\test.ps1 -k library -q

.\run-filler.ps1                  # 소스 GUI (= python -m hwpxfiller.webapp)
.\run-filler.ps1 -Cli --help      # 소스 CLI

.\packaging\build.ps1 -Target all # canonical 포터블 빌드 + selfcheck (filler/cli)
.\build.ps1                       # GUI 제품만 위임하는 호환 러너
.\package-installer.ps1           # Inno Setup 6 설치본
```

의존성을 바꿨으면 `uv lock` + `uv sync` 후 `uv.lock` 을 함께 커밋한다 — CI 는
`uv sync --locked` 라 선언과 잠금이 다르면 실패한다.

CI(`.github/workflows/quality.yml`)는 서로 의존하지 않는 세 잡이다: `static`(Ruff·Pyright) /
`pytest + package coverage floor` / `distribution`. CI 의 Ruff 는 `scripts` 까지 보는데
`test.ps1` 은 `src tests conftest.py` 만 본다 — `scripts/` 를 고쳤으면 `uv run ruff check scripts` 를
따로 돌린다. 릴리스는 `pyproject.toml` 버전과 같은 `vX.Y.Z` 태그 push 로만 나간다.

## 아키텍처 — 3링 경계

정본: `docs/UI_CONTRACT.md`. 요약하면 의존은 바깥에서 안으로만 흐른다.

1. **링0 도메인** `src/hwpxfiller/core/`, `src/hwpxfiller/data/` — 문서 생성·저장 모델·데이터
   소스. UI 런타임을 모른다.
2. **링1 ViewModel** `src/hwpxfiller/gui/*_state.py` — Qt-free·DOM-free 상태 모델. 판정·게이트·
   문안을 소유하고 직렬화 가능한 값을 낸다. 이름이 `gui` 지만 위젯이 아니다.
3. **링2 프레젠테이션** `src/hwpxfiller/webapp/`(컨트롤러·브리지) + `web/`(HTML/CSS/JS).
   링1 을 불러 JSON-safe 스냅샷으로 바꿔 DOM 에 그린다.

컨트롤러(`webapp/screen_*.py`)는 pywebview 를 import 하지 않아 **헤드리스로 구동·테스트된다**.
푸시 sink 가 생성자 주입이라 앱에선 `evaluate_js`, 테스트에선 리스트 수집으로 붙는다.

### 웹↔Python 두 경로

- **디스패치 경로**: `WebFrontend.initial(screen)` / `dispatch(screen, action, payload)`.
  허용 화면·액션·payload 키는 `webapp/action_registry.py` 의 `validate_dispatch` 가 검증한다 —
  오타난 키가 `dict.get` 으로 조용히 무시되지 않게 하는 것이 이 파일의 존재 이유다.
- **직접 브리지 경로**: 네이티브 자원이 관여하는 호출(파일 피커, `generate`,
  `import_template_file`, 경로 열기/추적, 클립보드·테마·설정, `load_data_sheet`)은 `web/js/bridge.js`
  가 `WebFrontend` 공개 메서드를 직접 부른다. **action registry 밖**이므로 새 직접 메서드를
  추가하면 payload 검증을 메서드 본문에 직접 쓰고 `docs/UI_CONTRACT.md` 의 목록도 갱신한다.

Python→웹은 `window.__push(screen, snapshot)`. 파괴 전이의 확인 왕복(`needs_confirm`)은
네이티브 다이얼로그가 아니라 JS `Modal.confirm`(`web/js/modal.js`)이 구현한다 — **판정·수치는
Python, 문안·확인 UI 는 웹**.

### 화면과 소유권

상단 탭은 `job`(문서 만들기)·`library`(문서 작업) 2탭이고 `tpl` 은 과도기 잔존이다.
`editor`·`workbench` 는 탭 없는 **몰입 표면**으로, 이탈 가드 위임은 화면별 특례가 아니라
`web/js/app.js` 의 `IMMERSIVE` 목록이 진다. 화면을 추가·삭제·개명하면 DOM 루트, 화면 JS 의
`SCREEN`, Python 컨트롤러 `name`, `WebFrontend.controllers`, action registry, `docs/UI_CONTRACT.md`
를 **한 계약 변경으로** 갱신한다.

세션 소유권은 **데이터-우선**이다: 마운트된 데이터·선택·필터는 `JobController` 세션 소유이고
작업 전환에서 생존한다. 잃는 것은 실행 증거뿐. 마운트 직후 선택은 0건이고, 실행 입력 순서는
표시순서 투영(`_display_indices`)을 통과한다 — 표·거울·파일 이름 계획이 전부 같은 투영을 쓴다.
배경과 대조표는 `docs/DATA_FIRST_INTEGRATION_MAP.md`.

## 제품 규칙 — 조용히 틀리지 않는다

이 앱의 핵심 계약은 **"묻고 확정하게 하거나, 시끄럽게 알린다"** 다. 법적 효력이 있는 문서를
만드는 도구라서 애매할 때 조용히 추측하고 넘어가는 경로를 만들지 않는다. 구체적으로:

- 런타임 부재를 자동 감지해 테스트를 조용히 스킵하지 않는다(명시 옵트아웃 환경변수만).
- 실패·거절은 숨기지 않고 사유를 재진술한다. 보관·끊김 항목은 숨기는 대신 비활성 + 사유 병기.
- 빈 값·미치환 토큰은 빈칸으로 새지 않고 표식으로 남는다.

같은 상태를 두 곳이 판정하게 만들지 않는 것도 같은 원칙의 구조적 얼굴이다. 링2 에서 링1 의
판정·문안을 다시 조립하지 않는다.

## 상태·영속

앱 홈은 `HWPXFILLER_HOME` 또는 `~/.hwpxfiller` 이고 해석기는 `core/paths.py` 단일 출처다.
그 아래 작업 레지스트리(`core/job.py`), TXT 템플릿(`core/text_registry.py`), 데이터 참조 풀
(`core/dataset_pool.py`, 경로만 저장하고 실행 때 다시 읽음), 생성 원장(`core/fill_ledger.py`),
설정(`webapp/settings.py`)이 산다.

테스트 seam 은 `HWPXFILLER_HOME`(홈 격리)·`HWPXFILLER_WEB_DIR`(자산 루트 교체)이다. 루트
`conftest.py` 와 `tests/conftest.py` 가 autouse 로 홈을 임시 폴더에 못박는다 — **개발자 실설정
오염과 템플릿 그룹 유령 삭제를 막는 안전망**이라 우회하지 않는다.

## 테스트 계층

| 계층 | 파일 | 맡는 것 |
|---|---|---|
| 정적 DOM 계약 | `tests/test_web_dom_contract.py` | 실제 배포 `web/` 자산의 id 유일성·화면 루트·script 배선·seam |
| 실앱 게이트 | `tests/test_web_selftest_gate.py`, `python -m hwpxfiller.webapp --selftest` | 실 WebView2 부팅·렌더·클릭·브리지 왕복 되읽기 |
| 헤드리스 컨트롤러 | `tests/test_webapp_*.py` | 링2 컨트롤러 dispatch·스냅샷 |
| 링1 | `tests/test_*_state.py` | ViewModel 판정 |
| 아키텍처·품질 | `test_architecture.py`, `test_quality_workflow.py`, `test_package_coverage_gate.py` | 링 경계·코어 역의존 금지, CI 형상, coverage 하한 |

두 게이트는 대체 관계가 아니다 — 구조적 누락은 정적 계약이, 브라우저 런타임에서만 드러나는
결함은 selftest 가 잡는다. selftest 프로브의 `click` 은 hidden 요소도 통과하므로 가시성 단언을
따로 걸지 않으면 눈으로 본 것과 다른 결론이 나온다.

커버리지는 `docs/package_coverage_floors.toml` 의 **패키지별** line/branch 하한이 차단 조건이다.
비재귀 경로라 새 서브패키지는 하한을 등록하지 않으면 게이트가 실패한다(조용한 스킵 금지).
`hwpxcore.native` 는 하한 대신 `tests/test_native_positive.py` 를 별도 CI 단계로 강제한다.

옵트아웃 환경변수: `HWPX_SKIP_GUI_TESTS=1`(WebView2 실창), `HWPX_SKIP_NATIVE_TESTS=1`.
화면 없는 환경에서만 명시로 쓴다.

## 단일 출처 목록

바꿀 때 원천을 고치고 생성물을 커밋한다 — 생성물을 직접 고치면 드리프트 게이트가 잡는다.

- 디자인 토큰: `src/hwpxfiller/gui/design_tokens.json` → `scripts/gen_design_tokens.py` →
  `web/css/tokens.css`(+ 동결 목업 구간), 게이트 `tests/test_design_tokens.py`.
- 레이아웃·컴포넌트 CSS: `web/css/app.css`. 동결 목업의 인라인 CSS 로 현재 앱을 판단하지 않는다.
- 제품 버전: `pyproject.toml` `project.version` 만. PyInstaller·Inno 버전은 빌드 시 생성.
- 사용자 문구: 한 곳에서만 쓰는 정적 문구는 `web/index.html` 또는 그 산출자가 소유하고,
  둘 이상이 공유하는 것만 `web/js/copy.js` 같은 공용 상수로 올린다. 문형·금지어는
  `docs/COPY_STYLE_GUIDE.md`, 용어는 `docs/UI_VOCABULARY.md`.
- 확장자 필터(`gui/file_filters.py`), 작업 방식 라벨(`gui/work_mode.py`), 식별 요약
  (`core/identity_summary.py`) 처럼 여러 표면이 같은 문자열을 써야 하는 것들도 각자 단일 출처다.

## 문서

`docs/README.md` 가 문서 지도이자 상태 정의(현재 정본 / 유효 결정 / 부분 대체 / 역사 기록 /
동결 시안)의 정본이다. **현재 동작의 최종 권위는 코드·테스트·빌드 설정**이고 문서는 그것을
설명하거나 결정 배경을 보존한다. 먼저 읽을 것:

- `docs/DEVELOPMENT_ENVIRONMENT.md` — 환경·게이트·패키징·릴리스 절차
- `docs/UI_CONTRACT.md` — 현재 웹 UI 의 링 구조·라우팅·화면별 계약
- `docs/DATA_FIRST_INTEGRATION_MAP.md` — v6 워크플로 계약 ↔ master seam 대조
- `examples/quickstart-101/README.md` — 실제 사용 흐름(예제 템플릿·데이터 동봉)

문서에 TODO 를 쓰지 않는다 — "done 상태가 있는가?"가 리트머스이고, 이산 조치는 GitHub 이슈,
서사·원칙·설계는 `docs/` 다.

## 작업 규율

- 링1 공개 API 를 바꾸면 소비 컨트롤러와 헤드리스 테스트를 같은 변경에 담는다. DOM `id`·
  `data-*`·script 순서·화면 루트를 바꾸면 정적 DOM 계약을 먼저 갱신하고, 실동작이 관여하면
  selftest 시나리오까지 갱신한다.
- 동결 목업(`docs/UI_PROTOTYPE_APPB.html`, `docs/r-flow-mockups/`)은 현재 기능을 설계·검증하려고
  먼저 고치지 않는다.
- 커밋 메시지는 한국어 Conventional Commits + PR 번호(`feat: … (#319)`, 파괴적 변경은 `feat!:`).
- 커밋하지 않는 것: `.venv/`, `.secrets/`, `build/`·`dist/`·`installer-dist/`, coverage·pytest 보고서,
  `.claude/settings.local.json`, `research-private/`.
- 나라장터(조달청 API) 소스는 **동결**이다 — 어댑터·CLI 접합부만 유지하고 웹 표면에 노출하지
  않는다. 풀에 있는 nara 항목은 숨기지 말고 시끄럽게 거절한다. 테스트는 실 API·서비스 키
  대신 `tests/fixtures` 의 응답을 쓴다.
