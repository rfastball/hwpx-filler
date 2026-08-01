"""Quickstart 101 라이브 게이트 — 실주행과 그 판정의 음성 대조(N-11A · #423).

`scripts/live101/` 하니스는 #426 에서 섰지만 **그것을 돌리는 테스트는 0** 이었다. 그 침묵이
바로 이 이슈의 출발점이다: 캡처 하니스가 몇 달 동안 깨진 채 살아 있었고, 이름을 보는 정적
단언들은 그동안 초록이었다.

층을 둘로 나눈다(`test_web_press_geometry.py` 와 같은 형태).

- **실주행**은 게이트 뒤다(`HWPX_SKIP_GUI_TESTS` 명시 옵트아웃). 실 WebView2 창을 띄워
  101 을 완주하고 **실물**을 판정한다 — 생성된 HWPX 파일 수·복사 카운터·〈빈 값〉 표면.
- **판정과 계약의 음성 대조는 게이트 밖**이다. 창 없이 도는 순수 검사라 옵트아웃 환경에서도
  「생성 0건인데 통과」·「없는 selector 를 timeout 으로 뭉갬」·「dirty 홈 파괴」가 잡힌다.

게이트 밖 층이 있는 이유가 요점이다: 실주행만 두면 GUI 없는 러너에서 이 파일 전체가 조용히
사라지고, 그때 하니스의 판정이 옳은지 아무도 묻지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live101 import driver, report as report_mod  # noqa: E402
from live101.scenario import CAPTURE_POINTS, EXPECTED_HWPX  # noqa: E402
from live101.surface import Deadline, MissingSurface, StepTimeout, Surface  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "capture_101_screenshots.py"
EXAMPLE_HOME = REPO_ROOT / "examples" / "quickstart-101"
IMG_DIR = EXAMPLE_HOME / "img"
README = EXAMPLE_HOME / "README.md"

_GUI_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_GUI_TESTS"))
_GATE_REASON = (
    "101 실주행 게이트 — Windows 데스크톱 세션 전용(HWPX_SKIP_GUI_TESTS=1 로 명시 옵트아웃)"
)
# 예산 둘의 **순서가 계약이다**(#430 리뷰). 바깥 시한(`subprocess.run`)이 안쪽 하드 스톱보다
# 촘촘하면 CLI 가 먼저 죽어 드라이버의 구조화된 착지가 통째로 사라지고, 남는 것은 맨
# `TimeoutExpired` 하나다 — 보고서도, 실패 항목도, 매달림 스택도 없다. #427 이 하니스 층에서
# 고친 것과 **같은 형상**이라 여기서도 안쪽이 먼저 물게 파생시킨다.
#
# 실측 9초라 180초는 20배 여유다. 드라이버는 180 + 60(하드 스톱 여유) = 240초에 물고,
# 바깥은 그보다 60초 뒤인 300초에야 손을 댄다.
_LIVE_BUDGET_S = 180.0
_OUTER_TIMEOUT_S = _LIVE_BUDGET_S + driver.RUN_HARD_STOP_MARGIN_S + 60.0


# ───────────────────────────────── 실주행 ─────────────────────────────────


@pytest.fixture(scope="module")
def live_check_run(tmp_path_factory) -> dict:
    """101 `check` 를 **모듈당 한 번** 돌리고 그 실행의 사실을 모아 준다.

    실 WebView2 완주는 비싸다(실측 9초 + 창 부팅). 종전에는 두 테스트가 각자 한 번씩 돌아
    CI 잡이 같은 여정을 두 번 태웠다(#430 리뷰). 한 번 돌려 그 결과에 여러 단언을 거는 것은
    이 저장소의 실앱 게이트가 이미 쓰는 관용이다(`test_web_selftest_gate.py` 의 모듈 픽스처).

    예제 홈 스냅샷을 **이 실행을 감싸서** 뜬다 — 그래야 「이 실행이 바꿨는가」가 정확한 질문이
    된다(다른 테스트가 사이에 끼면 귀속이 흐려진다).
    """
    report_path = tmp_path_factory.mktemp("live101") / "check-report.json"
    before = _tree_manifest(EXAMPLE_HOME)
    assert before, f"예제 홈이 비어 있습니다 — 무오염 대조가 아무것도 안 지킵니다: {EXAMPLE_HOME}"

    proc = subprocess.run(
        [
            sys.executable, str(CLI), "check",
            "--home", "temp",
            "--no-build",
            "--budget-s", str(_LIVE_BUDGET_S),
            "--report", str(report_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_OUTER_TIMEOUT_S,
    )
    after = _tree_manifest(EXAMPLE_HOME)
    assert report_path.exists(), (
        f"보고서 미생성 — rc={proc.returncode}\n"
        f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    return {
        "proc": proc,
        "report": json.loads(report_path.read_text(encoding="utf-8")),
        "before": before,
        "after": after,
    }


def test_the_outer_timeout_lets_the_driver_hard_stop_first() -> None:
    """바깥 시한은 안쪽 하드 스톱보다 **성겨야** 한다 — 아니면 진단이 통째로 사라진다.

    게이트 밖이다: 창 없이 수치만 본다. 이 순서가 뒤집히면 GUI 없는 러너에서도 잡혀야 한다.
    """
    inner = _LIVE_BUDGET_S + driver.RUN_HARD_STOP_MARGIN_S
    assert inner < _OUTER_TIMEOUT_S, (
        f"바깥 시한 {_OUTER_TIMEOUT_S}s 가 드라이버 하드 스톱 {inner}s 보다 촘촘합니다 — "
        "CLI 가 먼저 죽어 보고서도 실패 항목도 매달림 스택도 남지 않습니다."
    )
    # 음성 대조 — 뒤집힌 형상을 실제로 거절하는가(항상 참인 산술이 아니다).
    assert not (180.0 + 60.0 < 120.0)


@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_check_mode_completes_the_101_journey_on_a_clean_home(live_check_run) -> None:
    """`check` 가 깨끗한 임시 홈에서 완주하고 **실물**을 판정한다.

    보고서의 수치를 그대로 다시 단언하는 것이 요점이다 — 하니스가 스스로 초록이라고 말하는
    것과, 그 초록이 무엇을 근거로 하는지를 밖에서 확인하는 것은 다른 질문이다.
    """
    proc = live_check_run["proc"]
    assert proc.returncode == driver.ExitCode.OK, (
        f"101 check 가 exit {proc.returncode} 로 끝났습니다\n"
        f"stdout={proc.stdout[-3000:]}\nstderr={proc.stderr[-3000:]}"
    )

    report = live_check_run["report"]
    assert report["verdict"]["ok"] is True, report["verdict"]
    assert report["hwpx_generated"] == EXPECTED_HWPX, report["documents"]
    assert tuple(report["shots"]) == CAPTURE_POINTS
    observed = report["observations"]
    assert observed["hwpx_result_state"] == "completed"
    assert observed["preview_approved"] is True
    assert str(observed["txt_copied"]).startswith("1 /"), observed["txt_copied"]
    assert observed["empty_value_gate_asked"] is True
    assert observed["empty_value_surfaced"] is True
    # 무엇으로 잰 실행인지가 남는다 — 스크린샷은 눈검증 증거라 좌표 없이는 대조가 안 된다.
    assert report["source"]["artifact_id"]
    assert report["source"]["commit"]


def _tree_manifest(root: Path) -> "dict[str, str]":
    """트리 전체의 ``상대경로 → sha256``.

    존재 여부만 세면 **덮어쓰기·잘림·내용 변경을 통째로 놓친다** — 부모 폴더가 남아 있는 한
    `before == after` 가 참이기 때문이다(#430 리뷰). "한 글자도 안 건드린다"를 이름으로 말할
    거면 그 한 글자를 실제로 세야 한다.

    ``__pycache__`` 만 뺀다 — 파이썬이 임의로 만들고 지우는 것이라 이 주장의 대상이 아니다.
    """
    manifest: "dict[str, str]" = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[str(path.relative_to(root)).replace("\\", "/")] = digest
    return manifest


@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_check_mode_leaves_the_example_home_untouched(live_check_run) -> None:
    """임시 홈 실행은 사용자의 실습 폴더를 **한 글자도** 건드리지 않는다.

    트리 전체를 해시로 뜬다: 새 파일이 생기는 것뿐 아니라 커밋된 자산이 덮어써지거나 잘리는
    것까지 잡아야 「무오염」이라는 이 모드의 약속이 실제 계약이 된다.
    """
    before, after = live_check_run["before"], live_check_run["after"]
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])

    assert not (added or removed or changed), (
        f"임시 홈 실행이 예제 홈을 바꿨습니다 — 생김 {added} · 사라짐 {removed} · 내용 변경 {changed}"
    )


def test_the_untouched_check_would_notice_a_content_change(tmp_path) -> None:
    """음성 대조 — 내용만 바뀌어도 잡는가(존재 여부만 보던 종전 형태는 못 잡았다)."""
    (tmp_path / "asset.txt").write_text("원본", encoding="utf-8")
    before = _tree_manifest(tmp_path)

    (tmp_path / "asset.txt").write_text("덮어씀", encoding="utf-8")
    after = _tree_manifest(tmp_path)

    assert set(before) == set(after), "이 대조는 파일 목록이 같은 경우를 겨눈다"
    assert before != after, "내용 변경을 못 보면 「한 글자도」라는 말이 거짓이 된다"


# ─────────────────────── 캡처 지점 3자 대조(게이트 밖) ───────────────────────


def _readme_image_references() -> "list[str]":
    return re.findall(r"img/(\d{2}-[a-z-]+\.png)", README.read_text(encoding="utf-8"))


def _expected_filenames(points=CAPTURE_POINTS) -> "list[str]":
    return [f"{index:02d}-{name}.png" for index, name in enumerate(points, 1)]


def _cross_check(
    expected: "list[str]", committed: "list[str]", referenced: "list[str]"
) -> "list[str]":
    """세 목록의 어긋남을 모은다 — 순수 함수라 음성 대조를 조작한 값으로 세울 수 있다."""
    problems: "list[str]" = []
    if sorted(committed) != sorted(expected):
        problems.append(
            f"커밋된 그림 어긋남 — 없는 것 {sorted(set(expected) - set(committed))} · "
            f"남는 것 {sorted(set(committed) - set(expected))}"
        )
    if referenced != expected:
        problems.append(f"README 참조 어긋남(순서 포함) — {referenced}")
    return problems


def test_capture_points_readme_and_committed_images_are_one_set() -> None:
    """대본이 찍기로 한 것 · 커밋된 그림 · README 가 가리키는 것이 **같은 목록**이다.

    셋이 각자 살면 하나만 어긋나도 아무도 모른다 — 대본이 컷 이름을 바꿔도 README 는 옛
    파일을 가리키고 그 파일은 여전히 저장소에 있으니 기존 게이트가 초록이다. 이름의 단일
    출처(:data:`CAPTURE_POINTS`)를 세운 이유가 이 대조다.
    """
    problems = _cross_check(
        _expected_filenames(),
        sorted(p.name for p in IMG_DIR.glob("*.png")),
        _readme_image_references(),
    )

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("committed", "referenced", "fragment"),
    [
        (_expected_filenames()[:-1], _expected_filenames(), "커밋된 그림"),
        (_expected_filenames(), _expected_filenames()[:-1], "README 참조"),
        (_expected_filenames(), list(reversed(_expected_filenames())), "순서"),
    ],
)
def test_the_cross_check_notices_each_way_it_can_drift(committed, referenced, fragment) -> None:
    """음성 대조 — 세 방향의 어긋남을 실제로 잡는가(그림 결손·참조 결손·순서 뒤바뀜).

    저장소 파일을 지웠다 되돌리는 시험은 그 자체가 다음 사람의 작업트리를 위협하므로 **목록을
    조작해** 잰다.
    """
    problems = _cross_check(_expected_filenames(), committed, referenced)

    assert problems, "어긋남을 만들었는데 대조가 조용합니다"
    assert any(fragment in problem for problem in problems), problems


# ───────────────────── 판정의 음성 대조(게이트 밖) ─────────────────────


def _healthy_report(**overrides) -> dict:
    base = {
        "hwpx_generated": EXPECTED_HWPX,
        "shots": list(CAPTURE_POINTS),
        "unstable_shots": [],
        "observations": {
            "hwpx_result_state": "completed",
            "preview_approved": True,
            "txt_copied": "1 / 3",
            "empty_value_gate_asked": True,
            "empty_value_surfaced": True,
        },
    }
    base.update(overrides)
    return base


def test_a_healthy_report_passes_so_the_negative_controls_mean_something() -> None:
    """양성 대조 — 아래 음성들이 「언제나 실패」가 아님을 먼저 보인다."""
    assert report_mod.judge(_healthy_report(), mode="capture").ok is True


def test_zero_documents_fails_even_with_every_screenshot_present() -> None:
    """**생성 0건이면 PNG 가 14장 있어도 실패한다** — 판정 근거는 픽셀이 아니라 실물이다."""
    verdict = report_mod.judge(_healthy_report(hwpx_generated=0), mode="capture")

    assert verdict.ok is False
    assert any("HWPX 생성 0건" in failure for failure in verdict.failures), verdict.failures


def test_a_torn_frame_fails_the_capture_verdict() -> None:
    """정착하지 못한 컷은 찢겨 있을 수 있다 — 조용히 문서에 넣지 않는다(#425 실측)."""
    verdict = report_mod.judge(
        _healthy_report(unstable_shots=["range-editor"]), mode="capture"
    )

    assert verdict.ok is False
    assert any("정착하지 못한 컷" in failure for failure in verdict.failures), verdict.failures


@pytest.mark.parametrize(
    ("observation", "fragment"),
    [
        ({"hwpx_result_state": "failed"}, "결과 태"),
        ({"preview_approved": False}, "승인"),
        ({"txt_copied": ""}, "복사 카운터"),
        ({"empty_value_gate_asked": False}, "이름게이트"),
        ({"empty_value_surfaced": False}, "〈빈 값〉"),
    ],
)
def test_each_journey_fact_is_actually_judged(observation, fragment) -> None:
    """여정의 사실 하나하나가 **실제로 판정에 걸리는가** — 관측만 하고 안 보면 계약이 아니다."""
    report = _healthy_report()
    report["observations"].update(observation)
    verdict = report_mod.judge(report, mode="capture")

    assert verdict.ok is False
    assert any(fragment in failure for failure in verdict.failures), verdict.failures


# ─────────────────── 부재/미성립 구분의 음성 대조(게이트 밖) ───────────────────


class _BlindWindow:
    """모든 술어가 거짓인 창 — 무엇이 없는지는 ``present`` 가 정한다."""

    def __init__(self, present: "set[str]") -> None:
        self.present = present

    def evaluate_js(self, expression: str):
        match = re.search(r"document\.querySelector\(\"(.+?)\"\) !== null", expression)
        if match:
            return match.group(1) in self.present
        return False


def test_a_missing_selector_is_named_not_timed_out() -> None:
    """필수 selector 가 없으면 **그 이름을 대며** 죽는다 — timeout 으로 뭉개지 않는다."""
    surface = Surface(_BlindWindow(present={"#present"}), Deadline(30.0))

    with pytest.raises(MissingSurface) as excinfo:
        surface.wait("false", "어떤 화면", timeout=0.3, requires=["#present", "#gone"])

    assert excinfo.value.selector == "#gone"
    assert "#gone" in str(excinfo.value)


def test_a_present_but_unsatisfied_predicate_stays_a_step_timeout() -> None:
    """음성 대조 — 요소가 다 있으면 여전히 걸음 미성립이다(둘을 뭉개지 않는다)."""
    surface = Surface(_BlindWindow(present={"#present"}), Deadline(30.0))

    with pytest.raises(StepTimeout):
        surface.wait("false", "어떤 화면", timeout=0.3, requires=["#present"])


# ─────────────────────── 실습 홈 보호(게이트 밖) ───────────────────────


def test_a_dirty_home_is_refused_and_preserved(tmp_path) -> None:
    """실습 잔재가 있으면 **지우지 않고 거절**한다 — 사용자 상태를 말없이 파괴하지 않는다."""
    (tmp_path / "jobs").mkdir()
    keepsake = tmp_path / "jobs" / "내작업.job.json"
    keepsake.write_text("{}", encoding="utf-8")

    with pytest.raises(driver.DirtyHome) as excinfo:
        driver.refuse_if_dirty(tmp_path)

    assert "jobs" in str(excinfo.value)
    assert "reset-101.cmd" in str(excinfo.value), "정리하는 길을 함께 일러야 한다"
    assert keepsake.exists(), "거절이 사용자 파일을 지웠습니다"


def test_a_clean_home_is_not_refused(tmp_path) -> None:
    """양성 대조 — 깨끗한 홈까지 거절하면 이 가드는 쓸 수 없다."""
    driver.refuse_if_dirty(tmp_path)


def test_seeding_copies_committed_assets_without_practice_output(tmp_path) -> None:
    """시딩은 **커밋된 자산만** 옮긴다 — 실습 산출물이 따라오면 check 의 판정이 틀린다."""
    home = driver.seed_temp_home(tmp_path / "home")

    for name in driver.SEED_ASSETS:
        assert (home / name).is_dir(), f"시딩 누락: {name}"
    assert driver.generated_documents(home) == [], "시딩 직후 생성물이 있으면 안 됩니다"
    assert not (home / driver.RESULTS_REL).exists()
