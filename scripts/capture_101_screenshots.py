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

**두 모드 모두 OS 클립보드를 한 번 덮어쓴다.** 대본이 작업대의 「복사」를 실제로 누르고, 그
아래는 실물 경로이기 때문이다(native 파일 선택 말고는 아무것도 대체하지 않는 것이 이
하니스의 계약이다). 종전 이 머리말은 ``capture`` 만 지목했는데, 같은 대본을 쓰는 이상
``check`` 도 똑같이 덮어쓴다 — 「안전한 검사」로 읽히면 그것이 곧 조용한 손실이다(#426
라운드 3). 그래서 실행 시작에 한 줄로 다시 알린다.

``capture`` 는 예제 홈이 깨끗해야 한다(실습 잔재 = 비결정 화면). 잔재가 있으면 지우지 않고
**거부**한다 — 사용자의 로컬 실습 상태를 말없이 파괴하지 않는다.
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

    def _add_report(target: argparse.ArgumentParser) -> None:
        """보고서 경로는 **두 모드 공통**이다 — 판정 근거를 파일로 받는 일에 모드 구분이 없다.

        종전에는 ``capture`` 에만 달려 있었고, ``check --report`` 는 argparse 사용법 오류로
        죽었다. 그 오류의 종료 코드가 하필 2 라 dirty 홈 거절과 구별되지 않았다
        (:class:`~live101.driver.ExitCode` 주석 참조).
        """
        target.add_argument(
            "--report",
            type=Path,
            default=None,
            help="실행 보고서(JSON)를 쓸 경로. 미지정이면 표준 출력 요약만 남는다.",
        )
        target.add_argument(
            "--budget-s",
            type=float,
            default=driver.RUN_BUDGET_S,
            help=(
                "실행 전체 예산(초). 부른 쪽이 자기 시한을 갖는다면 이 값을 **그보다 작게**"
                " 줘야 드라이버가 자기 하드 스톱에 먼저 닿아 구조화된 착지를 남긴다."
            ),
        )
        target.add_argument(
            "--no-build",
            action="store_true",
            help=(
                "프런트를 다시 만들지 않고 **이미 봉인된** build/web 을 쓴다."
                " 산출물을 이미 만든 러너(CI)나 게이트가 쓴다."
            ),
        )

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
    _add_report(check)

    capture = subparsers.add_parser("capture", help="문서용 14컷을 재생성한다")
    capture.add_argument(
        "--home",
        choices=("example", "temp"),
        default="example",
        help="실행 홈. 기본 example — 화면에 뜨는 저장 폴더 경로가 문서와 같아야 한다.",
    )
    _add_report(capture)
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
    #
    # 다만 불변식의 본체는 「빌드가 먼저」가 아니라 **「파괴 전에 산출물이 유효하다」** 다.
    # 빌드는 그것을 *만들어서* 지키고, `--no-build` 는 *검증해서* 지킨다 — 검증까지 건너뛰면
    # stale seal 로 14컷을 지운 **뒤에야** 부팅이 거절된다(#430 리뷰). 이미 만든 러너(CI)가
    # 두 번 만들지 않게 하려던 것이지, 보장을 빼려던 것이 아니다.
    if args.no_build:
        problems = driver.preflight(args.mode)
        for problem in problems:
            print(f"산출물 검증 실패(--no-build): {problem}", file=sys.stderr)
        if problems:
            return driver.ExitCode.ENVIRONMENT
    else:
        driver.build_web_artifact()

    out_dir = None
    if args.mode == "capture":
        out_dir = driver.IMG_DIR
        if out_dir.exists():
            shutil.rmtree(out_dir)  # 전량 재생성 — 스테일 프레임 잔존 금지

    # 시끄럽게 알린다 — 대본이 작업대의 「복사」를 실제로 누르므로 두 모드 다 클립보드를
    # 덮어쓴다. 문서에만 적어 두면 `check` 를 "안전한 검사"로 읽는 사람이 잃는다.
    print("알림: 이 실행은 OS 클립보드를 한 번 덮어씁니다(작업대 「복사」를 실제로 누릅니다).")

    temp_root = None
    if use_example_home:
        home = driver.EXAMPLE_HOME
    else:
        temp_root = Path(tempfile.mkdtemp(prefix="hwpx-101-"))
        home = driver.seed_temp_home(temp_root / "home")

    # 착지는 **하나의 함수**다. 드라이버가 정상 반환이든 강제 종료(teardown 매달림·브리지
    # 무응답)든 반드시 이것을 정확히 한 번 지나게 한다 — 종전에는 워치독의 `os._exit` 가
    # 두 번째 착지 경로라서, 착지 책임이 하나 생길 때마다 그쪽 복제가 누락됐다(#426 라운드 3).
    def land(result) -> int:
        return _land(
            result,
            home=home,
            temp_root=temp_root,
            use_example_home=use_example_home,
            report_path=getattr(args, "report", None),
        )

    return driver.run(
        mode=args.mode, home=home, out_dir=out_dir, land=land, budget_s=args.budget_s
    )


def _land(
    result,
    *,
    home: Path,
    temp_root: "Path | None",
    use_example_home: bool,
    report_path: "Path | None",
) -> int:
    """실행 하나를 마무리한다 — 보고서 쓰기 · 정리 · 요약 · 종료 코드.

    **여기 있는 것이 곧 착지의 정의다.** 새 책임을 더하면 정상 경로와 워치독 경로 양쪽에
    자동으로 걸린다(그것이 이 함수가 콜백인 이유다).
    """
    report_json = json.dumps(result.report, ensure_ascii=False, indent=2)

    if not result.ok:
        # 첫 줄이 **축**을 말한다 — 환경인가 제품인가(#460). 로그를 읽는 쪽(특히 무인 판정)이
        # 「내 변경이 깼나」를 그 한 줄로 답할 수 있어야 한다. 종전에는 창이 안 뜬 실행도
        # 제품 실패 7줄을 달고 나와, 그 질문의 답이 로그 어디에도 없었다.
        axis = "환경" if result.environment else "제품"
        print(f"101 {result.mode} 실패[{axis}] — {result.error}", file=sys.stderr)
        for failure in result.report.get("verdict", {}).get("failures", []):
            print(f"  · {failure}", file=sys.stderr)
        if result.environment:
            print(
                "  (제품 판정을 돌리지 않았습니다 — 창이 뜨지 못한 실행은 제품에 대해"
                " 아무것도 말하지 않습니다)",
                file=sys.stderr,
            )
        print(f"잔재를 진단용으로 남깁니다: {home}", file=sys.stderr)
        _write_report(report_path, report_json)
        return result.exit_code()

    # 성공 완주 — 자기 잔재만 치운다.
    (home / "_live101_result.json").unlink(missing_ok=True)
    if use_example_home:
        driver.clean_practice_state(home)  # 재실행 가능 상태로
    if temp_root is not None:
        shutil.rmtree(temp_root, ignore_errors=True)

    # 보고서는 **정리 뒤에** 쓴다(#426 리뷰 라운드 6). 먼저 쓰면 `--report` 가 정리 대상 안을
    # 가리킬 때(`out/`·`templates/Results/`·임시 홈 안) 그 파일이 몇 줄 아래에서 지워지고,
    # 명령은 요청받은 보고서가 없는 채로 성공을 알린다.
    _write_report(report_path, report_json)

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


def _write_report(report_path: "Path | None", report_json: str) -> None:
    """요청받은 보고서를 쓴다 — 정리가 끝난 **뒤에** 불린다."""
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_json, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
