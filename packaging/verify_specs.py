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
QT_EXCLUDES = {
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtWebEngineCore",
    "PySide6.QtMultimedia",
}


def main() -> int:
    specs = {
        name: (HERE / name).read_text(encoding="utf-8")
        for name in ("hwpx_diff.spec", "hwpx_filler.spec", "hwpx_cli.spec")
    }
    for name, text in specs.items():
        assert "COLLECT(" in text, f"{name}: onedir COLLECT 없음"
        assert "exclude_binaries=True" in text, f"{name}: onefile 형식"

    filler = specs["hwpx_filler.spec"]
    missing_qt = sorted(item for item in QT_EXCLUDES if f'"{item}"' not in filler)
    assert not missing_qt, f"filler Qt exclude 누락: {missing_qt}"
    # 앱 B(filler) Qt 위젯 exe 는 아직 Qt 를 싣는다(단계 B 에서 웹 전환) → DLL 슬리밍 유지.
    # 앱 A(diff)는 #22 로 웹 이관돼 Qt 미탑재 → SLIM_QT 는 diff spec 에 더는 요구하지 않는다.
    assert "SLIM_QT_BINARIES" in filler, "filler: Qt DLL 훅 필터 누락"
    assert 'startswith("qt6qml")' in filler, "filler: QML DLL 필터 누락"

    cli = specs["hwpx_cli.spec"]
    missing_hidden = sorted(item for item in REQUIRED_HIDDEN if f'"{item}"' not in cli)
    assert not missing_hidden, f"CLI hidden import 누락: {missing_hidden}"
    assert '"PySide6"' in cli, "CLI에서 PySide6 제외 누락"

    # 웹 프론트엔드 spec(에픽 #20) — onedir·Qt 전량 제외·web/ 번들·브리지 hidden import.
    web = (HERE / "hwpx_filler_web.spec").read_text(encoding="utf-8")
    assert "COLLECT(" in web and "exclude_binaries=True" in web, "web spec: onedir 아님"
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
