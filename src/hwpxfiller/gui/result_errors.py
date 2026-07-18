"""생성 실패 원문 → 행동 지향 안내(RC-30) — Qt 비의존 순수 문자열 로직(링1).

원시 errno/WinError 문자열을 사용자가 취할 조치가 있는 문장으로 보강하되, **원문은
괄호로 보존**한다(증거 무손실 — 조용한 재작성 금지). webview 컨트롤러
(webapp.screen_run)가 소비하며 위젯 계층에서 분리해 둔다 —
:mod:`~hwpxfiller.gui.batch_run` 은 하위호환으로 이 이름을 재export 한다.
"""
from __future__ import annotations

# 원시 오류 원문 → 행동 지향 안내(RC-30). 원문은 괄호로 보존한다(증거 무손실).
# Windows 에서 os.replace(원자 쓰기 = 이 제품의 실제 저장 경로)는 영문 errno 가 아니라
# 지역화된 "[WinError N] …" 문자열로 도착한다(한국어 Windows) — 숫자 코드와 한국어
# 메시지 양쪽을 겨눠야 대상 플랫폼에서 발화한다(반려 조치).
_HINT_ACCESS = (
    "파일 접근이 거부됐습니다 — 같은 이름의 문서가 다른 프로그램(한글 등)에 열려 있지 않은지, "
    "폴더 쓰기 권한이 있는지 확인하세요."
)
_HINT_IN_USE = (
    "파일이 다른 프로그램(한글 등)에 열려 있습니다 — 해당 문서를 닫은 뒤 다시 시도하세요."
)
_HINT_DISK = "디스크 공간이 부족합니다 — 공간을 비우거나 다른 저장 폴더를 지정하세요."
_HINT_MISSING = "경로를 찾을 수 없습니다 — 저장 폴더가 이동·삭제되지 않았는지 확인하세요."

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
