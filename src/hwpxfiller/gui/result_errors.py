"""생성 실패 원문 → 행동 지향 안내(RC-30) — Qt 비의존 순수 문자열 로직(링1).

원시 errno/WinError 문자열을 사용자가 취할 조치가 있는 문장으로 보강하되, **원문은
괄호로 보존**한다(증거 무손실 — 조용한 재작성 금지). webview 컨트롤러
(webapp.screen_job)가 소비하며 위젯 계층에서 분리해 둔다 —
:mod:`~hwpxfiller.gui.batch_run` 은 하위호환으로 이 이름을 재export 한다.
"""
from __future__ import annotations

# 원시 오류 원문 → 행동 지향 안내(RC-30). 원문은 괄호로 보존한다(증거 무손실).
# Windows 에서 os.replace(원자 쓰기 = 이 제품의 실제 저장 경로)는 영문 errno 가 아니라
# 지역화된 "[WinError N] …" 문자열로 도착한다(한국어 Windows) — 숫자 코드와 한국어
# 메시지 양쪽을 겨눠야 대상 플랫폼에서 발화한다(반려 조치).
_HINT_ACCESS = (
    "파일 접근이 거부됐습니다. 같은 이름의 문서가 다른 프로그램(한글 등)에 열려 있지 않은지, "
    "폴더 쓰기 권한이 있는지 확인하세요."
)
_HINT_IN_USE = (
    "파일이 다른 프로그램(한글 등)에 열려 있습니다. 해당 문서를 닫은 뒤 다시 시도하세요."
)
_HINT_DISK = "디스크 공간이 부족합니다. 공간을 비우거나 다른 저장 폴더를 지정하세요."
_HINT_MISSING = "경로를 찾을 수 없습니다. 저장 폴더가 이동·삭제되지 않았는지 확인하세요."

_ERROR_HINTS: "tuple[tuple[str, str], ...]" = (
    # errno 영문(비-Windows·일부 라이브러리 경유)
    ("Permission denied", _HINT_ACCESS),
    ("No space left", _HINT_DISK),
    ("No such file or directory", _HINT_MISSING),
    # WinError — 코드(로케일 무관)와 한국어 메시지(코드가 잘려도) 양쪽을 겨눈다.
    ("[WinError 5]", _HINT_ACCESS),
    ("액세스가 거부", _HINT_ACCESS),
    ("[WinError 32]", _HINT_IN_USE),
    ("다른 프로세스가 파일을 사용 중", _HINT_IN_USE),
    ("[WinError 112]", _HINT_DISK),
    ("디스크에 공간이 부족", _HINT_DISK),
)


def describe_result_error(error: str) -> str:
    """레코드 실패 사유를 행동 지향 문구로 보강(RC-30) — 원시 errno 관통 해소.

    아는 패턴이 없으면 원문 그대로(조용한 재작성 금지 — 원문이 곧 증거).
    """
    for needle, hint in _ERROR_HINTS:
        if needle in error:
            return f"{hint} (원문: {error})"
    return error


# FillNote kind → (사후 문안, 사전 문안) 짝 — 같은 사실을 시제만 바꿔 말한다
# ("사전에 알고 사후에 확인"). 한 표에 짝으로 두어 새 kind 가 한쪽만 갱신되는
# 드리프트를 구조로 막는다. {field}=필드명, {kinds}=제거 대상 열거(detail).
# occurrence_unfillable 은 "일부" 라 말하지 않는다 — 전 자리가 불가할 수도 있고
# 그때 실행은 unmatched 로 더 시끄럽게 끝난다(범위 미정 시 규칙만 재진술).
_FILL_NOTE_WORDING: "dict[str, tuple[str, str]]" = {
    "inline_stripped": (
        "누름틀 '{field}' 값 안의 인라인 요소({kinds})를 값과 함께 "
        "제거하고 채웠습니다. 형광펜 등 표식이 사라졌을 수 있으니 산출물을 확인하세요.",
        "누름틀 '{field}' 값 안에 인라인 요소({kinds})가 있습니다. "
        "다른 값을 채우면 값과 함께 제거됩니다.",
    ),
    "slot_synthesized": (
        "빈 누름틀 '{field}' 에 값 자리를 새로 만들어 채웠습니다. "
        "서식은 누름틀 주변 서식을 따릅니다.",
        "빈 누름틀 '{field}': 채울 때 값 자리를 새로 만듭니다.",
    ),
    "occurrence_unfillable": (
        "누름틀 '{field}' 자리 중 구조상 기입할 수 없는 곳이 있어 건너뛰었습니다. "
        "산출물에서 해당 자리를 확인하세요.",
        "누름틀 '{field}' 자리 중 구조상 기입할 수 없는 곳이 있습니다. "
        "그 자리는 채워지지 않습니다.",
    ),
}


def _fill_note_text(note, *, pre: bool) -> str:
    pair = _FILL_NOTE_WORDING.get(note.kind)
    if pair is None:
        return f"누름틀 '{note.field}': {note.kind}"  # 미지 종류 원문 관통
    return pair[1 if pre else 0].format(
        field=note.field, kinds=", ".join(note.detail)
    )


def describe_fill_note(note) -> str:
    """채움 완화 처리(:class:`~hwpxfiller.core.fields.FillNote`) → 사후 문안(#154).

    코어는 사실(필드·종류·제거 요소)만 담고 문안은 여기서 성형한다 — CLI 와 webview
    컨트롤러가 같은 문장을 공유한다. 미지 종류는 원문 관통(조용한 누락 금지).
    """
    return _fill_note_text(note, pre=False)


def describe_precheck_note(note) -> str:
    """사전 판정(:func:`~hwpxfiller.core.fields.fill_precheck`) → 점검 문안(#154).

    사후(:func:`describe_fill_note`)와 같은 사실의 시제 변환판 — 짝은
    :data:`_FILL_NOTE_WORDING` 한 표가 강제한다.
    """
    return _fill_note_text(note, pre=True)
