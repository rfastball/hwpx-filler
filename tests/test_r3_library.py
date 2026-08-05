"""코드리뷰 3차(구 home 클러스터 · 재작성 F2 이후 라이브러리) 회귀 가드 — 태그 왕복(C9)·새로고침 배선(N1).

C9: library.js(구 home.js) editTags 가 현재 태그를 '축=값, 축=값' 콤마 직렬화로 프리필한 뒤 재파싱했다.
값에 쉼표가 있으면(백엔드 _do_set_tags 는 허용 — 수동 .job.json 편집으로 도달 가능)
프리필을 그대로 OK 해도 태그가 조용히 쪼개져 재작성되거나 형식 오류로 편집이 막혔다.
봉합: 직렬화 직후 재파싱해 원본과 대조하는 왕복 가드 — 불일치면 인라인 편집 불가를
시끄럽게 알리고 중단한다(confirm-or-alarm, 조용한 재작성 금지).

N1: 새로고침 경로의 Bridge.call 이 fire-and-forget 이라 레지스트리 IO 실패 등의
rejection 이 삼켜져 무반응이 됐다. .catch 로 표면화한다. 수동 새로고침 버튼(homeRefresh)은
F6 으로 제거됐다 — 이 화면의 갱신은 전환 자동 새로고침(셸 상태기계 nav.ts 의 REFRESH_ON_NAV,
R3-02)이 유일 경로이므로 N1 가드도 그 배선으로 이관한다(버튼 재도입·자동 갱신 탈락 둘 다 회귀).

순수 JS 지점이라 정적 계약 테스트(test_r3_js.py 패턴) + 백엔드 전제(콤마 값 허용)는
LibraryController 로 실행 검증한다.
"""
from __future__ import annotations

import re

from _web_source import SOURCE_INDEX, SOURCE_JS_DIR
from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_library import LibraryController

LIB_JS = SOURCE_JS_DIR / "screens" / "library.js"


def _edit_tags_body(src: str) -> str:
    """editTags 함수 본문 조각 — 다음 최상위 함수 정의 전까지(정적 검사 범위 한정)."""
    start = src.index("function editTags")
    end = src.index("function relinkTemplate")
    return src[start:end]


# --------------------------------------------------------------- C9: 태그 왕복 가드

def test_edit_tags_roundtrip_guard_before_prompt():
    """직렬화(ser) 직후·prompt 이전에 재파싱-대조 왕복 가드가 있어야 한다(C9).

    가드가 prompt 뒤로 밀리거나 사라지면 쉼표 값 태그가 OK 한 번에 조용히 쪼개진다.
    """
    src = LIB_JS.read_text(encoding="utf-8")
    body = _edit_tags_body(src)
    assert "parseTags(ser)" in body, (
        "editTags 가 프리필 직렬화(ser)를 재파싱해 원본과 대조하지 않습니다 — C9 왕복 가드 소실."
    )
    assert "sameTags(" in body, "editTags 왕복 가드가 의미 동치 비교(sameTags)를 하지 않습니다(C9)."
    guard_pos = body.index("parseTags(ser)")
    # 네이티브 window.prompt 는 Modal.prompt 로 이관됨(#86) — 가드는 여전히 그 이전이어야 한다.
    prompt_pos = body.index("Modal.prompt")
    assert guard_pos < prompt_pos, (
        "왕복 가드가 Modal.prompt 뒤에 있습니다 — 편집 진입 전에 중단해야 합니다(C9)."
    )
    # 가드 불일치 분기는 조용한 진행이 아니라 loud alert + 중단이어야 한다.
    guard_branch = body[guard_pos:prompt_pos]
    assert "window.alert" in guard_branch and "return" in guard_branch, (
        "왕복 가드 불일치 분기가 alert 후 중단하지 않습니다 — confirm-or-alarm 위반(C9)."
    )


def test_edit_tags_single_parser_no_inline_copy():
    """파싱 로직은 parseTags 단일 정의여야 한다 — 프리필 검증·입력 파싱이 갈라지면
    가드가 검사하는 문법과 실제 저장 문법이 어긋난다(C9)."""
    src = LIB_JS.read_text(encoding="utf-8")
    assert "function parseTags" in src, "parseTags 공유 파서가 없습니다(C9)."
    # '=' 분할 파싱(indexOf("="))이 parseTags 밖에 복제되면 안 된다.
    positions = [m.start() for m in re.finditer(re.escape('indexOf("=")'), src)]
    assert len(positions) == 1, (
        f"'=' 분할 파싱이 {len(positions)}곳에 있습니다 — parseTags 단일 출처 회귀(C9)."
    )
    body = _edit_tags_body(src)
    assert "parseTags(raw)" in body, "editTags 가 사용자 입력을 parseTags 로 파싱하지 않습니다(C9)."


def test_backend_set_tags_accepts_comma_values(tmp_path):
    """전제 고정: _do_set_tags 는 값 내 쉼표를 허용한다(기존 데이터 호환).

    이 전제가 참인 한 웹 인라인 편집은 왕복 가드 없이는 안전하지 않다 — 백엔드가
    쉼표를 거부하게 바뀌면(호환 검토 필요) 이 테스트가 시끄럽게 알린다(C9 스코프 문서화).
    """
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="", filename_pattern="공고-{{ID}}"))
    txt = tmp_path / "txt"
    txt.mkdir()
    ctrl = LibraryController(reg, TextTemplateRegistry(txt), lambda s, snap: None,
                          pool_registry=DatasetPoolRegistry(tmp_path / "datasets"))
    ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"지역": "본청, 대전"}})
    assert reg.load("공고서").tags == {"지역": "본청, 대전"}
    # 웹 프리필 표면에도 그대로 실린다 — library.js 왕복 가드가 다루는 바로 그 값.
    # 프리필의 원천은 **상세**다(행이 아니다): 행은 걸러진 투영이라 정체의 원천이 될 수 없다
    # (리뷰 1R P1 근본 조치 — 행 페이로드에서 태그를 걷었다).
    ctrl.dispatch("select_work", {"name": "공고서"})
    assert ctrl.snapshot()["detail"]["tags"] == {"지역": "본청, 대전"}


# --------------------------------------------------------------- N1: 새로고침 배선(F6 이관)

APP_JS = SOURCE_JS_DIR / "app.js"
# R3-02(#411) — 화이트리스트·재당김 규약 판정의 정본은 셸 상태기계로 이동했다. 발신
# (Bridge.call)과 실패 재진술(alert)은 집행 adapter(app.js)에 남는다.
NAV_TS = SOURCE_JS_DIR.parent / "src" / "shell" / "nav.ts"
WEB_INDEX = SOURCE_INDEX


def test_manual_home_refresh_button_removed():
    """수동 새로고침 버튼은 제거 상태를 유지해야 한다(F6) — 자동 갱신(REFRESH_ON_NAV)과
    중복인 잉여 어포던스의 재도입 회귀 가드. tpl·pool 의 새로고침(외부 파일 재스캔)과 다르다."""
    assert 'id="homeRefresh"' not in WEB_INDEX.read_text(encoding="utf-8"), (
        "homeRefresh 버튼이 다시 들어왔습니다 — 홈은 전환 자동 새로고침이 유일 경로입니다(F6)."
    )
    assert "homeRefresh" not in LIB_JS.read_text(encoding="utf-8"), (
        "home.js 가 제거된 homeRefresh 를 참조합니다(F6)."
    )


def test_nav_refresh_covers_library_and_surfaces_rejection():
    """갱신의 유일 경로(전환 자동 새로고침)가 library 를 포함하고 rejection 을 표면화한다(N1).

    library 가 REFRESH_ON_NAV 에서 빠지면 수동 버튼 없는 이 화면은 스냅샷이 고착되고,
    .catch 가 빠지면 갱신 실패가 조용히 삼켜진다 — 둘 다 시끄럽게 잡는다. 이 화면의
    refresh 는 레지스트리와 **영속 그룹 접힘**을 함께 다시 읽는다(다른 화면에서 접은 상태).

    8R 근본 조치로 재당김이 `Nav.refresh` 한 정의로 모였다 — 분기 위치가 아니라 ①목록에
    library 가 있는가 ②그 정의가 refresh 액션을 쏘는가 ③전환의 발신이 rejection 을 표면화
    하는가를 본다(구현 형태를 못 박으면 다음 정리가 무고하게 붉어진다).
    """
    src = APP_JS.read_text(encoding="utf-8")
    nav_ts = NAV_TS.read_text(encoding="utf-8")
    m = re.search(r"REFRESH_ON_NAV[^=]*=\s*Object\.freeze\(\[[^\]]*\]\)", nav_ts)
    assert m and '"library"' in m.group(0), (
        "상태기계 REFRESH_ON_NAV 에 library 가 없습니다 — 수동 버튼 제거(F6) 전제가 무너집니다."
    )
    definition = re.search(r"function refresh\(id: string\)[\s\S]*?\n  \}", nav_ts)
    assert definition, "재당김 단일 정의(상태기계 refresh)가 없습니다(REFRESH_ON_NAV 소비처 소실)."
    wiring = definition.group(0)
    assert "REFRESH_ON_NAV.includes(id)" in wiring, (
        "재당김 정의가 REFRESH_ON_NAV 화이트리스트를 보지 않습니다 — 미지 액션 무차별 dispatch."
    )
    assert re.search(r'Bridge\.call\(id, "refresh"', src), (
        "집행 adapter 가 refresh 액션을 발신하지 않습니다 — 판정이 통과해도 재당김이 죽습니다."
    )
    assert re.search(r"refresh\(id\)\.catch\([\s\S]*?notifyRefreshFailure", nav_ts), (
        "전환의 자동 새로고침이 fire-and-forget 입니다 — 실패가 조용히 삼켜집니다(N1)."
    )
    assert re.search(r"notifyRefreshFailure\(err\) \{[\s\S]*?window\.alert", src), (
        "실패 재진술 포트가 alert 로 착지하지 않습니다 — 재진술 없는 표면화는 침묵입니다(N1)."
    )
    # N-06 후계: Nav 는 앱 셸 factory 산물(`const Nav = { go, refresh }`)이고 전역 별칭은
    # 죽었다 — 여기서는 표면에 refresh 가 실려 반환되는가를 본다.
    assert re.search(r"const Nav = \{[^}]*\brefresh\b", src), (
        "Nav.refresh 가 노출되지 않았습니다 — 이탈 착지가 전환 전에 기다릴 수 없습니다(8R P1)."
    )
