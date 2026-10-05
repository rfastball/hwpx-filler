"""Eight short onboarding lessons and their persistent guidance position.

One beat is one boxed control and one user action (#1127). Explanation beats use ``next``.
Action beats advance from a verified product event supplied by the tutorial controller, or —
for a press that runs no product command (opening a dock, checking a sheet, a top-nav move) —
from the web's report that the beat's own boxed control was pressed (:data:`UI_PRESS_EVENTS`).
The old T0–T17 checklist is intentionally not a source of completion for this curriculum.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Beat:
    id: str
    title: str
    body: str
    screen: str | None
    target: str | None
    event: str | None = None
    placement: str = "right"
    entry_screen: str | None = None
    #: Parameter of the anchor key (file, field, column, job or slot name; ``pool:<sheet>``).
    arg: str = ""

    @property
    def mode(self) -> str:
        return "action" if self.event else "explain"


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    description: str
    beats: tuple[Beat, ...]


#: Events a beat completes by the press of its own boxed control: the press opens client-only
#: UI and runs no product command, so no product observation can witness it (#1127 decision 1).
UI_PRESS_EVENTS = frozenset({
    "create_form_opened", "trial_dock_opened", "sheet_checked", "slice_closed", "screen_entered_job",
    "binding_menu_opened", "template_menu_opened",
})

#: Bump when beat lists change: stored checkpoints of an older curriculum point at other beats.
CURRICULUM = 5

_NEW_JOB = "'＋ 새 작업'은 템플릿과 데이터를 묶은 문서 작업을 새로 만듭니다. 누르세요."
_TO_BINDING = "'다음 ▶'은 템플릿 필드마다 채울 데이터 열을 정하는 '연결 확인' 단계로 넘어갑니다. 누르세요."
_PICK_JOB = "'문서 작업' 목록에는 저장한 작업이 모여 있습니다. '{name}'을 누르세요."
_USE_JOB = "'문서 만들기에서 사용'은 이 작업과 연결된 데이터를 문서 만들기 화면에 엽니다. 누르세요."
_VISIBLE_ROWS = "'보이는 행 모두 선택' 칸은 필터로 남은 행만 한꺼번에 고릅니다. 누르세요."
_ALL_ROWS = "표 머리의 '전체 선택' 칸은 표의 행을 한꺼번에 고릅니다. 눌러서 {what}을 고르세요."
_OPEN_WORKBENCH = "'검토·복사 시작'은 고른 행의 채운 문장을 한 건씩 보여 주는 작업대를 엽니다. 누르세요."
_SAVE_OPEN = "'저장하고 문서 만들기로'는 작업을 저장하고 문서 만들기 화면에서 바로 엽니다. 누르세요."
_TRIAL_OPEN = "'결과 시험'은 시험값을 넣은 결과 문서를 보여 줍니다. 누르세요."
_SAVE_TEMPLATE = "'저장'은 바꾼 서식을 파일에 씁니다. 누르세요."
_OPTIONS_HELP = "'포함할 내용'은 문서마다 넣을 문단을 고르는 자리입니다. "
_METHOD = "'낙찰자 결정방법'에서 '고시 미만'을 고르세요."
_TXT = "낙찰자 선정 및 계약체결 안내.txt"


def _new_job() -> Beat:
    return Beat("new_job", "새 작업 열기", _NEW_JOB, "library", "new-job", "new_job_opened")


def _to_binding() -> Beat:
    return Beat("to_binding", "연결 확인 단계로", _TO_BINDING, "editor", "editor-next", "editor_section_binding")


def _pick_job(name: str) -> Beat:
    return Beat("pick_job", "저장한 작업 고르기", _PICK_JOB.format(name=name), "library", "library-row",
                "library_job_selected", arg=name)


def _use_job() -> Beat:
    return Beat("use_job", "문서 만들기에서 열기", _USE_JOB, "library", "library-use", "job_opened")


def _all_rows(what: str) -> Beat:
    return Beat("rows", "행 모두 고르기", _ALL_ROWS.format(what=what), "job", "row-selection", "rows_selected")


def _open_workbench(event: str = "txt_workbench_opened") -> Beat:
    return Beat("workbench", "검토·복사 시작", _OPEN_WORKBENCH, "job", "open-workbench", event)


def _create(beat_id: str, title: str, body: str, command: str) -> Beat:
    return Beat(beat_id, title, body, "authoring", "create-command", "create_form_opened", arg=command)


def _open_template() -> tuple[Beat, ...]:
    """The way into template authoring (#1146): the practice TXT is opened from the template list, never silently."""
    return (
        Beat("open_list", "템플릿 목록 열기",
             "'＋ 새 작업'의 '고르기' 단계에는 서식 폴더의 템플릿 목록이 있습니다. 누르세요.",
             "library", "new-job", "new_job_opened"),
        Beat("open_menu", "템플릿 메뉴 열기",
             f"'{_TXT}' 줄 끝의 '⋮'은 이 템플릿에 쓰는 명령을 엽니다. 누르세요.",
             "editor", "template-more", "template_menu_opened", arg=_TXT),
        Beat("open_edit", "템플릿 저작 열기", "'내용 편집'은 이 템플릿을 템플릿 저작 화면에서 엽니다. 누르세요.",
             "editor", "menu-item", "practice_template_opened", arg="edit"),
    )


def _trial_open() -> Beat:
    return Beat("trial_open", "결과 시험 열기", _TRIAL_OPEN, "authoring", "trial-toggle", "trial_dock_opened")


LESSONS: tuple[Lesson, ...] = (
    Lesson("first_hwpx", "엑셀로 공고서 만들기",
           "공고서 서식과 엑셀 공고 목록을 연결해 작업을 저장하고, 고른 3행으로 공고서 3건을 만듭니다.", (
        Beat("intro", "시작", "공고서 서식과 공고목록 엑셀로 공고서 3건을 만듭니다. '다음'을 누르세요.", None, None,
             entry_screen="library"),
        _new_job(),
        Beat("template", "공고서 템플릿 고르기",
             "왼쪽 '템플릿' 목록은 문서의 틀이 되는 파일입니다. '물품 구매입찰 공고.hwpx'를 누르세요.",
             "editor", "template-row", "template_selected", arg="물품 구매입찰 공고.hwpx"),
        Beat("data", "공고 데이터 고르기",
             "오른쪽 '데이터' 목록은 문서에 채울 엑셀 시트입니다. '공고목록.xlsx'의 '공고' 시트를 누르세요.",
             "editor", "data-row", "notice_data_selected", arg="pool:공고"),
        _to_binding(),
        Beat("confirm_method", "낙찰자결정방법 연결 확인",
             "'제안'은 이름이 달라 앱이 짐작한 연결입니다. '낙찰자결정방법'에 제안된 '낙찰방법' 열이 맞으니 '제안'을 눌러 확인하세요.",
             "editor", "map-confirm", "notice_row_confirmed", arg="낙찰자결정방법"),
        Beat("confirm_phone", "담당자 전화번호 연결 확인",
             "'담당자 전화번호'에는 '담당자전화' 열이 제안됐습니다. '제안'을 눌러 확인하세요.",
             "editor", "map-confirm", "notice_mapping_confirmed", arg="담당자 전화번호"),
        Beat("date_format", "게시일시 표시형",
             "'게시일시'는 공고서 머리에 적히는 날짜입니다. '게시일시'의 표시형에서 '날짜' 아래 "
             "'표준(연·월)'을 고르세요.",
             "editor", "map-format", "notice_date_format_set", arg="게시일시"),
        Beat("date_confirm", "게시일시 연결 확인",
             "표시형을 바꾼 연결은 '확인 필요'로 표시됩니다. '확인 필요'를 눌러 확인하세요.",
             "editor", "map-confirm", "notice_date_confirmed", arg="게시일시"),
        Beat("to_filename", "이름·저장 단계로",
             "'다음 ▶'은 작업 이름과 문서 파일 이름을 정하는 단계로 넘어갑니다. 누르세요.",
             "editor", "editor-next", "editor_section_filename"),
        Beat("pattern", "문서 파일 이름 정하기",
             "'문서 파일 이름'은 만들 파일마다 붙는 이름 규칙입니다. 칸을 구매입찰공고-{{입찰공고번호}}로 바꾸고 Tab 키를 누르세요.",
             "editor", "filename-pattern", "notice_pattern_set"),
        Beat("save", "저장하고 열기", _SAVE_OPEN, "editor", "save-and-open", "notice_job_saved"),
        Beat("filter", "소상공인 행만 남기기",
             "'소상공인'은 메모에 소상공인이 든 행만 남기는 저장한 필터입니다. 누르세요.",
             "job", "filter-chip", "notice_first_filtered", arg="소상공인"),
        Beat("rows", "보이는 3행 고르기", _VISIBLE_ROWS, "job", "row-selection", "notice_first_rows"),
        Beat("qualification", "입찰참가자격 고르기",
             _OPTIONS_HELP + "'입찰참가자격'에서 '소기업·소상공인'을 고르세요.",
             "job", "slot-options", "slot_option_chosen", arg="입찰참가자격"),
        Beat("method", "낙찰자 결정방법 고르기", _METHOD, "job", "slot-options", "notice_first_options",
             arg="낙찰자 결정방법"),
        Beat("generate", "문서 만들기", "'문서 만들기'는 고른 행마다 HWPX 파일을 하나씩 만듭니다. 누르세요.",
             "job", "generate", "notice_first_generated"),
        Beat("result", "만든 문서 열어 보기",
             "'만든 문서'에는 이번에 만든 파일이 이름과 함께 놓입니다. 첫 문서의 '내용 보기'를 누르세요.",
             "job", "result-open", "notice_result_opened"),
    )),
    Lesson("contract_txt", "안내문 문장 복사하기",
           "계약 데이터로 채운 안내 문장을 행마다 확인하고, 기안에 붙여 넣을 수 있게 복사합니다.", (
        _new_job(),
        Beat("template", "계약 안내 템플릿 고르기",
             f"TXT 템플릿은 파일을 만들지 않고 채운 문장을 복사해 쓰는 서식입니다. '{_TXT}'를 누르세요.",
             "editor", "template-row", "contract_template_selected", arg=_TXT),
        Beat("data", "계약 데이터 고르기",
             "'계약' 시트에는 계약 건마다 업체와 금액이 한 행씩 있습니다. '공고목록.xlsx'의 '계약' 시트를 누르세요.",
             "editor", "data-row", "contract_inputs_selected", arg="pool:계약"),
        _to_binding(),
        Beat("firm_source", "대표계약업체 열 고르기",
             "'데이터 열'은 이 필드에 채울 엑셀 열입니다. '대표계약업체'에는 같은 이름의 열이 없으니 '계약상대자'를 고르세요.",
             "editor", "map-source", "contract_source_chosen", arg="대표계약업체"),
        Beat("firm_confirm", "대표계약업체 연결 확인",
             "직접 고른 연결은 '확인 필요'로 표시됩니다. '확인 필요'를 눌러 확인하세요.",
             "editor", "map-confirm", "contract_mapping_set", arg="대표계약업체"),
        Beat("currency", "계약보증금 표시형",
             "'표시형'은 값을 문장에 적는 모양입니다. '계약보증금'의 표시형에서 '금액' 아래 '원'을 고르세요.",
             "editor", "map-format", "contract_currency_set", arg="계약보증금"),
        Beat("currency_confirm", "계약보증금 연결 확인",
             "표시형을 바꾼 연결도 '확인 필요'로 표시됩니다. '확인 필요'를 눌러 확인하세요.",
             "editor", "map-confirm", "contract_amount_confirmed", arg="계약보증금"),
        Beat("to_filename", "이름·저장 단계로", "'다음 ▶'은 작업 이름을 정하는 단계로 넘어갑니다. 누르세요.",
             "editor", "editor-next", "editor_section_filename"),
        Beat("save", "저장하고 열기", _SAVE_OPEN, "editor", "save-and-open", "contract_job_saved"),
        _all_rows("계약 6행"),
        _open_workbench(),
        Beat("copy_first", "첫 문장 복사", "가운데 글은 이 행의 데이터로 채운 문장입니다. '복사'를 누르세요.",
             "workbench", "wb-copy", "first_row_copied"),
        Beat("next_row", "다음 행으로", "'다음'은 다음 계약 행의 문장으로 넘어갑니다. 누르세요.",
             "workbench", "wb-next", "contract_two_reviewed"),
        Beat("copy_second", "두 번째 문장 복사", "이 행의 문장도 '복사'를 누르세요.",
             "workbench", "wb-copy", "contract_two_copied"),
    )),
    Lesson("purchase_txt", "데이터 값 다듬기",
           "엑셀 칸 값의 일부만 쓰도록 가공하고, 날짜·금액이 문장에 적히는 모양을 확인합니다.", (
        Beat("slice_open", "군품명 가공 열기", "'가공'은 칸 값의 일부만 문장에 쓰게 합니다. '군품명' 행의 '+ 가공'을 누르세요.",
             "editor", "map-slice", "slice_popover_opened", arg="군품명"),
        Beat("slice_pick", "쓸 부분 끌어 고르기",
             "'예시 값'에서 쓸 부분을 끌어 고르면 방식이 맞춰집니다. '드릴'만 끌어 고르세요.",
             "editor", "slice-sample", "purchase_slice_set"),
        Beat("slice_done", "가공 완료", "'완료'는 고른 가공으로 편집 칸을 닫습니다. 누르세요.",
             "editor", "slice-done", "slice_closed"),
        Beat("slice_confirm", "군품명 연결 확인",
             "가공을 바꾼 연결은 '확인 필요'로 표시됩니다. '확인 필요'를 눌러 확인하세요.",
             "editor", "map-confirm", "purchase_slice_confirmed", arg="군품명"),
        Beat("format", "다른 행 미리보기",
             "'미리보기'는 데이터 한 행으로 채운 값입니다. '▶'를 눌러 다음 행의 날짜와 금액이 적히는 모양을 확인하세요.",
             "editor", "preview-next", "purchase_formats_checked"),
        Beat("save", "저장하고 열기",
             "'저장하고 문서 만들기로'는 바꾼 가공을 저장하고 문서 만들기 화면에서 엽니다. 누르세요.",
             "editor", "save-and-open", "purchase_job_saved"),
        _all_rows("공고 12행"),
        _open_workbench(),
        Beat("copy", "가공한 문장 복사", "가운데 문장의 군품명 자리에 가공한 값이 들어갔는지 확인하고 '복사'를 누르세요.",
             "workbench", "wb-copy", "purchase_copied"),
    )),
    Lesson("replace_data", "작업의 데이터 파일 바꾸기",
           "저장한 작업이 새로 받은 엑셀 파일을 쓰도록 데이터를 바꾸고, 연결을 다시 확인해 저장합니다.", (
        _pick_job("공고서 작업"),
        Beat("edit_job", "작업 편집 열기", "'작업 편집'은 저장한 작업의 템플릿·데이터·연결을 고치는 화면을 엽니다. 누르세요.",
             "library", "library-edit", "editor_job_opened"),
        Beat("to_template", "고르기 단계 열기", "'고르기'는 이 작업의 템플릿과 데이터를 바꾸는 단계입니다. 누르세요.",
             "editor", "editor-tab", "editor_section_template", arg="template"),
        Beat("browse", "새 파일 찾기", "'파일 찾아보기…'는 등록하지 않은 엑셀 파일을 데이터로 고릅니다. 누르세요.",
             "editor", "data-browse", "data_browse_started"),
        Beat("reset", "연결 초기화 확인",
             "데이터를 바꾸면 확인한 연결이 모두 미확정으로 돌아갑니다. '미확정으로 되돌리기'를 누르고, 열리는 창에서 '공고목록(새 판).xlsx'를 여세요.",
             "editor", "dialog-confirm", "data_file_picked"),
        Beat("sheet", "공고 시트 체크", "'가져올 시트 선택'에서 쓸 시트를 고릅니다. '공고'에 체크하세요.",
             "editor", "sheet-check", "sheet_checked", arg="공고"),
        Beat("import", "시트 가져오기", "'선택한 1개 시트 가져오기'를 누르세요.",
             "editor", "sheet-import", "derived_data_selected"),
        Beat("to_binding", "연결 확인 단계 열기", "'연결 확인'에서 새 파일의 열과 필드 연결을 다시 확인합니다. 누르세요.",
             "editor", "editor-tab", "editor_section_binding", arg="binding"),
        Beat("menu", "연결 메뉴 열기", "'⋯'에는 연결 표 전체에 쓰는 명령이 있습니다. 누르세요.",
             "editor", "binding-more", "binding_menu_opened"),
        Beat("resuggest", "자동 제안 다시 받기",
             "'자동 제안 다시 받기'는 새 파일의 열 이름으로 모든 연결을 다시 제안합니다. 누르세요.",
             "editor", "menu-item", "resuggest_asked", arg="resuggest-all"),
        Beat("resuggest_confirm", "다시 받기", "'다시 받기'를 누르세요.", "editor", "dialog-confirm", "rows_resuggested"),
        Beat("confirm_all", "제안 모두 확인", "표 위 '모두 확인' 단추는 제안된 연결을 한 번에 확인합니다. 누르세요.",
             "editor", "confirm-all", "rebind_rows_confirmed"),
        Beat("save", "저장하고 열기",
             "'저장하고 문서 만들기로'는 바뀐 데이터로 작업을 저장하고 문서 만들기에서 엽니다. 누르세요.",
             "editor", "save-and-open", "derived_reopened"),
    )),
    Lesson("blank_values", "빈 칸 확인하기",
           "데이터에 비어 있는 칸이 문장에 어떻게 표시되는지 보고, 일부러 비워 둔 항목과 비교합니다.", (
        _pick_job("계약 안내 작업(빈 칸)"),
        _use_job(),
        _all_rows("계약 6행"),
        _open_workbench("blank_observed"),
        Beat("blank", "〈빈 값〉 표식",
             "〈빈 값〉은 데이터 칸이 비어 있는 자리입니다. 이 행은 '계약보증금' 칸이 비어 있습니다. '다음'을 누르세요.",
             "workbench", "wb-blank", arg="계약보증금"),
        Beat("declared", "비움 확정",
             "'단위'는 일부러 비워 둔 항목(비움 확정)입니다. 본문에는 똑같이 〈빈 값〉으로 보이지만 복사 전 확인에서 빠집니다. '다음'을 누르세요.",
             "workbench", "wb-declared", arg="단위"),
    )),
    Lesson("field_trial", "내 서식에 필드 만들기",
           "안내문의 문구를 데이터가 들어갈 필드로 바꾸고, 시험값으로 결과를 확인한 뒤 저장합니다.", (
        *_open_template(),
        Beat("range", "바꿀 문구 고르기",
             "본문에서 끌어 고른 문구가 필드로 바뀔 자리입니다. 3번 문단의 '10일'을 끌어 고르세요.",
             "authoring", "authoring-range", "field_range_selected", entry_screen="authoring"),
        _create("create", "필드로 만들기", "'필드로 만들기'는 고른 문구를 데이터가 들어갈 자리로 바꿉니다. 누르세요.",
                "create_field"),
        Beat("name", "필드 이름 적기", "'필드 이름'은 데이터 열과 연결할 이름입니다. 재배정기한을 적고 Enter 키를 누르세요.",
             "authoring", "property-name", "practice_field_created"),
        _trial_open(),
        Beat("fill", "빈 시험 칸 채우기",
             "'필드 이름 사용'은 비어 있는 시험 칸을 필드 이름으로 채우고 결과를 다시 만듭니다. 누르세요.",
             "authoring", "trial-fill-names", "field_trial_passed"),
        Beat("save", "서식 저장", _SAVE_TEMPLATE, "authoring", "save-template", "field_practice_saved"),
    )),
    Lesson("option_apply", "넣거나 뺄 문단 만들기",
           "문단을 문서마다 넣거나 뺄 수 있는 '항목'으로 만들고, 두 '선택'을 시험한 뒤 서식을 저장합니다.", (
        Beat("about", "이 연습에서 할 일",
             "안내문의 3번 문단을 '항목'으로 묶고, 문단을 넣는 '선택'과 빼는 '선택'을 만듭니다. "
             "그러면 문서마다 이 문단을 넣을지 뺄지 고를 수 있습니다. '다음'을 누르세요.",
             None, None, entry_screen="library"),
        *_open_template(),
        Beat("item_range", "문단 고르기", "색으로 표시한 13~15번 줄을 끝까지 끌어 고르세요.",
             "authoring", "authoring-range", "item_range_selected", entry_screen="authoring"),
        _create("item_create", "항목으로 만들기", "'항목으로 만들기'는 고른 줄을 하나의 '항목'으로 묶습니다. 누르세요.",
                "create_slot"),
        Beat("item_name", "항목 이름 적기",
             "'표시 이름'은 문서 만들기에서 보일 '항목' 이름입니다. 예산재배정을 적고 Enter 키를 누르세요.",
             "authoring", "property-name", "practice_item_created"),
        Beat("include_range", "넣을 문단 고르기",
             "'선택'은 '항목' 안에서 문서마다 고를 수 있는 내용입니다. 색으로 표시한 3번 문단을 끌어 고르세요.",
             "authoring", "authoring-range", "include_range_selected"),
        _create("include_create", "선택으로 만들기", "'선택으로 만들기'는 고른 줄을 이 '항목'의 '선택' 하나로 만듭니다. 누르세요.",
                "create_option"),
        # A choice of whole lines applies at the first Enter; any other first shows its effect and the button then
        # carries the Enter key. A fixed "press Enter twice" sent the second Enter into the editor over the new choice.
        Beat("include_name", "'안내포함' 이름", "'표시 이름'에 안내포함을 적고 Enter 키를 누르세요. 단추에 Enter 표시가 나오면 한 번 더 누르세요.",
             "authoring", "property-name", "option_created"),
        Beat("omit_range", "빈 줄 고르기", "색으로 표시한 '항목' 안의 빈 줄을 누르세요. 문단을 뺄 때 이 줄이 대신 들어갑니다.",
             "authoring", "authoring-range", "omit_range_selected"),
        _create("omit_create", "선택으로 만들기", "'선택으로 만들기'를 누르세요.", "create_option"),
        Beat("omit_name", "'안내생략' 이름", "'표시 이름'에 안내생략을 적고 Enter 키를 누르세요. 단추에 Enter 표시가 나오면 한 번 더 누르세요.",
             "authoring", "property-name", "practice_options_created"),
        _trial_open(),
        Beat("fill", "빈 시험 칸 채우기", "'필드 이름 사용'은 비어 있는 시험 칸을 필드 이름으로 채웁니다. 누르세요.",
             "authoring", "trial-fill-names", "trial_names_filled"),
        Beat("trial_include", "'안내포함' 시험", "'예산재배정'에서 '안내포함'을 고르세요. 결과가 다시 만들어집니다.",
             "authoring", "trial-slot", "option_trial_passed", arg="예산재배정"),
        Beat("trial_omit", "'안내생략' 시험", "이번에는 '안내생략'을 고르세요.",
             "authoring", "trial-slot", "practice_both_trials_passed", arg="예산재배정"),
        Beat("save", "서식 저장", _SAVE_TEMPLATE, "authoring", "save-template", "option_practice_saved"),
    )),
    Lesson("change_apply", "바뀐 서식을 작업에 적용하기",
           "'항목'을 더한 서식을 저장한 작업에 적용하고, 문서 만들기에서 그 '항목'을 골라 채운 문장을 확인합니다.", (
        *_open_template(),
        Beat("impact", "변경 영향 열기",
             "'변경 영향·작업 적용'은 이 서식을 쓰는 저장한 작업에 바뀐 점을 반영하는 패널입니다. 누르세요.",
             "authoring", "impact-tab", "impact_tab_opened", entry_screen="authoring"),
        Beat("check", "적용 영향 확인", "'적용 영향 확인'은 작업에 생길 변화를 먼저 보여 줍니다. 누르세요.",
             "authoring", "apply-check", "prepare_apply_ready"),
        Beat("apply", "기존 작업에 적용", "'기존 작업에 적용'을 누르면 '계약 안내 작업'이 바뀐 서식을 씁니다. 누르세요.",
             "authoring", "apply-confirm", "option_change_applied"),
        Beat("to_job", "문서 만들기로 이동", "상단 '문서 만들기'는 데이터를 골라 작업을 실행하는 자리입니다. 누르세요.",
             "authoring", "nav-job", "screen_entered_job"),
        Beat("include", "'안내포함' 고르기", "'포함할 내용'의 '예산재배정'에서 '안내포함'을 고르세요.",
             "job", "slot-options", "slot_option_chosen", arg="예산재배정"),
        _all_rows("계약 6행"),
        _open_workbench("option_result_reviewed"),
    )),
)

BY_ID = {lesson.id: lesson for lesson in LESSONS}
_ROUND_KEYS = ("reviewed_rows", "copied_rows", "trial_options", "generated", "applied")


def _restored_records(stored: dict, curriculum_current: bool) -> dict[str, dict]:
    """Stored records of known lessons; an older curriculum keeps completion but restarts position."""
    records: dict[str, dict] = {}
    for lesson in LESSONS:
        entry = stored.get(lesson.id)
        if not isinstance(entry, dict):
            continue
        index = entry.get("checkpoint")
        if type(index) is not int or not 0 <= index <= len(lesson.beats):
            continue
        context = entry.get("context") if isinstance(entry.get("context"), dict) else {}
        records[lesson.id] = {
            "checkpoint": index if curriculum_current else 0,
            "completed": entry.get("completed") is True,
            "context": context if curriculum_current else {},
        }
    return records


class LessonProgress:
    """IO-free guidance state; records survive pause, close, and restart."""

    def __init__(self, raw: dict | None = None, *, first_launch: bool = False) -> None:
        raw = raw if isinstance(raw, dict) and raw.get("version") == 1 else {}
        self.invite_seen = raw.get("invite_seen") is True
        self.first_launch = first_launch
        #: Settings-owned toggle (#1147), injected by the controller — this viewmodel stays IO-free.
        #: Hides the HUD pill and the first-launch invitation; the controller ORs in practice-active.
        self.entry_visible = True
        selected = raw.get("selected")
        self.selected = selected if isinstance(selected, str) and selected in BY_ID else None
        stored = raw.get("records") if isinstance(raw.get("records"), dict) else {}
        assert isinstance(stored, dict)
        self.records: dict[str, dict] = _restored_records(stored, raw.get("curriculum") == CURRICULUM)
        self.active = False  # restarting the app never opens the coach automatically
        self.result: dict | None = None

    def progress(self) -> dict:
        return {
            "version": 1,
            "curriculum": CURRICULUM,
            "invite_seen": self.invite_seen,
            "selected": self.selected,
            "records": self.records,
        }

    def record(self, lesson_id: str) -> dict:
        if lesson_id not in BY_ID:
            raise ValueError(f"알 수 없는 튜토리얼 과정: {lesson_id}")
        return self.records.setdefault(lesson_id, {"checkpoint": 0, "completed": False, "context": {}})

    def later(self) -> None:
        self.invite_seen = True
        self.active = False

    def select(self, lesson_id: str) -> None:
        entry = self.record(lesson_id)
        self.selected = lesson_id
        self.invite_seen = True
        self.active = entry["checkpoint"] < len(BY_ID[lesson_id].beats)
        self.result = None

    def pause(self) -> None:
        self.active = False

    def restart(self, lesson_id: str) -> None:
        # Guidance position is independent of evidence and the user's work.
        record = self.record(lesson_id)
        record["checkpoint"] = 0
        for key in _ROUND_KEYS:
            record["context"].pop(key, None)
        self.selected = lesson_id
        self.active = True
        self.result = None

    def beat(self) -> Beat | None:
        if not self.selected:
            return None
        lesson = BY_ID[self.selected]
        index = self.record(self.selected)["checkpoint"]
        return lesson.beats[index] if index < len(lesson.beats) else None

    def rewind(self, beat_id: str) -> bool:
        """Return to an earlier beat whose established fact no longer holds (never forward)."""
        if not self.selected:
            return False
        entry = self.record(self.selected)
        index = next(i for i, item in enumerate(BY_ID[self.selected].beats) if item.id == beat_id)
        if index >= entry["checkpoint"]:
            return False
        entry["checkpoint"] = index
        return True

    def _advance(self) -> bool:
        if not self.selected:
            return False
        entry = self.record(self.selected)
        entry["checkpoint"] += 1
        if entry["checkpoint"] == len(BY_ID[self.selected].beats):
            entry["completed"] = True
            self.active = False
        return True

    def next(self) -> None:
        beat = self.beat()
        if not self.active or beat is None or beat.event is not None:
            raise ValueError("이 단계는 실제 동작을 마친 뒤에 넘어갈 수 있습니다.")
        self._advance()

    def observed(self, event: str, *, context: dict | None = None) -> bool:
        beat = self.beat()
        if not self.active or beat is None or beat.event != event:
            return False
        if context and self.selected:
            self.record(self.selected)["context"].update(context)
        return self._advance()

    def _invite_visible(self) -> bool:
        """첫 안내 카드 — 첫 실행·미열람·토글 켜짐(#1147) 셋을 모두 요구한다."""
        return self.first_launch and not self.invite_seen and self.entry_visible

    def snapshot(self) -> dict:
        beat = self.beat() if self.active else None
        selected_lesson = BY_ID.get(self.selected) if self.selected else None
        checkpoint = self.record(self.selected)["checkpoint"] if self.selected else 0
        stages = [] if selected_lesson is None else [
            {"id": item.id, "title": item.title,
             "status": "done" if i < checkpoint else "current" if i == checkpoint else "pending"}
            for i, item in enumerate(selected_lesson.beats)
        ]
        return {
            "kind": "tutorial-lessons/v1",
            "invitation": {
                "visible": self._invite_visible(),
                "title": "문서나르미 첫 안내",
                "body": "예제 서식과 데이터로 첫 문서를 만드세요. 시작할 때 연습 사본을 준비합니다.",
            },
            #: Toggle-only value (#1147); the controller ORs in practice-active before this reaches the web.
            "entry": {"visible": self.entry_visible},
            "active": self.active,
            "paused": not self.active and selected_lesson is not None and checkpoint < len(selected_lesson.beats),
            "scenario_id": self.selected,
            "checkpoint": checkpoint,
            "beat_count": len(selected_lesson.beats) if selected_lesson else 0,
            "stages": stages,
            "scenarios": [
                {
                    "id": lesson.id,
                    "title": lesson.title,
                    "description": lesson.description,
                    "recommended": lesson.id == LESSONS[0].id,
                    "completed": self.record(lesson.id)["completed"],
                    "checkpoint": self.record(lesson.id)["checkpoint"],
                    "step_count": len(lesson.beats),
                }
                for lesson in LESSONS
            ],
            "beat": None if beat is None else _beat_view(beat),
            "recovery": None,
            "resources": {"ready": False, "summary": ""},
            "show_result": self.result is not None,
            "result": self.result,
            "copy": {
                "start": "예제로 시작", "later": "나중에", "pause": "안내 일시정지",
                "resume": "계속하기", "skip": "건너뛰기", "restart": "처음부터 안내",
                "next": "다음", "next_lesson": "다음 연습",
                "cleanup": "연습 파일 정리", "reset": "학습 기록 초기화",
                "cleanup_confirm": "아래 목록에서 삭제로 표시한 연습 사본만 지웁니다. 수정한 파일과 작업이 참조하는 파일은 그대로 둡니다.",
                "reset_confirm": "모든 과정의 학습 위치와 완료 기록을 지웁니다. 연습 파일, 사용자 파일, 저장한 작업과 생성 결과는 그대로 둡니다.",
                "open_tutorial": "튜토리얼", "close": "닫기", "choose_scenario": "과정 고르기",
                "practice": "연습 중", "exit": "연습 종료", "return": "현재 단계로 돌아가기",
            },
        }


def _beat_view(beat: Beat) -> dict:
    return {
        "id": beat.id,
        "title": beat.title,
        "body": beat.body,
        "mode": beat.mode,
        "screen": beat.screen,
        "entry_screen": beat.entry_screen,
        "target": beat.target,
        "arg": beat.arg,
        "press": beat.event in UI_PRESS_EVENTS,
        "placement": beat.placement,
        "can_next": beat.event is None,
        #: Range beats: the text range the guide resolves on the open practice document.
        "range": None,
    }
