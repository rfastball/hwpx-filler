# UI 계약 — 목업 ↔ ViewModel seam (앱 B)

이 문서는 목업(`UI_PROTOTYPE_APPB.html`)의 각 요소가 **어떤 ViewModel 표면**을 렌더/호출하는지의
살아있는 매핑이다. 목업 요소에는 `data-vm="클래스.속성"` 주석이 붙어 있고,
`tests/test_ui_contract.py` 가 그 주석 전부가 실제 ViewModel에 존재하는지 CI에서 검사한다 —
디자인 스펙과 구현이 조용히 갈라지지 않게(이름이 바뀌면 테스트가 실패).

**계약의 방향:** ViewModel(링1) 공개 API가 seam이고, 목업(디자인)과 Qt 위젯(구현)은 **둘 다
그 seam의 렌더러**다. 그래서 디자인 패스는 목업/위젯/토큰만 만지고 ViewModel·백엔드는 불변이다.

관련: [UI_DESIGN_HANDOFF.md](UI_DESIGN_HANDOFF.md)(무엇을) · [UI_DESIGN_DECISIONS.md](UI_DESIGN_DECISIONS.md)(왜) ·
[ARCH_UI_SEPARATION.md](ARCH_UI_SEPARATION.md)(레이어링·왜 이 seam인가).

## 홈 (`gui/home.py` ← `gui/home_state.py`)

| 목업 셀렉터 | ViewModel 심볼 | 종류 | 근거 |
|---|---|---|---|
| `#jcount` | `HomeViewModel.count_label` | 상태 | A/B |
| `.jobs` | `HomeViewModel.rows` | 상태(목록) | A |
| `.job .jn` | `JobRow.name` | 상태 | B |
| `.job .jm` | `JobRow.meta_line` | 상태(성형) | B |
| `.job .jr` | `JobRow.last_run_display` | 상태 | B |
| `.pill.warn`("템플릿 없음") | `JobRow.template_missing` | 상태 | B |
| `#emptyView` | `HomeViewModel.is_empty` | 상태(분기) | A |
| `#hRun` | `HomeViewModel.has_selection` | 상태(활성) | A |
| `#hEdit` | `HomeViewModel.selected_name` | 상태 | A |

선택/삭제 명령: `HomeViewModel.select` · `HomeViewModel.delete` · `HomeViewModel.refresh`(구독 통지).
네비게이션은 위젯 Qt 시그널(`run/edit/delete/new_job_requested`) — VM 밖(라우팅은 `app.py`).

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

## 집행 (`gui/run_view.py` ← `gui/run_state.py` + `gui/selection_state.py`)

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

## 규율

- 목업 요소를 늘리거나 바꿀 때 **정적 요소**에 `data-vm` 을 달면 계약 테스트가 자동으로 지켜준다
  (JS로 생성되는 행은 정적 `th`/컨테이너에 대표로 단다).
- ViewModel API 이름을 바꾸면 목업 주석과 이 표를 함께 갱신한다 — 테스트가 강제한다.
