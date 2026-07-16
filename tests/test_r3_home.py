"""코드리뷰 3차(home 클러스터) 회귀 가드 — 태그 왕복(C9)·새로고침 배선(N1).

C9: home.js editTags 가 현재 태그를 '축=값, 축=값' 콤마 직렬화로 프리필한 뒤 재파싱했다.
값에 쉼표가 있으면(백엔드 _do_set_tags 는 허용 — 수동 .job.json 편집으로 도달 가능)
프리필을 그대로 OK 해도 태그가 조용히 쪼개져 재작성되거나 형식 오류로 편집이 막혔다.
봉합: 직렬화 직후 재파싱해 원본과 대조하는 왕복 가드 — 불일치면 인라인 편집 불가를
시끄럽게 알리고 중단한다(confirm-or-alarm, 조용한 재작성 금지).

N1: $("homeRefresh") → Bridge.call(SCREEN,"refresh") 이 fire-and-forget 이라 레지스트리
IO 실패 등의 rejection 이 삼켜져 클릭이 무반응이 됐다. .catch 로 표면화한다.

순수 JS 지점이라 정적 계약 테스트(test_r3_js.py 패턴) + 백엔드 전제(콤마 값 허용)는
HomeController 로 실행 검증한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_home import HomeController

HOME_JS = Path(__file__).resolve().parents[1] / "web" / "js" / "screens" / "home.js"


def _edit_tags_body(src: str) -> str:
    """editTags 함수 본문 조각 — 다음 최상위 함수 정의 전까지(정적 검사 범위 한정)."""
    start = src.index("function editTags")
    end = src.index("function onJobsClick")
    return src[start:end]


# --------------------------------------------------------------- C9: 태그 왕복 가드

def test_edit_tags_roundtrip_guard_before_prompt():
    """직렬화(ser) 직후·prompt 이전에 재파싱-대조 왕복 가드가 있어야 한다(C9).

    가드가 prompt 뒤로 밀리거나 사라지면 쉼표 값 태그가 OK 한 번에 조용히 쪼개진다.
    """
    src = HOME_JS.read_text(encoding="utf-8")
    body = _edit_tags_body(src)
    assert "parseTags(ser)" in body, (
        "editTags 가 프리필 직렬화(ser)를 재파싱해 원본과 대조하지 않습니다 — C9 왕복 가드 소실."
    )
    assert "sameTags(" in body, "editTags 왕복 가드가 의미 동치 비교(sameTags)를 하지 않습니다(C9)."
    guard_pos = body.index("parseTags(ser)")
    prompt_pos = body.index("window.prompt")
    assert guard_pos < prompt_pos, (
        "왕복 가드가 window.prompt 뒤에 있습니다 — 편집 진입 전에 중단해야 합니다(C9)."
    )
    # 가드 불일치 분기는 조용한 진행이 아니라 loud alert + 중단이어야 한다.
    guard_branch = body[guard_pos:prompt_pos]
    assert "window.alert" in guard_branch and "return" in guard_branch, (
        "왕복 가드 불일치 분기가 alert 후 중단하지 않습니다 — confirm-or-alarm 위반(C9)."
    )


def test_edit_tags_single_parser_no_inline_copy():
    """파싱 로직은 parseTags 단일 정의여야 한다 — 프리필 검증·입력 파싱이 갈라지면
    가드가 검사하는 문법과 실제 저장 문법이 어긋난다(C9)."""
    src = HOME_JS.read_text(encoding="utf-8")
    assert "function parseTags" in src, "parseTags 공유 파서가 없습니다(C9)."
    # '=' 분할 파싱(indexOf("="))이 parseTags 밖에 복제되면 안 된다.
    positions = [m.start() for m in re.finditer(re.escape('indexOf("=")'), src)]
    assert len(positions) == 1, (
        f"'=' 분할 파싱이 {len(positions)}곳에 있습니다 — parseTags 단일 출처 회귀(C9)."
    )
    body = _edit_tags_body(src)
    assert "parseTags(input)" in body, "editTags 가 사용자 입력을 parseTags 로 파싱하지 않습니다(C9)."


def test_backend_set_tags_accepts_comma_values(tmp_path):
    """전제 고정: _do_set_tags 는 값 내 쉼표를 허용한다(기존 데이터 호환).

    이 전제가 참인 한 웹 인라인 편집은 왕복 가드 없이는 안전하지 않다 — 백엔드가
    쉼표를 거부하게 바뀌면(호환 검토 필요) 이 테스트가 시끄럽게 알린다(C9 스코프 문서화).
    """
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="", filename_pattern="공고-{{ID}}"))
    txt = tmp_path / "txt"
    txt.mkdir()
    ctrl = HomeController(reg, TextTemplateRegistry(txt), lambda s, snap: None)
    ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"지역": "본청, 대전"}})
    assert reg.load("공고서").tags == {"지역": "본청, 대전"}
    # 웹 스냅샷 프리필 표면에도 그대로 실린다 — home.js 왕복 가드가 다루는 바로 그 값.
    rows = [r for sec in ctrl.snapshot()["grouped_rows"] for r in sec["rows"]]
    assert rows[0]["tags"] == {"지역": "본청, 대전"}


# --------------------------------------------------------------- N1: 새로고침 배선

def test_home_refresh_rejection_surfaced():
    """homeRefresh 클릭 배선이 rejection 을 표면화해야 한다(N1) — fire-and-forget 회귀 가드."""
    src = HOME_JS.read_text(encoding="utf-8")
    # 배선 문장 전체(첫 ';' 까지 — 내부에 세미콜론 없음)를 잡아 .catch 존재를 검사한다.
    m = re.search(r'\$\("homeRefresh"\)\.addEventListener\([^;]*;', src, re.S)
    assert m, "homeRefresh → refresh 배선이 없습니다."
    assert '"refresh"' in m.group(0), "homeRefresh 배선이 refresh 액션을 호출하지 않습니다."
    wiring = m.group(0)
    assert ".catch" in wiring, (
        "homeRefresh 의 Bridge.call 이 fire-and-forget 입니다 — 실패가 조용히 삼켜집니다(N1)."
    )
    assert "window.alert" in wiring, "homeRefresh 실패 표면화가 alert 로 재진술되지 않습니다(N1)."
