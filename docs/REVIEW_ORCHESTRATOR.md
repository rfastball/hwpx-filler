# 병렬 코드·프로덕트 리뷰 오케스트레이터 — 킥오프 설계서

> **용도**: 새 세션에서 이 문서 하나를 포인터로 읽고 리뷰 라운드를 즉시 실행하기 위한
> 자기완결 설계서. 2026-07-12 킥오프 세션의 저장소 전수 탐색(병렬 4에이전트) +
> 실행 스모크(두 GUI offscreen 렌더·캡처 성공, corpus 실물로 신구대비표 렌더 확인)에
> 근거한다. 본 문서의 파일:라인 인용은 킥오프 시점 기준 — 실행 전 유효성 재확인 필수.
>
> **새 세션 킥오프 방법**: 이 문서를 읽고 §9 실행 절차의 라운드 1을 수행하라.
> 대규모 수정·리팩터링은 리뷰 범위 밖(발견·검증·보고까지만).

---

## 1. 프로젝트 요약 (탐색 확정 사실)

**제품 2개 + 공통 코어 1개의 Windows 데스크톱 모노레포.** 웹·서버·모바일 요소 전무 —
반응형·세션·rate limit·실시간 동기화 등은 리뷰 항목에서 전부 제외한다.
유일한 네트워크 표면은 나라장터 조달청 API 취득 하나.

```yaml
products:
  - id: hwpxdiff            # 앱 A — 읽기 도구
    purpose: 규격서 개정 두 판본의 의미 기반 비교(전문 신구대비표)
    user_interfaces: [GUI(PySide6 QMainWindow), CLI]
    entry_points: [python -m hwpxdiff → app.DiffReviewWindow, hwpxdiff.cli:main]
    core_dependencies: [hwpxcore]        # hwpxfiller 임포트 금지(패키징에서도 제외)
    outputs: [화면 신구대비표, stdout 요약, HTML 리포트]
    packaging_target: dist\hwpx-diff\hwpx-diff.exe (onedir + Inno 설치본)

  - id: hwpxfiller          # 앱 B — 쓰기 도구
    purpose: 누름틀 템플릿에 데이터(Excel/CSV/나라장터/파이프라인) 주입 → 공고서 일괄 생성
    user_interfaces: [GUI(다중 톱레벨 창 허브 — JobListHome), CLI(서브커맨드 7종)]
    entry_points: [hwpxfiller.gui.app:main, hwpxfiller.cli:main]
    core_dependencies: [hwpxcore]
    outputs: [생성 .hwpx 배치, fill-ledger.json(opt-in), txt 기안 렌더/클립보드]
    packaging_target: dist\hwpx-filler\hwpx-filler.exe (+ CLI 전용 spec)

shared_layers:
  - path: src/hwpxcore
    responsibility: OCF zip 열기/저장, 본문 트리 추출, 사전검증 — 제품 로직 없음
    allowed_dependents: [hwpxdiff, hwpxfiller]
    forbidden_dependencies: [양 제품, PySide6, 제품 어휘(나라장터 코드 등)]
  - path: src/hwpxfiller/gui/design_tokens.json + scripts/gen_design_tokens.py
    responsibility: 팔레트 단일 원천 → 양 제품 style.py의 <gen:tokens> 블록 생성(의도된 복제)
```

환경: Python 3.13(uv 고정, `uv.lock`), lxml+openpyxl, GUI는 PySide6 extra.
품질 게이트 `.\test.ps1`(ruff→pyright→pytest+coverage, offscreen). `.venv` 준비 완료.

## 2. 아키텍처 경계 지도 — 무엇이 이미 집행되고, 어디가 틈인가

의존 방향 `hwpxdiff → hwpxcore ← hwpxfiller`는 **테스트로 집행**된다:

- `tests/test_architecture.py` — AST 기반: 제품 상호 임포트 금지, core의 제품 어휘 금지,
  `core`/`data`/CLI의 Qt 무임포트, `hwpxdiff/diff.py`의 stdlib-only.
- `tests/test_ui_contract.py` + `docs/UI_CONTRACT.md` — 목업(`docs/UI_PROTOTYPE_APPB.html`)의
  `data-vm` 셀렉터 ↔ ViewModel 멤버 계약.
- `tests/test_design_tokens.py` — 토큰 드리프트 가드.
- `tests/test_partial_gate.py` — PARTIAL 템플릿 확인-또는-경보 게이트.
- GUI 3링 모델(`docs/ARCH_UI_SEPARATION.md`): 링0 도메인 ↔ 링1 순수 ViewModel(`gui/*_state.py`,
  Qt 임포트 금지) ↔ 링2 Qt 뷰.

**따라서 리뷰 초점은 선언된 경계 위반이 아니라, 테스트가 못 보는 틈 4곳:**

1. **흐름 접착층의 GUI/CLI 이중화** — 프리미티브(engine/batch/fill_ledger/job)는 공유되나
   오케스트레이션이 `cli.py:326-368`과 `run_state.py`(RunViewModel)에 각각 존재.
   드리프트 하드게이트 3곳(`cli.py:341`, `run_state.py:282`, `batch.py:130-141`),
   원장 export 2곳(`cli.py:371` vs `run_state.py:327`), 나라 취득 경로 2갈래
   (CLI에는 resultCode 검증·키리스 스냅샷 없음).
2. **링1→링2 누수** — 도메인 게이트 판단이 위젯에 상주:
   `run_view.py:398-423`(드리프트 종류 해석+차단 메시지+버튼 활성이 위젯 안),
   `home.py:36`(CompileState→색상 분기).
3. **hwpxdiff GUI의 도메인 성형 로직** — `_coalesce_ops`/`_group_changes`/`_row_group_key`가
   `app.py`에 상주(92-179행 부근), `_snippet`은 `app.py:131`과 `diff.py:635`에 사본 2개.
4. **hasattr 전방호환 배선의 침묵 실패** — `app.py:39`가 `manage_templates_requested`를
   가드하지만 `home.py`는 그 시그널을 정의하지 않음(135-198행에 pool/matrix/vocab만 존재)
   → **템플릿 관리 워크숍이 GUI에서 도달 불가**(킥오프에서 grep으로 확정).
   확인-또는-경보 원칙을 라우팅 계층이 스스로 어긴 사례.

## 3. 기능 지도

| # | 기능 (사용자 목표) | 인터페이스 | 진입점 | 관련 코드 | 실패 상태(존재 확인) | 위험도 |
|---|---|---|---|---|---|---|
| F1 | 작업(Job) 저작 — 템플릿·데이터·매핑 명시 확정·저장 | GUI | 홈→JobEditorWizard | `job_editor.py`, `wizard.py`(718줄), `mapping_state.py`(PARTIAL 게이트), `mapping_table.py` | RAW/PARTIAL 차단, 매핑 미확정 행, ack 불일치 | **높음** |
| F2 | 단일 작업 실행 — 레코드 선택→프리플라이트→일괄 생성 | GUI | 홈→RunView | `run_view.py`(537줄), `run_state.py`, `worker.py`, `batch.py`, `fill_ledger.py` | 드리프트 차단, 누락열, 빈값 ack, 부분 실패, **기존 파일 덮어쓰기 무가드, 취소 불가** | **최고** |
| F3 | 매트릭스 일괄 실행 (M작업×공유데이터) | GUI | 홈→MatrixRunView | `matrix_view.py`, `matrix_state.py`, `batch.generate_matrix` | 전작업 사전 드리프트 게이트(원자적), 부분 실패 | 높음 |
| F4 | 나라장터 취득·키 관리 | GUI+CLI | NaraAcquireDialog / `--source nara` | `nara_view.py`, `nara_state.py`, `data/nara.py`, `data/secret_store.py` | NaraFetchError(키 마스킹), resultCode≠00, **UI 스레드 동기 네트워크** | 높음 |
| F5 | 데이터셋 풀 관리(참조 등록·수명주기) | GUI | 홈→DatasetPoolPanel | `dataset_pool_panel.py`, `core/dataset_pool.py`, `data/factory.py` | 참조 원본 소실, 활성/보관/은퇴 전이 | 중간 |
| F6 | 파이프라인 조립(merge/append) | GUI | PipelineBuilder 다이얼로그 | `pipeline_builder.py`, `data/pipeline.py` | AssemblyError(시끄러운 실패) | 중간 |
| F7 | 템플릿 관리 워크숍(fieldize/lint/드리프트) | GUI(**도달 불가**)+CLI | `app._open_template_manager`(사각) / CLI lint·drift | `template_manager.py`, `core/template_status.py`, `core/authoring.py`, `core/lint.py` | GUI 진입 자체가 실패 상태 | **높음(확정 결함 포함)** |
| F8 | 어휘 워크벤치(공유 베이스 매핑) | GUI | 홈→VocabWorkbench | `vocab_workbench.py`, `core/mapping_base.py` | 베이스 삭제 시 참조 작업 영향 | 중간 |
| F9 | txt 기안 즉석 렌더(온나라 등) | GUI+CLI | 홈 txt 트랙 / `render` | `txt_view.py`, `core/text_render.py`, `core/text_registry.py` | 미치환 `{{토큰}}` 잔존(의도된 loud), 클립보드 실패 | 낮음~중간 |
| F10 | CLI 일괄 채우기 + 원장 export | CLI | 기본 흐름 `--template --data --out` | `cli.py:299-412`, `batch.py`, `naming.py` | 검증 실패 exit1, 부분 실패, F2와 동일 덮어쓰기 문제 | **높음** |
| F11 | CLI 저작 도구(schema/fieldize) | CLI | 서브커맨드 | `cli.py:33-88`, `core/schema.py`, `core/authoring.py` | dry-run 미리보기, 저장 실패 | 중간 |
| F12 | 개정 비교 리뷰(신구대비표) | GUI | `python -m hwpxdiff` | `hwpxdiff/app.py`(539줄), `hwpxdiff/diff.py`(858줄) | 파싱 실패 모달, 빈 비교, 대용량 문서 | 중상 |
| F13 | diff CLI 요약·HTML 리포트 | CLI | `hwpxdiff OLD NEW --html` | `hwpxdiff/cli.py`(36줄), `diff.render_html` | 파일 없음, 쓰기 실패 | 낮음 |
| F14 | 패키징·selfcheck·설치 | 패키징 | `build.ps1`, release.yml | `packaging/*` | spec 계약 위반, selfcheck 실패 | 중간(라운드 3) |

위험도 근거: F2/F10은 법적 효력 문서를 디스크에 쓰는 경로 + 덮어쓰기·취소 부재 + 이중 구현.
F1은 UI 복잡도 최대 + 명시성 게이트 심장부. F7은 확정 결함 보유. F4는 비밀·네트워크·UI 블로킹 교차점.

## 4. UI 렌더링 — 실행 검증된 캡처 레시피

킥오프에서 두 GUI 모두 offscreen 렌더·`QWidget.grab()` 캡처에 성공했고,
corpus 실물 규격서 2판본으로 hwpxdiff 신구대비표(KPI 타일 36/41/78/7, 변경 그룹
네비게이션, 낱말 del/ins 강조)까지 관찰했다. 브라우저 자동화는 불필요·부적용.

**표준 env (전 UI Auditor 실행 공통):**

| env | 값 | 이유 |
|---|---|---|
| `QT_QPA_PLATFORM` | `offscreen` | 헤드리스 렌더 |
| `QT_QPA_FONTDIR` | `C:\Windows\Fonts` | **없으면 한글 전부 □(tofu)** — 킥오프 대조 캡처로 확증 |
| `HWPXFILLER_HOME` | 임시 폴더 | 사용자 실 작업/풀/어휘(`~/.hwpxfiller`) 오염 방지 — 전 레지스트리가 이 루트를 따름 |

**검증된 스모크 스크립트 원형** (킥오프 세션 스크래치패드에서 실행 성공 — 필요 시 재작성용):

```python
# .venv/Scripts/python.exe 로 실행. 저장소 루트가 cwd.
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

# 앱 B 홈 (임시 registry로 실데이터 비접촉)
from hwpxfiller.core.job import JobRegistry
from hwpxfiller.gui.app import _AppController
ctl = _AppController(JobRegistry(tempfile.mkdtemp(prefix="review-jobs-")))
ctl.home.resize(1280, 800); ctl.home.show(); app.processEvents()
ctl.home.grab().save("filler_home.png")

# 앱 A 신구대비표 (corpus 실물)
from hwpxdiff.app import DiffReviewWindow
w = DiffReviewWindow(); w.resize(1400, 900); w.show()
w.ed_old.setText("tests/corpus/real/spec_revision_2025.hwpx")
w.ed_new.setText("tests/corpus/real/spec_revision_2026.hwpx")
w._on_compare(); app.processEvents()
w.grab().save("diff_populated.png")
```

- **컨트롤→소스 추적**: 위젯이 `self.btn_generate`, `self.ed_old` 같은 명명 속성으로
  노출되고 뷰↔VM 배선이 파일 규약(`<screen>.py` + `<screen>_state.py`)을 따르므로
  정적 grep만으로 역추적 가능. 추가 instrumentation 불요.
- **테스트 데이터**: `tests/corpus/scenario/`(입찰공고서.hwpx 22필드, 구매요청서.hwpx,
  조달_한글.csv/xlsx, 나라장터 응답/매핑 JSON) + `tests/corpus/real/` + 루트
  `sample_bid_data.csv`. 합성 상태는 `tests/fixtures/make_hwpx.py`/`make_xlsx.py`로 조성.
- **나라장터 실패 상태**: 주입 가능한 `fetcher`(`data/nara.py:104`)로 재현.
  **실 API·실 ServiceKey 호출 금지**(저장소 정책, `docs/DEVELOPMENT_ENVIRONMENT.md`).
- **알려진 제약**: offscreen 캡처는 글꼴이 실 디스플레이보다 가늘고 네이티브 테마가 빠짐.
  레이아웃·구조·상태 판단에는 무영향. 픽셀성 이슈 의심 시에만 기본 플랫폼으로 재캡처,
  아니면 `investigation_needed`로 격하.
- **offscreen 모달 주의**: `QMessageBox` 등 모달은 블로킹 — 스모크 테스트가 하듯
  monkeypatch로 우회(`tests/test_gui_smoke.py:720-722` 참조).

## 5. 에이전트 구조 (이 프로젝트에 필요한 역할만)

Project Mapper는 킥오프가 수행 완료(본 문서가 산출물). **제외**: 브라우저/웹 자동화,
접근성 트리, 서버·동시성 에이전트 — 해당 표면이 존재하지 않음.

| 역할 | 필요한 이유(탐색 근거) | 입력 | 출력 | 병렬 | 의존 |
|---|---|---|---|---|---|
| **Rendered UI Auditor** | 목업↔VM 계약은 있으나 픽셀·흐름은 무가드("human eye") 영역 — §4 레시피로 실행 가능 검증됨 | 작업 패키지 + §4 레시피 + corpus | 캡처 PNG + 재현 절차 + 관찰→위젯/핸들러 매핑 | 기능별(각자 임시 HWPXFILLER_HOME) | 없음 |
| **UI Coupling Reviewer** | fat handler(`run_view.py:431-481`), 뷰 상주 도메인 게이트, QThread 배선·`_open_folder` 사본(run/matrix 동일), hasattr 침묵 배선 | 작업 패키지 + 링 규율 문서 | 결합 이슈(파일:라인+영향) | 기능별 | 없음 |
| **Naming & Semantics Reviewer** | "어휘/베이스/매핑프로파일" 3용어 1개념, `fb` 불투명 축약, `_JobCard` 등 언더스코어 주력 클래스, "은퇴" 상태명 | GUI 문구·CLI 도움말·docs 용어·코드 심볼 4원 대조 | 용어 불일치·모호명 이슈 | **전역 1패스**(교차 비교가 본질) | 없음 |
| **Workflow Failure Reviewer** | 덮어쓰기 무가드(`naming.py:94`는 배치 내 충돌만), 취소 부재(`batch.py:35`), UI 스레드 동기 네트워크(`nara_state.py:212`), 비원자 저장(`package.py:70`, LESSONS K/A) | 작업 패키지 + 실패 상태 목록 + fixture 빌더 | 실패 시나리오 실행 증거 | 기능별 | 없음 |
| **Cross-Surface Correlator** | GUI/CLI 흐름 접착 이중화가 중심 문제 — 개별 발견의 공통 원인 병합 필수 | 위 4역할 전체 발견 | 근본 원인 단위 이슈 트리 | 아니오(배리어 뒤 1개) | 4역할 전체 |
| **Verifier & Review Editor** | 증거 규칙 집행: 재현·파일:라인 확인·취향/결함 구분·`investigation_needed` 분류 | 병합 이슈 | 최종 이슈 목록(§7 스키마) | 이슈별 병렬 | Correlator |

**오케스트레이션 흐름:**

```text
Feature Work Packages (§6)
  → Parallel Review  ┬ Rendered UI Auditor   (F별)
                     ├ UI Coupling Reviewer  (F별)
                     └ Workflow Failure Rev. (F별)
     + Naming & Semantics Reviewer (전역 1패스, 병행)
  → [배리어] Cross-Surface Correlation
  → Verification (이슈별 병렬 — 재현 + 반증 시도)
  → Review Editing (심각도·신뢰도 확정, 최종 보고)
```

기능 간에는 배리어 없이 흘려보내고(파이프라인), 배리어는 Correlation 앞 한 곳만.

## 6. 리뷰 매트릭스와 라운드 1 작업 패키지

| 기능 | UI 렌더링 | 명명 | 결합 | 실패 흐름 | 경계 검토 | 우선순위 |
|---|---:|---:|---:|---:|---:|---:|
| F2+F10 문서 생성 쌍 | ✅ | ✅ | ✅ | ✅ | ✅(중복 흐름) | 1 |
| F1 작업 저작 위저드 | ✅ | ✅ | ✅ | ✅(PARTIAL 게이트) | — | 2 |
| F12 diff GUI 리뷰 | ✅ | ✅ | ✅(app.py 성형 로직) | 소 | ✅(diff.py 이관 후보) | 3 |
| F7 템플릿 워크숍+홈 라우팅 | ✅(도달 불가 확정) | ✅ | ✅(hasattr 배선) | — | — | 4 |
| F4 나라장터 취득·키 | ✅ | 소 | ✅(스레딩 비대칭) | ✅ | ✅(CLI 격차) | 5(여력 시) |
| F3 매트릭스 / F5 F6 F8 F9 F11 F13 | 라운드 2 | 전역패스 포함 | 선별 | 선별 | — | 6+ |
| F14 패키징 | — | — | — | selfcheck만 | spec 제외 규칙 | 라운드 3 |

### 라운드 1 작업 패키지 (4+1)

```yaml
- feature: F2+F10 문서 생성(GUI 단일 실행 + CLI 기본 채우기 — 교차 쌍)
  product: hwpxfiller
  user_goal: 확정된 작업에 데이터를 대고 공고서 배치를 생성한다
  interface: gui+cli
  entry_point: RunView / python -m hwpxfiller.cli --template ... --data ... --out ...
  scope: [gui/run_view.py, gui/run_state.py, gui/worker.py, batch.py, naming.py,
          cli.py:245-412, core/fill_ledger.py]
  excluded_scope: [매트릭스(F3), 나라 취득(F4), 데이터셋 풀(F5)]
  input_examples: [tests/corpus/scenario/templates/입찰공고서.hwpx,
                   tests/corpus/scenario/data/조달_한글.csv, sample_bid_data.csv]
  scenarios:
    - 드리프트 차단(템플릿 교체 후 실행 시도)
    - 빈값 ack 게이트(미입력 확인 흐름)
    - 기존 동명 파일이 있는 폴더로 생성 → 덮어쓰기 관찰
    - 생성 중 오류 1건 섞인 배치의 부분 결과·요약 표시
    - --ledger 왕복(export → verify_output 읽기 검증)
    - GUI와 CLI 동일 입력 → 산출 동등성 비교
  review_focus: [fat handler 분해 타당성, 게이트 3중화, 원장 export 이중화,
                 덮어쓰기·취소 실패 흐름, 진행/완료 후 다음 행동 명확성]
  evidence_required: [캡처, 파일:라인, 런타임 로그, 생성 파일 상태]
  completion_criteria: 시나리오 전건 실행 + 관찰-원인 연결 초안

- feature: F1 작업 저작 위저드
  product: hwpxfiller
  user_goal: 템플릿·데이터·매핑을 명시적으로 확정해 durable Job으로 저장한다
  interface: gui
  entry_point: 홈 → 새 작업 → JobEditorWizard 3단계
  scope: [gui/job_editor.py, gui/wizard.py, gui/mapping_state.py, gui/mapping_table.py,
          gui/record_select.py, core/job.py, core/mapping.py]
  excluded_scope: [실행(F2), 어휘 워크벤치(F8)]
  input_examples: [tests/corpus/scenario/templates/*.hwpx, 조달_한글.xlsx,
                   fixtures/make_hwpx.py로 만든 RAW/PARTIAL 템플릿]
  scenarios:
    - RAW/PARTIAL 템플릿 진입 → 게이트 차단 화면·ack 재진술 요구
    - 매핑 행 확정 전/후 완료 버튼 상태
    - 기본 파일명 패턴 이중 기본값("공고서-{{ID}}" vs "output-{{ID}}") 관찰
    - 긴 필드명·많은 행에서 매핑 테이블 레이아웃
  review_focus: [wizard.py 718줄 책임 분해, "wizard/에디터" 명명 잔재,
                 표시형·구분자 열 용어(fmt/sep/const) 대 UI 문구]
  evidence_required: [단계별 캡처, 파일:라인]
  completion_criteria: 3단계 전 과정 캡처 + 게이트 상태 4종 관찰

- feature: F12 개정 비교 리뷰(hwpxdiff GUI)
  product: hwpxdiff
  user_goal: 규격서 2판본의 변경을 신구대비표로 검토한다
  interface: gui (+cli 대조)
  entry_point: python -m hwpxdiff
  scope: [hwpxdiff/app.py, hwpxdiff/diff.py, hwpxdiff/cli.py, hwpxdiff/style.py]
  excluded_scope: [hwpxfiller 전체]
  input_examples: [tests/corpus/real/spec_revision_2025/2026.hwpx,
                   form_purchase_v1/v2.hwpx, tests/corpus/golden_diff/*.json]
  scenarios:
    - 정상 비교(§4 스모크 재현) + 필터 체크박스·번호변경 토글 상호작용
    - 변경 그룹 선택 → 앵커 스크롤 정합
    - 동일 파일 2회 비교(변경 0건) 화면
    - 손상/비HWPX 파일 → 오류 모달 문구
    - CLI --html 리포트와 GUI 표현의 정보 동등성
  review_focus: [app.py 상주 성형 로직(_coalesce_ops/_group_changes/_row_group_key)의
                 diff.py 이관 타당성, _snippet 사본 2개, KPI 타일·필터 행 시각 위계]
  evidence_required: [캡처, 파일:라인, golden 대조]
  completion_criteria: 시나리오 전건 + 성형 로직 이관 판단 근거

- feature: F7 홈 라우팅·템플릿 관리 워크숍
  product: hwpxfiller
  user_goal: 홈에서 템플릿 위생(컴파일·lint·드리프트)을 관리한다
  interface: gui (+cli lint/drift 대조)
  entry_point: (현재 GUI 도달 불가 — 그 자체가 이슈) / CLI lint·drift
  scope: [gui/app.py(_AppController 배선 전체), gui/home.py, gui/template_manager.py,
          gui/template_manager_state.py, core/template_status.py]
  excluded_scope: [저작 위저드 내부(F1)]
  scenarios:
    - manage_templates_requested 부재 확정 재현(런타임에서 버튼/경로 부재 확인)
    - hasattr 가드 4곳 전수: 어느 것이 살아있고 어느 것이 침묵 no-op인지
    - TemplateManagerPanel 직접 인스턴스화로 화면 자체 품질 관찰(도달 불가와 별개)
    - CLI lint/drift와 워크숍 기능의 동등성
  review_focus: [전방호환 hasattr 패턴 vs 확인-또는-경보 원칙, 죽은 라우트 처리 권고]
  evidence_required: [grep+런타임 증거, 캡처]
  completion_criteria: 배선 감사표 + 확정 이슈화

- feature: F4 나라장터 취득·키 관리 (여력 시)
  product: hwpxfiller
  interface: gui+cli
  scope: [gui/nara_view.py, gui/nara_state.py, data/nara.py, data/secret_store.py,
          cli.py:210-279]
  scenarios: [주입 fetcher로 성공/HTTP실패/resultCode≠00, 키 마스킹 확인(redact),
              UI 스레드 블로킹 관찰(지연 fetcher), CLI 경로의 resultCode 미검증 격차]
  constraint: 실 API·실 ServiceKey 절대 사용 금지 — fixtures/nara_std_response.json만
```

## 7. 증거 기준

각 확정 이슈는 아래 JSON 스키마로 기록한다:

```json
{
  "feature": "F2", "interface": "gui | cli | library | packaging",
  "scenario": "...", "type": "defect | convention_deviation | code_smell | polish | investigation_needed",
  "category": "...", "severity": "critical | high | medium | low",
  "title": "...", "observed_behavior": "...", "expected_behavior": "...", "user_impact": "...",
  "visual_evidence": {"screenshot": "...", "window_state": "...", "target_control": "..."},
  "code_evidence": [{"file": "...", "lines": "...", "symbol": "..."}],
  "runtime_evidence": {"command": "...", "logs": [], "test_result": "..."},
  "architectural_impact": "...", "root_cause": "...", "recommendation": "...",
  "verification_method": "...", "confidence": 0.0
}
```

규칙: 실행 못 한 UI를 본 것처럼 쓰지 않는다 / 파일:라인 미확인 구조 문제는 확정 표현 금지 /
취향≠결함 / 재현 불가는 `investigation_needed` / 동일 근본 원인의 다중 증상은 한 이슈로 병합 /
수정 제안은 관찰 영향에 비례, 최소 책임 경계 우선. **심각도 가중**: 이 저장소의 자체 원칙
(확인-또는-경보)상 "조용한 추측/조용한 no-op"류는 같은 냄새라도 한 단계 상향.

## 8. 킥오프 선행 발견 (라운드 1 검증 대상 — 확정 아님, ①만 확정)

1. **[확정·defect]** 템플릿 워크숍 GUI 도달 불가 — `gui/app.py:39` hasattr 가드가
   `home.py`에 없는 시그널을 기다림 → 침묵 no-op. (`home.py`엔 pool/matrix/vocab만)
2. 출력 덮어쓰기 무가드 — `naming.py:94` `_dedupe`는 배치 내 충돌만, 디스크 기존 파일은
   `engine.generate`→`package.py:70` 무조건 기록.
3. 배치 취소 불가 — `batch.py:35` progress 콜백만, cancel 토큰 없음. `worker.py:26`도 무중단.
4. 나라 취득이 UI 스레드에서 동기 실행 — `nara_state.py:212,250` + `nara_view.py:202`.
5. 드리프트 하드게이트 3중화 — `cli.py:341` / `run_state.py:282` / `batch.py:130-141`.
6. 원장 export 병렬 구현 — `cli.py:371` vs `run_state.py:327`(source_pointer 로직 상이).
7. diff `_snippet` 사본 2개 — `hwpxdiff/app.py:131` / `hwpxdiff/diff.py:635`.
8. `run_view.py:431-481` fat handler(게이트+매핑+원장+스레딩+UI 혼재),
   `_open_folder`/`_teardown_thread`/QThread 배선이 run_view↔matrix_view에 사본.
9. 기본 파일명 패턴 이중 기본값 — `job_editor.py:138` "공고서-{{ID}}" vs `:106` "output-{{ID}}".
10. 파일 다이얼로그 필터 문자열 5곳+ 하드코딩(run_view/matrix_view/txt_view/dataset_pool_panel/wizard).
11. 용어 3중화: "어휘 워크벤치/공유 베이스/MappingProfile"이 한 개념.
12. 비원자 저장 `package.py:70`(temp+os.replace 후보 — `docs/UNIVCONTRACTOR_LESSONS.md` K/A 기왕 인지).

## 9. 실행 절차 (다음 세션이 수행할 라운드 1)

1. **준비**: `.venv` 존재 확인(`./.venv/Scripts/python.exe -c "import PySide6"`).
   없으면 `uv sync --locked --all-extras --group dev --group build`.
   증거 저장 위치: 세션 스크래치패드 `review-round1/<feature_id>/`(캡처·로그·이슈 JSON).
   저장소에는 쓰지 않는다(최종 보고만 대화/문서로).
2. **병렬 투입**: §6 패키지 4개 → 기능당 UI Auditor 먼저, 그 관찰을 물려 Coupling·Failure
   리뷰어 이어달리기(기능 간 배리어 없음). Naming 전역 1패스 병행.
3. **배리어**: 전량 도착 후 Cross-Surface Correlator 1개 — §8 선행 발견과 병합,
   근본 원인 단위 재편(예: "흐름 접착 이중화" 아래 5·6·게이트 증상 통합).
4. **검증**: 이슈별 병렬 Verifier — defect는 재현 스크립트 필수, 반증 시도 포함.
5. **편집**: 심각도·신뢰도 확정, 기능별/전역 분리, §7 스키마로 최종 보고.
6. **예상 충돌**: F2·F3의 worker/배선 사본은 같은 원인 이중 보고 예상(Correlator 병합);
   Naming 전역 패스와 기능별 지적 중복은 전역 패스 우선.

### 환경 함정 (필수 숙지)

- uv는 `%USERPROFILE%\.local\bin`에 있음(PATH 누락 주의). 저장소 스크립트는
  `uv run --no-sync ...` 패턴 — 직접 실행은 `./.venv/Scripts/python.exe`가 간단.
- pytest는 `--basetemp=.pytest-tmp` 필수(WinError5 플레이크). `test.ps1`이 이미 설정.
- `build.ps1`에 `2>&1` 금지(PS 5.1 NativeCommandError로 성공이 실패로 위장됨).
- 콘솔 한글: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`(스크립트들이 이미 설정).
- CLI `lint`는 이슈 발견 시 정상적으로 exit 1(자동화 게이트 의도) — 실패로 오판 금지.
- GUI 리뷰 산출물·임시 registry는 반드시 임시 `HWPXFILLER_HOME` 아래 — 사용자
  `~/.hwpxfiller` 절대 비접촉.

## 10. 실행 기록

- **라운드 1 완료 (2026-07-12)**: 원발견 140건 → 근본 원인 36건, 상위 20건 적대적 검증
  전건 confirmed. 전량 박제: **`docs/REVIEW_ROUND1_FINDINGS.md`** (패치 추적 표 포함 —
  후속 작업은 그 표를 원장으로 갱신). §8 선행 발견 12건은 전부 확정 또는 상위 이슈로 흡수.
- 라운드 2(F3/F5/F6/F8/F9/F11)·라운드 3(F14 패키징)은 미실행 — §6 매트릭스 그대로 유효.
- **UI 디자인 전용 라운드 완료 (2026-07-13)**: 별도 설계서
  [REVIEW_UI_ORCHESTRATOR.md](REVIEW_UI_ORCHESTRATOR.md)(디자인 5렌즈·캡처 뱅크) →
  발견 원장 [REVIEW_UI_FINDINGS.md](REVIEW_UI_FINDINGS.md)(UD-01~45).
