"""Quickstart 101 라이브 실행 CLI — 인자 해석과 조립만(N-11A · #423).

이 파일이 하는 일은 셋이다: 인자를 읽고, 실행 홈을 정하고, :mod:`live101` 의 조각을 붙인다.
앱 부팅·대본·픽셀·종료 정책은 전부 그 패키지가 소유한다 — 종전에는 다섯 책임이 여기 764줄에
겹쳐 있었고, 그 겹침 속에서 호출 계약이 조용히 깨진 채 몇 달을 살았다.

실행(저장소 루트, Windows 데스크톱 세션 필요)::

    # 동작만 검사 — PNG 없음, 임시 홈, 저장소 작업트리 무오염
    uv run --extra gui python scripts/capture_101_screenshots.py check

    # 문서용 14컷 재생성 — 예제 홈(화면에 뜨는 경로가 문서와 같아야 한다)
    uv run --with pillow --extra gui python scripts/capture_101_screenshots.py capture

    # 실행 없이 전제만 증명(CI 선행조건 단계)
    uv run python scripts/capture_101_screenshots.py check --preflight

두 모드는 **같은 대본**(:mod:`live101.scenario`)을 쓴다. 갈리는 것은 셔터가 픽셀을 만드는지와
어느 홈에서 도는지뿐이다 — 그래야 "찍히는 화면"과 "검사되는 화면"이 갈라지지 않는다.

``capture`` 는 클립보드를 한 번 덮어쓰고, 예제 홈이 깨끗해야 한다(실습 잔재 = 비결정 화면).
잔재가 있으면 지우지 않고 **거부**한다 — 사용자의 로컬 실습 상태를 말없이 파괴하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from live101 import driver  # noqa: E402 — sys.path 조정 뒤라야 import 된다


def _parse_args(argv: "list[str] | None") -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="capture_101_screenshots.py",
        description="Quickstart 101 을 실 렌더로 완주한다(동작 검사 또는 문서 캡처).",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    check = subparsers.add_parser("check", help="동작만 검사한다(PNG 없음)")
    check.add_argument(
        "--home",
        choices=("temp", "example"),
        default="temp",
        help="실행 홈. 기본 temp — 커밋된 101 자산을 임시 폴더에 시딩해 돈다.",
    )
    check.add_argument(
        "--preflight",
        action="store_true",
        help="실행하지 않고 전제(Windows·자산·봉인 산출물)만 증명한다.",
    )

    capture = subparsers.add_parser("capture", help="문서용 14컷을 재생성한다")
    capture.add_argument(
        "--home",
        choices=("example", "temp"),
        default="example",
        help="실행 홈. 기본 example — 화면에 뜨는 저장 폴더 경로가 문서와 같아야 한다.",
    )
    capture.add_argument(
        "--report",
        type=Path,
        default=None,
        help="캡처 보고서(JSON)를 쓸 경로. 미지정이면 표준 출력 요약만 남는다.",
    )
    return parser.parse_args(argv)


def main(argv: "list[str] | None" = None) -> int:
    args = _parse_args(argv)

    if getattr(args, "preflight", False):
        problems = driver.preflight(args.mode)
        for problem in problems:
            print(f"선행조건 미충족: {problem}", file=sys.stderr)
        if problems:
            return driver.ExitCode.ENVIRONMENT
        print(f"선행조건 충족 — {args.mode} 를 이 환경에서 돌릴 수 있습니다.")
        return driver.ExitCode.OK

    if sys.platform != "win32":
        print("Windows 데스크톱 세션 전용(WebView2 실창)", file=sys.stderr)
        return driver.ExitCode.ENVIRONMENT

    use_example_home = args.home == "example"
    if use_example_home:
        try:
            driver.refuse_if_dirty(driver.EXAMPLE_HOME)
        except driver.DirtyHome as exc:
            print(str(exc), file=sys.stderr)
            return driver.ExitCode.DIRTY_HOME

    # 산출물 빌드가 **파괴보다 먼저**다 — 빌드가 실패한 뒤 스크린샷 폴더를 비우면 문서가
    # 그림 없이 남는다. 이 순서는 tests/test_web_m1_topology.py 가 AST 로 못박는다.
    driver.build_web_artifact()

    out_dir = None
    if args.mode == "capture":
        out_dir = driver.IMG_DIR
        if out_dir.exists():
            shutil.rmtree(out_dir)  # 전량 재생성 — 스테일 프레임 잔존 금지

    temp_root = None
    result = None
    try:
        if use_example_home:
            home = driver.EXAMPLE_HOME
        else:
            temp_root = Path(tempfile.mkdtemp(prefix="hwpx-101-"))
            home = driver.seed_temp_home(temp_root / "home")
        result = driver.run(mode=args.mode, home=home, out_dir=out_dir)
        return _land(result, home=home, use_example_home=use_example_home, args=args)
    finally:
        # 성공한 실행만 자기 임시 홈을 지운다 — 실패한 실행의 홈은 진단 증거다.
        if temp_root is not None and result is not None and result.ok:
            shutil.rmtree(temp_root, ignore_errors=True)


def _land(result, *, home: Path, use_example_home: bool, args: argparse.Namespace) -> int:
    report_json = json.dumps(result.report, ensure_ascii=False, indent=2)
    report_path = getattr(args, "report", None)
    if report_path is not None:
        report_path.write_text(report_json, encoding="utf-8")

    if not result.ok:
        print(f"101 {result.mode} 실패 — {result.error}", file=sys.stderr)
        for failure in result.report.get("verdict", {}).get("failures", []):
            print(f"  · {failure}", file=sys.stderr)
        print("잔재를 진단용으로 남깁니다:", home, file=sys.stderr)
        return result.exit_code()

    if use_example_home:
        driver.clean_practice_state(home)  # 재실행 가능 상태로

    summary = result.report
    if result.mode == "capture":
        print(
            f"완료: {len(summary['shots'])}컷 → {driver.IMG_DIR.relative_to(driver.REPO_ROOT)}"
            f" (HWPX {summary['hwpx_generated']}건 · {summary['elapsed_s']}s"
            f" · artifact {summary['source'].get('artifact_id', '?')[:12]})"
        )
    else:
        print(
            f"완료: 101 check 통과 (HWPX {summary['hwpx_generated']}건 ·"
            f" 캡처 지점 {len(summary['shots'])}개 · {summary['elapsed_s']}s)"
        )
    if report_path is None and result.mode == "capture":
        print(report_json)
    return driver.ExitCode.OK


if __name__ == "__main__":
    raise SystemExit(main())
