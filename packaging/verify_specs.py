"""K1 패키징 계약을 빌드 전에 빠르게 검증한다."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

REQUIRED_HIDDEN = {
    "hwpxfiller.core.schema",
    "hwpxfiller.core.authoring",
    "hwpxfiller.core.lint",
    "hwpxfiller.data.nara",
}


def main() -> int:
    # 세 빌드 타깃 모두 웹 이관 완료(#20·#22·#23)로 Qt 미탑재 — filler 는 웹 spec 이 유일하다.
    specs = {
        name: (HERE / name).read_text(encoding="utf-8")
        for name in ("hwpx_diff.spec", "hwpx_filler_web.spec", "hwpx_cli.spec")
    }
    for name, text in specs.items():
        assert "COLLECT(" in text, f"{name}: onedir COLLECT 없음"
        assert "exclude_binaries=True" in text, f"{name}: onefile 형식"

    cli = specs["hwpx_cli.spec"]
    missing_hidden = sorted(item for item in REQUIRED_HIDDEN if f'"{item}"' not in cli)
    assert not missing_hidden, f"CLI hidden import 누락: {missing_hidden}"
    assert '"PySide6"' in cli, "CLI에서 PySide6 제외 누락"

    # filler 웹 프론트엔드 spec(#20·#23) — onedir·Qt 전량 제외·web/ 번들·브리지 hidden import.
    web = specs["hwpx_filler_web.spec"]
    assert '"PySide6"' in web, "web spec: PySide6 전량 제외 누락(Qt 미탑재)"
    assert '(str(REPO / "web"), "web")' in web, "web spec: 정적 자산 web/ 번들 누락"
    assert '"hwpxfiller.webapp.app"' in web, "web spec: 브리지 hidden import 누락"

    # diff 웹 프론트엔드 spec(#22) — onedir·Qt 전량 제외·web-diff/ 번들·브리지 hidden import.
    diffweb = specs["hwpx_diff.spec"]
    assert '"PySide6"' in diffweb, "diff spec: PySide6 전량 제외 누락(Qt 미탑재)"
    assert '(str(REPO / "web-diff"), "web-diff")' in diffweb, "diff spec: 정적 자산 web-diff/ 번들 누락"
    assert '"hwpxdiff.webapp.app"' in diffweb, "diff spec: 브리지 hidden import 누락"
    assert "SLIM_QT_BINARIES" not in diffweb, "diff spec: Qt DLL 필터 잔존(웹은 Qt 미탑재)"

    all_specs = "\n".join(specs.values()).lower()
    assert "win32com" not in all_specs and "comtypes" not in all_specs, "한글 COM 번들 금지"
    print("spec contract: OK (onedir=3, hidden-imports, Qt excludes, COM optional)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
