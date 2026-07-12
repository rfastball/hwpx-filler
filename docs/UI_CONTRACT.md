# UI 계약 — 목업 ↔ ViewModel seam (앱 B)

이 문서는 목업(`UI_PROTOTYPE_APPB.html`)의 각 요소가 **어떤 ViewModel 표면**을 렌더/호출하는지의
살아있는 매핑이다. 목업 요소에는 `data-vm="클래스.속성"` 주석이 붙어 있고,
`tests/test_ui_contract.py` 가 그 주석 전부가 실제 ViewModel에 존재하는지 CI에서 검사한다 —
디자인 스펙과 구현이 조용히 갈라지지 않게(이름이 바뀌면 테스트가 실패).

**계약의 방향:** ViewModel(링1) 공개 API가 seam이고, 목업(디자인)과 Qt 위젯(구현)은 **둘 다
그 seam의 렌더러**다. 그래서 디자인 패스는 목업/위젯/토큰만 만지고 ViewModel·백엔드는 불변이다.

관련: [UI_DESIGN_HANDOFF.md](UI_DESIGN_HANDOFF.md)(무엇을) · [UI_DESIGN_DECISIONS.md](UI_DESIGN_DECISIONS.md)(왜) ·
[ARCH_UI_SEPARATION.md](ARCH_UI_SEPARATION.md)(레이어링·왜 이 seam인가).

## 대시보드 홈 (`gui/home.py` ← `gui/home_state.py`) — 투트랙 허브(ADR I)

| 목업 셀렉터 | ViewModel 심볼 | 종류 | 근거 |
|---|---|---|---|
| `.kpis` | `HomeViewModel.kpi` → `DashboardKpi` | 파생(요약) | I/B |
| `#jobsView` | `HomeViewModel.rows` | 상태(HWPX 목록) | A |
| `.jcard .jn` | `JobRow.name` | 상태 | B |
| `.jcard .jm` | `JobRow.meta_line` | 상태(성형) | B |
| `.jcard .jr` | `JobRow.last_run_display` | 상태 | B |
| `.pill.warn`("템플릿 없음") | `JobRow.template_missing` | 상태 | B |
| `.jcard .pill`(컴파일 배지) | `JobRow.compile_badge` (+`compile_state`) | 파생(C2 재산출) | B/C2 |
| `#emptyView` | `HomeViewModel.is_empty` | 상태(분기) | A |
| `.tlist` | `HomeViewModel.txt_rows` | 상태(txt 목록) | I/H |
| `.titem .tn` | `TxtRow.name` | 상태 | H |
| `.titem .tm` | `TxtRow.field_count` | 상태 | H |

HWPX 카드별 액션은 위젯 Qt 시그널(`run/edit/delete_job_requested`), txt 진입은 `open_txt/new_txt_requested`
(라우팅 `app.py`). 선택/삭제/갱신: `HomeViewModel.select`/`delete`/`refresh`.

## 즉시 기안 txt (`gui/txt_view.py` ← `gui/txt_state.py` + `core/text_registry.py`) — ADR H

| 목업 셀렉터 | ViewModel 심볼 | 종류 | 근거 |
|---|---|---|---|
| `#tplSel` | `TxtDraftViewModel.template_names` | 상태(루트 목록) | H |
| 데이터 선택 버튼 | `TxtDraftViewModel.load_data` | 명령 | F/H |
| `.stepper` | `TxtDraftViewModel.step` (+`record_count`) | 명령/상태 | H |
| `#tokPanel` | `TxtDraftViewModel.token_states` → `TokenState` | 파생(채움/빈값/미입력) | E/B |
| `#renderView` | `TxtDraftViewModel.render` → `(text, RenderReport)` | 파생(실시간 view=진실) | C/E |
| `#copyBtn` | `TxtDraftViewModel.render` (복사=commit) | 명령 | C |

미입력 토큰은 `render` 가 `{{}}` 를 남긴다(조용히 안 지움) — `RenderReport.missing_fields`(ADR E).

## 작업 에디터 (`gui/wizard.py`·`gui/job_editor.py` ← `gui/mapping_state.py`)

| 목업 셀렉터 | ViewModel 심볼 | 종류 | 근거 |
|---|---|---|---|
| `#mapBody` | `MappingModel.rows` | 상태(행 목록) | D |
| `th`(확정) | `RowState.confirmed` | 상태 | D |
| `th`(템플릿 필드) | `RowState.template_field` | 상태 | — |
| `th`(소스) | `RowState.sources` | 상태 | F |
| `th`(변환) | `RowState.transform` | 상태 | — |
| `th`(표시형) | `RowState.fmt` | 상태 | — |
| `th`(구분자·상수) | `RowState.sep` | 상태 | — |
| `th`(미리보기) | `RowState.to_mapping` | 파생(값 미리보기) | C |
| `#pvSummary` | `MappingModel.preview_empties` | 파생 | B |
| `#gateCount` | `MappingModel.is_complete` | 상태(게이트) | D |
| `#confAll` | `MappingModel.confirm_all` | 명령 | D |
| `#unconfAll` | `MappingModel.unconfirm_all` | 명령 | D |

행 편집 명령: `MappingModel.set_sources`/`set_transform`/`set_fmt`/`set_sep`/`set_const`/`set_confirmed`.
프로파일 IO: `MappingModel.apply_profile`/`to_profile`.

## 실행 (`gui/run_view.py` ← `gui/run_state.py` + `gui/selection_state.py`)

| 목업 셀렉터 | ViewModel 심볼 | 종류 | 근거 |
|---|---|---|---|
| `#rNew`·`#rCont` | `RunViewModel.set_target_mode` | 명령 | G |
| `#prevPick`·`#overlapNote` | `RunViewModel.set_prev_output` → `PrevNote` | 명령/상태 | G |
| 데이터 선택 버튼 | `RunViewModel.load_data` | 명령 | F |
| `.preflight` | `RunViewModel.preflight` → `PreflightResult` | 파생 | — |
| `#fieldBadges` | `RunViewModel.blank_fields` | 파생 | E/B |
| `#genGate` | `RunViewModel.blank_fields` | 파생(게이트) | E |
| `#genBtn` | `RunViewModel.validate_generate` → `[GateError]` | 명령/게이트 | E/G |
| `#genBar` | `RunViewModel.mapped_records` | 파생(배치) | — |
| `#recList` | `SelectionModel.selected_indices` | 상태 | — |
| `#selCount` | `SelectionModel.selected_count` | 상태 | — |
| `#selAll` | `SelectionModel.set_all` | 명령 | — |
| `#selNone` | `SelectionModel.set_none` | 명령 | — |

`〘미입력·{field}〙` 표식 주입은 `RunViewModel.mapped_records(mark_missing=…)`(엔진 `RunRequest` 경유).
ADR-E 인라인 게이트 최종형(강제 상호작용)은 위젯만 손대면 되고 `blank_fields` seam은 불변이다.

## 목업의 권위 범위 — 층별로 다르다 (디자인 워크플로)

디자인 개선은 **목업 먼저 → 코드** 순서로 굴린다. 단, 목업이 "진실"인 층은 하나뿐이다.

| 층 | 권위 | 워크플로 | 가드 |
|---|---|---|---|
| **구조·seam** (어떤 요소가 어떤 VM 표면에 물리나) | **목업** | 목업에 요소+`data-vm` 먼저 → 계약 테스트 red(VM에 멤버 없음) → 코드가 따라와 green | `test_ui_contract.py`(자동) |
| **시각·레이아웃** (배치·간격·그룹핑) | Qt 위젯 | 목업은 근사 배치도(diagram)로만 — HTML/CSS 는 QLayout 렌더를 예측 못 한다 | 없음(사람 눈) |
| **문구·라벨** | **코드**(`run_view.py` 등) | 최종 문구는 코드가 SoT. 목업 텍스트는 참고용·비권위 | 없음 → 이중 관리 금지 |

**왜 이 분할인가.** 목업 먼저가 *안전한* 건 구조/seam 층뿐이다 — 거기엔 계약 테스트라는 red-green
가드가 있어 목업이 코드보다 앞서가도 CI 가 수렴을 강제한다. 시각은 매체가 달라(HTML≠Qt) 목업이
앞서봐야 Qt 에서 다시 손봐야 하고, 문구는 가드가 없어 두 곳에 두면 반드시 갈라진다(실제로
"이전 출력"→"기존 문서" drift 로 확인). 그래서 문구는 코드 한 곳에만 둔다.

**실무 순서(구조 변경 시).** ① 목업에 요소+`data-vm` 추가 → ② `pytest tests/test_ui_contract.py`
red 확인 → ③ VM 에 seam 멤버 구현 → ④ green → ⑤ 위젯(Qt)·문구는 코드에서 마감.

## 규율

- 목업 요소를 늘리거나 바꿀 때 **정적 요소**에 `data-vm` 을 달면 계약 테스트가 자동으로 지켜준다
  (JS로 생성되는 행은 정적 `th`/컨테이너에 대표로 단다).
- ViewModel API 이름을 바꾸면 목업 주석과 이 표를 함께 갱신한다 — 테스트가 강제한다.
- **문구는 예외** — 라벨/메시지는 코드가 SoT다. 목업 텍스트가 코드와 달라도 그건 버그가 아니라
  코드 소관이다(위 "권위 범위" 참조). 목업엔 문구를 다시 물지 말 것.
