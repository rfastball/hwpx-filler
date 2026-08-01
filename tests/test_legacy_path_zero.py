"""폐기된 source 트리 이름이 저장소에서 **0인가**(N-11 · #383).

마일스톤 N 은 프런트 source 를 옮겼고 트리 자체는 사라졌다. 제품 런타임이 그 이름으로
되돌아가지 않는 것은 ``test_web_m1_topology`` 의 AST 게이트가 이미 진다. 그런데 그 게이트는
**Python 경로 조립**만 본다 — 문서 산문, 목업의 ``<link href>``, 주석, 테스트 라벨은 아무도
안 봤고, 실제로 남아 있었다. 그중 한 목업은 스타일시트 링크가 깨진 채였는데도 전 게이트가
초록이었다.

그래서 여기서는 좁게 파고들지 않고 **저장소 전역**을 센다. 세 가지를 지킨다:

1. 대상은 ``git ls-files`` 의 추적 파일뿐이다. ``build/``·``node_modules/``·
   ``.claude/worktrees/`` 의 stale 사본이 이 판정을 오염시키지 못한다.
2. 구분자는 ``/`` 와 역슬래시 둘 다 본다. Windows 전용 저장소라 PowerShell·문서에서
   역슬래시 형태가 실제로 쓰인다 — 한 형태만 보면 다른 형태로 조용히 돌아온다.
3. 역사 인용은 **파일이 아니라 인용 하나하나**를 허용한다. 파일 단위로 열면 그 안에 새
   참조가 들어와도 기존 인용이 허용을 계속 만족시켜 아무도 모른다(#383 리뷰 지적).
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 금지 토큰은 조립한다 — 안 그러면 탐지기 자신이 첫 위반이 된다.
#: (N-09 실증: 봉인의 금지 패턴이 자기 어휘를 거절했다.)
_RETIRED_ROOT = "w" + "eb"

#: 무엇을 잡고 무엇을 놓는가:
#:
#: - 역할 세그먼트를 **요구**한다 — 산문 속 "{root}/ 강제 색상 모드" 같은 무해한 표현을 잡지
#:   않기 위해서다.
#: - 앞에 경로 구분자나 낱말 문자가 붙은 것은 **놓는다** — ``build/web/css/base.css`` 는
#:   폐기된 source 가 아니라 sealed 산출물이고, 이 저장소가 소비하는 정상 경로다.
#: - 단 ``../`` 계열 상대 접두는 매치의 일부로 먼저 삼켜서, 목업의
#:   ``href="../../{root}/css/base.css"`` 는 잡는다.
#: - 뒤따르는 경로 성분까지 삼켜 진단이 "무엇이 새로 들어왔는지"를 말하게 한다.
#:
#: **선언된 축소**: ``docs/../web/css`` 처럼 디렉터리를 거슬러 올라가는 표기는 앞의
#: 구분자 때문에 놓친다. 문서·목업에서 쓰이지 않는 형태라 잡지 않기로 한 것이고, 조용한
#: 누락이 아니라 여기 적어둔 한계다.
LEGACY_PATH_RE = re.compile(
    r"(?<![\w.\\/-])(?:\.\.[\\/])*"
    + _RETIRED_ROOT
    + r"[\\/](?:js|css|img|fonts|src|index\.html)(?:[\\/][\w.\-]+)*"
)

#: 바이너리·대용량 자산은 텍스트로 읽지 않는다.
_SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff2", ".hwpx", ".xlsx", ".zip"}
)

#: 사유와, 허용되는 인용의 **정확한 다중집합**. 전부 과거 시점의 실재 경로를 인용하는
#: 자리라 현재 이름으로 고치면 인용이 틀린 것이 된다(고쳐야 할 것이 아니라 고치면 안 되는
#: 것). 다중집합이라 새 경로가 들어오는 것도, 같은 경로가 한 번 더 들어오는 것도 잡힌다.
#:
#: 경로는 ``{root}`` 자리표시로 적는다 — 날 경로를 적으면 **이 파일이 첫 위반**이 된다
#: (실측: 자리표시 없이 적었더니 게이트가 자기 허용 목록을 위반으로 신고했다).
HISTORICAL_CITATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "docs/archive/DATA_FIRST_INTEGRATION_MAP.md": (
        "완주·동결된 원장 — 당시 표면의 실제 경로 인용",
        (
            "{root}/js/data_picker.js",
            "{root}/js/intent.js",
            "{root}/js/screens/editor.js",
            "{root}/js/screens/home.js",
            "{root}/js/screens/home.js",
            "{root}/js/screens/library.js",
        ),
    ),
    "docs/r-flow-mockups/block4-filter-crystallize-demo.html": (
        "동결 시안 — 시연 근거로 당시 코드 출처를 표기한다",
        (
            "{root}/js",
            "{root}/js",
            "{root}/js/screens/run.js",
            "{root}/js/screens/run.js",
        ),
    ),
    "docs/UX_FEEDBACK_U2.md": (
        "git 고고학 인용 — 과거 commit 에 실재한 경로라 현재 이름으로 고치면 틀린다",
        (
            "{root}/css",
            "{root}/css",
            "{root}/css/app.css",
            "{root}/css/app.css",
            "{root}/css/base.css",
            "{root}/css/job.css",
            "{root}/css/job.css",
            "{root}/css/job.css",
            "{root}/index.html",
        ),
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
    """폐기된 source 경로 참조를 **하나씩** 돌려준다(음성 대조가 직접 부르는 몸통)."""
    return LEGACY_PATH_RE.findall(text)


def _expand(citations: tuple[str, ...]) -> tuple[str, ...]:
    """허용 목록의 ``{root}`` 자리표시를 실제 이름으로 편다."""
    return tuple(item.format(root=_RETIRED_ROOT) for item in citations)


def _citations() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for relative in _tracked_files():
        if relative.suffix.lower() in _SKIP_SUFFIXES:
            continue
        path = ROOT / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = scan(text)
        if hits:
            found[relative.as_posix()] = hits
    return found


def test_scanner_catches_every_shape_a_reference_can_take() -> None:
    """양성 대조 — 실제로 쓰이는 네 형태를 모두 잡는가.

    Windows 구분자를 빼면 역슬래시 표기가 조용히 통과한다. 이 저장소는 Windows 전용이고
    PowerShell·문서가 그 형태를 실제로 쓴다(#383 리뷰 지적).
    """
    shapes = {
        "posix": _RETIRED_ROOT + "/js/bridge.js",
        "windows": _RETIRED_ROOT + "\\css\\base.css",
        "relative-link": '<link href="../../' + _RETIRED_ROOT + '/css/tail.css">',
        "relative-windows": "..\\" + _RETIRED_ROOT + "\\img\\narmi-mark.svg",
    }
    missed = [name for name, text in shapes.items() if not scan(text)]
    assert not missed, f"스캐너가 놓친 참조 형태: {missed}"


def test_scanner_leaves_the_sealed_artifact_and_prose_alone() -> None:
    """음성 대조 — 잡으면 **안 되는** 것을 잡지 않는가.

    ``build/web/...`` 은 폐기된 source 가 아니라 이 저장소가 소비하는 sealed 산출물이다.
    여기서 오탐이 나면 게이트가 자기가 지키려는 대상을 거절한다(#383 리뷰 지적: 종전 음성
    대조는 역할 세그먼트 없는 ``build/web/`` 만 물어서 이 오탐을 놓쳤다).
    """
    allowed = (
        "sealed 산출물은 build/" + _RETIRED_ROOT + "/css/base.css 에 있다",
        "번들 진입은 build/" + _RETIRED_ROOT + "/index.html 이다",
        "frozen 은 build\\" + _RETIRED_ROOT + "\\index.html 을 싣는다",
        "강제 색상 모드는 " + _RETIRED_ROOT + "/ 전역에 걸린다",
        "front" + "end/js/bridge.js 가 직접 브리지를 진다",
    )
    caught = {text: scan(text) for text in allowed if scan(text)}
    assert not caught, f"스캐너가 무해한 표현을 잡았습니다: {caught}"


def test_no_tracked_file_points_at_the_retired_source_tree() -> None:
    citations = _citations()
    unexpected = {
        name: hits
        for name, hits in citations.items()
        if name not in HISTORICAL_CITATIONS
    }

    assert not unexpected, (
        "폐기된 source 트리 경로가 남아 있습니다 — 현재 이름으로 정산하거나, "
        "역사 인용이면 사유와 함께 HISTORICAL_CITATIONS 에 올립니다:\n"
        + "\n".join(f"  {name}: {sorted(set(hits))}" for name, hits in unexpected.items())
    )


def test_allowlisted_files_may_not_grow_new_references() -> None:
    """허용은 **파일이 아니라 인용 하나하나**에 붙는다.

    파일 단위로 열면, 그 문서에 새 live 참조가 들어와도 기존 인용이 허용을 계속 만족시켜
    아무도 모른다. 그래서 인용의 정확한 다중집합을 대조한다 — 새 경로가 들어오는 것도,
    같은 경로가 한 번 더 늘어나는 것도 실패다. 인용이 사라진 항목이 남는 것도 실패다
    (허용이 통짜로 썩지 못하게).
    """
    citations = _citations()
    drift: list[str] = []
    for name, (reason, allowed) in HISTORICAL_CITATIONS.items():
        assert reason.strip(), f"허용에는 사유가 있어야 합니다: {name}"
        actual = Counter(citations.get(name, ()))
        expected = Counter(_expand(allowed))
        added = sorted((actual - expected).elements())
        removed = sorted((expected - actual).elements())
        if added or removed:
            drift.append(f"  {name}: 새로 생김={added} 사라짐={removed}")

    assert not drift, (
        "역사 인용 허용과 실제가 다릅니다 — 새로 생긴 것은 현재 이름으로 정산하고, "
        "사라진 것은 허용에서 지웁니다:\n" + "\n".join(drift)
    )


def test_a_new_reference_in_an_allowlisted_file_is_caught() -> None:
    """허용 파일에 새 참조가 들어오는 상황을 **직접** 재현해 잡히는지 본다.

    실제 저장소는 통과 상태라 위 두 테스트만으로는 "허용이 인용 단위로 좁다"가 초록의
    이유인지, 아니면 그냥 아무 일도 없어서인지 구별되지 않는다.
    """
    name = "docs/UX_FEEDBACK_U2.md"
    _, allowed = HISTORICAL_CITATIONS[name]
    intruder = _RETIRED_ROOT + "/js/new_screen.js"

    expanded = _expand(allowed)
    expected = Counter(expanded)
    actual = Counter([*expanded, intruder])

    assert sorted((actual - expected).elements()) == [intruder], (
        "인용 다중집합 대조가 새 참조를 잡지 못합니다"
    )
    assert scan(intruder), "스캐너가 침입 참조 자체를 못 잡습니다"


def test_the_allowlist_is_not_empty() -> None:
    """허용 자체가 비면 대조가 무의미해진다 — 목록이 살아 있는지 센다."""
    assert HISTORICAL_CITATIONS
    assert all(allowed for _, allowed in HISTORICAL_CITATIONS.values())
