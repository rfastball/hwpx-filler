# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 이 저장소가 담은 것

파서 `hwpxcore` 위에 제품 `hwpxfiller` 가 서는 저장소다. 의존은 아래로만 흐른다:
`hwpxfiller → hwpxcore`. 코어에 제품 로직을 두지 않는다(`tests/repo_contract/test_architecture.py` 가 강제).

- `hwpxfiller` — 누름틀 HWPX 템플릿 + 엑셀/CSV 데이터로 문서 일괄 생성. 사용자 대면
  제품명은 **문서나르미**, 기술 식별자는 `hwpx-filler`/`hwpxfiller` 계열.
- HWP 프로그램·COM 자동화를 쓰지 않는다. `zipfile` + `lxml` 로 OCF ZIP 을 직접 읽고 쓴다.

Windows 전용(pywebview 6.x + WebView2). Python 은 `.python-version` 의 3.13 고정이고
환경은 전부 `uv` 가 소유한다 — 시스템 Python·수동 venv 를 만들지 않는다.

## 명령

```powershell
uv python install 3.13
uv sync --locked --all-extras --group dev --group build   # 최초 1회

.\test.ps1                        # web build → npm test → Ruff → Pyright → pytest + coverage
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

CI(`.github/workflows/quality.yml`)는 **생산자 1 + 소비자 N** 이다. `sealed-web` 하나가 프런트를
만들어 봉인하고, 같은 설치로 Node 단위 테스트와 sealed artifact 계약까지 마친 뒤 업로드한다.
실 산출물 소비자는 그것을 내려받아 `build-web.ps1 -Mode VerifyExisting` 으로 되짚는다 — 그
검증은 `setup-node` **앞에** 서서 빌드 도구 없이 통과한다(순서가 계약이다). 나머지는 자원 축이
가른다 — `static`(Ruff·Pyright·`tests/repo_contract`) /
`pytest-contract`(순수 Python 행동 집합 + 커버리지 하한) / `windows-native` /
`browser-render` / `live-webview2` / `distribution-webview2`. 그 일곱을 명시 열거해 `success`
만 통과시키는 `quality-gate` 가 브랜치 보호가 겨눌 단 하나의 이름이고, 실주행·패키징 증거는
`if: always()` 로 실패해도 회수된다. CI 와 `test.ps1` 의 Ruff 는 둘 다 `src tests scripts` 를
본다 — 어느 쪽도 `packaging/` 은 안 보므로 spec·엔트리·빌드 스크립트를 고쳤으면
`uv run ruff check packaging` 을 따로 돌린다. 릴리스는 `pyproject.toml` 버전과 같은 `vX.Y.Z`
태그 push 로만 나가고, 네 사본(source·dist·installed·portable)의 web artifact identity 대조와
`build-metadata.json` 의 프런트 identity·출하 런타임 기재가 그 출하의 증거다
(`docs/DEVELOPMENT_ENVIRONMENT.md` §5). 대조 판정은 `scripts/reconcile_shipped_copies.py` 하나가
지고 호출자가 `--expect` 로 사본 집합을 **선언**한다 — 매 병합 패키징 게이트는 셋
(source·dist·portable), 릴리스 태그는 넷. 설치본 사본은 `packaging\build.ps1 -IncludeInstaller`
로 로컬에서 재현한다.

## 아키텍처 — 3링 경계

정본: `docs/UI_CONTRACT.md`. 요약하면 의존은 바깥에서 안으로만 흐른다.

1. **링0 도메인** `src/hwpxcore/`, `src/hwpxfiller/domain/`, `src/hwpxfiller/data/` — 형식
   kernel·제품 모델·데이터 소스. UI 런타임을 모른다.
2. **링1 ViewModel** `src/hwpxfiller/gui/*_state.py` — Qt-free·DOM-free 상태 모델. 판정·게이트·
   문안을 소유하고 직렬화 가능한 값을 낸다. 이름이 `gui` 지만 위젯이 아니다.
3. **링2 프레젠테이션** `src/hwpxfiller/webapp/`(컨트롤러·브리지) +
   `frontend/`(유일한 HTML/CSS/JS source). 제품 런타임은 sealed `build/web/`만 소비한다.
   링1 을 불러 JSON-safe 스냅샷으로 바꿔 DOM 에 그린다.

컨트롤러(`webapp/screen_*.py`)는 pywebview 를 import 하지 않아 **헤드리스로 구동·테스트된다**.
푸시 sink 가 생성자 주입이라 앱에선 `evaluate_js`, 테스트에선 리스트 수집으로 붙는다.

### 웹↔Python 두 경로

- **디스패치 경로**: `WebFrontend.initial(screen)` / `dispatch(screen, action, payload)`.
  허용 화면·액션·payload 키는 `webapp/action_registry.py` 의 `validate_dispatch` 가 검증한다 —
  오타난 키가 `dict.get` 으로 조용히 무시되지 않게 하는 것이 이 파일의 존재 이유다.
- **직접 브리지 경로**: 네이티브 자원이 관여하는 호출(파일 피커, `generate`,
  `import_template_file`, 경로 열기/추적, 클립보드·테마·설정, `load_data_sheet`)은
  `frontend/js/bridge.js`
  가 `WebFrontend` 공개 메서드를 직접 부른다. **action registry 밖**이므로 새 직접 메서드를
  추가하면 payload 검증을 메서드 본문에 직접 쓰고 `docs/UI_CONTRACT.md` 의 목록도 갱신한다.

Python→웹은 제품 공개 API `window.__hwpx` 의 `snapshot` 사건이다(임시 전역 `window.__push` 는 N-10 에서 사라졌다). 파괴 전이의 확인 왕복(`needs_confirm`)은
네이티브 다이얼로그가 아니라 JS `Modal.confirm`(`frontend/js/modal.js`)이 구현한다 — **판정·수치는
Python, 문안·확인 UI 는 웹**.

### 화면과 소유권

상단 탭은 `job`(문서 만들기)·`library`(문서 작업) 2탭이고 `tpl` 은 과도기 잔존이다.
`editor`·`workbench` 는 탭 없는 **몰입 표면**으로, 이탈 가드 위임은 화면별 특례가 아니라
셸 상태기계 `frontend/src/shell/nav.ts` 의 `IMMERSIVE_SURFACES` 목록이 진다(R3-02 —
판정은 상태기계, 클래스·속성 집행은 `frontend/js/app.js` adapter, 리스너·부팅 수명주기는
React ShellHost). 화면을 추가·삭제·개명하면 DOM 루트, 화면 JS 의
`SCREEN`, Python 컨트롤러 `name`, `WebFrontend.controllers`, action registry, `docs/UI_CONTRACT.md`
를 **한 계약 변경으로** 갱신한다.

작업↔데이터는 **durable 강결합**이다(U4 §2.4 · #932 U4-C — U2 §5.3 판정 D 의 명시 철회):
`Job` 이 경로·시트·헤더 행 한 벌을 들고, 작업을 고르면 그 데이터가 서고, 데이터를 열면
거기 결속된 작업이 후보로 선다. 관계는 **하나**이고 스키마 호환을 후보 축으로 병존시키지
않는다 — 호환 판정(`compatibility_for`)은 결속된 파일의 열이 사라진 경우를 잡는 실행
게이트로만 산다. 결속을 쓰는 자리는 **편집기 저장 하나**다.

그 위에서 세션 소유권은 그대로다: 마운트된 데이터·선택·필터는 `JobController` 세션 소유이고
작업 전환에서 생존한다(잃는 것은 실행 증거뿐). 마운트 직후 선택은 0건이고, 실행 입력 순서는
표시순서 투영(`_display_indices`)을 통과한다 — 표·거울·파일 이름 계획이 전부 같은 투영을 쓴다.
`docs/archive/DATA_FIRST_INTEGRATION_MAP.md` 는 **역사 기록**이고 그 「데이터-우선」 전제는
위 재판정이 대체했다 — 동결 문서는 고치지 않고 승계 진술을 `docs/UI_CONTRACT.md` 가 진다.

## 제품 규칙 — 조용히 틀리지 않는다

이 앱의 핵심 계약은 **"묻고 확정하게 하거나, 시끄럽게 알린다"** 다. 법적 효력이 있는 문서를
만드는 도구라서 애매할 때 조용히 추측하고 넘어가는 경로를 만들지 않는다. 구체적으로:

- 런타임 부재를 자동 감지해 테스트를 조용히 스킵하지 않는다(명시 옵트아웃 환경변수만).
- 실패·거절은 숨기지 않고 사유를 재진술한다. 보관·끊김 항목은 숨기는 대신 비활성 + 사유 병기.
- 빈 값·미치환 토큰은 빈칸으로 새지 않고 표식으로 남는다.

같은 상태를 두 곳이 판정하게 만들지 않는 것도 같은 원칙의 구조적 얼굴이다. 링2 에서 링1 의
판정·문안을 다시 조립하지 않는다.

## 상태·영속

앱 홈은 `HWPXFILLER_HOME` 또는 `~/.hwpxfiller` 이고 해석기는 `host/locations.py` 단일 출처다.
그 아래 작업 레지스트리(`external/job_store.py`), TXT 템플릿(`external/text_registry.py`), 데이터 참조 풀
(`external/dataset_store.py`, 경로만 저장하고 실행 때 다시 읽음), 생성 원장(`domain/fill_ledger.py`),
설정(`external/settings.py`)이 산다.

테스트 seam 은 `HWPXFILLER_HOME`(홈 격리)이다. 웹 자산 경로 override는 없다. source 제품은
현재 commit의 sealed `build/web/`, frozen 제품은 번들된 sealed `web/`만 검증해 사용한다. 루트
`conftest.py` 와 `tests/conftest.py` 가 autouse 로 홈을 임시 폴더에 못박는다 — **개발자 실설정
오염과 템플릿 그룹 유령 삭제를 막는 안전망**이라 우회하지 않는다.

## 테스트 계층

| 계층 | 파일 | 맡는 것 |
|---|---|---|
| 저장소 형상 계약 | `tests/repo_contract/` | 계층·공개 경계·legacy 부재·CI/릴리스 형상 |
| 봉인 산출물 계약 | `tests/artifact_contract/` | sealed web identity·manifest·출하 메타데이터 |
| 실앱 게이트 | `tests/test_web_selftest_gate.py`, `python -m hwpxfiller.webapp --selftest` | 실 WebView2 부팅·렌더·클릭·브리지 왕복 되읽기 |
| 실렌더 기하 | `tests/test_web_press_geometry.py`(+`_press_probe.py`) | sealed `build/web/` CSS를 loopback으로 제공한 최소 문서에서 `:active` 유지 중 기준면 이탈. `prefers-reduced-motion` 을 **명시 강제**(Playwright + 설치 Chrome) |
| 헤드리스 컨트롤러 | `tests/test_webapp_*.py` | 링2 컨트롤러 dispatch·스냅샷 |
| 링1 | `tests/test_*_state.py` | ViewModel 판정 |
| 아키텍처·품질 | `tests/repo_contract/test_architecture.py`, `tests/repo_contract/test_quality_workflow.py`, `tests/repo_contract/test_package_coverage_gate.py` | 링 경계·코어 역의존 금지, CI·릴리스 형상, coverage 하한 |
| 패키징·출하 | `tests/repo_contract/test_packaging_contract.py`, `tests/artifact_contract/test_build_metadata.py`, `tests/repo_contract/test_legacy_path_zero.py` | spec hidden import 해소, 릴리스 메타데이터↔seal 대조, 폐기 source 경로 저장소 전역 0 |

이 게이트들은 대체 관계가 아니다 — 구조적 누락은 정적 계약이, 브라우저 런타임에서만 드러나는
결함은 selftest 가 잡는다. selftest 프로브의 `click` 은 hidden 요소도 통과하므로 가시성 단언을
따로 걸지 않으면 눈으로 본 것과 다른 결론이 나온다.

**실 창 게이트는 콜드 부팅을 늘리지 않는다.** WebView2 콜드 부팅 하나는 러너에서 플레이크
주사위 하나다 — 저장소가 이미 아는 결함류이고 패키징 쪽은 `webview_boot_flake` 유한 재시도로
흡수한다(#477). 그래서 새 실런타임 단언은 기존 session/module fixture의 `selftest_result`에
필드를 더하거나 이미 서 있는 창에 단계를 붙인다. 완료된 migration의 파일 census를 되살려
창 수를 간접 관리하지 않는다. 새 창이 불가피하면 해당 fixture와 CI job에서 비용·사유를 함께
드러낸다. 예산은 파일마다 들지 않고 공용 상수를 받는다:
예산이 하는 일은 매달림을 유한 시간에 빨강으로 만드는 것이지 느린 러너를 탈락시키는 것이
아니다(느림으로 난 빨강은 정보가 0 이고 재주행 비용만 남긴다).

**정적 계약은 규칙의 존재를 보고 결과를 못 본다**(U2 §2.11 표본): `.jobtb tbody tr:active` 의
`transform:scale(.97)` 이 910px 행의 좌변을 13.65px 옮겨 표 머리와 정렬을 잃는 동안 눌림 계약은
초록이었다. 그래서 기하가 결과인 계약은 실렌더 층이 진다. **모션 층은 `prefers-reduced-motion`
을 강제하지 않으면 검사되지 않는다** — Windows 「애니메이션 표시」를 끈 기기에서 Chromium 은
`reduce` 를 보고하고 모션 층 전체가 강등돼 프로브가 영영 초록이다. 양성·음성 대조를 두 값으로
각각 세운다.

커버리지는 `docs/package_coverage_floors.toml` 의 **패키지별** line/branch 하한이 차단 조건이다.
비재귀 경로라 새 서브패키지는 하한을 등록하지 않으면 게이트가 실패한다(조용한 스킵 금지).
`hwpxfiller.host.native` 는 하한 대신 `tests/test_native_positive.py` 를 별도 CI 단계로 강제한다.

옵트아웃 환경변수: `HWPX_SKIP_GUI_TESTS=1`(WebView2 실창), `HWPX_SKIP_NATIVE_TESTS=1`,
`HWPX_SKIP_MOTION_TESTS=1`(눌림 기하 — 설치 Chrome 부재). 화면·브라우저 없는 환경에서만 명시로
쓴다. CI 는 셋 다 **걷고** 돌린다.

같은 세 자원이 pytest marker 축이기도 하다 — `live`(실 WebView2) · `native`(실 Win32) ·
`browser`(설치 Chrome). marker 는 옵트아웃을 대체하지 않고 그 위에 얹혀 **CI 가 잡을 가르는
선택자**로 산다(무표 집합 = 결정론적 contract suite). 계약은 두 가지다: 게이트 `skipif` 와 축
marker 는 **같은 노드에 함께** 있고, 축은 서로 겹치지 않는다. 완료된 수집 메타테스트는
퇴역했고, CI 의 자원 축·contract 라우팅은 `tests/repo_contract/test_quality_workflow.py` 가
워크플로 실형상으로 검증한다. `--strict-markers` 라 새 marker 는 `pyproject.toml` 의
`markers` 에 **먼저 등록**해야 한다.

## 단일 출처 목록

바꿀 때 원천을 고치고 생성물을 커밋한다 — 생성물을 직접 고치면 드리프트 게이트가 잡는다.

- 디자인 토큰: `src/hwpxfiller/gui/design_tokens.json` → `scripts/gen_design_tokens.py` →
  `frontend/css/tokens.css`(+ 동결 목업 구간). 생성 드리프트는
  `scripts/gen_design_tokens.py --check`, 사용자 안전 대비 하한은
  `tests/repo_contract/test_contrast_wcag.py`가 각각 확인한다.
- 레이아웃·컴포넌트 CSS: `frontend/css/`의 ordered product graph. 동결 목업의 인라인 CSS 로
  현재 앱을 판단하지 않는다.
- 제품 버전: `pyproject.toml` `project.version` 만. PyInstaller·Inno 버전은 빌드 시 생성.
- 사용자 문구: 한 곳에서만 쓰는 정적 문구는 `frontend/index.html` 또는 그 산출자가 소유하고,
  둘 이상이 공유하는 것만 공용 상수 모듈로 올린다(승격 대상이 없으면 모듈도 없다 —
  R5-99 B2 에서 `frontend/js/copy.js` 가 소비자 0 으로 삭제된 전례). 문형·금지어는
  `docs/COPY_STYLE_GUIDE.md`, 용어는 `docs/UI_VOCABULARY.md`.
- 확장자 필터(`gui/file_filters.py`), 작업 방식 라벨(`gui/work_mode.py`), 식별 요약
  (`domain/identity_summary.py`) 처럼 여러 표면이 같은 문자열을 써야 하는 것들도 각자 단일 출처다.

## 문서

`docs/README.md` 가 문서 지도이자 상태 정의(현재 정본 / 유효 결정 / 부분 대체 / 역사 기록 /
동결 시안)의 정본이다. **현재 동작의 최종 권위는 코드·테스트·빌드 설정**이고 문서는 그것을
설명하거나 결정 배경을 보존한다. 먼저 읽을 것:

- `docs/DEVELOPMENT_ENVIRONMENT.md` — 환경·게이트·패키징·릴리스 절차
- `docs/UI_CONTRACT.md` — 현재 웹 UI 의 링 구조·라우팅·화면별 계약
- `docs/UX_FEEDBACK_U3.md` — 현재 실사용 피드백 라운드의 판정(새 판정은 여기, 조치 추적 #873).
  이전 라운드는 `docs/UX_FEEDBACK_U2.md`
- `docs/archive/DATA_FIRST_INTEGRATION_MAP.md` — v6 워크플로 계약 ↔ master seam 대조.
  **완주·동결**(2026-07-29) — 인용은 하되 새 판정을 덧붙이지 않는다
- `examples/quickstart-101/README.md` — 실제 사용 흐름(예제 템플릿·데이터 동봉)

문서에 TODO 를 쓰지 않는다 — "done 상태가 있는가?"가 리트머스이고, 이산 조치는 GitHub 이슈,
서사·원칙·설계는 `docs/` 다.

## 작업 규율

- **위임 라우팅** (모델별 자세는 claude-model-postures 플러그인 훅이 주입한다 — 이 절은
  메인 모델이 무엇이든 적용되는 always-on 층):
  - 규모 있는 구현은 메인 세션에서 인라인하지 않는다. 스펙(정확한 델타·범위·산출물·
    정지조건·제외)을 쓰고 executor 서브에이전트(`model: opus`)에 위임한 뒤 결과를
    검증한다. 승인된 스펙에 빠르게 수렴하는 executor 는 결함이 아니라 의도된 동작이다.
  - 항목별 판단이 필요한 팬아웃(리더 패널·감사·스윕)은 Sonnet 워커, 경계 지어진 기계적
    읽기·변환은 Haiku 워커. 반환은 핵심 수치·경로의 추출로 받는다 — 원문 덤프 금지.
  - 병렬 워커는 직교성 인증이 전제다: `gui/style.py` 는 단일 소유자라 둘 이상 병렬 금지,
    domain 변경은 `gui/*_state.py` 로 파문되므로 같은 기능은 한 워커에 묶고, `hwpxcore`
    변경은 저장소 전역으로 파문되므로 단일 워커 직렬. 확신이 없으면 직렬이 기본값이다.
  - diff 리뷰는 계획 일치와 별개로 **기존 코드와의 교차 계약**을 확인한다(전부 blocker):
    새 UI 컨트롤의 기존 열거형(busy/disabled 잠금 id 목록 등) 등록, 프론트 트리거↔백엔드
    액션의 양방향 존재, 기존 공유 팩토리·상수·헬퍼의 인라인 재구현 여부, 문서화된 seam
    계약(docstring 의 접근 제한 등) 우회 여부.
- 링1 공개 API 를 바꾸면 소비 컨트롤러와 헤드리스 테스트를 같은 변경에 담는다. DOM `id`·
  `data-*`·script 순서·화면 루트를 바꾸면 **그 좌표를 든 게이트를 같은 변경에 담는다** —
  지금 그것을 지키는 것은 selftest 프로브(`frontend/src/selftest/probes/`)·live101 대본
  (`scripts/live101/scenario.py`)·press geometry(`tests/test_web_press_geometry.py`)·
  blocker 어포던스 표(`src/hwpxfiller/webapp/blocker_affordance.py` + 그 계약 테스트)다.
  종전 서술이 가리키던 별도의 「정적 DOM 계약」 파일(`test_web_dom_contract.py`·
  `test_web_datazone.py`)은 **존재하지 않는다**(#932 B4).
- 동결 목업(`docs/UI_PROTOTYPE_APPB.html`, `docs/r-flow-mockups/`)은 현재 기능을 설계·검증하려고
  먼저 고치지 않는다.
- 커밋 메시지는 한국어 Conventional Commits + PR 번호(`feat: … (#319)`, 파괴적 변경은 `feat!:`).
- 커밋하지 않는 것: `.venv/`, `.secrets/`, `build/`·`dist/`·`installer-dist/`, coverage·pytest 보고서,
  `.claude/settings.local.json`, `research-private/`.
- 작업/템플릿 **태그·그룹은 동결**이다(U4 §2-30) — 모델·판정·영속(`Job.tags`·`Job.group`·
  `webapp/template_groups.py`·설정의 `template_groups`·`job_collapsed_groups`)은 지우지 않고
  두되 **웹 표면에 노출하지 않는다**: 지정·개명·해산·접힘·태그 편집·태그 facet 동사가 전부
  걷혔고 링2 투영도 그 축을 묻지 않는다(`library_sections(grouped=False)` ·
  `build_sections(grouped_view=False)`). 되살릴 때 그 자리에서 다시 소비하면 된다.
- 나라장터(조달청 API) 소스는 **동결**이다 — 어댑터·CLI 접합부만 유지하고 웹 표면에 노출하지
  않는다. 풀에 있는 nara 항목은 숨기지 말고 시끄럽게 거절한다. 테스트는 실 API·서비스 키
  대신 `tests/fixtures` 의 응답을 쓴다.
