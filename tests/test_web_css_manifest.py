"""분할된 앱 스타일시트의 **매니페스트 게이트** — 순서와 전수를 사람이 아니라 게이트가 지킨다.

`app.css` 를 9조각으로 자르면서 생긴 새 실패 방식은 "조용한 누락"이다. 새 CSS 파일을 만들고
`<link>` 만 걸면, 그 파일은 `_web_css.app_css()` 밖이라 16개 계약 테스트(색 리터럴·모션 상한·
스크롤포트·모달·sticky …) 전부가 **그 파일을 못 보면서 초록**이 된다. 게이트가 빨간불이 아니라
침묵으로 죽는 이 결함류는 이 저장소가 index.html 분할을 기각한 바로 그 이유이므로, 분할을
하려면 같은 자리에서 막아야 한다(`confirm-or-alarm`).

그래서 두 방향을 다 막는다:
- 링크에는 있는데 매니페스트에 없다 → 순서 대조가 잡는다.
- 디스크에는 있는데 링크에도 매니페스트에도 없다 → glob 전수가 잡는다.

형태는 `test_web_dom_contract.test_render_layer_state_budget_covers_every_screen` 과 같다 —
다음 누락은 사람이 아니라 게이트가 잡는다.
"""

from __future__ import annotations

from pathlib import Path

from _web_css import ALL_CSS_FILES, APP_CSS_FILES, WEB_CSS_DIR, linked_css

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"


def test_app_css_manifest_matches_index_link_order() -> None:
    """셸의 `<link>` 순서 == `ALL_CSS_FILES`. 순서는 장식이 아니라 캐스케이드 계약이다.

    조각들은 규칙을 옮기지 않고 경계에서만 자른 것이라, 이어붙이면 옛 `app.css` 와 바이트
    동일하다 — 그 등가는 **이 순서일 때만** 참이다. 같은-명시도 hover→상태 쌍(`.navbtn:hover`
    → `.navbtn[aria-current]` 류)과 앞선 전 구역을 덮어야 하는 `forced-colors` 가 순서에
    걸려 있어, 한 줄만 뒤바뀌어도 화면이 조용히 달라진다.
    """
    linked = linked_css(INDEX.read_text(encoding="utf-8"), "css/")
    assert linked == ALL_CSS_FILES, (
        "web/index.html 의 스타일시트 <link> 순서가 매니페스트와 다릅니다.\n"
        f"  링크:       {linked}\n"
        f"  매니페스트: {ALL_CSS_FILES}\n"
        "순서를 맞추거나, 새 파일이면 tests/_web_css.py 의 APP_CSS_FILES 에 "
        "제 위치로 등재하세요(등재 없이는 계약 테스트가 그 파일을 못 봅니다)."
    )


def test_every_css_file_on_disk_is_manifested() -> None:
    """`web/css/*.css` 전수가 매니페스트에 있다 — 등재 없는 파일이 검사 밖으로 새지 못하게.

    링크 대조만 있으면 "링크도 매니페스트도 없는" 파일이 통과한다. 그런 파일은 실앱에
    안 실리므로 죽은 코드거나, 누군가 곧 링크할 예정인 미등재 파일이다 — 둘 다 시끄러워야 한다.
    """
    on_disk = {p.name for p in WEB_CSS_DIR.glob("*.css")}
    manifested = set(ALL_CSS_FILES)
    unmanifested = sorted(on_disk - manifested)
    missing = sorted(manifested - on_disk)
    assert not unmanifested, (
        f"web/css 에 매니페스트 밖 파일이 있습니다: {', '.join(unmanifested)}. "
        "tests/_web_css.py 의 APP_CSS_FILES 에 등재하고 web/index.html 에 링크하세요 — "
        "미등재 파일은 색 리터럴·모션 상한·스크롤포트 계약 검사를 전부 우회합니다."
    )
    assert not missing, (
        f"매니페스트에 있는데 디스크에 없는 파일: {', '.join(missing)}."
    )


def test_split_stylesheets_are_nonempty_and_comment_balanced() -> None:
    """각 조각이 비어 있지 않고 블록 주석이 파일 안에서 닫힌다.

    컷이 주석 한가운데를 지나가면 이어붙인 문자열은 여전히 원본과 같지만 **개별 파일**은
    깨진 CSS 가 된다(앞 조각은 열린 채 끝나고 뒷 조각은 `*/` 로 시작). 브라우저는 이어붙여
    읽지 않고 파일마다 파싱하므로 그 순간 규칙이 통째로 증발한다 — 원본 컷(`app.css:813` 의
    고아 주석)이 실제로 그 형태였다.
    """
    for name in APP_CSS_FILES:
        text = (WEB_CSS_DIR / name).read_text(encoding="utf-8")
        assert text.strip(), f"{name} 이 비어 있습니다 — 컷 경계가 틀렸습니다."
        assert text.count("/*") == text.count("*/"), (
            f"{name} 의 블록 주석이 파일 안에서 닫히지 않습니다 "
            f"(열림 {text.count('/*')} · 닫힘 {text.count('*/')}) — "
            "컷이 주석을 가로질렀습니다."
        )
