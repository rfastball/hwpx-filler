# UI 디자인 핸드오프 — 트랙 C 셸

이 문서는 **작업(Job) 앵커 데이터모델 + GUI 스캐폴드**(앱 B)와 **diff 리뷰어**(앱 A)가
랜딩된 뒤, 세부 UI 구현을 넘기기 위한 계약서다. 스캐폴드가 **고정한 이음새**(모듈 경계·
시그널/슬롯·데이터 바인딩 지점)와 **디자인이 채울 것**(레이아웃·위젯·스타일·상호작용)을
가른다. §0~§6 = 앱 B(생성기), §8 = 앱 A(diff 리뷰어).

> **관통 원칙 — UI는 기능이 거쳐 UX로 드러나는 통로다.** function → UX → UI 이지 그 역이
> 아니다. 빈 슬롯을 채우려 **없던 기능을 발명하지 말 것**(과거 "빠른 생성" 드리프트 재발
> 금지). 아래 각 화면의 UX는 안정된 기능에서 도출됐다 — 디자인은 그 위에 옷을 입힌다.

---

## 0. 전체 구조 — 오케스트레이터 + 라우팅 화면들

핸드오프 시점 스캐폴드는 홈·에디터·실행 **3화면**이었다(§5 이음새표의 원형). 이후 화면들이
착지해 현재 `_AppController` 라우팅은 다음과 같다(`gui/app.py` 확인, 2026-07-12):

```
gui/app.py  _AppController ──라우팅──┬─▶ home.JobListHome            (홈 = 투트랙 허브)
   (QApplication, 자식창 수명 소유)   ├─▶ job_editor.JobEditorWizard  (작업 저작: 저장으로 끝)
                                     ├─▶ run_view.RunView             (실행: 데이터 겨눠 생성)
                                     ├─▶ txt_view.TxtDraftView        (즉시 기안 txt — ADR H)
                                     ├─▶ template_manager.TemplateManagerPanel (템플릿 관리 — C5)
                                     ├─▶ dataset_pool_panel.DatasetPoolPanel   (데이터 풀 관리 — J1)
                                     ├─▶ matrix_view.MatrixRunView             (여러 작업 일괄 실행 — J2)
                                     └─▶ vocab_workbench.VocabWorkbenchPanel   (어휘 워크벤치 — J3)
```

- **홈**이 오케스트레이터다(하나의 태스크가 아니라 능력 라우터).
- **에디터**와 **실행**을 가른다: 무거운 명시성 게이트(매핑 확정)는 **셋업(에디터)에만**.
  실행은 사전검증만 — 매핑 재확정 없음.
- 분리 예정이던 둘의 착지는 **갈렸다**: diff GUI만 별도 앱(앱 A, `src/hwpxdiff/`)으로 분리
  완료(§8), **템플릿관리는 앱 B 안에 착지** — `gui/template_manager.py`+`template_manager_state.py`,
  `app.py`의 `manage_templates_requested` 배선(착지 커밋 `c1ee653`).

실행: `python -m hwpxfiller.gui.app` (또는 `hwpx-filler` gui-script). 헤드리스 테스트는
`QT_QPA_PLATFORM=offscreen` + `tests/test_gui_smoke.py`.

---

## 1. 데이터모델 계약 (`core/job.py`) — Qt 비의존, 이미 완성·테스트됨

디자인이 건드리지 않는다. UI가 **읽고 쓰는 대상**의 형태:

| 심볼 | 계약 |
|---|---|
| `Job(name, template_path, mapping: MappingProfile, filename_pattern, version)` | durable 바인딩 `{템플릿·매핑·파일명}`. **데이터·행은 없음**(실행 일회성). `template_fields()`·`source_keys()`·`to_dict/from_dict/save/load`. 이후 가산 필드 2종 착지: `last_run_at`(마지막 성공 실행 ISO 시각 — 사용 메타, 데이터 미포함 불변식과 무관)·`base_mapping_name`(J3 공유 베이스 계보, 순수 메타 — 엔진은 합성된 `mapping`만 소비). 가산 필드는 version 불증가(`from_dict` `.get` 하위호환). |
| `JobRegistry(directory)` | 작업당 JSON 1개. `save(job)`·`load(name)`·`exists`·`delete`·`list_jobs()`·`names()`. |
| `RunRequest(job, datasource, selected_indices)` | 1회 실행(저장 안 함). `selected_records()`·`mapped_records()`·`source_report()`·`output_report()`. **실행 로직은 여기 있다** — 뷰는 호출만. |
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
- ~~**기존 작업 편집 프리로드**(스텁)~~ → **착지 완료**(핸드오프 당시 스텁이던 설계 지점 그대로):
  `app.py`의 `_open_editor_edit`가 `initial_job`으로 기존 Job을 위저드에 전달,
  `wizard.py` MappingPage가 `wiz.model.apply_profile(job.mapping)`로 프리시드,
  `job_editor.py` SaveJobPage가 기존 이름·패턴을 1회 프리필(사용자 수정 불가침).
  `# TODO(디자인)` 표식은 소스에서 소거됨(0건).

---

## 4. 실행 — `gui/run_view.py` `RunView(QMainWindow)`

**스캐폴드가 고정:**
- 생성자 `RunView(job, *, pool_registry=None, secret_store=None, nara_fetcher=None)`
  (`run_view.py:57` — 키워드 인자는 전부 주입 가능·기본은 표준 레지스트리; 핸드오프 당시
  `RunView(job)`에서 가산 확장). 흐름: **데이터 겨눔 → 행 선택 → 사전검증 → 생성**. 매핑 테이블 없음.
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

핸드오프 당시 3화면 기준 표. 이후 착지한 화면(§0 다이어그램의 txt_view·template_manager·
dataset_pool_panel·matrix_view·vocab_workbench·pipeline_builder)도 같은 이음새 규율
(모듈 경계·시그널 계약·Qt-free 상태모델 분리)을 따른다 — 각자의 `*_state.py`가 계약이다.

| 스캐폴드가 고정(계약) | 디자인이 채움 |
|---|---|
| 화면 모듈 경계 (home/job_editor/run_view — 원형 3화면 + 이후 착지 화면들) | 위젯 레이아웃·스타일·빈 상태 |
| 홈 네비게이션 시그널(이름·인자) | 작업 카드 비주얼·대시보드 크롬 |
| 에디터 명시성 게이트(전 행 확정) | 페이지 폴리시·표시형 UX |
| `MappingModel.to_profile()` → 저장 | 기존 작업 편집 프리로드 UX(착지 완료 — §3) |
| `RecordSelector`/`SelectionModel` 임베드 | 소스-종류 선택기(신규 vs 누적) |
| `RunRequest.source/output_report()` 표시 | 능동 빈칸 게이트 + `〘미입력·{필드}〙` 표식 |
| `GenerateWorker` 수명 배선 | 진행/로그/결과 표현 |

---

## 6. 지켜야 할 불변식 / 발명 금지(non-goal)

**지킬 것:**
- **명시성** — 변환은 명시 선언·암묵 자동 금지·결과는 미리보기(파서 철학의 저작 확장).
- **실행 시 매핑 재확정 없음** — 매핑은 작업 정의 때 1회. 실행은 사전검증만.
- **Job에 데이터·행 미포함** — 일회성. 소스는 `DataSource` 추상 참조로만.
- **누락은 시끄럽게** — 부분 문서를 내되 외치게(표식). pre-flight로 중단만 하지 않음.

**발명 금지(명시적 non-goal):**
- **"빠른 생성"**(매핑 뺀 직결) — 삭제된 `main_window`의 죄. 명시성 게이트 우회 = 재발 금지.
- **조인 엔진 / 데이터-뷰 계층** — 한 겹 유지. 조립은 `DataSource` 이음새 뒤.
  → 조립의 *목표 형태*는 **ADR K**로 확정(사용자 저작 Power-Query식 파이프라인, 추론 엔진 아님);
  당시엔 파킹(근거는 "철학"이 아니라 "수요")했고 이후 **착지 완료**: `data/pipeline.py`
  (파이프라인 엔진) + `gui/pipeline_builder.py`(저작 UI). 이음새 아래 *DataSource 생산층*이라
  UI 한 겹 원칙은 그대로다 — 뷰는 여전히 단일 `datasource`만 소비한다.
- **조건부 조립·문서 병합·반복행(B-5)** — 스코프 밖("값 치환의 확장이지 문서 조립 아님").

---

## 7. 착수 지점

1. `python -m hwpxfiller.gui.app` 로 현재 스캐폴드 구동(빈 홈 → 새 작업 → 저장 → 실행).
2. 화면별로 §2~§4의 "디자인이 채울 것"을 위→아래로. 시그널/모델 계약은 **불변**으로 두고
   그 위에 위젯·레이아웃만 얹는다.
3. 각 변경은 `tests/test_gui_smoke.py`(offscreen)로 배선 유지 확인 — 로직은
   `test_job.py`·`test_mapping_state.py`·`test_selection_state.py`가 헤드리스로 지킨다.

---

## 8. 앱 A — diff 리뷰어 (별도 서브프로젝트 `src/hwpxdiff/`)

diff 는 앱 B와 **별도 제품**이다 — 2026-07 서브프로젝트로 분리 완료: `hwpxdiff` 패키지
(GUI `hwpxdiff/app.py`, 알고리즘 `hwpxdiff/diff.py`, CLI `hwpxdiff/cli.py`), 진입점
`python -m hwpxdiff` / gui-script `hwpx-diff` / 단독 exe(`packaging/`). 공유는 공통 파서
`hwpxcore` 뿐(hwpxfiller 와 상호 임포트 금지). 상호작용 형태가 근본 다르다:
앱 B=쓰기 도구(위저드·실행), 앱 A=**읽기 도구**(문서를 바꾸지 않는다).

**코어 계약** (`src/hwpxdiff/diff.py`, 완성·골든 고정 — 디자인이 건드리지 않음):
- `diff_files(old, new) -> DiffResult` — 실코퍼스 기준 ~30ms(동기 실행으로 충분).
- `DiffResult.rows` — **equal 포함 전문(全文) 대조 스트림**(`DocRow`; 변경 행은
  `seq` == `Change.seq`, equal 은 None). 골든(to_dict) 밖의 뷰 데이터 — 신구대비표의 원천.
- `DiffResult.change_items`·`render_html` 은 CLI(diff --html)용으로 유지 — GUI 는 안 쓴다.
- `KIND_LABELS/KIND_COLORS` — 종류(추가/삭제/변경/번호변경) 어휘·색 단일 출처.

**뷰 형태(2026-07 사용자 피드백으로 확정 — 변경분 리포트 폐기):**
- **전문 신구대비표** — 원문 전체를 좌(구판)/우(신판) 대조 렌더(`_render_doc_html`).
  변경만 발라내면 본문 맥락이 날아가 diff 를 파악할 수 없다는 피드백의 산물.
  변경 행은 구판 측 del / 신판 측 ins 로 갈라 강조, equal 행은 좌우 동일 원문.
- **변경 리스트 = 네비게이션** — 인접(연속 seq)·같은 종류 변경을 그룹 1행으로
  (`_group_changes`, 파편화 완화). 클릭 → `scrollToAnchor(chg-{첫 seq})`.
- **필터는 종류 3종 고정**(추가/삭제/변경) + 번호변경 전용 토글(기본 접힘·개수 노출).
  세분 범주(숫자/조항/문구…) 필터는 부정확한 노이즈라 제거.
- **내보내기 없음** — 「브라우저에서 열기」·「HTML 저장」 제거(불필요 기능 피드백).
- 낱말 diff 파편화는 뷰 측 `_coalesce_ops` 가 완화(변경 사이 한두 글자 equal 흡수).

**남은 개선 후보:**
- 드래그&드롭·최근 비교 목록(구현됨) 외: 대형 문서용 워커 스레드(현재 동기),
  전문 뷰 내 검색, 변경 간 이전/다음 점프 키.

**발명 금지:** 이 앱은 읽기 도구다 — 문서 편집·주석·병합 기능을 붙이지 말 것(스코프 밖).
diff 정밀도(표 제목 매칭·셀 재번호 인지)는 코어 파킹 항목이지 UI 일이 아니다.
