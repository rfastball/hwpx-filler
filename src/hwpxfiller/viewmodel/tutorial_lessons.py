"""Eight short onboarding lessons and their persistent guidance position.

Only explicit explanation steps use ``next``. Action steps advance from a
verified product event supplied by the tutorial controller. The old T0–T17
checklist is intentionally not a source of completion for this curriculum.
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

    @property
    def mode(self) -> str:
        return "action" if self.event else "explain"


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    description: str
    beats: tuple[Beat, ...]


LESSONS: tuple[Lesson, ...] = (
    Lesson("first_hwpx", "첫 HWPX 문서", "공고서 작업을 만들고 3건을 생성합니다.", (
        Beat("intro", "첫 문서", "연습용 공고서와 공고 데이터로 첫 문서를 만드세요.", None, None),
        Beat("template", "서식 고르기", "문서 작업에서 새 작업을 열고 연습용 '물품 구매입찰 공고' 서식을 고르세요.", "editor", "template-list", "template_selected", entry_screen="library"),
        Beat("data", "공고 시트 고르기", "공고목록.xlsx의 '공고' 시트를 연결하세요.", "editor", "data-picker", "notice_data_selected"),
        Beat("mapping", "두 연결 확인", "'낙찰자결정방법'은 '낙찰방법', '담당자 전화번호'는 '담당자전화'로 연결된 제안을 직접 확인하세요.", "editor", "mapping", "notice_mapping_confirmed"),
        Beat("pattern", "파일 이름 규칙", "파일 이름 규칙을 구매입찰공고-{{입찰공고번호}}로 정하세요.", "editor", "filename-pattern", "notice_pattern_set"),
        Beat("save", "작업 저장", "확인한 연결과 파일 이름 규칙으로 작업을 저장하세요.", "editor", "save-job", "notice_job_saved"),
        Beat("open", "작업 열기", "저장한 공고서 작업을 문서 만들기에서 여세요.", "job", "job-list", "notice_job_opened"),
        Beat("filter", "메모로 3행 찾기", "메모 열에서 '소기업·소상공인'인 행만 찾으세요.", "job", "row-filter", "notice_first_filtered"),
        Beat("rows", "3행 선택", "검색된 3행을 선택하세요.", "job", "row-selection", "notice_first_rows"),
        Beat("options", "두 항목 고르기", "입찰참가자격은 '소기업·소상공인', 낙찰자 결정방법은 '고시 미만'을 고르세요.", "job", "content-options", "notice_first_options"),
        Beat("generate", "문서 만들기", "선택한 3행의 문서 만들기를 실행하세요.", "job", "generate", "notice_first_generated"),
        Beat("result", "결과 확인", "결과 3건과 파일 이름을 확인하고 한 문서의 내용을 여세요.", "job", "results", "notice_result_opened"),
    )),
    Lesson("repeat_hwpx", "저장한 작업 다시 쓰기", "다른 행과 내용을 골라 같은 작업을 다시 실행합니다.", (
        Beat("open", "저장한 작업 열기", "문서 작업에서 준비된 공고서 작업을 문서 만들기로 여세요.", "job", "job-list", "notice_job_opened", entry_screen="library"),
        Beat("clear", "이전 선택 비우기", "앞서 고른 행을 해제해 새 묶음과 섞이지 않게 하세요.", "job", "row-selection", "rows_cleared"),
        Beat("filter", "다른 메모 조건", "메모에서 '중·소기업' 묶음인 R26BK99000004-000부터 006-000까지 찾으세요.", "job", "row-filter", "notice_second_filtered"),
        Beat("rows", "다른 행 고르기", "이번 묶음의 3행만 선택하세요.", "job", "row-selection", "notice_second_rows"),
        Beat("options", "포함할 내용 바꾸기", "입찰참가자격은 '중·소기업', 낙찰자 결정방법은 '고시 미만'을 고르세요.", "job", "content-options", "notice_second_options"),
        Beat("generate", "다시 만들기", "새 행의 입찰공고번호가 파일 이름에 들어가는지 확인하고 문서를 만드세요.", "job", "generate", "notice_second_generated"),
    )),
    Lesson("contract_txt", "계약 TXT 검토·복사", "계약 데이터 2건을 확인하고 각각 복사합니다.", (
        Beat("template", "계약 시트", "문서 작업에서 새 작업을 열고 계약 안내 TXT와 공고목록.xlsx의 '계약' 시트를 고르세요.", "editor", "template-list", "contract_inputs_selected", entry_screen="library"),
        Beat("mapping", "대표계약업체 연결", "'대표계약업체'에 '계약상대자' 열을 직접 연결하세요.", "editor", "mapping", "contract_mapping_set"),
        Beat("currency", "계약보증금 원 표시", "'계약보증금' 표시형을 금액 '원'으로 고르세요.", "editor", "mapping", "contract_currency_set"),
        Beat("save", "TXT 작업 저장", "연결을 확인하고 TXT 작업을 저장하세요.", "editor", "save-job", "contract_job_saved"),
        Beat("open", "두 행 검토", "저장한 계약 작업을 문서 만들기로 열고 두 행을 선택해 검토·복사 작업대로 들어가세요. 서로 다른 두 행을 확인하세요.", "workbench", "txt-review", "contract_two_reviewed", entry_screen="library"),
        Beat("copy", "각각 복사", "각 행의 채운 문장을 따로 복사하세요. 앱은 외부 붙여넣기를 확인하지 않습니다.", "workbench", "txt-copy", "contract_two_copied"),
    )),
    Lesson("purchase_txt", "구매추진 TXT 가공", "군품명의 첫 조각과 날짜·금액 표시를 확인합니다.", (
        Beat("inputs", "공고 시트", "문서 작업에서 새 작업을 열고 구매추진 안내 TXT와 '공고' 시트를 고르세요.", "editor", "template-list", "purchase_inputs_selected", entry_screen="library"),
        Beat("slice", "군품명 가공", "'군품명'을 쉼표로 나눈 첫 조각으로 가공하세요. 예제의 '드릴,전동식,휴대용'은 '드릴'이 됩니다.", "editor", "mapping", "purchase_slice_set"),
        Beat("format", "날짜와 금액 표시", "날짜와 금액의 표시형을 미리보기로 확인하세요.", "editor", "mapping", "purchase_formats_checked"),
        Beat("save", "작업 저장", "구매추진 TXT 작업을 저장하세요.", "editor", "save-job", "purchase_job_saved"),
        Beat("preview", "여러 행 미리보기", "저장한 구매추진 작업을 문서 만들기로 열고 두 행을 선택해 검토·복사 작업대로 들어가세요. 서로 다른 행의 문장을 확인하세요.", "workbench", "txt-review", "purchase_two_reviewed", entry_screen="library"),
        Beat("copy", "TXT 복사", "필요한 행의 TXT를 복사하세요.", "workbench", "txt-copy", "purchase_copied"),
    )),
    Lesson("replace_data", "다른 데이터 연결", "연습 데이터 사본을 작업에 다시 연결합니다.", (
        Beat("prepare", "연습 데이터 사본", "원본과 별개인 연습 데이터 사본을 준비하세요.", None, "prepare-examples", "derived_data_prepared"),
        Beat("connect", "새 데이터 연결", "연습 사본을 데이터 선택 목록에 연결하세요.", "editor", "data-picker", "derived_data_selected"),
        Beat("rebind", "작업에 다시 연결", "문서 작업에서 준비된 연습 작업의 편집기를 열고 새 데이터 사본의 공고 시트를 연결하세요. 연결을 다시 제안하고 두 제안을 확인한 뒤 저장하세요.", "editor", "mapping", "derived_job_rebound", entry_screen="library"),
        Beat("reopen", "저장하고 다시 열기", "작업을 저장하고 다시 열어 새 경로와 시트가 유지되는지 확인하세요.", "job", "job-list", "derived_reopened"),
    )),
    Lesson("blank_values", "빈 값 살펴보기", "빈 값 표식을 확인하고 직접 입력으로 고칩니다.", (
        Beat("prepare", "빈 값이 있는 연습 시트", "원본 예제에는 빈 셀이 없습니다. 빈 셀 하나가 있는 연습 사본을 준비하세요.", None, "prepare-examples", "blank_data_prepared"),
        Beat("observe", "빈 값 표식 확인", "문서 작업에서 준비된 계약 연습 작업을 열고 빈 값이 있는 행을 검토·복사 작업대로 보내세요. 카드의 〈빈 값〉 표시를 확인하세요.", "workbench", "txt-review", "blank_observed", entry_screen="library"),
        Beat("repair", "직접 입력으로 고치기", "그 행의 필요한 값을 직접 입력해 다시 확인하세요.", "workbench", "txt-review", "blank_repaired"),
        Beat("compare", "의도적인 비움 비교", "직접 입력으로 고친 '계약보증금'과 의도적으로 비워 둔 '단위'를 비교하세요.", "workbench", "txt-review"),
    )),
    Lesson("field_trial", "내 필드와 결과 시험", "TXT에 필드를 만들고 시험값으로 확인합니다.", (
        Beat("open", "연습 TXT 열기", "템플릿 작업대의 파일 열기로 계약 안내 TXT 연습 사본을 여세요.", "authoring", "authoring-canvas", "field_practice_opened", entry_screen="authoring"),
        Beat("field", "10일을 필드로", "본문의 '10일'을 골라 '재배정기한' 필드로 만드세요.", "authoring", "authoring-canvas", "practice_field_created"),
        Beat("input", "시험값 넣기", "결과 시험에 필드값을 넣으세요.", "authoring", "trial", "field_trial_input"),
        Beat("trial", "결과 시험", "시험을 실행해 현재 구성의 결과를 확인하세요.", "authoring", "trial", "field_trial_passed"),
        Beat("save", "사용 준비로 저장", "구조 오류가 없는 '사용 준비' 상태로 저장하세요.", "authoring", "save-template", "field_practice_saved"),
    )),
    Lesson("option_apply", "항목·선택과 변경 적용", "두 갈래를 시험하고 저장한 변경을 작업에 적용합니다.", (
        Beat("open", "연습 TXT와 작업", "템플릿 작업대의 파일 열기로 준비된 작업에 연결된 계약 안내 TXT 연습 사본을 여세요.", "authoring", "authoring-canvas", "option_practice_opened", entry_screen="authoring"),
        Beat("item", "안내 항목 만들기", "3번 문단을 '예산 재배정 안내' 항목으로 묶으세요.", "authoring", "authoring-canvas", "practice_item_created"),
        Beat("options", "포함·생략 선택 만들기", "'안내 포함'은 문단을, '안내 생략'은 빈 줄을 담게 만드세요.", "authoring", "authoring-canvas", "practice_options_created"),
        Beat("trials", "두 갈래 시험", "두 선택을 각각 시험하고 현재 결과를 확인하세요.", "authoring", "trial", "practice_both_trials_passed"),
        Beat("save", "서식 저장", "구조 오류 없이 템플릿을 저장하세요.", "authoring", "save-template", "option_practice_saved"),
        Beat("apply", "변경사항 확인·적용", "연결된 작업의 변경사항을 확인하고 적용하세요.", "authoring", "apply-change", "option_change_applied"),
        Beat("review", "내용 다시 확인", "문서 만들기에서 '안내 포함'을 고르고 검토·복사 작업대에서 예산 재배정 문단을 확인하세요.", "job", "content-options", "option_result_reviewed"),
    )),
)

BY_ID = {lesson.id: lesson for lesson in LESSONS}


class LessonProgress:
    """IO-free guidance state; records survive pause, close, and restart."""

    def __init__(self, raw: dict | None = None, *, first_launch: bool = False) -> None:
        raw = raw if isinstance(raw, dict) and raw.get("version") == 1 else {}
        self.invite_seen = raw.get("invite_seen") is True
        self.first_launch = first_launch
        selected = raw.get("selected")
        self.selected = selected if isinstance(selected, str) and selected in BY_ID else None
        stored = raw.get("records") if isinstance(raw.get("records"), dict) else {}
        assert isinstance(stored, dict)
        self.records: dict[str, dict] = {}
        for lesson in LESSONS:
            entry = stored.get(lesson.id)
            if not isinstance(entry, dict):
                continue
            index = entry.get("checkpoint")
            if type(index) is not int or not 0 <= index <= len(lesson.beats):
                continue
            context = entry.get("context") if isinstance(entry.get("context"), dict) else {}
            self.records[lesson.id] = {
                "checkpoint": index,
                "completed": entry.get("completed") is True,
                "context": context,
            }
        self.active = False  # restarting the app never opens the coach automatically
        self.result: dict | None = None

    def progress(self) -> dict:
        return {
            "version": 1,
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
        for key in ("reviewed_rows", "copied_rows", "trial_options", "generated", "applied"):
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
                "visible": self.first_launch and not self.invite_seen,
                "title": "문서나르미 첫 안내",
                "body": "예제 서식과 데이터로 첫 문서를 만드세요. 시작할 때 연습 사본을 준비합니다.",
            },
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
            "beat": None if beat is None else {
                "id": beat.id,
                "title": beat.title,
                "body": beat.body,
                "mode": beat.mode,
                "screen": beat.screen,
                "entry_screen": beat.entry_screen,
                "target": beat.target,
                "placement": beat.placement,
                "can_next": beat.event is None,
            },
            "recovery": None,
            "resources": {"ready": False, "summary": ""},
            "show_result": self.result is not None,
            "result": self.result,
            "copy": {
                "start": "예제로 시작", "later": "나중에", "pause": "안내 일시정지",
                "resume": "계속하기", "skip": "건너뛰기", "restart": "처음부터 안내",
                "next": "다음", "prepare": "연습 파일 새로 준비",
                "cleanup": "연습 파일 정리", "reset": "학습 기록 초기화",
                "cleanup_confirm": "아래 목록에서 삭제로 표시한 연습 사본만 지웁니다. 수정한 파일과 작업이 참조하는 파일은 그대로 둡니다.",
                "reset_confirm": "모든 과정의 학습 위치와 완료 기록을 지웁니다. 연습 파일, 사용자 파일, 저장한 작업과 생성 결과는 그대로 둡니다.",
                "open_tutorial": "튜토리얼", "close": "닫기", "choose_scenario": "과정 고르기",
                "practice": "연습 중", "exit": "연습 종료", "return": "현재 단계로 돌아가기",
            },
        }
