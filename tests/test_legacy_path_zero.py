"""폐기된 source 트리 이름이 저장소에서 **0인가**(N-11 · #383).

마일스톤 N 은 프런트 source 를 옮겼고 트리 자체는 사라졌다. 제품 런타임이 그 이름으로
되돌아가지 않는 것은 ``test_web_m1_topology`` 의 AST 게이트가 이미 진다. 그런데 그 게이트는
**Python 경로 조립**만 본다 — 문서 산문, 목업의 ``<link href>``, 주석, 테스트 라벨은 아무도
안 봤고, 실제로 남아 있었다(착수 시점 추적 파일 14개). 그중 한 목업은 스타일시트 링크가
깨진 채였는데도 전 게이트가 초록이었다.

그래서 여기서는 좁게 파고들지 않고 **저장소 전역**을 센다. 두 가지를 지킨다:

1. 대상은 ``git ls-files`` 의 추적 파일뿐이다. ``build/``·``node_modules/``·
   ``.claude/worktrees/`` 의 stale 사본이 이 판정을 오염시키지 못한다.
2. 역사 인용은 **파일별로 사유와 함께** 허용하고, 허용 목록이 썩지 않도록 각 항목이 실제로
   아직 인용을 담고 있는지 되짚는다. 디렉터리 통짜 허용은 두지 않는다 — 통짜로 열면 그 안에
   새 참조가 들어와도 아무도 모른다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 금지 토큰은 조립한다 — 안 그러면 탐지기 자신이 첫 위반이 된다.
#: (N-09 실증: 봉인의 금지 패턴이 자기 어휘를 거절했다.)
_RETIRED_ROOT = "w" + "eb"

#: 역할 세그먼트를 **요구**한다. 산문 속 "web/ 강제 색상 모드" 같은 무해한 표현이나
#: ``build/web`` 산출물 경로를 잡지 않기 위해서다.
LEGACY_PATH_RE = re.compile(
    rf"(?<![\w.\-])(?:(?:\.\./)+)?{_RETIRED_ROOT}/(?:js|css|img|fonts|src|index\.html)"
)

#: 바이너리·대용량 자산은 텍스트로 읽지 않는다.
_SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff2", ".hwpx", ".xlsx", ".zip"}
)

#: 파일별 허용과 **사유**. 전부 과거 시점의 실제 경로를 인용하는 자리라, 현재 이름으로
#: 고치면 인용이 틀린 것이 된다(고쳐야 할 것이 아니라 고치면 안 되는 것).
HISTORICAL_CITATIONS = {
    "docs/archive/DATA_FIRST_INTEGRATION_MAP.md": (
        "완주·동결된 원장 — 당시 표면의 실제 경로 인용"
    ),
    "docs/r-flow-mockups/block4-filter-crystallize-demo.html": (
        "동결 시안 — 시연 근거로 당시 코드 출처를 표기한다"
    ),
    "docs/UX_FEEDBACK_U2.md": (
        "git 고고학 인용 — 과거 commit 에 실재한 경로라 현재 이름으로 고치면 틀린다"
    ),
}


def _tracked_files() -> tuple[Path, ...]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return tuple(Path(name) for name in listing.split("\0") if name)


def scan(text: str) -> list[str]:
    """폐기된 source 경로 참조를 담은 줄만 돌려준다(음성 대조가 직접 부르는 몸통)."""
    return [line for line in text.splitlines() if LEGACY_PATH_RE.search(line)]


def _offenders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for relative in _tracked_files():
        if relative.suffix.lower() in _SKIP_SUFFIXES:
            continue
        path = ROOT / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = scan(text)
        if lines:
            found[relative.as_posix()] = lines
    return found


def test_scanner_detects_a_known_reference() -> None:
    """음성 대조 — 추적 파일이 0이 되면 양성만으로는 스캐너가 죽었는지 알 수 없다.

    실제 위반 형태 셋(직접·상대·링크 속성)을 모두 잡는지, 그리고 잡으면 **안 되는**
    형태(산출물 경로·산문)를 놓아주는지 함께 센다.
    """
    caught = scan(
        "\n".join(
            (
                "링크는 `" + _RETIRED_ROOT + "/js/bridge.js` 가 진다",
                '<link rel="stylesheet" href="../../' + _RETIRED_ROOT + '/css/base.css">',
                "패비콘은 " + _RETIRED_ROOT + "/img/narmi-mark.svg",
            )
        )
    )
    assert len(caught) == 3, f"스캐너가 알려진 위반을 놓쳤습니다: {caught}"

    allowed = scan(
        "\n".join(
            (
                "sealed 산출물은 build/" + _RETIRED_ROOT + "/ 아래에 있다",
                "강제 색상 모드는 " + _RETIRED_ROOT + "/ 전역에 걸린다",
                "frontend/js/bridge.js 가 직접 브리지를 진다",
            )
        )
    )
    assert not allowed, f"스캐너가 무해한 표현을 잡았습니다: {allowed}"


def test_no_tracked_file_points_at_the_retired_source_tree() -> None:
    offenders = _offenders()
    unexpected = {
        name: lines
        for name, lines in offenders.items()
        if name not in HISTORICAL_CITATIONS
    }

    assert not unexpected, (
        "폐기된 source 트리 경로가 남아 있습니다 — 현재 이름으로 정산하거나, "
        "역사 인용이면 사유와 함께 HISTORICAL_CITATIONS 에 올립니다:\n"
        + "\n".join(
            f"  {name}: {lines[0].strip()[:100]}" for name, lines in unexpected.items()
        )
    )


def test_the_allowlist_cannot_rot_into_a_blanket() -> None:
    """허용 목록의 각 항목이 아직 실제로 인용을 담고 있는가.

    지워진 인용의 허용이 남으면, 그 파일에 나중에 들어온 **진짜** 참조까지 함께 통과한다.
    허용은 사유가 살아 있는 동안만 유효하다.
    """
    offenders = _offenders()
    stale = sorted(set(HISTORICAL_CITATIONS) - set(offenders))

    assert not stale, f"인용이 사라진 허용 항목은 지웁니다: {stale}"
    assert all(reason.strip() for reason in HISTORICAL_CITATIONS.values()), (
        "허용에는 사유가 있어야 합니다"
    )
