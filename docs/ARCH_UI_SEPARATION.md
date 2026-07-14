# 아키텍처 결정 — UI 디자인 / 백엔드 분리 (앱 B)

## 문제

앱 B(문서 생성기)의 UI를 설계 문서에서 목업(`UI_PROTOTYPE_APPB.html`)으로 옮긴 뒤 두 압력이 생겼다:
(1) 목업이 실제 구현을 반영하는 살아있는 스펙이어야 하고, (2) **UI 디자인 패스가 백엔드 수정을
강요하면 안 된다**. 실제로 두 누수가 있었다 — 색 hex가 `style.py`·`mapping_table.py`·목업 세 곳에
손으로 중복(드리프트), 그리고 `run_view.py`·`home.py`가 위젯 안에서 `ExcelDataSource`·`HwpxEngine`·
레지스트리를 직접 만짐(프레젠테이션↔백엔드 결합).

## 결정 — 3링 레이어링 + 토큰 파이프라인 + 목업=스펙 seam

**Qt(PySide6)가 계속 실제 UI다. 목업은 디자인 단일출처(SoT)이지 런타임이 아니다.**

### 링 (의존은 안쪽으로만, 안쪽 링은 Qt 미포함)

- **링0 — 도메인/코어** (`core/*`, `data/*`): `Job`·`JobRegistry`·`RunRequest`·`MappingProfile`·
  `HwpxEngine`·`DataSource` 포트. UI 이유로 절대 바뀌지 않는다. 이미 Qt 비의존·헤드리스 테스트됨.
- **링1 — 앱/ViewModel** (Qt-free): `mapping_state.MappingModel`·`selection_state.SelectionModel`
  (기존) + `home_state.HomeViewModel`·`run_state.RunViewModel`(신규) + `data/factory.py`.
  이후 착지 VM 6종도 같은 링이다: `matrix_state`·`dataset_pool_state`·`pipeline_builder_state`·
  `vocab_workbench_state`·`template_manager_state`·`nara_state`(전부 PySide6 무임포트 —
  링0/`data`만 의존, 2026-07-12 임포트 확인). **PySide6 임포트 금지.** 변경 통지는 Qt 시그널이 아니라 순수 옵저버 콜백. 상태는 직렬화 가능
  dataclass(`JobRow`·`PreflightResult`·`PrevNote`·`GateError`)로 낸다.
- **링2 — 프레젠테이션/Qt + 토큰** (얇은 렌더러): `style.py`·위젯·화면·`app.py`. ViewModel을 들고
  바인딩, Qt 시그널·`QThread`·`QMessageBox`·`QFileDialog`는 여기서만. **디자인 패스가 만지는
  유일한 링**(+ 토큰 파일). 예: 시트 확정 다이얼로그(`view_helpers.ask_sheet_choice`, T2 —
  `QInputDialog`)는 이 링이다 — 링1 VM은 다이얼로그의 존재를 모른 채 **확정된 `sheet` 값만**
  키워드 인자(`load_data(path, sheet=None)`)로 수취해 팩토리로 관통시킨다(취소=중단 판정도
  링2 소관, [UI_CONTRACT.md](UI_CONTRACT.md) 데이터 겨눔 콜백 계약).

**계약 seam = 링1 ViewModel 공개 API + 상태 dataclass.** ([UI_CONTRACT.md](UI_CONTRACT.md))

### 토큰 파이프라인 (디자인 색 = 데이터, 코드 아님)

`gui/design_tokens.json` 단일 출처 → `scripts/gen_design_tokens.py` 가 `style.py` 의 `<gen:tokens>`
영역(팔레트 상수)과 목업의 `<gen:tokens>` 영역(`--a-*` CSS 변수)을 함께 찍는다. 색 변경 = JSON
1곳 편집 + regen, 백엔드·QSS 구조 무접촉. `tests/test_design_tokens.py` 가 드리프트를 CI에서 막고,
`mapping_table.py` 는 색 리터럴 대신 `style` 상수를 임포트한다. 생성물은 **커밋되는 소스**다
(패키징 exe는 쓰기 가능 폴더가 없어 런타임 생성 불가; 생성기는 dev/CI 전용).

### 목업 = 스펙

목업 정적 요소에 `data-vm="클래스.속성"` 주석을 달고 `tests/test_ui_contract.py` 가 그 전부가 실제
ViewModel 표면에 존재하는지 검사한다 — 디자인 스펙과 구현이 조용히 갈라지지 않게.

## 결과 — 이 분리가 보장하는 것

- **디자인 패스**(색·레이아웃·위젯·상시 인라인 게이트 형태 등)는 링2 + 토큰만 건드린다.
  링0/링1은 불변 → 백엔드 회귀 위험 0.
- **소스 종류 확장**(누적치환·나라장터·API 직결)은 `data/factory.py` 에만 추가 → UI/VM 무수정.
- **로직 회귀 방어**는 헤드리스로 — `test_home_state.py`·`test_run_state.py`·`test_data_factory.py`
  는 QApplication 없이 링1을 검증하고, `test_gui_smoke.py`(offscreen)는 배선만 확인한다.

## 지켜야 할 불변식

- 링1은 PySide6를 임포트하지 않는다(헤드리스 테스트 가능성이 그 증거).
- 위젯의 Qt 시그널 계약(`*_job_requested`·`run_finished`·`completeChanged`·`selectionChanged`·
  `job_saved`)과 스모크가 찌르는 속성(RunView `datasource`/`records`/`_template_override`/
  `_effective_template()`/`_on_generate()`/`_thread`, Home `list`/`stack`/`btn_empty_new`)은
  위임 프로퍼티로 보존한다 — 개명 시 green 깨짐.
- 기존 ViewModel(`MappingModel`·`SelectionModel`)을 재발명하지 않는다 — 새 VM은 이들을 질의한다.
- 명시성 게이트(`MappingModel.is_complete`)·실행 시 매핑 재확정 없음·누락 시끄럽게(`MISSING_MARKER`)는
  ViewModel로 옮겨도 그대로다(리팩터는 재배치이지 정책 변경이 아니다).

## 스코프 밖

HWPX 트랙 앱 B만. diff 리뷰어(앱 A `hwpxdiff`)·txt 트랙·앱 B용 PyInstaller spec은 별개.
링1 `EditorSession` dataclass는 연기(위저드 세션 상태는 현행 유지; `DataPage` 데이터 로드만
팩토리 경유로 정리했다).
