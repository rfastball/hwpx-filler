# UI 디자인 핸드오프 — 트랙 C 셸

이 문서는 **작업(Job) 앵커 데이터모델 + GUI 스캐폴드**(앱 B)와 **diff 리뷰어**(앱 A)가
랜딩된 뒤, 세부 UI 구현을 넘기기 위한 계약서다. 스캐폴드가 **고정한 이음새**(모듈 경계·
시그널/슬롯·데이터 바인딩 지점)와 **디자인이 채울 것**(레이아웃·위젯·스타일·상호작용)을
가른다. §0~§6 = 앱 B(생성기), §8 = 앱 A(diff 리뷰어).

> **관통 원칙 — UI는 기능이 거쳐 UX로 드러나는 통로다.** function → UX → UI 이지 그 역이
> 아니다. 빈 슬롯을 채우려 **없던 기능을 발명하지 말 것**(과거 "빠른 생성" 드리프트 재발
> 금지). 아래 각 화면의 UX는 안정된 기능에서 도출됐다 — 디자인은 그 위에 옷을 입힌다.

---

## 0. 전체 구조 — 3화면 + 오케스트레이터

```
gui/app.py  _AppController ──라우팅──┬─▶ home.JobListHome      (홈 = 작업 목록)
   (QApplication, 자식창 수명 소유)   ├─▶ job_editor.JobEditorWizard (작업 저작: 저장으로 끝)
                                     └─▶ run_view.RunView       (집행: 데이터 겨눠 생성)
```

- **홈**이 오케스트레이터다(하나의 태스크가 아니라 능력 라우터).
- **에디터**와 **집행**을 가른다: 무거운 명시성 게이트(매핑 확정)는 **셋업(에디터)에만**.
  집행은 사전검증만 — 매핑 재확정 없음.
- diff·템플릿관리 GUI는 이 앱(앱 B) 밖 별도 앱(앱 A)으로 분리 예정 — 이번 스캐폴드 범위 아님.

실행: `python -m hwpxfiller.gui.app` (또는 `hwpx-filler` gui-script). 헤드리스 테스트는
`QT_QPA_PLATFORM=offscreen` + `tests/test_gui_smoke.py`.

---

## 1. 데이터모델 계약 (`core/job.py`) — Qt 비의존, 이미 완성·테스트됨

디자인이 건드리지 않는다. UI가 **읽고 쓰는 대상**의 형태:

| 심볼 | 계약 |
|---|---|
| `Job(name, template_path, mapping: MappingProfile, filename_pattern, version)` | durable 바인딩 `{템플릿·매핑·파일명}`. **데이터·행은 없음**(집행 일회성). `template_fields()`·`source_keys()`·`to_dict/from_dict/save/load`. |
| `JobRegistry(directory)` | 작업당 JSON 1개. `save(job)`·`load(name)`·`exists`·`delete`·`list_jobs()`·`names()`. |
| `RunRequest(job, datasource, selected_indices)` | 1회 집행(저장 안 함). `selected_records()`·`mapped_records()`·`source_report()`·`output_report()`. **집행 로직은 여기 있다** — 뷰는 호출만. |
| `default_jobs_dir()` | GUI 기본 레지스트리 위치(`~/.hwpxfiller/jobs`, `HWPXFILLER_HOME` override). |

재사용 상태 모델(둘 다 Qt 비의존, 테스트 완비): `gui/mapping_state.MappingModel`,
`gui/selection_state.SelectionModel`. 재사용 위젯: `gui/mapping_table.MappingTable`,
`gui/record_select.RecordSelector`.

---

## 2. 홈 — `gui/home.py` `JobListHome(QMainWindow)`

**스캐폴드가 고정:**
- 생성자 `JobListHome(registry)`. `refresh()`가 `registry.names()`를 `self.list`(QListWidget)에 바인딩.
- **네비게이션 시그널 계약**(app.py가 배선, 바꾸지 말 것):
  - `new_job_requested` (인자 없음)
  - `edit_job_requested(str)` · `run_job_requested(str)` · `delete_job_requested(str)` (작업 이름)
- `selected_job_name()`, 선택 시 버튼 활성 토글(`_sync_buttons`).

**디자인이 채울 것:**
- 작업 **카드**(현재는 이름만 있는 QListWidget) — 템플릿명·필드수·최근 사용 등 메타 노출.
- **빈 상태**(작업 0개일 때 "새 작업 만들기" 유도).
- 레이아웃·버튼 배치·스타일. 앱 레벨 상태(기본 출력 폴더·나라 ServiceKey)는 후일 홈이 소유.

---

## 3. 작업 에디터 — `gui/job_editor.py` `JobEditorWizard(QWizard)`

**스캐폴드가 고정:**
- 4스텝: `TemplatePage → DataPage → MappingPage`(모두 `gui/wizard.py`에서 재사용) `→ SaveJobPage`.
- **명시성 게이트는 MappingPage에 그대로**(전 행 확정 전 진행 불가 = `MappingModel.is_complete`).
  이 게이트가 기능의 존재 이유다 — **약화 금지**.
- **마지막 스텝 = 저장**(생성 아님). `accept()`가 `model.to_profile()`로 `Job`을 굳혀
  `registry.save`. 성공 시 `job_saved(str)` 방출.
- 세션 상태는 위저드 속성으로(`template_path/schema/data_path/datasource/source_fields/records/model`).
- **샘플 데이터는 매핑 저작용일 뿐 Job에 저장 안 함**(서브타이틀에 명시) — 흐리지 말 것.

**디자인이 채울 것:**
- 각 페이지 폴리시(현재 기능형 레이아웃). MappingPage의 표시형·미리보기 UX 다듬기.
- **기존 작업 편집 프리로드**(현재 스텁): `app.py`의 `_open_editor_edit`가 새 작업 흐름을
  재사용한다. 설계 지점 = `MappingPage.initializePage`에서 `wiz.model.apply_profile(job.mapping)`로
  프리시드 + `SaveJobPage`에 기존 이름·패턴 채우기. `# TODO(디자인)` 표식 참조.

---

## 4. 집행 — `gui/run_view.py` `RunView(QMainWindow)`

**스캐폴드가 고정:**
- 생성자 `RunView(job)`. 흐름: **데이터 겨눔 → 행 선택 → 사전검증 → 생성**. 매핑 테이블 없음.
- **데이터는 이음새 뒤.** `self.datasource`는 추상 참조 — 지금 `ExcelDataSource`만 고르지만
  **누적치환(이전 출력을 소스로)·나라 세부·API 직결**은 같은 이음새에 꽂히는 미래 *소스 종류*다.
  **여기서 종류로 분기하지 말 것**(단일 `self.datasource` 유지).
- 행 선택 = `RecordSelector`(`SelectionModel`) 재사용.
- 사전검증 = `RunRequest.source_report()`(빠진 소스키=치명)·`output_report()`(빈 출력값=경고)를 표시만.
- 생성 = `GenerateWorker`(백그라운드) + `RunRequest.mapped_records()`. 템플릿 부재 가드 있음.
- 시그널: `run_finished(BatchResult)`, `back_requested()`.

**디자인이 채울 것:**
- **소스-종류 선택기**: "새 데이터(신규)" vs "이전 출력 이어채우기(누적치환)". 엔진은 이미 지원
  (빈값 스킵→이전 패스 안 덮음); 빠진 건 워크플로 UI뿐. 규칙: 단계별 필드 **서로소**.
- **능동 빈칸 게이트 + 표식**: 사전검증을 수동 로그가 아니라 "빈칸 N필드 — 허용하고 생성?"
  능동 게이트로. **미충족 공란**만 grep 가능 표식(예 `〘미입력·{필드}〙`, 누름틀 유지) 주입,
  **의도적 공란**(매핑 비움)은 표식 없음(경보 피로 방지). 파서 "누락은 시끄럽게"의 출력 짝.
- 레이아웃·진행/로그 표현·결과 요약.

---

## 5. 이음새 요약표

| 스캐폴드가 고정(계약) | 디자인이 채움 |
|---|---|
| 3화면 모듈 경계 (home/job_editor/run_view) | 위젯 레이아웃·스타일·빈 상태 |
| 홈 네비게이션 시그널(이름·인자) | 작업 카드 비주얼·대시보드 크롬 |
| 에디터 명시성 게이트(전 행 확정) | 페이지 폴리시·표시형 UX |
| `MappingModel.to_profile()` → 저장 | 기존 작업 편집 프리로드 UX(스텁) |
| `RecordSelector`/`SelectionModel` 임베드 | 소스-종류 선택기(신규 vs 누적) |
| `RunRequest.source/output_report()` 표시 | 능동 빈칸 게이트 + `〘미입력·{필드}〙` 표식 |
| `GenerateWorker` 수명 배선 | 진행/로그/결과 표현 |

---

## 6. 지켜야 할 불변식 / 발명 금지(non-goal)

**지킬 것:**
- **명시성** — 변환은 명시 선언·암묵 자동 금지·결과는 미리보기(파서 철학의 저작 확장).
- **집행 시 매핑 재확정 없음** — 매핑은 작업 정의 때 1회. 집행은 사전검증만.
- **Job에 데이터·행 미포함** — 일회성. 소스는 `DataSource` 추상 참조로만.
- **누락은 시끄럽게** — 부분 문서를 내되 외치게(표식). pre-flight로 중단만 하지 않음.

**발명 금지(명시적 non-goal):**
- **"빠른 생성"**(매핑 뺀 직결) — 삭제된 `main_window`의 죄. 명시성 게이트 우회 = 재발 금지.
- **조인 엔진 / 데이터-뷰 계층** — 한 겹 유지. 조립은 `DataSource` 이음새 뒤(ERP·나라 세부와 파킹).
- **조건부 조립·문서 병합·반복행(B-5)** — 스코프 밖("값 치환의 확장이지 문서 조립 아님").

---

## 7. 착수 지점

1. `python -m hwpxfiller.gui.app` 로 현재 스캐폴드 구동(빈 홈 → 새 작업 → 저장 → 집행).
2. 화면별로 §2~§4의 "디자인이 채울 것"을 위→아래로. 시그널/모델 계약은 **불변**으로 두고
   그 위에 위젯·레이아웃만 얹는다.
3. 각 변경은 `tests/test_gui_smoke.py`(offscreen)로 배선 유지 확인 — 로직은
   `test_job.py`·`test_mapping_state.py`·`test_selection_state.py`가 헤드리스로 지킨다.

---

## 8. 앱 A — diff 리뷰어 (`gui/diff_app.py`, 별도 앱)

diff 는 앱 B와 **별도 앱**이다 — 별도 진입점(`python -m hwpxfiller.gui.diff_app`,
gui-script `hwpx-diff`)+창+exe, 공유는 `core/` 뿐(UI 상태 공유 0). 상호작용 형태가
근본 다르다: 앱 B=쓰기 도구(위저드·집행), 앱 A=**읽기 도구**(문서를 바꾸지 않는다).

**코어 계약** (`core/diff.py`, 완성·골든 고정 — 디자인이 건드리지 않음):
- `diff_files(old, new) -> DiffResult` — 실코퍼스 기준 ~30ms(동기 실행으로 충분).
- `DiffResult.change_items` — 우선순위 정렬된 리뷰어용 목록(`category/location_label/detail/order`).
- `render_html(result) -> str` — 자체 완결 HTML. **변경마다 앵커 `chg-{seq}`**
  (`ChangeItem.order` == `Change.seq`) — 클릭 이동·딥링크의 표적.

**스캐폴드가 고정** (`DiffReviewWindow(QMainWindow)`):
- 단일 화면: 판본 2개 픽커 → `비교` → 요약 라벨 + 좌(변경항목 QTableWidget)/우(QTextBrowser
  리포트) 스플리터.
- **클릭 이동**: 항목 선택 → `view.scrollToAnchor(f"chg-{seq}")` (seq는 `Qt.UserRole`).
- 「브라우저에서 열기」(원본 충실 뷰 — QTextBrowser 는 CSS 근사 렌더) · 「HTML 저장…」.

**디자인이 채울 것:**
- 변경항목 리스트의 **배지 색**(HTML 리포트의 `b-{category}` 팔레트와 일치시킬 것)·행 스타일.
- **범주 필터**(숫자/조항/문구/표…)와 **번호변경(renumber) 접기 토글** — 리포트의
  "실질 변경과 섞지 않되 조용히 버리지 않는" 규칙을 리스트에도.
- 임베드 뷰 개선: QTextBrowser 근사의 한계를 수용하거나, Qt 친화 HTML 변형 렌더를 별도
  작성(코어 `render_html` 은 브라우저 기준 유지 — 갈라야 하면 뷰 측에서).
- 드래그&드롭 파일 투입·최근 비교 목록·대형 문서용 워커 스레드(현재 동기) 등 편의.

**발명 금지:** 이 앱은 읽기 도구다 — 문서 편집·주석·병합 기능을 붙이지 말 것(스코프 밖).
diff 정밀도(표 제목 매칭·셀 재번호 인지)는 코어 파킹 항목이지 UI 일이 아니다.
