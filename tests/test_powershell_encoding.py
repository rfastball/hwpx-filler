"""추적되는 ``.ps1`` 이 Windows PowerShell 5.1 에서 **읽히는가**(#431).

BOM 없는 UTF-8 을 ``powershell.exe``(5.1)는 시스템 ANSI 코드페이지로 읽는다. 결과는 두 단계로
나빠진다. **첫째, 항상 다른 문자를 읽는다** — ACP 949 기기 실측으로 ``'한글표본'.Length`` 가
4 대신 6 이고, 스크립트가 ``throw`` 하는 한글 문구가 ``?꾨씫`` 로 나온다. **둘째, 그 깨짐이
따옴표·중괄호에 닿으면 파서가 죽는다** — 실제 원인과 **무관한 줄**을 가리키는
``Missing closing '}'`` 가 그것이고, #423 의 101 실주행이 ``build-web.ps1`` 을
``powershell.exe`` 로 부르면서 드러났다(#431).

이 게이트가 지키는 것은 **첫째**다. 둘째는 파일 내용에 달렸고 — 같은 기기에서 지금 저장소의
넷은 깨져 읽히면서도 파싱은 된다 — 그래서 「죽는가」를 술어로 삼으면 내용이 조금 바뀌는 날
조용히 돌아온다. PowerShell 7 은 BOM 없는 파일을 UTF-8 로 읽고 Windows 11 「Unicode UTF-8
사용」을 켠 기기도 마찬가지라, 이 결함은 릴리스 경로(``packaging/build.ps1``)에 몇 달째
잠복해 있었다.

**한 파일을 고치는 것으로는 닫히지 않는 결함류**다. 이미 ``run-filler.ps1`` 은 BOM 을 갖고
있었다 — 누군가 같은 함정을 밟고 그 파일만 고쳤다는 뜻이고, 그래서 다음 스크립트에서 조용히
돌아왔다. 여기서는 저장소가 추적하는 PowerShell 스크립트 **전수**를 센다.

세는 방식은 :mod:`test_legacy_path_zero` 와 같다. 대상은 ``git ls-files`` 의 추적 파일뿐이라
``build/``·``.uv-cache/``·가상환경의 ``Activate.ps1`` 사본이 판정을 오염시키지 못한다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: UTF-8 BOM. 이것이 있으면 5.1 도 7 도 같은 문자를 읽는다.
BOM = b"\xef\xbb\xbf"

#: PowerShell 파서를 지나는 확장자. ``.psd1`` 은 데이터 파일이지만 같은 파서를 지나므로 함께
#: 센다 — 지금 저장소에 없어도 생기는 순간 규칙 안에 있어야 한다.
SUFFIXES = ("*.ps1", "*.psm1", "*.psd1")


def _tracked_scripts() -> list[Path]:
    """추적되는 PowerShell 스크립트 전수."""
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", *SUFFIXES],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    names = completed.stdout.decode("utf-8").split("\0")
    return [ROOT / name for name in names if name]


def _label(script: Path) -> str:
    """진단·테스트 id 는 저장소 상대 경로다 — ``build.ps1`` 은 두 곳에 있다."""
    try:
        return script.relative_to(ROOT).as_posix()
    except ValueError:  # tmp_path 표본
        return script.name


def _bom_violation(script: Path) -> str | None:
    """BOM 이 없으면 진단 문자열, 있으면 ``None``."""
    if script.read_bytes()[:3] == BOM:
        return None
    return (
        f"{_label(script)} 에 UTF-8 BOM 이 없다 — "
        "Windows PowerShell 5.1 이 ANSI 코드페이지로 읽어 파서 오류로 죽는다"
    )


SCRIPTS = _tracked_scripts()


def test_the_census_is_not_empty() -> None:
    """0 건을 세고 초록이 되는 게이트는 게이트가 아니다.

    ``git ls-files`` 가 빈 목록을 내면(경로 오타·실행 위치 이동) 아래 전수 판정은 아무것도
    검사하지 않은 채 통과한다. 이 저장소가 반복해 만난 실패 형태라 공허를 먼저 막는다.
    """
    assert SCRIPTS, "추적되는 PowerShell 스크립트가 0 건 — 수집 경로가 깨졌다"
    assert ROOT / "test.ps1" in SCRIPTS, "개발 진입점이 수집에서 빠졌다"


@pytest.mark.parametrize("script", SCRIPTS, ids=_label)
def test_every_tracked_powershell_script_carries_a_utf8_bom(script: Path) -> None:
    """BOM 이 없으면 5.1 은 이 파일을 다른 문자로 읽는다."""
    assert _bom_violation(script) is None, _bom_violation(script)


@pytest.mark.parametrize("script", SCRIPTS, ids=_label)
def test_every_tracked_powershell_script_really_is_utf8(script: Path) -> None:
    """BOM 은 선언이고 내용은 결과다 — 선언만 맞고 내용이 다른 인코딩이면 같은 오류가 난다."""
    body = script.read_bytes().removeprefix(BOM)
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - 위반이 없으면 도달하지 않는다
        pytest.fail(f"{_label(script)} 가 UTF-8 로 읽히지 않는다: {exc}")


def test_the_detector_rejects_a_script_without_the_bom(tmp_path: Path) -> None:
    """탐지기의 음성 대조 — 위반 표본을 실제로 빨갛게 만드는가.

    전수 판정이 초록인 것은 「위반이 없다」와 「탐지기가 죽었다」 둘 다와 양립한다. 둘을
    가르는 것은 이 표본뿐이다.
    """
    body = "Write-Output '한글'\n".encode("utf-8")

    victim = tmp_path / "no-bom.ps1"
    victim.write_bytes(body)
    assert _bom_violation(victim) is not None

    blessed = tmp_path / "with-bom.ps1"
    blessed.write_bytes(BOM + body)
    assert _bom_violation(blessed) is None
