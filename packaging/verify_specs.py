"""K1 패키징 계약을 빌드 전에 빠르게 검증한다."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent

SPEC_NAMES = ("hwpx_filler_web.spec", "hwpx_cli.spec")

REQUIRED_HIDDEN = {
    "hwpxfiller.domain.schema",
    "hwpxfiller.domain.authoring",
    "hwpxfiller.domain.lint",
    "hwpxfiller.data.nara",
}


class SpecContractError(AssertionError):
    """스펙 계약 위반 — 빌드 전에 시끄럽게 거절한다."""


def declared_hidden_imports(text: str) -> tuple[str, ...]:
    """``Analysis(...)`` 의 ``hiddenimports=[...]`` 문자열 리터럴을 그대로 읽는다.

    정규식이 아니라 AST 로 읽는 이유는 주석·docstring 에 적힌 모듈 이름을 계약으로
    오인하지 않기 위해서다. 리스트 안에 문자열 아닌 요소가 오면(변수·f-string 등) 조용히
    건너뛰지 않고 거절한다 — 그 순간 이 게이트는 무엇을 셌는지 말할 수 없게 된다.
    """
    for node in ast.walk(ast.parse(text)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "hiddenimports":
                continue
            if not isinstance(keyword.value, ast.List):
                raise SpecContractError("hiddenimports 가 리스트 리터럴이 아닙니다")
            names: list[str] = []
            for element in keyword.value.elts:
                if not (
                    isinstance(element, ast.Constant) and isinstance(element.value, str)
                ):
                    raise SpecContractError(
                        "hiddenimports 에 문자열 리터럴이 아닌 항목이 있습니다: "
                        f"line {element.lineno}"
                    )
                names.append(element.value)
            return tuple(names)
    raise SpecContractError("Analysis(hiddenimports=...) 를 찾지 못했습니다")


def unresolvable_imports(names: tuple[str, ...]) -> list[str]:
    """임포트 그래프에서 해소되지 않는 이름만 돌려준다.

    PyInstaller 는 없는 hiddenimport 를 **경고**로만 넘기고 빌드를 성공시킨다. 그래서
    삭제된 모듈 이름이 번들 계약처럼 살아남는다(#383 표본: 웹 spec 이 이미 없는
    ``hwpxfiller.gui.txt_state`` 를 선언하고 있었다). 선언이 아니라 해소 결과를 센다.
    """
    missing: list[str] = []
    for name in names:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def main(spec_dir: Path | None = None) -> int:
    here = spec_dir or HERE
    # 두 빌드 타깃 모두 웹 이관 완료(#20·#23)로 Qt 미탑재 — filler 는 웹 spec 이 유일하다.
    # (hwpx_diff.spec 은 hwpxdiff 저장소 분리와 함께 나갔다.)
    specs = {name: (here / name).read_text(encoding="utf-8") for name in SPEC_NAMES}
    for name, text in specs.items():
        assert "COLLECT(" in text, f"{name}: onedir COLLECT 없음"
        assert "exclude_binaries=True" in text, f"{name}: onefile 형식"

    cli = specs["hwpx_cli.spec"]
    missing_hidden = sorted(item for item in REQUIRED_HIDDEN if f'"{item}"' not in cli)
    assert not missing_hidden, f"CLI hidden import 누락: {missing_hidden}"
    assert '"PySide6"' in cli, "CLI에서 PySide6 제외 누락"

    # filler 웹 프론트엔드 spec(#20·#23) — onedir·Qt 전량 제외·sealed build/web 번들.
    web = specs["hwpx_filler_web.spec"]
    assert '"PySide6"' in web, "web spec: PySide6 전량 제외 누락(Qt 미탑재)"
    assert '(str(REPO / "build" / "web"), "web")' in web, (
        "web spec: sealed build/web 산출물 번들 누락"
    )
    assert '(str(REPO / "web"), "web")' not in web, (
        "web spec: legacy source web/ 번들 경로 재유입"
    )
    assert '(str(REPO / "frontend"), "web")' not in web, (
        "web spec: frontend source를 runtime data로 번들하면 안 됩니다"
    )
    # 온보딩 동봉 예제(#891 · ONBOARDING_TUTORIAL.md §4.5) — 설치본·포터블도 소스 실행과
    # 같은 설치 동작이어야 한다. 자산 **폴더 셋만** 싣는지까지 본다: 폴더를 통째로 넣으면
    # 생성 스크립트·__pycache__ 가 배포본에 실린다.
    assert 'ONBOARDING_SRC = REPO / "examples" / "onboarding"' in web, (
        "web spec: 온보딩 예제 자산 원천 경로 누락(#891)"
    )
    assert 'for name in ("templates", "text_templates", "data")' in web, (
        "web spec: 온보딩 예제 자산 폴더 셋(templates·text_templates·data) 열거 누락"
    )
    assert "*onboarding_datas," in web, "web spec: 온보딩 예제 자산 datas 합류 누락"
    assert '(str(REPO / "examples"), "examples")' not in web, (
        "web spec: examples/ 를 통째로 번들하면 안 됩니다(스크립트·테스트 유입)"
    )
    assert '"hwpxfiller.webapp.app"' in web, "web spec: 브리지 hidden import 누락"
    assert "hwpx-filler.ico" in web, "web spec: 문서나르미 아이콘(#258) 배선 누락"
    assert (here / "hwpx-filler.ico").exists(), "hwpx-filler.ico 없음(#258 브랜딩 아이콘)"

    # 선언한 hiddenimports 가 전부 실제로 해소되는가(유령 계약 금지, #383).
    resolved = 0
    for name, text in specs.items():
        declared = declared_hidden_imports(text)
        if not declared:
            raise SpecContractError(f"{name}: hiddenimports 가 비어 있습니다")
        missing = unresolvable_imports(declared)
        if missing:
            raise SpecContractError(
                f"{name}: 해소되지 않는 hidden import 가 있습니다 — "
                "삭제된 모듈 이름을 번들 계약으로 남기지 않습니다: " + ", ".join(missing)
            )
        resolved += len(declared)

    all_specs = "\n".join(specs.values()).lower()
    assert "win32com" not in all_specs and "comtypes" not in all_specs, "한글 COM 번들 금지"
    print(
        "spec contract: OK (onedir=2, hidden-imports, Qt excludes, COM optional, "
        f"resolved-hidden-imports={resolved})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
