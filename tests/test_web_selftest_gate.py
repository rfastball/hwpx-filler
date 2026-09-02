"""실앱 WebView2 게이트 — ``--selftest`` 로 실 창을 띄워 렌더/브리지 DOM 을 되읽어 단언(#30 접근 A).

Node의 정적·React 계약은 배포 자산의 구조를 보고 렌더 로직은 돌리지 않는다. 이 모듈은 그
위층을 메운다: 실 :class:`~hwpxfiller.webapp.app.WebFrontend` + 실 컨트롤러 + 실 ``render()`` 를 pywebview 로
구동하고 ``evaluate_js`` 로 DOM 을 되읽어 **렌더 거동**(창 부팅·작업 기본 화면·홈 경보·내비 실체)을
CI 에서 가드한다.

**Windows/WebView2 전용.** 데스크톱 세션이 없는 헤드리스 러너는 ``HWPX_SKIP_GUI_TESTS=1`` 로
명시 옵트아웃한다 — 런타임 부재를 자동 감지해 조용히 스킵하지 않는다(confirm-or-alarm: 커버리지
착시 금지). 실행 자리는 ``build.ps1``/``test.ps1`` (WebView2 존재). 이 경계는 "게이트 테스트"이지
클라우드-CI 헤드리스 커버가 아니다. 이 게이트가 확인하는 대상은 Windows 앱의
focus/scroll/layout 거동이다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

from _live_budget import SELFTEST_AGGREGATE_BOOT_S, SELFTEST_HARNESS_MARGIN_S
from _web_source import NAV_SCREENS
from _web_source import source_text
from _web_source import RETIRED_COMPAT_GLOBALS as _RETIRED_COMPAT_GLOBALS
from hwpxfiller.webapp import app as app_mod
from hwpxfiller.webapp import boot_budget
from hwpxfiller.webapp import live_run

# 게이트: Windows 아니거나 명시 옵트아웃이면 스킵. 자동 감지 스킵 아님(위 docstring).
_GUI_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_GUI_TESTS"))
_GATE_REASON = (
    "실앱 WebView2 게이트 — Windows 데스크톱 세션 전용(HWPX_SKIP_GUI_TESTS=1 로 옵트아웃)"
)

# 하니스 상한은 **아래 층들에서 파생된다**(#427). 종전에는 90 이라는 상수였는데, 그 값이
# 지키려던 층화를 정작 지키지 못했다:
#
#   제품 폴백 표시 예산(콜드) 60s + selftest 엔진 80s + hard-stop 여유 60s > 하니스 상한 90s
#
# 세 층의 의도는 순서다 — JS 가 먼저 구조화된 실패를 내고, 그 다음 파이썬이 시끄럽게 끝나고,
# 하니스는 **마지막 그물**이다(app.py 의 예산 사슬 주석). 그런데 마지막 그물이 그 아래
# 그물보다 촘촘하면 순서가 뒤집힌다. 실제로 뒤집혔다: 스위트가 27~39% 느려진 CI 실행에서만
# 이 상한이 먼저 발화해, 아무 진단도 없이 "90초 기다렸다"만 남겼다(#427).
#
# 콜드 예산이 매번 걸리는 것도 우연이 아니다 — 각 테스트가 **새 홈**을 쓰므로 완주 이력이
# 없고, `boot_budget.decide()` 는 그때마다 "첫 실행"으로 판정한다.
#
# 여유(margin)는 「러너가 이만큼은 느릴 수 있다」는 인내가 아니라 **판별 불능 구간의 정직한
# 폭**이다(#477) — 값과 그 사유는 `tests/_live_budget.py` 가 소유한다. 종전 30초는 층화(#427)만
# 지키고 공유 러너의 실측을 안 봤다 — PR #476 CI 가 이 상한을 여유 0.0(170.0s/170s)으로 물었고,
# 코드 무변경 재실행이 초록이었다. 그 값으로는 완주 직전이었는지 매달렸는지 말할 수 없다.
# 상한이 무는 순간 "명백히 멈췄다"라고 말할 수 있으려면 실측 최악(콜드 부팅 76.9초·40배 감속
# 여정)을 훨씬 웃돌아야 하고, 그 아래 구간의 성능은 차단이 아니라 **보고**의 몫이다(모듈 끝
# 양성 대조). 시한 자체는 남는다 — 매달림은 진짜 결함이고, 이 상한이 마지막 그물이다.
_HARNESS_MARGIN_S = SELFTEST_HARNESS_MARGIN_S
_SELFTEST_TIMEOUT = (
    app_mod._SELFTEST_BUDGET_S
    + boot_budget.COLD_BUDGET_SECONDS
    + live_run.RUN_HARD_STOP_MARGIN_S
    + _HARNESS_MARGIN_S
)

# 부팅 하나의 상한을 늘리면 **최악의 경우가 곱해진다**(#428 리뷰 P1). 이 모듈은 파라미터화
# 포함 십수 회 부팅하고 pytest 는 시한 초과 뒤에도 다음 테스트로 간다 — WebView2 가 전면
# 매달리면 대기만으로 CI 잡 상한을 넘길 수 있다. 그때 러너가 잡을 죽이면 위에서 애써 남긴
# 진단도 커버리지 산출물도 **회수되기 전에 사라진다**. 진단을 겨냥한 그 시나리오에서 진단을
# 잃는 셈이라, 합계에도 상한이 있어야 한다.
#
# 정상 실행은 이 예산 근처에 오지 않는다(로컬 부팅당 2.2s, 느린 CI 에서도 십수 초). 그래서
# 이 상한은 "느린 러너"가 아니라 **전면 매달림**에서만 발화하고, 그때는 더 기다려 봐야 배울
# 것이 없으므로 남은 부팅을 즉시 실패시킨다.
#
# 산술(#477 갱신 — 부팅 하나 상한을 벌리면 합계도 같이 벌려야 이 관계가 산다):
#   발화선 = 합계 - 부팅 하나 몫. 정상 소진(로컬 실측 33s·감속 러너 수백 초)의 여러 배라
#   느린 러너로는 안 닿는다.
#   최악 대기는 유계다: 매달림 한 번 뒤 남은 예산이 부팅 하나 몫 아래로 떨어져 나머지가
#   즉시 실패하므로, 대기 총량 ≤ 이 합계다. 이 항이 101 phase 들과 함께 live-webview2 잡의
#   최악 산술을 이루고, 그 산술과 잡 상한의 대조는 **기계 단언**이 진다 — 항·합·판정 모두
#   `tests/_live_budget.py`(값) + `tests/repo_contract/test_quality_workflow.py`(대조) 소유다.
#   종전에는 같은 합이 여기·워크플로·형상 계약 세 곳의 주석에 손으로 복사돼 있었고, 이
#   주석은 워크플로 주석을 「산술 정본」이라 가리키면서 정작 그 값을 읽지 않았다(#912).
_AGGREGATE_BOOT_BUDGET_S = SELFTEST_AGGREGATE_BOOT_S

#: 지금까지 부팅 대기에 쓴 시간과 실제로 시한을 넘긴 부팅들 — 진단이 "몇 번째부터 무너졌나"를
#: 말할 수 있게 남긴다.
_boot_waits: "dict[str, object]" = {"spent_s": 0.0, "timed_out": [], "boots": 0}


def _boot_selftest(env: "dict[str, str]", *, out: Path, what: str) -> "subprocess.CompletedProcess":
    """``--selftest`` 프로세스 하나를 띄운다 — **모든 부팅의 단일 입구**.

    시한 초과를 그냥 던지면 남는 것은 "N초 기다렸다" 뿐이고, 그 문장은 *느린 것*과 *매달린
    것*을 구별하지 못한다(#427). 둘은 원인도 조치도 다르므로 여기서 갈 수 있는 데까지의
    사실을 함께 낸다: 무엇을 띄우려 했는지 · 실제 소요 · **증거 파일이 생겼는지**(= 드라이버가
    종결에 닿았는지) · 자식이 남긴 출력 꼬리 · 그때의 예산 사슬 수치.

    합계 예산이 남지 않으면 **기다리지 않고** 실패한다 — 잘린 시한으로 기다리면 그 실패가
    이 부팅의 문제인지 합계 소진인지 구별되지 않는다(#428 리뷰 P1).
    """
    spent = float(_boot_waits["spent_s"])
    if _AGGREGATE_BOOT_BUDGET_S - spent < _SELFTEST_TIMEOUT:
        raise AssertionError(_exhausted_report(what, spent))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"],
            # 파이프 양끝의 인코딩을 **로캘과 무관하게** 맞춘다(#778). 읽는 쪽만 고정하면
            # 한국어 Windows 에서 자식이 cp949 로 써 나가 사유가 뭉개지고, 아무것도 고정하지
            # 않으면 reader thread 가 `UnicodeDecodeError` 로 죽어 `stdout` 이 `None` 이 된다.
            # `PYTHONIOENCODING` 은 자식의 **스트림만** 바꾼다 — 파일 기본 인코딩은 그대로라
            # 이 게이트가 재는 제품 거동은 움직이지 않는다.
            env={**env, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=_SELFTEST_TIMEOUT,
        )
        if completed.returncode != 0:
            raise AssertionError(_process_failure_report(completed, out=out, what=what))
        return completed
    except subprocess.TimeoutExpired as expired:
        _boot_waits["timed_out"].append(what)  # type: ignore[union-attr]
        raise AssertionError(
            _timeout_report(expired, out=out, what=what, elapsed=time.monotonic() - started)
        ) from None
    finally:
        _boot_waits["spent_s"] = spent + (time.monotonic() - started)
        _boot_waits["boots"] = int(_boot_waits["boots"]) + 1


def _exhausted_report(what: str, spent: float) -> str:
    """합계 예산 소진 — 이 부팅의 잘못이 아니라는 것을 문안이 분명히 말한다."""
    stuck = _boot_waits["timed_out"] or ["(없음)"]
    return "\n".join(
        [
            f"selftest 부팅 합계 예산 소진 — {what} 은(는) 기다리지 않고 실패시킵니다",
            f"  누적 대기 {spent:.0f}s / 합계 상한 {_AGGREGATE_BOOT_BUDGET_S:.0f}s"
            f" (부팅 하나 상한 {_SELFTEST_TIMEOUT:.0f}s)",
            f"  먼저 시한을 넘긴 부팅: {stuck}",
            "  → WebView2 가 전면 매달린 상태로 보입니다. 남은 부팅을 마저 기다리면 CI 잡"
            " 상한을 넘겨 이 진단조차 회수되지 못합니다.",
        ]
    )


def _timeout_report(
    expired: subprocess.TimeoutExpired, *, out: Path, what: str, elapsed: float
) -> str:
    """시한 초과를 **진단**으로 바꾼다 — 다음 사람이 재실행 말고 읽을 것이 있게."""
    tail = _tail(expired.stderr) or _tail(expired.stdout) or "(자식 출력 없음)"
    reached = _evidence_progress(out)
    return "\n".join(
        [
            f"selftest 부팅 시한 초과 — {what}",
            f"  소요 {elapsed:.1f}s / 상한 {_SELFTEST_TIMEOUT:.0f}s"
            f" (= selftest 엔진 {app_mod._SELFTEST_BUDGET_S:.0f}s"
            f" + 콜드 부팅 예산 {boot_budget.COLD_BUDGET_SECONDS:.0f}s"
            f" + hard-stop 여유 {live_run.RUN_HARD_STOP_MARGIN_S:.0f}s"
            f" + 부모 진단 여유 {_HARNESS_MARGIN_S:.0f}s)",
            f"  증거 파일: {reached} ({out})",
            f"  자식 출력 꼬리:\n{tail}",
        ]
    )


def _process_failure_report(
    completed: "subprocess.CompletedProcess", *, out: Path, what: str
) -> str:
    event = {
        live_run.TEARDOWN_HUNG_EXIT_CODE: "teardown_hung",
        live_run.RUN_HUNG_EXIT_CODE: "run_hung",
    }.get(completed.returncode, "process_failed")
    tail = _tail(completed.stderr) or _tail(completed.stdout) or "(자식 출력 없음)"
    return "\n".join(
        [
            f"selftest 프로세스 실패 — {what}",
            f"  event={event} rc={completed.returncode}",
            f"  증거 파일: {_evidence_progress(out)} ({out})",
            f"  자식 출력 꼬리:\n{tail}",
        ]
    )


def _evidence_progress(out: Path) -> str:
    if not out.exists():
        return "없음 — 종결에 못 닿았다"
    try:
        parsed = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "불완전 — 종결 증거를 쓰는 중 멎었다"
    return (
        "유효함 — 결과를 쓴 뒤 프로세스 종료에 못 닿았다"
        if isinstance(parsed, dict)
        else "불완전 — 종결 증거가 JSON 객체가 아니다"
    )


def _tail(stream: "str | bytes | None", limit: int = 2000) -> str:
    if not stream:
        return ""
    # backslashreplace: 되돌릴 수 있는 손실만 낸다 — U+FFFD 로 뭉개면 인코딩 사고의 원 바이트가
    # 사라져 사후에 원인을 짚을 수 없다(#778, `src/hwpxfiller/cli.py` 와 같은 정책).
    text = stream if isinstance(stream, str) else stream.decode("utf-8", "backslashreplace")
    return text[-limit:]


@pytest.fixture(scope="module")
def selftest_result(tmp_path_factory) -> dict:
    """``--selftest`` 로 앱을 모듈당 1회 구동하고 DOM 되읽기 결과 JSON 을 로드한다.

    WebView2 콜드스타트가 비싸므로 창을 한 번만 띄우고 그 스냅샷에 여러 단언을 건다.
    출력 경로는 ``HWPX_SELFTEST_OUT`` 로 결정(하네스가 소유) — 동결 exe 옆에 쓰는 기본 거동과 분리.

    ``HWPXFILLER_HOME`` 은 여기서 **명시로** 격리한다: conftest 의 autouse 격리는 function
    스코프라 이 module 스코프 픽스처가 먼저 인스턴스화된다 — os.environ 상속에 맡기면
    서브프로세스가 실홈(``~/.hwpxfiller``)의 ``settings.json`` 을 물려받아, 사용자가 저장한
    테마가 ``test_theme_defaults_to_system_when_unpersisted`` 를 오염시킨다(미저장 전제 붕괴, #74).
    """
    out = tmp_path_factory.mktemp("selftest") / "selftest_result.json"
    home = tmp_path_factory.mktemp("selftest-home")
    env = dict(os.environ, HWPX_SELFTEST_OUT=str(out), HWPXFILLER_HOME=str(home))
    proc = _boot_selftest(env, out=out, what="full 모드 모듈 픽스처")
    assert out.exists(), (
        "selftest 결과 파일 미생성 — 창 부팅/렌더 실패 가능. "
        f"rc={proc.returncode}\nstdout={_tail(proc.stdout)}\nstderr={_tail(proc.stderr)}"
    )
    return json.loads(out.read_text(encoding="utf-8"))


def probe(evidence: dict, name: str):
    """프로브 결과를 **사유와 함께** 꺼낸다 — 실패한 프로브는 키를 아예 내지 않는다.

    러너는 실패한 프로브의 키를 내보내지 않는다(부분 결과 금지 — 옳은 설계다). 그런데 소비자가
    ``evidence["job_mirror"]`` 로 곧장 읽으면 원인 **하나**가 ``KeyError`` **열몇 개**로 번역돼
    로그에서 진짜 사유 한 줄을 파묻는다(#429: 실제로 CI 로그의 실패 11건 중 원인은 첫 줄
    하나였고 나머지는 전부 그 그림자였다).

    이 접근자는 부재를 「그 프로브가 실패했다」로 재진술하고 러너가 남긴 사유를 함께 댄다.
    """
    if name in evidence:
        return evidence[name]
    reason = evidence.get("error") or "(러너가 사유를 남기지 않았다)"
    raise AssertionError(
        f"`{name}` 프로브가 결과를 내지 못했습니다 — 이 테스트의 단언이 아니라 **그 프로브**가"
        f" 원인입니다.\n  러너 사유: {reason}"
    )


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
class TestWebSelftestGate:
    """실 창을 띄워 되읽은 DOM 스냅샷에 대한 렌더 거동 계약."""

    def test_no_probe_error(self, selftest_result: dict) -> None:
        # evaluate_js 프로브가 예외 없이 전부 돌았는가(브리지/렌더 파이프 무결).
        assert "error" not in selftest_result, selftest_result.get("error")

    def test_react_runtime_commits_one_root_with_a_live_store_marker(
        self,
        selftest_result: dict,
    ) -> None:
        """한 제품 창에서 React 커밋과 snapshot store 결속을 함께 증명한다.

        과거에는 root·store 전용 WebView2 창을 따로 띄웠다. 제품 selftest가 이미 같은
        sealed artifact에서 이 형상을 되읽으므로, 장기 계약은 이 모듈의 단일 부팅 결과가
        소유한다. revision의 절댓값은 실행 순서에 따라 달라질 수 있어 형상만 단언한다.
        """
        runtime = probe(selftest_result, "react_runtime")
        assert runtime["mounted"] == "1", runtime
        assert runtime["roots"] == 1, runtime
        assert re.fullmatch(r"[0-9]+", runtime["store_rev"]), runtime

    def test_sealed_artifact_runs_on_one_loopback_origin(self, selftest_result: dict) -> None:
        """제품/selftest가 같은 seal을 쓰며 file/dev/external resource를 하나도 싣지 않는다."""
        runtime = selftest_result["runtime"]
        url = selftest_result["url"]
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+/index\.html", url), url
        assert runtime["page_url"] == url
        assert runtime["origin"] == (f"{urlsplit(url).scheme}://{urlsplit(url).netloc}")
        assert re.fullmatch(r"[0-9a-f]{64}", runtime["artifact_id"])
        assert re.fullmatch(r"[0-9a-f]{64}", runtime["tree_sha256"])
        assert runtime["resource_urls"], "제품 CSS/JS resource가 하나도 기록되지 않았습니다."
        assert runtime["resources_same_origin"] is True
        assert runtime["forbidden_resources"] == []
        assert runtime["external_fetch_completed"] is None
        assert runtime["external_fetch_succeeded"] is None
        assert runtime["external_fetch_blocked"] is None

    def test_document_title_rendered(self, selftest_result: dict) -> None:
        # 실 DOM 의 document.title 이 비어있지 않음 = 문서 부팅·셸 로드 확인.
        assert selftest_result["title_dom"]

    def test_all_nav_buttons_rendered(self, selftest_result: dict) -> None:
        # 내비(.navbtn) 가 실체로 그려짐 — 화면 소실 회귀 가드.
        assert selftest_result["nav_count"] == len(NAV_SCREENS)

    def test_job_is_default_screen(self, selftest_result: dict) -> None:
        # H-05: 콜드 부팅은 살아 있는 소비 화면인 작업으로 곧장 진입한다.
        assert selftest_result["job_on"] is True

    def test_data_picker_buttons_present(self, selftest_result: dict) -> None:
        # 데이터 선택 단일 출구(재작성 F1) — 세션 표면(문서 만들기)에 실재한다.
        # (「기안」 몫은 화면과 함께 사망 — F6 PR-B.)
        assert selftest_result["data_picker_buttons"] is True

    def test_data_picker_dialog_absorbs_pool_screen(self, selftest_result: dict) -> None:
        """`pool` 화면 사망의 승계처가 실앱에서 실제로 선다(지도 §10.7.4 점검표).

        정적 DOM 계약이 못 잡는 세 승계 의무를 실 렌더로 못박는다: 보관 항목이 목록에
        남아 `활성화` 에 도달 가능할 것(§10.7.2 C), 손상 격리가 상주 재진술될 것(RC-05),
        「이 데이터 고정」이 현재 마운트 대상을 프리필할 것(v6 pinDataDialog).
        """
        probe = selftest_result["data_picker"]
        assert probe["error"] is None, probe
        assert probe["opened"] is True, probe
        assert probe["rows"] == 3, probe
        # 보관 항목은 숨기지 않고 **정직하게 비활성** — 그래야 활성화 동사가 도달 가능하다.
        assert probe["use_active_enabled"] is True, probe
        assert probe["use_archived_disabled"] is True, probe
        assert probe["activate_reachable"] is True, probe
        assert probe["relink_reachable"] is True, probe
        assert probe["corrupt_shown"] is True, probe
        # 고정 = 등록 모달 재사용이되 진입 사유가 제목·프리필로 드러난다.
        assert probe["pin_offered"] is True, probe
        assert probe["pin_title"] == "이 데이터 고정", probe
        # 제목과 확정 버튼이 같은 동사를 쓴다 — 「고정」을 열고 「등록」을 누르게 하지 않는다.
        assert probe["pin_ok"] == "고정", probe
        assert probe["pin_path"] == "C:/d/대장.xlsx", probe
        assert probe["pin_sheet"] == "물품", probe

    def test_data_picker_single_path(self, selftest_result: dict) -> None:
        """데이터 선택 면 단일 경로화(U2 §2.7) — 문안이 약속한 고정 기회가 실제로 선다.

        찾아보기 성사 뒤에도 면이 열려 있고 「이 데이터 고정」이 **가시**여야 한다(1행) —
        프로브 click 은 hidden 요소도 통과하므로 존재가 아니라 가시성을 단언한다.
        「＋ 직접 등록…」은 소멸(4행), pin 모드의 path·sheet 는 읽기전용 + 폼 안
        찾아보기 감춤(5행)이다.
        """
        probe = selftest_result["data_picker"]
        assert probe["error"] is None, probe
        assert probe["register_gone"] is True, probe
        assert probe["pin_path_readonly"] is True, probe
        assert probe["pin_sheet_readonly"] is True, probe
        assert probe["pin_browse_hidden"] is True, probe
        # 찾아보기 마운트 성사 = 면 유지 + 재진술 + 고정 버튼 가시(허가지 의무가 아니다).
        assert probe["browse_kept_open"] is True, probe
        assert probe["browse_restated"] is True, probe
        assert probe["browse_pin_visible"] is True, probe

    def test_data_picker_identity_rekey(self, selftest_result: dict) -> None:
        """데이터 축 정체성 재편(#347, U2 §5.3) — 행동은 슬롯 키를 겨누고 병합은 loud 다.

        이름이 중복 허용 라벨로 강등돼 행 버튼이 키 없이 서면 동명 2건에서 남의 항목을
        겨눈다. 같은 데이터(경로+시트)를 가리키는 구판 등록 2건은 숨기거나 자동 정리하지
        않고 병합 확정 카드로 표면화한다(confirm-or-alarm).
        """
        probe = selftest_result["data_picker"]
        assert probe["error"] is None, probe
        assert probe["use_targets_key"] is True, probe
        assert probe["dupes_shown"] is True, probe

    def test_data_picker_registers_contract_lists(self, selftest_result: dict) -> None:
        """계약 목록이 이 면에서 **실제로** 서고 등록된다(#937 ADR N).

        엑셀과 좌표가 다른 종류라 정적 계약만으로는 「목록에 그려지는가」·「엑셀 전용
        동사가 새지 않는가」를 못 본다. 진입 버튼은 존재가 아니라 **가시**여야 하고
        (프로브 click 은 hidden 도 통과한다), 열린 폼은 기본 DB 자리를 프리필하되 시트는
        빈 placeholder 로 남긴다 — 계약면을 조용히 하나 고르면 문서 건수가 어긋난다.

        표면 어휘도 여기서 잰다: 옵션의 **값**은 백엔드 계약(실 뷰 이름)이지만 **보이는
        글자**에는 내부 이름도 저쪽 프로그램 이름도 서지 않는다.
        """
        probe = selftest_result["data_picker"]
        assert probe["error"] is None, probe
        # 종류가 달라도 목록에서 그냥 쓸 수 있다(끊김·보관이 아니면 비활성 사유가 없다).
        assert probe["pclm_row_usable"] is True, probe
        # 「다시 연결」은 경로+시트 좌표의 엑셀 전용 동사 — pclm 행에 서면 거짓 어포던스다.
        assert probe["pclm_no_relink"] is True, probe
        assert probe["pclm_entry"] is True, probe
        assert probe["pclm_entry_text"] == "계약 목록(.db) 등록…", probe
        # 고르게 할 시트 3 + 빈 placeholder 1 — 목록 첫 항목이 기본으로 서지 않는다.
        # 품목 뷰는 1계약 N줄이라 반복 표가 서기 전까지 웹 등록에서 고르게 하지 않는다.
        assert probe["pclm_reg_view_options"] == 4, probe
        assert probe["pclm_reg_db_prefill"] == "C:/AppData/Local/Pclm/pclm.db", probe
        # 값은 실 뷰 이름 그대로(백엔드 계약), 글자는 제목 — 표면에 `v_` 이름이 새지 않는다.
        assert probe["pclm_reg_view_values"] == "|v_통합_v1|v_공고_v1|v_계약_v1", probe
        assert "v_" not in probe["pclm_reg_view_text"], probe
        assert probe["pclm_reg_view_text"].startswith("시트를 고르세요|통합 —"), probe
        assert probe["pclm_reg_view_label"] == "읽을 시트", probe

    def test_each_action_family_click_dispatches_and_returns_snapshot(
        self,
        selftest_result: dict,
    ) -> None:
        """네 화면군이 실 click→JS bridge→Python registry→snapshot을 한 부팅에서 왕복한다.

        (「기안」 군은 화면 사망으로 표에서 빠졌다 — F6 PR-B.)
        """

        probe = selftest_result["action_roundtrip"]
        assert probe["pending"] is False, probe
        expected = {
            "editor": ("editor", "new_session"),
            "job": ("job", "refresh"),
            "pool": ("pool", "refresh"),
            "template": ("tpl", "refresh"),
        }
        assert set(probe["families"]) == set(expected), probe
        for family, (screen, action) in expected.items():
            got = probe["families"][family]
            assert "error" not in got, f"{family}: {got}"
            assert (got["screen"], got["action"]) == (screen, action)
            assert got["snapshot"] is True, f"{family}: {got}"
            assert got["snapshot_keys"], f"{family}: 빈 snapshot: {got}"

    def test_home_screen_is_dead_and_library_stands(self, selftest_result: dict) -> None:
        """재작성 F2 — 홈 화면은 죽고 「문서 작업」 라이브러리가 그 자리를 잇는다.

        죽은 DOM(카드 나열·group-by 렌즈 바)이 남아 있으면 다음 세션의 부활 경로가 된다.
        승계처는 축 4종(보기·방식·태그·검색)과 2-pane 골격을 실물로 갖춰야 한다.
        """
        assert selftest_result["home_screen_gone"] is True
        assert selftest_result["library_surface"] is True
        assert selftest_result["library_view_tabs"] == [
            "all",
            "recent",
            "favorites",
            "needsAction",
        ]

    def test_display_order_axis_survives_the_push_rerender(self, selftest_result: dict) -> None:
        """재작성 F3 — 표시순서를 바꾸면 왕복 뒤에도 고른 값이 남는다.

        이 축의 결함류는 "왕복 중 도착한 push 가 컨트롤을 옛 값으로 되돌린다"이고, 정적
        계약은 요소 존재까지만 본다. 양성대조(`control_before`)가 먼저 선다 — 렌더가 실제로
        이 컨트롤의 상태를 축으로 세운다는 증명이 없으면, 값이 안 바뀌는 프로브도 통과한다.

        컨트롤은 U4 7번에서 `<select>` 에서 **표 머리의 스위치**로 바뀌었다(`#jobOrderToggle`).
        상태는 `aria-pressed`, 2값 고정(F3)은 `data-order-values` 선언이 진다 — 축의 이름과
        수는 그대로이므로 이 게이트가 재는 사실도 그대로다.
        """
        v = selftest_result["view_order"]
        assert v.get("error") is None, f"표시순서 프로브 오류: {v!r}"
        assert v["present"] is True and v["options"] == ["sourceDesc", "sourceAsc"]
        assert v["control_before"] is True, "양성대조 실패 — 렌더가 컨트롤 상태를 안 씁니다."
        assert v["after_roundtrip"] == "sourceAsc", "왕복 뒤 축이 옛 값으로 되돌아갔습니다."
        assert v["restored"] == "sourceDesc"

    def test_range_draft_refuses_to_open_without_data(self, selftest_result: dict) -> None:
        """재작성 F3 — 데이터 없이 여는 범위 편집기는 **거절**이고, 초안은 서지 않는다.

        면만 열리고 초안이 없으면 편집기가 무엇을 편집 중인지 거짓이 된다(성사 뒤에만
        연다). footer 는 화면 안에서 숨어 있다가 면 슬롯 안에서만 서는 것도 함께 본다 —
        공용 펼침 면 마크업에 화면 소유물이 새지 않는 계약이다(구 「기안」 공유의 잔재 계약,
        화면은 사망 — F6 PR-B).
        """
        d = selftest_result["range_draft"]
        assert d.get("error") is None, f"범위 초안 프로브 오류: {d!r}"
        assert d["present"] is True
        assert d["foot_hidden_in_screen"] is True, "footer 가 화면 안에서 노출돼 있습니다."
        assert d["opened_without_data"] is False, "데이터 없이 초안이 섰습니다(거절 계약 위반)."
        assert d["draft_state"]["open"] is False

    def test_call_chain_survives_a_rejected_link(self, selftest_result: dict) -> None:
        """리뷰 5R — 직렬화 체인은 실패 한 번으로 죽지 않는다.

        rejected 링이 체인에 남으면 이후 같은 키의 모든 호출이 그 링에 붙어 영영 실행되지
        않는다: 접힘 영속이 한 번 실패했다고 그 화면의 탭·검색·필터가 세션 내내 죽는다.
        실패는 **호출자에게 그대로 전해지되**(되돌리기·loud 재진술이 그 위에 선다) 저장된
        링은 성사 상태로 남아야 한다 — 정적 계약이 못 보는 실행 성질이라 실물로 본다.
        """
        c = selftest_result["chain_recovery"]
        assert c.get("error") is None, f"체인 복구 프로브 오류: {c!r}"
        assert c["rejected_surfaced"] is True, "실패가 호출자에게 전해지지 않습니다."
        assert c["after_ran"] is True, "실패 뒤 호출이 실행되지 않았습니다 — 체인이 죽었습니다."
        assert c["after_value"] == "ok"

    def test_shell_settings_modal_round_trips_theme_and_returns_focus(
        self, selftest_result: dict
    ) -> None:
        """토바 ⚙ → 설정 모달 → 테마 세그먼트 → 원래 값 복원 → 닫힘 → 초점 복귀.

        순환 토글 둘(`#themeToggle`·`#fontScaleToggle`)이 걷히고 값 선택이 모달 안 세그먼트로
        옮겨간 뒤, 사용자가 테마를 바꾸려면 **여섯 홉**을 지난다: 셸 리스너 → Modal.open →
        React portal 커밋 → 세그먼트 클릭 → Theme.set → documentElement 기입. 정적 계약은 이
        사슬의 각 조각이 소스에 있다는 것까지만 보고, 어느 홉이 끊겨도 초록이다.

        복원까지 한 프로브가 지는 이유: 복원이 빠지면 이 프로브가 뒤 실행의 콜드부트 테마를
        조용히 바꾼다(같은 창의 `theme_persist` 가 그 값을 읽는다). 그래서 「바뀌었다」와
        「되돌아왔다」를 한 쌍으로 단언한다.
        """
        s = selftest_result["shell_settings"]
        assert s["opened"] is True, "⚙ 클릭이 설정 모달의 hidden 을 해제하지 못했습니다."
        assert s["display"] != "none", "설정 모달이 열렸다면서 보이지 않습니다."
        assert s["option_visible"] is True, (
            "테마 세그먼트가 보이지 않는데 클릭이 통과했습니다 — .click() 은 숨은 요소도 누릅니다."
        )
        assert s["applied_theme"] == s["requested_theme"], (
            f"세그먼트 클릭이 테마에 닿지 않았습니다: {s!r}"
        )
        assert s["option_pressed"] == "true", "고른 값이 aria-pressed 로 말해지지 않습니다."
        assert s["theme_restored"] == s["theme_before"], (
            f"프로브가 테마를 되돌리지 못했습니다: {s!r}"
        )
        assert s["closed"] is True, "닫기 버튼이 설정 모달을 닫지 못했습니다."
        assert s["focus_back"] == "settingsOpen", (
            f"닫은 뒤 초점이 트리거(⚙)로 복귀하지 않았습니다: {s['focus_back']!r}"
        )

    def test_modal_opens_with_initial_focus_inside(self, selftest_result: dict) -> None:
        # 커스텀 모달을 열면 hidden 해제 + 초기 포커스가 모달 안(promptModalInput)으로 들어간다.
        # (표적 모달 재겨눔 2회: draftSaveTplModal 사망 → txtEditModal(F6 PR-B) →
        #  txtEditModal 이 폼 모달이 아니게 됨 → promptModal(R4-02). 내용의 생산자가 편집기
        #  React 표면으로 옮겨 「열어 두면 안에 요소가 있다」가 더는 참이 아니다.)
        m = selftest_result["modal_a11y"]
        assert m["opened"] is True
        assert m["focus_in"] == "promptModalInput"

    def test_modal_escape_closes_and_restores_focus(self, selftest_result: dict) -> None:
        # Escape 로 닫히고, 포커스가 열기 직전 트리거로 복귀한다(조용한 포커스 유실 금지 — #28).
        m = selftest_result["modal_a11y"]
        assert m["escape_entered_closing"] is True
        assert m["closed_by_escape"] is True
        assert m["focus_restored"] == m["focus_before"]

    def test_confirm_modal_toggles_display_and_focuses_cancel(self, selftest_result: dict) -> None:
        # #86/부록 B-9: 네이티브 confirm 대체 모달이 실 앱에서 실제로 열리고 닫히는지 계산 스타일로
        # 확인한다 — .modal{display:flex} 가 hidden 을 덮으면(B-9 결함 클래스) 닫아도 계속 보인다.
        m = selftest_result["modal_a11y"]
        assert m["confirm_display_closed_before"] == "none", (
            "열기 전 confirmModal 이 이미 보입니다."
        )
        assert m["confirm_opened"] is True, "Modal.confirm 이 hidden 을 해제하지 못했습니다."
        assert m["confirm_display_open"] == "flex", (
            "열린 confirmModal 의 display 가 flex 가 아닙니다."
        )
        # 기본 포커스=취소(머무르기) — Enter-반사 파괴 차단(F7, 결정 27/36/38).
        assert m["confirm_focus"] == "confirmModalCancel", (
            f"확인 모달 초기 포커스가 취소가 아닙니다(현재: {m['confirm_focus']!r})."
        )
        assert m["confirm_entered_closing"] is True, "확인 모달이 퇴장 상태를 거치지 않았습니다."
        assert m["confirm_closed"] is True, "확인 클릭 후 confirmModal 이 다시 hidden 이 아닙니다."
        assert m["confirm_display_closed"] == "none", (
            "닫힌 confirmModal 의 display 가 none 이 아닙니다 — .modal.hidden 이 display:flex 를 "
            "이기지 못합니다(부록 B-9 결함 재발)."
        )

    def test_choose_modal_offers_three_answers_and_defaults_to_refusal(
        self, selftest_result: dict
    ) -> None:
        # 3택 골격(재작성 F7) — patch 처분처럼 답이 셋인 자리. 확인 모달로 두 번 물으면
        # "취소가 무엇을 취소하는지"가 갈리므로 별 골격을 뒀다. 배선만 하고 안 보이면
        # 사용자는 편집기를 나갈 길이 없다 — 실 렌더로 세 버튼을 다 본다.
        m = selftest_result["modal_a11y"]
        assert m["choose_opened"] is True and m["choose_display"] == "flex", (
            f"3택 모달이 열리지 않았습니다: {m['choose_opened']!r}/{m['choose_display']!r}"
        )
        assert m["choose_focus"] == "chooseModalCancel", (
            f"3택 초기 포커스가 거절(머무르기)이 아닙니다: {m['choose_focus']!r} — Enter 반사로"
            " 편집이 사라지는 경로를 만든다."
        )
        assert m["choose_labels"] == "저장하고 이동|버리고 이동|머무르기", (
            f"세 버튼이 호출부 라벨을 받지 않았습니다: {m['choose_labels']!r}"
        )
        assert m["choose_all_visible"] is True, "3택 버튼 중 보이지 않는 것이 있습니다."

    def test_modal_open_rejects_non_modal_target_loudly(self, selftest_result: dict) -> None:
        # #132.4: 이 앱의 숨김 규칙은 `.modal.hidden` 뿐이라, .modal 없는 요소에 Modal.open 하면
        # `.hidden` 토글이 조용한 no-op(뜨지도 숨지도 않음)이 된다. confirm-or-alarm: 조용히
        # 삼키지 말고 loud(console.error) 거절 + 열지 않아야(요소가 hidden 유지) 한다.
        m = selftest_result["modal_a11y"]
        assert m["non_modal_open_rejected_loud"] is True, (
            "Modal.open 이 .modal 없는 요소를 조용히 삼켰습니다 — loud 거절(console.error)+미개방 기대."
        )

    def test_danger_confirm_toggles_visual_variant_without_leaking(
        self, selftest_result: dict
    ) -> None:
        """#219: 실 WebView2에서 danger 버튼이 솔리드 배경으로 서고 다음 중립 확인엔 남지 않는다."""
        m = selftest_result["modal_a11y"]
        assert m["danger_class"] is True
        assert m["danger_background"] not in ("transparent", "rgba(0, 0, 0, 0)")
        assert m["danger_resets_to_neutral"] is True

    def test_modal_close_rejects_non_modal_target_loudly(self, selftest_result: dict) -> None:
        # 동일 잠복(#132.4) — close 도 .modal 없는 대상을 loud 거절한다(open 과 대칭).
        m = selftest_result["modal_a11y"]
        assert m["non_modal_close_rejected_loud"] is True, (
            "Modal.close 가 .modal 없는 요소를 조용히 삼켰습니다 — loud 거절(console.error) 기대."
        )

    def test_malformed_confirm_root_refused_without_deadlock(self, selftest_result: dict) -> None:
        # Codex P2: confirm/prompt root 가 .modal 을 잃으면 open 가드가 조용히 early-return 해
        # pendingDialog 가 영영 갇히던(이후 모든 다이얼로그 재진입 거절 + Escape 불가) 교착을,
        # _promiseModal 이 pendingDialog 세우기 *전* .modal 을 검증해 막는다. 정적 계약상 도달
        # 불가하나(class="modal" 가드) 그 방어가 실제로 도는지 실앱에서 되읽는다.
        m = selftest_result["modal_a11y"]
        assert m["malformed_confirm_root_refused_loud"] is True, (
            "불량(.modal 없는) confirm root 가 loud 거절되지 않았습니다."
        )
        assert m["confirm_after_malformed_opens"] is True, (
            "불량 root 이후 정상 confirm 이 열리지 않았습니다 — pendingDialog 교착(Codex P2 회귀)."
        )

    def test_confirm_modal_serializes_single_inflight(self, selftest_result: dict) -> None:
        # promise 다이얼로그는 동시 1건 — 미결 confirm 위에 두 번째 confirm 을
        # 요청하면 즉시 안전측 거절(false) + loud(alert) 이어야 하고, 첫 다이얼로그의 본문·리스너가
        # 덮이면 안 된다(덮이면 OK 1클릭에 두 파괴 동작이 디스패치되는 이중 삭제 결함).
        m = selftest_result["modal_a11y"]
        assert m["confirm_reentry_alerts"] == 1, (
            f"재진입 거절이 loud 하지 않습니다(alert {m['confirm_reentry_alerts']}회) — "
            "조용한 거절은 confirm-or-alarm 위반(리뷰 #1/#4)."
        )
        assert m["confirm_body_after_reentry"] == "첫 확인 본문", (
            "재진입이 첫 다이얼로그 본문을 덮어썼습니다 — 단일 실행 직렬화 실패(리뷰 #1)."
        )
        s = selftest_result["modal_confirm_serial"]
        assert s["first"] is True, f"첫 confirm 이 확인 클릭으로 true 해소되지 않았습니다: {s!r}"
        assert s["second"] is False, (
            f"재진입 confirm 이 안전측 거절(false)로 해소되지 않았습니다: {s!r} — "
            "이중 바인딩이면 first 확정이 second 에도 새어 두 동작이 함께 실행됩니다(리뷰 #1)."
        )

    def test_confirm_modal_traps_tab_within_card(self, selftest_result: dict) -> None:
        # 포커스 트랩 — 모달의 마지막 포커서블(확인)에서 Tab 이 배경 버튼으로
        # 새지 않고 모달 안 첫 요소(취소)로 순환해야 한다. 배경 버튼 Tab+Enter 로 두 번째 파괴
        # 동작이 발화되는 경로(이중/오대상 삭제·생성 동시 실행)의 원천 차단.
        m = selftest_result["modal_a11y"]
        assert m["confirm_trap_wrapped"] == "confirmModalCancel", (
            f"Tab 이 모달 안에서 순환하지 않습니다(현재 포커스: {m['confirm_trap_wrapped']!r}) — "
            "배경으로 새면 미결 확인 뒤 두 번째 파괴 동작이 가능합니다(리뷰 #1)."
        )

    def test_sheet_gate_confirm_loads_chosen_sheet(self, selftest_result: dict) -> None:
        # 다중 시트 확정 게이트(#33) — SheetPicker.choose 가 실 DOM 에서 모달을 열고, 시트를
        # 확정(클릭)하면 그 시트로 로드돼 결과가 해소된다(첫 시트 강등이 아니라 확정값 반영).
        s = selftest_result["sheet_gate"]
        assert s.get("status") == "done", f"시트 게이트 프로브 실패: {s!r}"
        assert s["opened"] is True and s["btn_count"] == 2 and s["focus_first"] is True
        assert s["picked"] == "확정됨:낙찰현황", f"확정 시트로 로드 안 됨: {s['picked']!r}"

    def test_sheet_gate_cancel_aborts_without_loading(self, selftest_result: dict) -> None:
        # 취소(Escape)는 조용한 첫 시트 강등이 아니라 중단 — null 로 해소되고 모달이 닫힌다(#33).
        s = selftest_result["sheet_gate"]
        assert s["cancelled"] is None, f"취소가 null(중단)로 해소 안 됨: {s.get('cancelled')!r}"
        assert s["closed_after"] is True, "취소 후 시트 모달이 닫히지 않았습니다(#33)."

    def test_responsive_shell_keeps_all_tabs_reachable_at_min_width(
        self, selftest_result: dict
    ) -> None:
        # 최소폭(760<820 경계)에서 토바가 축약된다: 도구 값 라벨은 접히고 탭은 전부 남으며
        # 가로 오버플로가 없다 — 좁은 창에서 탭이 잘려 화면에 못 가는 것이 상단 셸의 진짜
        # 회귀다(F2 PR-B, 지도 §10.9 4계약면 4행). 접힘의 축은 종전 브랜드 워드마크였는데
        # 그 표면이 U4 §2-33 에서 사라져 같은 미디어 쿼리의 값 라벨이 승계했다.
        narrow = selftest_result["grid_narrow"]
        assert narrow["tabs"] == len(NAV_SCREENS), f"최소폭에서 탭이 사라짐: {narrow!r}"
        assert narrow["tool_labels_visible"] is False, (
            f"최소폭에서 도구 값 라벨이 안 접힘: {narrow!r}"
        )
        assert narrow["overflow"] is False, f"최소폭에서 가로 오버플로: {narrow!r}"

    def test_responsive_shell_expands_topbar_when_wide(self, selftest_result: dict) -> None:
        # 넓힐 때(경계 위) 값 라벨이 돌아오고 .app 은 여전히 2행(토바+스테이지)이다 —
        # 축약이 눌러앉아 상시 접힘이 되는 회귀 가드(#27 승계).
        wide = selftest_result["grid_wide"]
        assert wide["rows"] == 2, f"넓은 폭에서 .app 이 토바+스테이지 2행이 아님: {wide!r}"
        assert wide["tool_labels_visible"] is True, (
            f"넓은 폭에서 도구 값 라벨이 안 펴짐: {wide!r}"
        )
        assert wide["tabs"] == len(NAV_SCREENS) and wide["overflow"] is False, (
            f"넓은 폭 셸 이상: {wide!r}"
        )

    def test_preserve_restores_focus_and_caret_across_rerender(self, selftest_result: dict) -> None:
        # Preserve 헬퍼가 innerHTML 재구성을 가로질러 포커스와 캐럿/선택 범위를 복원한다(#28).
        p = selftest_result["preserve"]
        assert p["focus_id"] == "preserveProbeInput", f"재구성 뒤 포커스 유실: {p['focus_id']!r}"
        assert (p["sel_start"], p["sel_end"]) == (2, 4), f"캐럿/선택 범위 유실: {p!r}"

    def test_preserve_restores_scroll_across_rerender(self, selftest_result: dict) -> None:
        # 옵트인(data-preserve-scroll) 컨테이너의 스크롤 위치가 재구성을 가로질러 유지된다(#28).
        p = selftest_result["preserve"]
        assert p["scroll_top"] == 120, f"옵트인 스크롤 위치 유실: {p['scroll_top']!r}"

    def test_real_screen_renders_survive_rerender(self, selftest_result: dict) -> None:
        # 2개 실화면(「기안」 사망 — F6 PR-B)이 shipped __push 경로로 실 스냅샷을 재렌더해도
        # 던지지 않는다 — Preserve.around 래핑이 실 render() 를 깨지 않음을 실 DOM 에서 가드한다.
        p = selftest_result["preserve_real"]
        for scr in ("editor", "job"):
            assert p.get(scr) == "ok", f"{scr} 실화면 재렌더 실패: {p.get(scr)!r}"

    def test_real_screen_scroll_preserved_end_to_end(self, selftest_result: dict) -> None:
        # 실 편집기 본문(#editor-body, data-preserve-scroll)의 스크롤이 실 재렌더를 가로질러
        # 유지된다(#28) — 구 「기안」 토큰 패널 프로브의 승계(F6 PR-B). 합성 픽스처가 아닌
        # shipped render() 경로의 end-to-end 보존 검증. 보존 없으면 재구성이 0 으로 리셋하므로,
        # 설정값 60 근처(DPI 서브픽셀 스냅 허용 ±2)면 복원된 것.
        p = selftest_result["preserve_real"]
        top = p["editor_scroll_top"]
        assert isinstance(top, (int, float)) and abs(top - 60) < 2, (
            f"실화면 스크롤 유실(재구성이 0 으로 리셋됐거나 예외): {top!r}"
        )

    # (test_draft_expansion_sheets_move_and_restore_live_dom 삭제 — draft_sheets 프로브가
    #  「기안」 화면과 함께 걷혔다, F6 PR-B. 펼침 면 실 DOM 이동/복귀의 생존 판은
    #  job(dataSheet·jobConfirmSheet) 프로브·정적 계약이 진다.)

    def test_job_danger_banner_host_stands_without_a_summary_line(
        self, selftest_result: dict
    ) -> None:
        # 존 재편 — 구 「본문 확인」 존의 요약 한 줄(빈 값 필드·이름 건수)은 바로 위
        # 사전검증이 이미 말하는 사실의 **두 번째 발화**라 걷혔고, 남은 것은 행동을 든
        # danger 배너 host 하나다. 사라지는 변경이라 음성 단언이 진다(되살아나면 빨강),
        # 그리고 host 자신은 사전검증 **바로 뒤**에 살아 있어야 한다(양성 한 쌍).
        j = probe(selftest_result, "job_mirror")
        assert j.get("error") is None, f"위험 배너 프로브 예외: {j.get('error')!r}"
        assert j["mirror_host_present"] is True, "위험 배너 host(#jobMirror)가 없습니다."
        assert j["mirror_follows_preflight"] is True, (
            "위험 배너가 사전검증 바로 아래가 아닙니다 — 사유와 복구 동사가 갈립니다."
        )
        assert j["mirror_line_gone"] is True, (
            "철거된 본문 확인 요약 한 줄이 되살아났습니다 — 사전검증과 같은 사실의 2중 발화."
        )
        assert j["restate_gone"] is True, (
            "철거된 재진술 블록(#jobRestate)이 되살아났습니다 — 선택 수치의 3중 발화."
        )
        assert j["mirror_preview_exit_gone"] is True, (
            "철거된 확인 면 출구(#jobMirrorPreviewOpen)가 아직 렌더됩니다(#957)."
        )
        assert j["mirror_review_flag_gone"] is True, (
            "철거된 「승인 필요」 표지(#jobReviewFlag)가 아직 렌더됩니다(#957)."
        )
        # 정상 지형(danger 없음)에서는 배너 자리가 비어 있다 — 경보 인플레 금지(#364).
        assert j["mirror_banner_empty"] is True, "위험 없는 상태에서 배너가 서 있습니다."

    def test_job_result_three_state_zone_behaves(self, selftest_result: dict) -> None:
        """결과 3태 구획(F4, 지도 §10.10) — 태·증거·강등·잠금·닫기 착지의 실 WebView2 되읽기.

        정적 계약은 조각의 존재만 본다. 여기서 잡는 것은 **경로가 이어지는가**다(§10.9.5):
        증거를 열어 둔 채 스냅샷이 밀려와도 닫히지 않는지, 지문이 갈릴 때 결과가 지워지지
        않고 강등되는지, 실행 전 거절이 결과 자리를 비워 두지 않는지.
        """
        j = selftest_result["job_result"]
        assert j.get("error") is None, f"결과 3태 프로브 예외: {j.get('error')!r}"
        # ① 태는 Python 판정 그대로, 색은 별도 채널(level) — 둘을 한 축으로 접지 않는다.
        assert j["shown"] and j["state"] == "partiallyCompleted", j
        assert j["level"] == "danger" and "2개 성공" in j["title"], j
        # ② 실패 행 = 원본 index 앵커 + 식별 요약, 모르는 원인엔 미연결 표지.
        assert j["fail_row"] and j["fail_identity"] and j["undiagnosed"], j
        assert j["failed_sel_shown"] and "1건만 선택" in j["failed_sel_label"], j
        # 행 0개·전량 실패(배치 진입 전)에서도 복구 행동은 남는다 — 노출을 행 목록에서
        # 파생하면 그 런에서만 통째로 사라진다(1R P2). 대신 없는 행을 지어내지도 않는다.
        assert j["rowless_recovery_shown"] and "3건만 선택" in j["rowless_recovery_label"], j
        assert j["rowless_no_fake_rows"], j
        # ③ 증거는 접혀 서고, 연 뒤에는 재렌더를 건너 열린 채 남는다(계약면 1).
        assert j["evidence_shown"] and j["evidence_open_survives_rerender"], j
        # ④ 지문 변화의 처분은 성분별 2분기다(U2 §2.18) — 강등 표기 자체의 생존 판.
        assert j["stale_shown"] and j["alive_after_stale"], j
        # ⑤ 구획 행동은 생성 중 잠긴다(계약면 2) · ⑥ 닫기 뒤 포커스가 다음 행동에 착지.
        # 이름만 바뀐 경우는 **같은 작업**이라 결과가 살고 행동이 그대로 남는다(3R P2 ·
        # §2.18 — 주체가 이름을 추종하므로 개명은 전환이 아니다).
        assert j["renamed_keeps_result"], j
        assert j["renamed_rename_shown"] and j["renamed_failedsel_shown"], j
        # 작업 전환 = **초기화**(§2.18) — 링1 이 증거를 죽인 축이라 존이 닫힌다.
        assert j["switch_resets_result"], j
        # 선택 변경 = **강등 유지**(§2.18) — 「실패한 N건만 선택」이 자기 결과를 없애면 안 된다.
        assert j["selection_change_keeps_result"] and j["selection_change_demotes"], j
        # 데이터 교체 = **초기화**. 교체 판정은 **마운트 세대**가
        # 지고 표시 라벨은 그대로다(#363 리뷰 P2) — 같은 basename 의 다른 파일·같은
        # 통합문서의 다른 시트·같은 경로 재읽기가 라벨로는 구별되지 않기 때문이다.
        assert j["data_swap_label_unchanged"], "프로브가 라벨을 바꿔 정체 축을 안 재고 있습니다."
        assert j["data_swap_resets_result"], j
        # 강등 렌더러의 주체 방어(3R P2)는 남는다 — 푸시 없이 결과가 재수립되는 방어 경로에서
        # 남의 작업을 겨누는 버튼이 서지 않는다. 증거는 남는다.
        assert j["foreign_rename_hidden"] and j["foreign_failedsel_hidden"], j
        assert j["foreign_evidence_alive"] and j["foreign_stale_names_owner"], j
        assert j["busy_lock_declared"], j
        # 저장 폴더 줄의 숨김은 계산 스타일로 확인한다(display:flex 가 [hidden] 을 이기는
        # 결함 클래스 — 속성만 보는 계약은 이 결함을 통과시킨다).
        assert j["folder_hidden_while_running"] and j["folder_shown_on_result"], j
        # 닫기 뒤 포커스는 **실 DOM 에 착지**한다 — body 낙하가 결함이다. 게이트가 닫혀
        # 있으면 생성 버튼이 disabled 라 구획 자신이 받는다(방금 있던 문맥 유지).
        assert j["closed"] and j["close_focus"] in {"jobGenBtn", "jobResultZone"}, j
        # 실행 기록 상자는 퇴역했다(#957) — 결과 존 아래에 그 자리가 **없다**.
        assert j["runlog_absent"], j
        # ⑦ 실행 전 거절은 3태가 아니라 rejected 태 — 눌렀는데 아무 일도 없는 것으로 읽히지 않게.
        # 실패 시 판별 증거만 좁혀 보인다(전체 dict 는 pytest 가 자른다 — 판독 불능 덤프 금지).
        if not (j["reject_state"] == "rejected" and "최소 1건" in j["reject_text"]):
            print("REJECT_EVIDENCE_BEGIN")
            for k in (
                "reject_state",
                "reject_text",
                "reject_gen",
                "reject_hidden",
                "reject_pushes",
                "reject_btn_disabled",
                "reject_unhandled",
                "reject_dispatches",
                "reject_btn_label",
                "reject_run_action",
                "reject_alerts",
                "refusal_alerts",
            ):
                print(f"  {k} = {j.get(k)!r}")
            print("REJECT_EVIDENCE_END")
        # 누를 수 있는 상태가 아니었으면 아래 단언들은 전부 공허하다 — 먼저 그것부터 센다.
        assert j["reject_btn_disabled"] is False, (
            "생성 버튼이 잠긴 채였습니다 — 클릭이 핸들러에 닿지 않아 이후 단언이 공허합니다."
        )
        # 대역 문안은 살아 있는 실행 백스톱(`validate_generate`)이다 — 종전의 blank_set
        # 검토 게이트 문형은 #957 에서 죽었다(빈 값은 표식으로 나가고 막지 않는다).
        assert j["reject_state"] == "rejected" and "최소 1건" in j["reject_text"], (
            j["reject_state"],
            j["reject_text"],
        )
        # ⑧ 착지 재라우팅(#957) — 거절은 결과 구획 하나가 앉히므로 알림은 0 이고, 구획이
        # 말할 자리가 없는 거절(0건 재선택)은 알림 채널로 나간다. 두 극을 함께 잰다:
        # 위가 깨지면 재진술이 두 벌, 아래가 깨지면 조용한 거절이다.
        assert j["reject_alerts"] == 0, j
        assert len(j["refusal_alerts"]) == 1, j
        assert "다시 만들 실패 건이 남아 있지 않습니다" in j["refusal_alerts"][0], j

    def test_job_result_lists_documents_and_opens_the_artifact_sheet(
        self, selftest_result: dict
    ) -> None:
        """결과 존 문서 목록 + 산출물 관찰 시트(S7-03 · #825)의 실 WebView2 되읽기.

        **새 콜드 부팅은 0** 이다 — 위 결과 3태 프로브가 이미 세운 창의 증거에 붙은 하위
        필드를 읽는다. 정적 계약은 조각의 존재만 보고, 여기서 잡는 것은 ①행이 실제로
        **그려지는가**(hidden 요소 click 함정 회피 — `offsetParent`) ②「내용 보기」가 실제로
        백엔드를 쏘고 면이 뜨는가 ③관찰이 서지 않은 두 상태가 **다른 문안**을 받는가다.
        """
        j = selftest_result["job_result"]
        assert j.get("error") is None, f"결과 3태 프로브 예외: {j.get('error')!r}"
        a = j["artifact"]
        # ① 문서 목록 — 결과 dict 의 `delivered` 만큼 행이 서고 실제로 보인다.
        assert a["docs_shown"] and a["docs_rows"] == 2, a
        assert a["doc_visible"], "문서 행이 DOM 에는 있는데 그려지지 않았습니다."
        assert "공고서-001.hwpx" in a["doc_text"] and "새 파일" in a["doc_text"], a
        # 경로 어포던스는 공용 `path_actions` 재사용이다 — 열기는 걷고 둘만 남는다.
        assert a["doc_track_acts"] == ["reveal", "copy"], a
        # ② 「내용 보기」 — 눌린 버튼이 보이는 상태였고, 발신이 실제로 났고, 면이 떴다.
        assert a["open_btn_visible"], "「내용 보기」가 hidden 인 채 눌렸습니다(단언 공허)."
        assert "job/artifact_open" in a["open_dispatches"], a
        assert a["sheet_shown"], "산출물 관찰 시트가 DOM 에만 있고 그려지지 않았습니다."
        # ③ 관찰이 서지 않은 상태 = 조용한 빈 화면이 아니라 사유를 말하는 면이다.
        assert a["absent_title"] not in ("", "(자리 없음)"), a
        assert a["absent_save_disabled"], (
            "관찰이 서지 않았는데 저장 버튼이 살아 있습니다 — 원료 없는 저장의 미끼입니다."
        )
        # 무결성 실패와 준비 안 됨은 **다른 문장**이다(#775 교훈 · #820 §3).
        assert a["mismatch_differs_from_absent"], (a["absent_title"], a["mismatch_title"])
        assert "안착 기록과 다르다" in a["mismatch_detail"], a
        # ④ 관찰이 선 판 — 문단·병합 표·빈 값 표식·「표시하지 못한 구간」이 함께 선다.
        assert "계약 상대자 귀하" in a["observed_paragraph"], a
        assert a["observed_colspan"] == 2, "표 병합 메타가 colspan 으로 서지 않았습니다."
        assert "추정가격" in a["observed_markers"], a
        assert a["observed_save_enabled"], a
        # 부분 포섭은 숨기지 않고 **병기**한다(#820 D3) — 사유와 구간이 실제로 그려진다.
        assert a["unrendered_partial"] == "true" and a["unrendered_shown"], a
        assert "mystery" in a["unrendered_text"], a
        # ⑤ 닫기 — 면이 걷히고 초점이 그 행의 트리거로 돌아온다(runJobMirror 관용구).
        # 「닫혔다」는 **안 보인다**이지 DOM 소멸이 아니다(portal 내용은 마운트된 채다).
        assert a["sheet_closed"] and a["sheet_host_hidden"], a
        assert "job/artifact_close" in a["close_dispatches"], a
        assert a["close_focus_target_state"] == "ready", a

    def test_job_data_first_prework_surface(self, selftest_result: dict) -> None:
        # 데이터-우선(§18.2) — 작업 미선택+데이터 마운트 상태에서 세션 존·액션바가 살아 있고,
        # 후보 카드(available=클릭형·needs_action=정직한 비활성+없는 열 병기)와 prework 게이트
        # 문안, 표시순(sourceDesc — 최신 행 먼저) 테이블이 실 WebView2 에 그려지는지 되읽는다.
        j = selftest_result["job_data_first"]
        assert j.get("error") is None, f"data-first 프로브 예외: {j.get('error')!r}"
        assert j["zones_shown"] and j["actionbar_shown"], "무작업 상태에서 세션 존이 죽어 있습니다."
        # 액션바는 좌 열의 오른쪽 끝(구분선)에 맞춰 선다(U2 §2.2 · 리뷰 R5) — 같은 템플릿을
        # 공유해도 **재는 상자**가 다르면 어긋나므로 실 좌표로 잰다.
        assert j["actionbar_plane"] is not None, "액션바·구분선을 못 찾았습니다 — 프로브 겨눔 소실."
        assert abs(j["actionbar_plane"]) <= 1, (
            f"액션바에서 **눈에 보이는 마지막 것**이 구분선에서 {j['actionbar_plane']}px "
            "어긋났습니다 — 기준면 불일치(행의 상자가 아니라 보이는 끝이 기준이다)."
        )
        # 게이트 문안이 빈 상태(=생성이 열린 화면)에서도 같다 — 빈 문안이 자리를 안 비우면
        # 그 앞 gap 이 살아 마지막 버튼만 물러선다(실측 12px).
        assert abs(j["actionbar_plane_empty_note"]) <= 1, (
            f"빈 게이트 문안이 자리를 차지해 버튼이 {j['actionbar_plane_empty_note']}px "
            "물러섰습니다 — 폭 0 이어도 flex 항목이면 앞의 gap 이 남습니다."
        )
        # 표 머리 줄의 ⤢ 는 오른쪽 끝이다(리뷰 R5 의 결함류 그대로) — 규칙은 둘 다 살아 있고
        # **어느 쪽이 이기는가**만 갈리는 자리라 정적 검사가 못 본다. 겨눔은 U4 10번에서
        # 「현재 데이터」 캡션에서 표 머리(`#jobRecsHead`)로 옮겨왔다: 지키는 사실은 클래스
        # 이름이 아니라 「행동이 그 줄의 오른쪽 끝에 선다」이고, 그 줄이 바뀐 것뿐이다.
        cap = j["cap_actions"]
        assert cap, "표 머리 줄의 ⤢ 를 찾지 못했습니다 — 프로브 겨눔 소실."
        assert cap["display"] == "flex", (
            f"표 머리 줄이 flex 를 잃었습니다({cap['display']!r}) — 곁의 규칙이 덮었습니다."
        )
        assert abs(cap["far_edge"]) <= 1, (
            f"⤢ 가 표 머리 줄 오른쪽 끝에서 {cap['far_edge']}px 물러섰습니다."
        )
        assert j["cands_row_shown"] and j["cand_buttons"] == 2, j
        # 확인 필요·순위 밖은 후보 줄에서 수치 + 출구로만 말한다(슬라이스 3 구획 이사).
        assert j["cand_exit"] is True, "문서 탐색 출구가 후보 줄에 없습니다."
        assert j["cand_disabled_chips"] == 0, "확인 필요 비활성 칩이 후보 줄에 남아 있습니다."
        assert "2건" in j["cand_more_text"] and "1건" in j["cand_more_text"], j["cand_more_text"]
        assert "문서 작업을 선택하세요" in j["gate_text"], j["gate_text"]
        assert j["gen_disabled"] is True, "prework 상태에서 생성 버튼이 열려 있습니다."
        # 「선택한 작업」 존 사망(U2 §4, #342) — 작업 미선택이면 액션바 이름이 비고 자리를
        # 접는다(게이트 문안이 다음 할 일을 말한다). 정체 표시 실렌더는 job_active_card 소관.
        assert j["action_name_empty"] is True, "작업 미선택인데 액션바가 이름을 말합니다."
        assert j["tbl_rows_order"] == ["1", "0"], (
            f"표시순(최신 먼저)이 아닙니다: {j['tbl_rows_order']!r}"
        )
        # 곁에 섰던 두 단언은 죽었다: 「저장 폴더 선택 비활성」은 저장 폴더가 전역 설정이
        # 되면서(이 화면에 고르는 동사가 없다), 「prework 재진술 숨김」(#302 리뷰 P2)은
        # 재진술 블록 자체가 존 재편에서 걷히면서 — 부재는 job_mirror 가 한 번만 잰다.

    def test_job_candidate_ranking_renders_stars_suggestion_and_overflow(
        self, selftest_result: dict
    ) -> None:
        # 슬라이스 2 — 메인 순위 카드가 실 WebView2 에서 되읽힌다: Python 이 준 순서 그대로,
        # 별은 스냅샷 상태를 반영(낙관 토글 아님), 추천은 점선(활성과 구별되는 표지),
        # 잘린 나머지는 수치로 고지(조용한 절단 금지), 최근 사용은 날짜만.
        j = selftest_result["job_data_first"]
        assert j.get("error") is None, f"data-first 프로브 예외: {j.get('error')!r}"
        assert j["cand_order"] == ["공고서", "계약서"], j["cand_order"]
        assert j["fav_pressed"] == ["true", "false"], j["fav_pressed"]
        assert j["suggested_marks"] == 1, "추천 표지가 렌더되지 않았습니다."
        assert j["suggested_dashed"] == "dashed", j["suggested_dashed"]
        assert "2건" in j["more_text"], f"「외 N건」 고지가 없습니다: {j['more_text']!r}"
        # 후보 카드는 「이 데이터로 무엇을 만들 수 있는가」만 말한다(U4 §2-31) — 실행 이력
        # 문구는 걷혔다. 매체별 문안 자체는 라이브러리 목록이 계속 쓴다.
        assert "last_run_text" not in j, (
            f"후보 카드에 실행 이력 문구가 남아 있습니다: {j.get('last_run_text')!r}"
        )
        # 방식 구획(§19.3, F6) — 두 방식이 섞인 판이라 머리글이 **선다**. 카드 부제의
        # 방식 텍스트는 구획과 별개로 늘 남는다(색만으로 방식을 구별하지 않는다).
        assert j["cand_sec_caps"] == ["HWPX 문서 생성", "온나라 기안 검토·복사"], (
            f"작업 방식 구획 머리글이 서지 않았습니다: {j['cand_sec_caps']!r}"
        )
        assert j["cand_mode_texts"] == ["HWPX 생성", "온나라 기안"], j["cand_mode_texts"]
        # 별을 누르면 카드가 1순위로 이동한다 — 그 재렌더를 가로질러 포커스가 같은 작업의
        # 별에 남아야 키보드 사용자가 문서 처음으로 떨어지지 않는다(이름 유래 안정 id).
        assert j["fav_focus_restored"] == "kept", j["fav_focus_restored"]
        # 왕복 중 두 번째 클릭은 의도를 뒤집고(첫 카드는 이미 즐겨찾기 → false, true),
        # **앞 왕복이 끝나기 전에는 보내지 않는다**(클릭 순서 = 쓰기 순서, 4R P2).
        assert j["fav_sync_sends"] == 0, j["fav_sync_sends"]  # 클릭 = 체인 진입
        assert j["fav_intents"] == "[]", j["fav_intents"]
        assert json.loads(j["fav_chain"])["inflight"] == 1, j["fav_chain"]  # 둘째 대기
        # 발신열 = ① 첫 카드(즐겨찾기 상태) 두 번 = false,true — 클릭 순서 = 쓰기 순서,
        # ② 둘째 카드(미즐겨찾기) 3연속 = true,false,true 뒤 **첫 왕복만 실패로 완료**된
        # 상태의 4번째 클릭 = false. 정리를 값 비교로 하면 최신 의도가 지워져 여기서
        # true 가 나오고(=껐다가 다시 켜짐) 사용자 의도가 소실된다(5R P2).
        assert json.loads(j["fav_order"]) == [False, True, True, False, True, False], j["fav_order"]
        # 실패한 왕복의 거절은 **알림 채널**로 간다(#957 — 실행 기록 상자 퇴역). 조용히
        # 삼키면 별만 되돌아오고 왜 안 됐는지는 어디에도 없다.
        refusals = json.loads(j["fav_refusal_alerts"])
        assert refusals and all("실패 시늉" in line for line in refusals), refusals

    def test_job_document_browser_sheet_renders_tabs_rows_and_reasons(
        self, selftest_result: dict
    ) -> None:
        # 문서 탐색 면(§18.6·§19.5) — 후보 줄 출구로 실제로 열리고, 탭 라벨(검색 전 건수)·
        # 확인 필요 행의 막힌 열·검색으로 걸러낸 수 고지가 실 WebView2 에 그려진다.
        # 포커스는 검색 입력(이 표면에 온 이유가 찾기)이고 닫기로 닫힌다.
        j = selftest_result["job_data_first"]
        assert j.get("error") is None, f"data-first 프로브 예외: {j.get('error')!r}"
        assert j["browse_open"] is True, j["browse_open"]
        assert j["browse_tabs"] == ["사용 가능 7/false", "확인 필요 1/true"], j["browse_tabs"]
        assert len(j["browse_rows"]) == 1, j["browse_rows"]
        row = j["browse_rows"][0]  # flex gap 이라 textContent 에는 공백이 없다
        assert row.startswith("견적서") and "없는 열: 담당자" in row, row
        assert "2건" in j["browse_note"], j["browse_note"]
        assert j["browse_focus_is_query"] is True, "탐색 면 초기 포커스가 검색 입력이 아닙니다."
        # 왕복 경합(4R P2): 타이핑 중 도착한 옛 스냅샷은 입력을 덮지 않고, 포커스가 떠난
        # 뒤에는 서버 값으로 확정된다(데이터 존 검색과 같은 규칙).
        assert j["browse_query_kept"] == "견적요청", j["browse_query_kept"]
        assert j["browse_query_node_stable"] is True
        assert j["browse_query_node_connected"] is True
        assert j["browse_query_focus_stable"] is True
        assert j["browse_query_focus_left"] is True
        assert j["browse_query_settled"] == "견적", (
            f"value={j['browse_query_settled']!r}, stable={j.get('browse_query_node_stable')!r}, "
            f"connected={j.get('browse_query_node_connected')!r}, "
            f"focused={j.get('browse_query_focus_stable')!r}"
        )
        # 탭 전환은 재렌더다 — 안정 id 가 없으면 포커스가 열린 모달 밖으로 떨어진다(1R P2).
        assert j["browse_tab_focus"] == "jobBrowseTab-available", j["browse_tab_focus"]
        # 행을 고르면 **성사 뒤에** 면이 닫히고(가드 취소·거절에서 문맥 보존, 2R P2)
        # 포커스는 방금 고른 작업 카드에 착지한다(모달 복귀 트리거는 재렌더로 해제됨).
        assert j["browse_sheet_closed"] is True, "선택 성사 뒤 면이 닫히지 않았습니다."
        # 단순 닫기에서도 포커스는 페이지로 돌아온다(6R P2) — 면 안 재렌더로 끊긴 노드가
        # 아니라 **닫히는 시점의 출구**를 다시 찾아 세운다.
        assert j["browse_close_focus"] == "jobBrowseOpen", j["browse_close_focus"]
        assert j["browse_pick_focus"] == "jobCand-" + quote("공고서"), j["browse_pick_focus"]
        # 취소(그냥 닫기)는 고른 작업 카드가 아니라 **다시 열 출구**로 돌려보낸다.

    def test_job_active_card_succeeds_the_dead_active_zone(self, selftest_result: dict) -> None:
        # U2 §4(#342) — 「선택한 작업」 존 사망의 승계처 실렌더 되읽기: ①액션바가 활성 작업
        # 이름을 말하고 ②활성 카드에만 확장 부제(템플릿 파일명)·⋮ 가 서며 ③⋮ 부유 메뉴의
        # 두 항목(열기·폴더에서 보기)이 실제로 그 템플릿 경로를 겨누고 ④경고 카드는 「연결
        # 상태」 텍스트가 정본이고 ⑤경고 카드 클릭은 **선택이 아니다**(안내 다이얼로그 —
        # 취소하면 발신 0건).
        j = selftest_result["job_active_card"]
        assert j.get("error") is None, f"활성 카드 프로브 예외: {j.get('error')!r}"
        assert j["action_name"] == "공고서", j["action_name"]
        assert j["active_tpl"] == "공고서.hwpx", j["active_tpl"]
        assert j["menu_btn_in_active"] is True, "활성 카드에 ⋮ 가 없습니다."
        assert j["menu_btn_count"] == 1, f"⋮ 는 활성 카드에만 선다(판정 B): {j['menu_btn_count']!r}"
        assert j["menu_open"] is True and j["menu_closed"] is True, j
        assert j["menu_items"] == [
            "open:C:\\t\\공고서.hwpx:열기",
            "reveal:C:\\t\\공고서.hwpx:폴더에서 보기",
        ], j["menu_items"]
        assert j["warn_conn"] == "템플릿 없음", j["warn_conn"]
        # 도달 보장 축(#342 3R) — 정상 상태에선 조용하고, 데이터 미마운트로 후보 구획이
        # 통째로 숨어도(카드 0장) 액션바가 연결 상태·재연결을 **실제로 보이게** 세운다.
        # 세 라운드의 결함이 전부 "구획이 없으면 도달도 없다"였다.
        assert j["conn_quiet_when_ok"] is True, "정상 상태에서 연결 상태 경보가 떠 있습니다."
        assert j["cands_hidden_when_no_data"] is True and j["cand_cards_when_no_data"] == 0, j
        assert j["conn_text_no_data"] == "템플릿 없음", j["conn_text_no_data"]
        assert j["relink_visible_no_data"] is True, (
            "후보 구획이 숨은 상태에서 재연결 어포던스가 화면에 없습니다 — 도달 보장 소멸."
        )
        assert j["warn_redirect_modal"] is True, (
            "경고 카드 클릭이 안내 다이얼로그를 열지 않았습니다."
        )
        assert "선택" in j["warn_modal_body"] and "다시 연결" in j["warn_modal_body"], j[
            "warn_modal_body"
        ]
        assert json.loads(j["warn_click_sends"]) == [], (
            f"경고 카드 클릭이 발신을 만들었습니다(선택이 아니어야 합니다): {j['warn_click_sends']!r}"
        )

    def test_job_density_and_expansion_sheets(self, selftest_result: dict) -> None:
        j = probe(selftest_result, "job_mirror")
        assert j.get("error") is None, j
        # 편집기는 자기 화면으로 **덮는다**(재작성 F7). 종전 이 자리는 확인 면을 열어 둔 채
        # 그 전환을 쟀는데, 그 면이 #957 에서 철거돼 남는 것은 전환 자체다(펼침 면 일괄
        # 회수는 `sheet_gate`·`modal_a11y` 가 진다).
        assert j["edit_takes_over_screen"], (
            f"편집기 진입이 화면을 덮지 못했습니다 (창에 끼어든 push: {j.get('mirror_pushes')!r})"
        )
        # ⤢ 데이터 면은 별도 비동기 프로브(열기가 Python 왕복 뒤 — F3): 이동·헤더 고정·복귀
        # (포커스 포함)에 더해 범위 편집기 footer 가 **면 안에서만** 서는 것까지 본다.
        d = selftest_result["data_sheet"]
        assert d.get("error") is None, d
        assert d["moved"] and d["first_sticky"] and d["restored"], d
        assert d["foot_shown_in_sheet"] is True, "범위 편집기 footer 가 면 안에서 안 섭니다."
        assert len(j["job_grid_wide"].split()) == 2, j
        narrow = selftest_result["job_density_narrow"]
        assert narrow["panel"] <= 900, (
            f"협폭 프로브가 분기 폭(container 900px)을 안 밟았습니다: {narrow!r}"
        )
        assert len(narrow["columns"].split()) == 1

    # (test_job_restate_block_keeps_counts_and_loses_names 삭제 — 그 블록이 말하던 세 가지는
    #  표 머리·배달 계획·저장 폴더 표시 줄이 이미 말하던 사실이라 존 재편에서 걷혔다. 부재
    #  단언은 test_job_danger_banner_host_stands_without_a_summary_line 이 진다.)

    def test_job_filter_surface_renders_table_chips_strip(self, selftest_result: dict) -> None:
        # 필터 표면 — 합성 필터 스냅샷이 실 WebView2 에서:
        # 가시 1행 테이블 + <mark> 하이라이트(Python 세그먼트를 그대로 칠함) + 열 머리 필터
        # 아이콘 + 칩 줄(정의 재진술)·가지 ×(프루닝) + 필터 밖 선택 스트립(결정 3) + 선택
        # 유래 수치 병기(S4)로 되읽힌다.
        j = probe(selftest_result, "job_mirror")
        assert j["tbl_rows"] == 1, f"가시 행 렌더 수가 다릅니다: {j['tbl_rows']!r}"
        assert j["tbl_mark"] == "전산", f"하이라이트 세그먼트 미렌더: {j['tbl_mark']!r}"
        assert j["ficos"] == 2, f"열 머리 필터 아이콘 수가 다릅니다: {j['ficos']!r}"
        assert "「전산」" in j["chips_text"], f"칩 줄 정의 재진술 누락: {j['chips_text']!r}"
        assert j["branch_prune"] is True, "가지 칩 × 프루닝 어포던스가 없습니다."
        assert {"필터", "가지", "선택"} <= set(j["filter_role_labels"])
        assert j["definition_bg"] != j["branch_bg"]
        assert j["branch_border_style"] == "solid", "가지 칩 점선 방언이 남았습니다."
        assert j["strip_shown"] is True, "필터 밖 선택 스트립이 표시되지 않았습니다(결정 3)."
        assert j["strip_bg"] == j["branch_bg"], "가지·관통 스트립의 낮은 표면 위계가 어긋났습니다."
        assert "1행" in j["strip_text"] and "doc-002.hwpx" in j["strip_text"], (
            f"스트립이 필터 밖 선택을 재진술하지 않습니다: {j['strip_text']!r}"
        )
        assert j["strip_unsel"] is True, (
            "스트립에 항목별 × 해제 어포던스가 없습니다 — 필터 밖 선택을 개별로 뺄 수 없다."
        )
        # 선택 유래 수치(정의 매치/정의 밖)를 화면에 상시로 병기하던 재진술 블록은 존
        # 재편에서 죽었다 — 그 수치를 정말 다시 물어야 하는 자리는 선택을 파기하는 전이의
        # 확인 모달 하나이고, 그 문안은 아래 `guard_body` 가 되읽는다.

    def test_job_datazone_keeps_row_semantics_and_column_kinds(self, selftest_result: dict) -> None:
        """H-06: native 행/셀 의미와 Python 열 kind가 실 표 조판까지 도달한다."""
        j = probe(selftest_result, "job_mirror")
        assert j["row_role"] is None, "tr에 checkbox role이 남아 native row 의미를 덮었습니다."
        assert j["row_selected"] == "true"
        assert j["row_checkbox"] is True
        assert j["row_doccell_display"] == "flex", (
            "table-cell 대신 내부 래퍼가 flex를 소유해야 합니다."
        )
        # U4 8번 — 이름·요약이 표에서 사라졌다(사용자 확정: 그 이름은 쓸모 있는 정보가 아니다).
        # 사라지는 변경이라 **음성 단언**이 진다: 되살아나면 여기가 빨강이다.
        assert j["doccol_row_names"] == 0, "「문서」 열의 이름·요약이 표에 되살아났습니다."
        assert j["head_doccol_text"] == "", "선택 열 머리에 텍스트가 남았습니다."
        # U4 11번 — 그 자리에 온 것은 선택 동사다(자리는 바뀌어도 id 는 같다).
        assert j["head_selall"] is True, "전체 선택 동사가 열 머리에 서지 않았습니다."
        assert j["amount_align"] == "right"
        assert "tabular-nums" in j["amount_nums"]

    def test_job_row_toggle_is_optimistic_and_uses_live_state(self, selftest_result: dict) -> None:
        """I-217 R2: push를 미결로 둬도 표지가 즉시 뒤집히고 재클릭은 현 DOM 상태를 쓴다."""
        j = probe(selftest_result, "job_mirror")
        assert j["row_optimistic_off"] is True, f"첫 행 토글이 즉시 해제 표지를 못 냈습니다: {j!r}"
        assert j["row_optimistic_on"] is True, f"push 전 재클릭이 즉시 재선택되지 않았습니다: {j!r}"
        assert j["row_toggle_values"] == [False, True], (
            f"재클릭 값이 화면의 현재 상태를 따르지 않습니다: {j['row_toggle_values']!r}"
        )

    def test_filter_panel_shell_appears_before_backend_response(
        self, selftest_result: dict
    ) -> None:
        """I-217 R4: filter_panel 응답이 미결이어도 제목+로딩 껍데기는 클릭 프레임에 선다."""
        assert probe(selftest_result, "job_mirror")["panel_shell_immediate"] is True

    def test_job_filename_token_danger_blocks_with_an_exit(self, selftest_result: dict) -> None:
        # #128 — 파일명 토큰 danger 는 드리프트와 **같은 자격**이라 같은 자리에서 차단 배너 +
        # 행동 링크로 선다. 종전엔 거울이 「채움」 표를 그려 문서가 건강해 보이고, 재진술은
        # danger 라 말없이 사라지고, 남는 신호는 하단 회색 캡션 한 줄뿐인 막다른 경보였다.
        j = probe(selftest_result, "job_mirror")
        assert j["token_banner"] is True, "미해소 파일명 토큰에 차단 배너가 서지 않았습니다."
        assert j["token_fix_link"] is True, (
            "배너에 행동 링크가 없습니다 — 막다른 경보 금지(결정 36)."
        )
        assert "납품기한" in j["token_banner_text"], (
            f"배너가 남는 토큰을 재진술하지 않습니다: {j['token_banner_text']!r}"
        )

    def test_job_filter_panel_hidden_beats_flex(self, selftest_result: dict) -> None:
        # 열 필터 패널 기본 닫힘 — [hidden] 이 .colpanel 의 display:flex 를 실제로 이긴다
        # (부록 B-9 overlay/hidden 충돌 결함류의 자동 눈검증 — 시연에서 실증된 그 결함).
        j = probe(selftest_result, "job_mirror")
        assert j["panel_hidden"] is True, (
            "colpanel [hidden] 이 display:flex 에 져서 항시 떠 있습니다."
        )

    def test_job_guard_body_composes_counts_and_losses(self, selftest_result: dict) -> None:
        # 세션 가드 확인 본문(결정 27 종류별 수치 재진술) — 합성 문안을 되읽어
        # 수치 배치·소실 목록(행 선택+필터 정의)이 조용히 드리프트하지 않게 한다(RC-02 짝 동형).
        body = probe(selftest_result, "job_mirror")["guard_body"]
        assert "직접 선택 3행" in body, f"선택 수치 미표기: {body!r}"
        assert "정의 매치 2" in body and "정의 밖 1" in body, f"S4 델타 병기 누락: {body!r}"
        assert "데이터를 바꾸면" in body, f"전이 동사구 누락: {body!r}"
        assert "필터 정의(2개 조건)" in body, f"필터 소실 재진술 누락: {body!r}"
        # 필드축 ack 폐기(U2 §2.13) — 「빈 값 확인 N개」는 존재하지 않는 손실이라
        # 열거하면 가드가 거짓말을 한다(안 걷으면 F1 §10.7.3 감사 위반의 반대 방향).
        assert "빈 값 확인" not in body, f"폐기된 ack 손실을 열거합니다: {body!r}"
        # 필터 정의는 직전 슬롯에 남지만 **소스 일치**를 요구한다 — 조건을 함께 말한다.
        assert "직전 필터 재적용" in body, f"필터 복원 조건 재진술 누락: {body!r}"
        minimal = probe(selftest_result, "job_mirror")["guard_body_minimal"]
        assert "빈 값 확인" not in minimal, f"없는 손실을 열거합니다(과경고): {minimal!r}"
        assert "직전 필터 재적용" not in minimal, (
            f"필터 정의가 없는데 복원 문구가 붙습니다(과경고): {minimal!r}"
        )
        # 데이터 재겨눔 사전 확인은 JS 전용 가드 지점이라 존재 자체를 핀한다.
        assert probe(selftest_result, "job_mirror")["data_guard_wired"] is True, (
            "confirmDataSwapIfArmed 배선이 사라졌습니다 — 데이터 재겨눔 가드(결정 26) 회귀."
        )
        # 직전 필터 재적용 어포던스(결정 28) — 양 분기를 핀해 항상 떠 있는 죽은 버튼을 막는다.
        assert probe(selftest_result, "job_mirror")["reapply_shown"] is True, (
            "reapply_available=true 인데 「직전 필터 재적용」 버튼이 표시되지 않았습니다."
        )
        assert probe(selftest_result, "job_mirror")["reapply_hidden"] is True, (
            "reapply_available=false 인데 「직전 필터 재적용」 버튼이 계속 떠 있습니다."
        )
        # 무엇이 설치되는지 업고 있는가(#127) — 게이트를 3연언으로 좁혀 파괴는 막았지만,
        # 버튼이 여전히 "직전 필터"라고만 말하면 사용자는 누르기 전엔 알 수 없다.
        assert "(공고명) 포함 「전산」" in probe(selftest_result, "job_mirror")["reapply_title"], (
            "「직전 필터 재적용」 버튼이 설치할 정의를 업고 있지 않습니다: "
            f"{selftest_result['job_mirror']['reapply_title']!r}"
        )

    def test_job_opening_marker_and_no_data_exit_are_inherited(self, selftest_result: dict) -> None:
        """좌 목록이 죽으며 넘긴 두 의무를 승계처에서 되읽는다(F2 PR-B, 지도 §10.9).

        ① 「여는 중」 지연 표지(#217 R1) — 좌 목록 행에 있던 계약을 후보 카드가 진다.
           삭제는 의무를 상속한다: 표지가 같이 죽으면 큰 레지스트리에서 클릭이 아무 일도 안
           한 것처럼 보이는 시간이 되돌아온다.
        ② 데이터·작업이 둘 다 없을 때의 흡수처 출구(판정 C) — 데이터 없이 작업을 보는 경로는
           「문서 작업」이 흡수했고, 화면은 그 흡수처를 가리켜야 한다(막다른 화면 금지).
           데이터가 있으면 숨는다(소음 금지).
        """
        j = selftest_result["job_inherited"]
        assert j.get("error") is None, f"승계 어포던스 프로브 예외: {j.get('error')!r}"
        assert j["opening_marker_immediate"] is True, (
            f"후보 카드 클릭에 「여는 중」 표지가 즉시 서지 않습니다: {j!r}"
        )
        assert j["no_data_exit_with_data"] is False, (
            f"데이터가 있는데 흡수처 출구가 떠 있습니다(소음): {j!r}"
        )
        assert j["no_data_exit_shown"] is True and j["no_data_exit_target"] is True, (
            f"데이터·작업이 둘 다 없는데 「문서 작업」 출구가 없습니다: {j!r}"
        )

    # (test_draft_list_groups_render_and_menu · test_milestone_l_draft_density_duo_cap_and_fallback ·
    #  test_draft_session_zones_render 삭제 — draft_list/draft_session/draft_density_narrow
    #  프로브 결과가 「기안」 화면과 함께 걷혔다, F6 PR-B. 좌 목록·그룹 계약의 생존 판은
    #  라이브러리·tpl 프로브가, 세션·복사 계약은 작업대 프로브(test_workbench_*)가 진다.)

    def test_tab_move_autodiscards_without_asking(self, selftest_result: dict) -> None:
        # 확인 모달 전면 제거의 실런타임 가드 — dirty 인 채 탭을 눌러도 **아무것도 묻지 않고**
        # 한 발만 나간다. 음성(모달 미개방) 혼자로는 무동작 프로브와 구분되지 않으므로
        # 양성(발신 1발 + payload 가 `section` 하나)과 함께 센다.
        g = selftest_result["editor_tab_autodiscard"]
        assert g.get("error") is None, f"탭 이동 프로브 예외: {g.get('error')!r}"
        assert g.get("why") == "완료", f"탭 이동 프로브가 완주하지 못했습니다: {g!r}"
        assert g["calls"] == ["goto_section"], (
            "탭 이동이 한 발로 끝나지 않았습니다 — 처분 왕복이 되살아났습니다"
            f"(발신 기록: {g['calls']!r})."
        )
        assert g["payload_keys"] == ["section"], (
            f"이동 payload 에 처분 표지가 실렸습니다: {g['payload_keys']!r}"
        )
        assert g["target_sent"] == "filename", f"누른 탭이 실리지 않았습니다: {g!r}"
        assert g["choose_modal_open"] is False and g["confirm_modal_open"] is False, (
            f"탭 이동이 확인을 물었습니다 — 자동 버리기 계약이 죽었습니다: {g!r}"
        )

    def test_discard_runs_immediately_after_settling_pending_edit(
        self, selftest_result: dict
    ) -> None:
        # 「변경 버리기」는 묻지 않고 즉시 되돌린다. 확인이 사라져도 **정산 선행**은 그대로
        # 계약이다(§2.17 2R P2 의 승계): 큐에 든 `set_name` 이 버리기 뒤에 도착하면 방금
        # 되돌린 세션이 늦은 편집으로 다시 더러워지고, 화면은 버렸다고 말한 것을 그대로
        # 들고 선다. 정적 계약은 못 본다 — **비동기 도착 순서**만 어긋나기 때문이다.
        d = selftest_result["editor_discard_immediate"]
        assert d.get("error") is None, f"버리기 프로브 예외: {d.get('error')!r}"
        assert d.get("why") == "완료", f"버리기가 발신되지 않았습니다: {d!r}"
        assert d["discard_enabled_on_typing"] is True, (
            "타이핑 직후 버리기가 잠긴 채입니다 — 1R 계약(저장과 같은 술어)이 죽었습니다."
        )
        assert d["name_node_stable"] is True
        assert d["name_node_connected"] is True
        assert d["name_focus_stable"] is True
        assert d["confirm_modal_open"] is False, (
            f"버리기가 확인을 물었습니다 — 자동 버리기 계약이 죽었습니다: {d!r}"
        )
        assert d["call_order"] == "set_name,discard_patch", (
            "대기 편집 정산이 버리기 **뒤로** 밀렸습니다 — 늦게 도착한 편집이 되돌린 세션을"
            f" 다시 더럽힙니다(발신 기록: {d['call_order']!r})."
        )
        assert d["flushed_before_discard"] is True
        # 되돌린 스냅샷이 도착하면 이름은 저장본으로 돌아가고 두 행동이 함께 잠긴다.
        assert d["name_value_after_discard"] == "공고서", (
            f"버렸는데 친 값이 그대로 서 있습니다: {d['name_value_after_discard']!r}"
        )
        assert d["discard_disabled_after"] is True and d["save_disabled_after"] is True, (
            f"되돌린 뒤에도 두 행동이 무장한 채입니다 — 버릴 것이 남았다는 뜻입니다: {d!r}"
        )
        assert d["discarded"] is True, "버리기가 발신되지 않았습니다."

    def test_editor_template_tab_renders_txt_band_and_two_txt_tabs(
        self, selftest_result: dict
    ) -> None:
        # F6 PR-B — 「기안」 화면 사망의 TXT 생성 경로 승계처가 실 DOM 에 서는지. 정적
        # 계약은 「배선했지만 영영 안 보이는」 상태를 통과시킨다(F2 PR-B 실증) — 밴드
        # 머리 2종·TXT 선택 버튼·TXT 세션 탭 2개(파일 이름 탭 부재, §3.2)를 실물로 센다.
        b = selftest_result["editor_txt_band"]
        assert b.get("error") is None, f"TXT 밴드 프로브 예외: {b.get('error')!r}"
        assert b.get("why") == "완료", f"TXT 밴드 프로브 미완주: {b!r}"
        # U6-B(#976): 매체 **구획**은 사라졌다 — 한 목록에 서고 매체는 pill 이 가른다.
        # 음성 단언으로 남긴다(되살아나면 두 열 그림이 다시 갈린다).
        assert b["bands"] == [], (
            f"매체 구획 캡션이 되살아났습니다(U6-B 에서 pill 로 대체): {b['bands']!r}"
        )
        assert b["txt_pick"] is True, (
            "TXT 항목(.pitem[data-side=tpl])이 없습니다 — 목록만 있고 생성 경로가 닫혀 있습니다."
        )
        assert b["txt_media_pill"] == "TXT", (
            f"매체를 가르는 pill 이 TXT 를 말하지 않습니다: {b['txt_media_pill']!r}"
        )
        assert b["txt_tabs"] == 2, (
            f"TXT 세션 탭 수가 2가 아닙니다(파일 이름 탭은 HWPX 속성): {b['txt_tabs']!r}"
        )

    def test_txt_authoring_lintpad_mounts_lints_and_yields_escape(
        self, selftest_result: dict
    ) -> None:
        # S10-05 #862 — TXT 저작 표면이 CodeMirror 린트메모장인지, 그 판정이 **Python 왕복**
        # 에서 오는지를 실 WebView2 에서 되읽는다. 정적 계약은 모듈의 존재만 본다: 마운트가
        # 죽어도, 왕복이 죽어 강조가 0 이어도, vendor 키맵이 Escape 를 먹어 이탈 가드가
        # 우회돼도 전부 초록이다(U2 §2.11 표본과 같은 결함류).
        b = selftest_result["editor_txt_band"]
        assert b.get("error") is None, f"TXT 밴드 프로브 예외: {b.get('error')!r}"
        assert b["lintpad_trigger"] is True, "「새 TXT 템플릿…」 진입점이 없습니다."
        assert b["lintpad_mounted"] is True, (
            "TXT 저작 창에 CodeMirror 가 마운트되지 않았습니다(모듈은 있고 화면은 빈 상태)."
        )
        assert b["lintpad_content_editable"] is True, (
            f"#txtEditContent 가 편집 가능한 표면이 아닙니다: {b!r}"
        )
        # 새 생성 창의 첫 초점은 이름 칸이다 — 메모장이 마운트에서 가로채면 초기 초점의
        # 주인이 둘이 되고, 이기는 쪽이 효과 순서에 따라 갈린다.
        assert b["lintpad_focus"] == "txtEditName", (
            f"새 TXT 창의 첫 초점이 이름 칸이 아닙니다: {b['lintpad_focus']!r}"
        )
        assert b["lintpad_focusable"] == "txtEditContent", (
            f"메모장이 초점을 받을 수 있는 표면이 아닙니다: {b['lintpad_focusable']!r}"
        )
        # 양성 대조의 선행 음성 — 늘 켜져 있는 클래스가 초록을 훔치지 못하게.
        assert b["lintpad_marks_before"] == 0, (
            f"본문을 넣기 전부터 강조가 있습니다: {b['lintpad_marks_before']!r}"
        )
        assert b["lintpad_lint_arrived"] is True, (
            "본문을 넣었는데 판정이 도착하지 않았습니다 — tpl/txt_lint 왕복이 죽었습니다."
        )
        assert b["lintpad_field_marks"] == 1 and b["lintpad_marker_marks"] == 1, (
            "누름틀·구간 표기 강조가 1:1 로 서지 않습니다"
            f" (필드 {b['lintpad_field_marks']!r} · 마커 {b['lintpad_marker_marks']!r})."
        )
        assert b["lintpad_diag_count"] == 1, (
            f"진단 1건이 그대로 재진술되지 않았습니다: {b['lintpad_diag_count']!r}"
        )
        # 문안은 링0 이 낸 `message` 그대로다 — 표면이 `kind` 로 다시 지으면 여기서 갈린다.
        assert "닫는 마커가 없습니다" in b["lintpad_diag_text"], (
            f"진단 문안이 Python 이 낸 것과 다릅니다: {b['lintpad_diag_text']!r}"
        )
        assert b["lintpad_escape_asks"] is True, (
            "편집기 안의 Escape 가 모달 이탈 가드에 닿지 않았습니다"
            " — vendor 키맵이 먹으면 저장 안 한 저작이 조용히 사라집니다."
        )
        assert b["lintpad_disposed"] is True, (
            "창을 닫았는데 메모장 인스턴스가 남았습니다(다음 열기에서 두 벌이 됩니다)."
        )

    def test_editor_is_immersive_and_carries_its_context(self, selftest_result: dict) -> None:
        # 편집기가 실 WebView2 에서 **자기 화면**으로 서고 상단 2탭을 덮는지, 머리(이름·저장
        # 상태·판본)와 진입 문맥 배너가 실제로 그려지는지 되읽는다. 정적 계약(클래스·문자열
        # 존재)은 「배선했지만 영영 안 보이는」 상태를 통과시킨다 — F2 PR-B 가 같은 자리에서
        # 그 결함을 실물로 확인했다(코덱스 리뷰 P2).
        j = selftest_result["job_editmode"]
        assert j.get("error") is None, f"편집기 프로브 예외: {j.get('error')!r}"
        assert j["editor_screen_on"] and j["job_screen_off"], (
            f"편집기가 자기 화면으로 서지 않습니다(두 화면 동시 표시·미표시): {j!r}"
        )
        assert j["nav_hidden"] is True, (
            "편집 중에 상단 2탭이 살아 있습니다 — 처분 미확정 이탈구가 그대로입니다(F7)."
        )
        assert j["back_shown"] is True, "편집기의 유일한 출구(back)가 보이지 않습니다."
        assert j["wizard_steps"] == 3, f"신규 초안 단계 표지(번호) 수: {j['wizard_steps']!r}"
        assert j["foot_shown_new"] is True, "신규 초안 푸터(뒤로/다음)가 표시되지 않았습니다."
        assert j["edit_tabs"] == 3, f"편집 탭 버튼 수: {j['edit_tabs']!r}"
        assert j["foot_shown_edit"] is True, (
            "편집 탭에서 주 행동 푸터(「변경 저장」)가 보이지 않습니다 — 구판은 저장 분류에만"
            " 푸터가 있어 다른 탭에서는 저장 자체가 도달 불가였다(재작성 F7 판정 E)."
        )
        assert j["edit_dirty_tab_marked"] == 1, (
            "손댄 탭이 표지되지 않습니다 — 어느 자리를 처분해야 하는지 3택 모달 전에 보여야"
            f" 한다(§5.2): {j['edit_dirty_tab_marked']!r}"
        )
        # 3R P2 — 손댄 세션을 「저장됨」이라 말하면서 제자리 되돌리기도 없던 자리.
        assert "저장하지 않은 변경" in j["dirty_head"], (
            f"손댄 세션의 머리가 저장됐다고 말합니다: {j['dirty_head']!r}"
        )
        # U2 §2.17 — 버리기는 상시 표시 + 상태 비활성. 존재 단언(dirty_discard_shown)은 상시
        # 표시 승격의 순간 무엇을 밀어 넣어도 참이 되므로, clean/dirty 두 값으로 비활성을
        # 각각 재고 저장이 같은 술어를 쓰는지도 본다(양성·음성 대조 — declaration-lives 류 차단).
        assert j["discard_shown_clean"] is True and j["discard_disabled_clean"] is True, (
            "클린 세션에서 「변경 버리기」가 숨거나 활성입니다 — 상시 표시 + 비활성이어야"
            f" 합니다(§2.17): {j!r}"
        )
        assert j["save_disabled_clean"] is True, (
            "클린 세션에서 「변경 저장」이 활성입니다 — 버리기와 같은 술어여야 합니다."
        )
        assert j["discard_shown_dirty"] is True and j["discard_enabled_dirty"] is True, (
            "손댄 세션에 「변경 버리기」가 없거나 비활성입니다 — 나가지 않고는 되돌릴 길이"
            " 없습니다."
        )
        assert j["save_enabled_dirty"] is True, (
            "손댄 세션에서 「변경 저장」이 비활성입니다 — 버리기와 같은 술어여야 합니다."
        )
        # 머리 — 이름은 안정 입력이고 저장 상태는 **상태만** 말한다(#945 F5). 판본(저장 세대
        # 카운터)은 내부 어휘라 머리에서 걷혔다: 음성 단언을 함께 둬야 표기가 되살아나도 잡힌다.
        assert j["name_input_value"] == "공고서", f"이름 입력이 값을 받지 않습니다: {j!r}"
        assert "저장됨" in j["save_state"], (
            f"손대지 않은 세션의 머리가 「저장됨」이라 말하지 않습니다: {j['save_state']!r}"
        )
        assert "r" not in j["save_state"], (
            f"머리가 내부 판본 표기를 말합니다 — 읽는 사람에게 행동이 없는 어휘다: {j['save_state']!r}"
        )
        # 진입 문맥 — 자발적 진입이면 침묵, 사유가 있으면 증거·복귀 버튼과 함께 선다.
        assert j["ctx_hidden_when_voluntary"] is True, "할 말이 없는데 배너가 섰습니다."
        assert j["ctx_shown"] is True and j["ctx_return_btn"] is True, (
            f"진입 문맥 배너·복귀 버튼이 서지 않습니다: {j!r}"
        )
        assert "생성 실패 결과에서 열었습니다" in j["ctx_text"] and "4 / 12" in j["ctx_text"], (
            f"배너가 사유·증거를 말하지 않습니다: {j['ctx_text']!r}"
        )
        assert j["nav_back_after_leave"] is True, (
            "편집기를 나온 뒤에도 상단 2탭이 숨어 있습니다 — 몰입이 영구 은닉이 됐습니다."
        )

    def test_editor_binding_live_renders_four_column_table(
        self, selftest_result: dict
    ) -> None:
        # 2단계 「연결 확인」 표(U6-C #977 · U6 §2.2 · 동결 시안 장면 2) — 합성 매핑 스냅샷을
        # 실 render() 에 흘려 4열·머리 pill·일괄 승격·특수 항목 분기·행별 배지·스테퍼가 실
        # WebView2 에 그려지고 발신되는지 되읽는다(백엔드 판정은 test_mapping_state).
        e = selftest_result["editor_binding"]
        assert e.get("error") is None, f"연결 확인 프로브 예외: {e.get('error')!r}"
        assert e["head_cols"] == ["템플릿 필드", "데이터 열", "표시형", "미리보기"], (
            f"7열이 4열로 접히지 않았습니다: {e['head_cols']!r}"
        )
        assert "사용하지 않는 데이터 열 1개" in e["foot_text"], (
            f"표 바닥이 안 쓰는 열 수를 잇지 않습니다: {e['foot_text']!r}"
        )
        assert e["pills"] == ["자동 제안 2", "확인 필요 2", "고정값 0"], (
            f"머리 pill 셋이 Python 수치를 그대로 말하지 않습니다: {e['pills']!r}"
        )
        assert e["promote_label"] == "제안 2건 모두 확인", (
            f"일괄 승격 라벨이 링2 문안이 아닙니다: {e['promote_label']!r}"
        )
        # 배지 = 상태 4태의 링1 라벨. 채울 것이 없는 행은 확인할 것이 없어 잠기고 사유를 든다.
        assert e["badges"] == ["제안", "제안", "확인 필요", "확인 필요"], (
            f"행 배지가 링1 라벨과 다릅니다: {e['badges']!r}"
        )
        assert e["badge_disabled"] == [False, False, False, True], (
            f"배지 잠금 규칙이 `confirmable` 과 어긋납니다: {e['badge_disabled']!r}"
        )
        assert e["badge_hint"] and "비워 둠" in e["badge_hint"], (
            f"잠긴 배지가 사유를 말하지 않습니다: {e['badge_hint']!r}"
        )
        assert e["empty_select"] is True, "무결속 행의 열 칸이 조용합니다(경고 표지 부재)."
        assert e["preview_none"] is True, "열 필요 행의 미리보기가 「—」로 서지 않습니다."
        # 일괄 승격 — **양성과 음성 한 쌍**. 제안 2행만 오르고 확인 필요 2행은 그대로다.
        assert e["promote_call"] == 'confirm_suggested:{}', (
            f"일괄 승격이 `confirm_suggested` 를 내지 않았습니다: {e['promote_call']!r}"
        )
        assert e["badges_after"] == ["확인", "확인", "확인 필요", "확인 필요"], (
            f"일괄 승격이 확인 필요 행까지 건드렸거나 제안을 안 올렸습니다: {e['badges_after']!r}"
        )
        assert e["promote_disabled_after"] is True, "승격할 제안이 0 인데 버튼이 열려 있습니다."
        assert e["promoted_label_after"] == "제안을 모두 확인했습니다", (
            f"승격 뒤 문안이 Python 값이 아닙니다: {e['promoted_label_after']!r}"
        )
        # 특수 항목은 **열 이름 공간에 얹히지 않는다** — 각자 자기 액션으로 갈린다.
        assert e["pick_const"].startswith("set_type:"), f"고정값 분기: {e['pick_const']!r}"
        assert '"const"' in e["pick_const"], f"고정값 분기 payload: {e['pick_const']!r}"
        assert e["pick_today"].startswith("set_type:"), f"오늘 날짜 분기: {e['pick_today']!r}"
        assert e["pick_blank"].startswith("set_blank:"), f"비워 둠 분기: {e['pick_blank']!r}"
        assert e["pick_column"] == 'set_source:{"index":3,"source":"수량"}', (
            f"열 선택이 실 열 이름으로 가지 않습니다: {e['pick_column']!r}"
        )
        assert e["sentinel_in_set_source"] is False, (
            "센티넬이 `set_source` 로 샜습니다 — 동명 실열을 영영 못 겨누게 됩니다(리뷰 R5)."
        )
        assert e["badge_call"] == 'set_confirmed:{"index":0,"confirmed":true}', (
            f"배지 클릭이 행별 확인을 내지 않았습니다: {e['badge_call']!r}"
        )
        assert e["step_next"] == 'step_preview:{"delta":1}', f"스테퍼 ▶: {e['step_next']!r}"
        assert e["step_prev"] == 'step_preview:{"delta":-1}', f"스테퍼 ◀: {e['step_prev']!r}"
        # 퇴역 좌표의 음성 단언 — 있으면 같은 상태를 두 컨트롤이 판정한다.
        assert e["header_chips_gone"] is True, "「사용할 데이터 열」 칩이 남아 있습니다(U6 §2.5)."
        assert e["type_column_gone"] is True, "타입 열이 남아 있습니다(데이터 열 select 로 흡수)."
        assert e["confirm_checkbox_gone"] is True, "확정 체크박스가 남아 있습니다(배지로 흡수)."
        # 데이터 열 칸이 한 줄로 서는가(U2 §2.6) — 정적 CSS 검사로는 못 보고 실렌더 기하로만
        # 드러나는 결함이라 여기서 잰다. ↻ 가 있는 행과 없는 행의 칸 높이가 같으면 안 밀린 것이다.
        assert e["auto_revert_option"] is True, (
            "touched 행에 '자동 제안으로 되돌리기'(↻) 버튼이 없습니다(리뷰 R5)."
        )
        assert e["src_cell_h_manual"] == e["src_cell_h_suggested"], (
            "데이터 열 칸의 컨트롤이 둘째 줄로 밀렸습니다 — 수동 행과 제안 행의 칸 높이가 "
            f"다릅니다({e['src_cell_h_manual']} vs {e['src_cell_h_suggested']})."
        )
        assert e["revert_same_line"] is True, (
            "재제안 버튼과 select 의 세로 중심이 어긋났습니다 — 줄이 갈렸습니다."
        )

    def test_editor_save_gate_opens_on_typing_not_on_blur(self, selftest_result: dict) -> None:
        """편집(탭)의 「변경 저장」이 **타이핑 시점에** 열린다(U2 §2.4 게이트 · 리뷰 R2).

        `s.dirty` 는 `change`(=blur)에서만 갱신되는데, 그때까지 주 행동이 `disabled` 면 방금
        고친 사람의 **첫 클릭이 삼켜진다** — 비활성 버튼은 click 을 내지 않아 그 클릭은
        blur→change 만 태우고, 사용자는 아무 데나 한 번 누른 뒤 다시 눌러야 한다. 게이트를
        없애는 대신 「아직 도착하지 않은 입력이 있는가」라는 DOM 의 사실을 더해 합성한다.

        정적 검사로는 못 본다(이벤트 순서와 버튼 상태의 문제라 실 DOM 이 있어야 한다).
        """
        g = selftest_result["editor_save_gate"]
        assert g.get("error") is None, f"저장 게이트 프로브 예외: {g.get('error')!r}"
        assert g["save_present"] is True, "편집 모드 footer 에 「변경 저장」이 없습니다."
        assert g["clean_disabled"] is True, (
            "바꾼 것이 없는데 저장이 열려 있습니다 — 게이트 자체가 사라졌습니다(U2 §2.4)."
        )
        assert g["typing_enabled"] is True, (
            "이름을 고쳤는데 저장이 잠긴 채입니다 — 첫 클릭이 삼켜지는 그 상태입니다."
        )
        # §2.17 + PR #354 리뷰 — 버리기도 같은 술어로 **타이핑 시점에** 열리고, 되돌려 치면
        # 함께 잠긴다(저장만 열면 clean 세션 타이핑 직후 버리기 첫 클릭이 삼켜진다).
        assert g["typing_discard_enabled"] is True, (
            "이름을 고쳤는데 「변경 버리기」가 잠긴 채입니다 — 저장과 같은 술어여야 합니다."
        )
        assert g["rerender_keeps_enabled"] is True, (
            "타이핑 중 push 한 번에 저장이 도로 잠깁니다 — 버튼만 직접 켜고 렌더 경로는 "
            "옛 판정을 그대로 씁니다(두 자리가 다른 말을 합니다)."
        )
        assert g["reverted_disabled"] is True, (
            "되돌려 쳐서 원래 값이 됐는데 저장이 열린 채입니다 — 없는 변경을 저장하라고 합니다."
        )
        assert g["reverted_discard_disabled"] is True, (
            "되돌려 쳤는데 「변경 버리기」가 열린 채입니다 — 버릴 것 없는 버리기를 권합니다."
        )
        assert g["pattern_present"] is True, (
            "파일명 패턴 입력이 없습니다 — 프로브가 겨눌 자리 소실."
        )
        assert g["pattern_typing_enabled"] is True, (
            "패턴을 고쳤는데 저장이 잠긴 채입니다 — 이름만 고치고 패턴은 빠졌습니다."
        )
        # 매핑 행의 상수 입력도 같은 자격(리뷰 R3) — 머리·꼬리 입력만 세면 이 자리만 남는다.
        assert g["row_const_present"] is True, "매핑 행 상수 입력이 없습니다 — 프로브 겨눔 소실."
        assert g["row_clean_disabled"] is True, "행 단계에서 바꾼 것이 없는데 저장이 열려 있습니다."
        assert g["row_typing_enabled"] is True, (
            "매핑 행 상수를 고쳤는데 저장이 잠긴 채입니다 — 그 컨트롤에서 첫 클릭이 삼켜집니다."
        )
        assert g["row_reverted_disabled"] is True, (
            "행 상수를 되돌려 쳤는데 저장이 열린 채입니다 — 없는 변경을 저장하라고 합니다."
        )
        # 타이핑 도중 푸시(리뷰 R4 P1) — 값이 살고, 그래야 열린 버튼이 참이다.
        assert g["row_value_survives_push"] is True, (
            "재구성이 친 값을 지웠습니다 — 저장은 열려 있으니 사용자는 사라진 값을 저장했다고 "
            "믿습니다(조용한 소실을 표지가 가립니다)."
        )
        assert g["row_enabled_after_push"] is True, (
            "값은 살았는데 저장이 잠겼습니다 — 남은 편집을 없다고 말합니다."
        )
        assert g["gone_control_disables"] is True, (
            "되돌릴 자리가 사라졌는데 저장이 열린 채입니다 — 없는 편집을 있다고 말합니다."
        )

    def test_editor_notice_channel_is_inline_on_every_tab(self, selftest_result: dict) -> None:
        """편집기 통지는 세 탭 어디서든 화면 안(``#save-msg``)에 선다(#323).

        종전에는 파일 이름 탭 **본문**에만 노드가 있어, 나머지 두 탭의 구조화 거절이
        ``window.alert`` 로 샜다. 모달 경보는 읽는 순간 사라지고 그 뒤 화면은 왜 막혔는지
        아무 말도 하지 않는다. 정적 계약은 노드의 존재만 보고 **어느 탭에서** 서는지·실제로
        **보이는지**는 못 본다 — 그래서 실렌더 층이 이 계약을 진다.
        """
        n = probe(selftest_result, "editor_save_gate")["notice_channel"]
        assert n["present"] == {"template": True, "binding": True, "filename": True}, (
            f"통지가 갈 노드가 없는 탭이 있습니다: {n['present']!r} — 그 탭의 거절은 "
            "모달 경보로 새거나 아무 데도 안 섭니다."
        )
        assert n["save_enabled"] is True, "막힌 저장을 태울 주 행동이 잠겨 있습니다(측정 무효)."
        assert n["matches_block_reason"] is True, (
            f"차단 사유가 인라인에 실리지 않았습니다: {n['text']!r}"
        )
        # 프로브 click 은 hidden 도 통과한다 — 가시성을 따로 세지 않으면 눈으로 본 것과
        # 다른 결론이 난다(계산 스타일 + offsetParent 실가시성).
        assert n["visible"] is True, "통지 노드가 DOM 에는 있는데 보이지 않습니다."
        assert n["inside_body"] is False, (
            "통지가 본문(#editor-body) 안에 있습니다 — 탭 전환·본문 재렌더에 다시 증발합니다."
        )
        assert n["alerts"] == 0, (
            f"구조화 거절이 window.alert 로 샜습니다({n['alerts']}회)."
        )

    def test_editor_library_manage_renders_menus_and_dialog(self, selftest_result: dict) -> None:
        # F8(§10.17.2 판정 D) — 구 tpl 그룹 프로브의 승계 재작성: 관리 표면(그룹·⋮·칩·이동
        # 다이얼로그·행동 줄·결과 줄)이 편집기 「템플릿」 탭 실 WebView2 에 서는지 되읽는다
        # (부록 B-9 자동판 승계). 합성 editor 스냅샷을 실 render() 에 흘린다.
        t = selftest_result["editor_lib_manage"]
        assert t.get("error") is None, f"편집기 관리 표면 프로브 예외: {t.get('error')!r}"
        # U6-B(#976): 좌 열 동사는 넷이다 — 바닥의 「파일 가져오기…」·「서식 폴더 설정」·
        # 「새 TXT 템플릿…」과 머리의 「새로 읽기」. 「폴더에서 보기」는 PathActions 가 진다.
        assert t["toolbar"] == [True, True, True, True], (
            "좌 열 동사 줄(가져오기·서식 폴더 설정·새 TXT·새로 읽기) 소실:"
            f" {t['toolbar']!r}"
        )
        assert t["retired_folder_import"] is True, (
            "「폴더에서 가져오기…」가 남아 있습니다 — U6-A(#975)에서 퇴역한 동사입니다."
        )
        # U4 §2-30: 구획 헤더는 없다(밴드는 언제나 평면) — 행은 하나도 접히지 않는다.
        assert t["grp_heads"] == 0, f"그룹 헤더가 남아 있습니다: {t!r}"
        # 접힘이 없으니 두 밴드의 행이 전부 선다(hwpx 4 + txt 1).
        assert t["rows_visible"] == 5, f"평면 밴드의 행이 전부 서지 않았습니다: {t!r}"
        assert t["grp_more"] == 0, "그룹 ⋮ 가 남아 있습니다 — U4 §2-30 에서 걷혔습니다."
        assert t["row_more"] == 5, f"행 ⋮ 수가 가시 행 수와 다릅니다(오류 행 포함 도달성): {t!r}"
        # 동작 0 인 행(U6-A 에서 삭제가 퇴역해 생긴 상태)은 **비활성 + 사유**다 — 버튼이
        # 서 있는데 클릭이 조용히 삼켜지는 무반응은 이 저장소가 금지한다.
        assert t["dead_row_more_disabled"] is True, (
            "동작 0 인 행의 ⋮ 가 활성입니다 — 누르면 아무 일도 없습니다."
        )
        assert "할 수 있는 작업이 없습니다" in t["dead_row_more_reason"], (
            f"비활성 사유가 병기되지 않았습니다: {t['dead_row_more_reason']!r}"
        )
        assert t["live_row_more_enabled"] is True, "동사가 있는 행까지 잠갔습니다(과잠금)."
        assert t["assign_chips"] == 0, (
            "＋그룹지정 칩이 남아 있습니다 — 그룹 표면은 U4 §2-30 에서 걷혔습니다."
        )
        assert t["fill_warn"] is True, "채움 완화 사전 고지(#154)가 행에 렌더되지 않았습니다."
        assert t["result_line"] is True, "결과 재진술 줄(#tplResult 승계)이 렌더되지 않았습니다."
        assert t["band_caption"] is True, "좌 열 머리의 「서식 폴더」 부제가 없습니다."
        # HWPX 행 ⋮ = [링1 상태 동사] — 소비 동사 없음(행 버튼 소유, 같은 동사 2벌 금지).
        # TXT 행 ⋮ = [내용 편집]. 「이동」과 그룹 헤더 ⋮ 는 U4 §2-30 에서, 「삭제」는
        # U6-A(#975)에서 사망했다(앱은 사용자 서식 폴더에 쓰지 않는다).
        assert t["menu_shown"] is True, "행 ⋮ 클릭에 메뉴가 열리지 않았습니다."
        assert t["hwpx_menu_items"] == ["act:compile", "act:review"], (
            f"HWPX 행 ⋮ 구성이 [변환·검토]와 다릅니다: {t['hwpx_menu_items']!r}"
        )
        assert t["menu_closed"] is True, "바깥 클릭에 메뉴가 닫히지 않았습니다."
        assert t["txt_menu_items"] == ["edit"], (
            f"TXT 행 ⋮ 구성이 [내용 편집]과 다릅니다: {t['txt_menu_items']!r}"
        )
        # 구간 항목 목록 + 동사 1건 실왕복(S8-03 #834) — 같은 창에 얹은 단계다.
        assert t["slot_rows"] == 1, f"구간 항목 목록이 렌더되지 않았습니다: {t!r}"
        assert t["slot_verbs"] == [True, True, True], (
            f"항목 행 동사 3종(개명·표기로 되돌리기·삭제)이 다 서지 않았습니다: {t['slot_verbs']!r}"
        )
        assert t["slot_rename_visible"] is True, "개명 트리거가 보이지 않습니다(클릭은 hidden 도 통과)."
        # 밴드 동사(U4-E3 #939) — 행 1건에서도 서는 것이 노출 규칙이고(개수 문턱 없음),
        # 대상이 파일이라 `data-slot` 을 달지 않는다.
        assert t["slot_band_verb_visible"] is True, "「전부 표기로 되돌리기」가 보이지 않습니다."
        assert t["slot_band_verb_targets_file"] is True, (
            "밴드 동사가 항목 id 를 달고 있습니다 — 대상은 파일 하나여야 합니다."
        )
        assert t["slot_prompt_shown"] is True, "개명 트리거가 입력 창을 열지 않았습니다."
        assert t["slot_prompt_value"] == "특약 사항", (
            f"개명 프롬프트 초기값이 현재 이름이 아닙니다: {t['slot_prompt_value']!r}"
        )
        # 확정이 등록된 액션·payload 로 나간다(확인 왕복 없음 — 개명은 파괴가 아니다).
        assert t["slot_dispatch"] == [
            ["tpl", "slot_rename", "C:/lib/구간.hwpx", "특약", "특약 사항"]
        ], f"개명 발신이 계약과 다릅니다: {t['slot_dispatch']!r}"
        assert t["slot_notice_inline"] is True, (
            "동사 실패가 인라인 채널(#save-msg)에 보이게 서지 않았습니다(#323 라우팅)."
        )
        # 퇴화 불변식(결정 5) — 그룹 0개면 헤더 없는 평면.
        assert t["flat_heads"] == 0 and t["flat_rows"] == 1, f"퇴화 평면 위반: {t!r}"

    def test_milestone_h_heading_roles_and_job_steps_render(self, selftest_result: dict) -> None:
        """H-01/H-03: 계산 스타일 3단 역할과 작업 ①~④ 표지가 실 DOM에 선다."""
        h = selftest_result["milestone_h_wave1"]
        assert h["headings"]["screen"]["font_size"] == "19px"
        assert h["headings"]["screen"]["font_weight"] == "700"
        assert h["headings"]["section"]["font_size"] == "15px"
        assert h["headings"]["section"]["font_weight"] == "700"
        assert h["headings"]["zone"]["font_size"] == "13px"
        assert h["headings"]["zone"]["font_weight"] == "700"
        # 재작성 R1: 「작업」 세션 표면은 순서 있는 4존이 아니라 마주 보는 두 열이라 znum 이
        # 은퇴했다(정적 판은 test_job_session_surface_uses_v6_two_column_captions). 여기서는
        # **실렌더로** 서수 0 + v6 캡션 6종을 되읽어, 죽은 번호가 실화면에 남지 않았음을 본다.
        # zone-cap 타이포 역할(위 13px/700)은 그대로라 H-01 3역할 계약은 유지된다.
        assert h["job_step_badges"] == 0
        assert h["job_steps"] == [
            # 「실행 기록」 부캡션은 로그 상자와 함께 퇴역했다(#957) — 실패 고지는 알림
            # 채널로 갔고, 결과 존이 세우는 부캡션은 「만든 문서 N건」 하나뿐이다.
            "현재 데이터",
            # 「본문 확인」 부캡션은 존 재편에서 퇴역했다 — 그 존의 요약 한 줄은 사전검증과
            # 같은 사실이었고, 남은 위험 배너는 캡션 없이 사전검증 바로 아래 붙는다.
            "생성 결과",
            # 「시작하기」 = 데이터·작업이 둘 다 없을 때만 서는 흡수처 출구(F2 PR-B 판정 C).
            # 이 프로브의 합성 상태가 바로 그 상태라 캡션 목록에 함께 잡힌다.
            # 「선택한 작업」 존은 사망(U2 §4 판정 A, #342) — 활성 카드·액션바 이름이 승계.
            "시작하기",
            "이 데이터에 사용할 문서",
            "생성 준비",
        ]

    def test_milestone_h_template_and_card_surfaces_render(self, selftest_result: dict) -> None:
        """H-04/H-14: 매체 sunken 층과 지속 선택 막대가 계산 스타일에 반영된다."""
        h = selftest_result["milestone_h_wave1"]
        # 카드 상태 계약(F8 재겨눔) — .tplcard 는 tpl 화면과 함께 죽어, 같은 선택자 묶음의
        # 생존 소비자 .jcard 로 잰다. (H-04 매체 sunken 2면은 은퇴 — 승계 표면인 편집기
        # 밴드는 .grp 문법, 그 시각 계약은 editor_lib_manage 프로브 소관.)
        assert h["selected_card"] is not None
        assert h["selected_card"]["border_left"] != "rgba(0, 0, 0, 0)"
        assert h["selected_card"]["background"] != h["card_base"]["background"]

    def test_milestone_h_disabled_primary_and_pathtrack_hierarchy(
        self, selftest_result: dict
    ) -> None:
        """H-11/H-12: disabled primary가 물러나고 로케이트 동사는 아이콘 접근 이름을 갖는다."""
        h = selftest_result["milestone_h_wave1"]
        assert h["disabled_primary"]["background"] != h["enabled_primary"]["background"]
        assert h["disabled_primary"]["opacity"] == "1"
        assert h["pathtrack"]["count"] >= 2
        assert h["pathtrack"]["titled"] is True
        assert h["pathtrack"]["svg"] is True
        assert set(h["pathtrack"]["names"]) <= {"열기", "폴더에서 보기", "경로 복사"}

    def test_milestone_h_scrollport_holds_sticky_header(self, selftest_result: dict) -> None:
        """H-07: 실제 세로 스크롤포트가 gutter/contain을 쓰고 sticky 머리를 유지한다."""
        s = selftest_result["milestone_h_wave1"]["scroll"]
        assert s["overflow_y"] == "auto"
        assert "stable" in s["gutter"]
        assert "contain" in s["overscroll"]
        assert s["sticky_position"] == "sticky"
        assert s["scroll_top"] > 0
        assert s["sticky_holds"] is True

    def test_milestone_h_overlay_root_scrollbar_and_sticky_material_render(
        self, selftest_result: dict
    ) -> None:
        h = selftest_result["milestone_h_overlay"]
        assert h.get("error") is None, h.get("error")
        assert h["pending"] is False
        assert h["overlay_root_direct"] is True and h["overlay_children_owned"] is True
        assert h["scrollbar"] == {
            "width": "8px",
            "button_display": "none",
            "button_width": "0px",
            "button_height": "0px",
        }
        assert h["sticky_material"]["position"] == "sticky"
        assert "blur(14px)" in h["sticky_material"]["backdrop"]

    def test_milestone_h_workcard_and_popover_interactions_render(
        self, selftest_result: dict
    ) -> None:
        # workcard 프로브는 「기안」 카드 사망으로 작업대 #wbCard(.wb-preview + wc-render +
        # f-* 글꼴)로 재겨눔(F6 PR-B) — 구 .wc-render 전용 gutter/overscroll 은 승계 규칙에
        # 없어 프로브도 재지 않는다.
        #
        # 높이 계약은 **열 수에 달렸다**(리뷰 R1): 2열에서는 고정 캡이 아니라 `flex:1` 로 남는
        # 높이를 받고(캡은 낮은 창에서 `.wb-body` 를 넘쳐 footer 가 마지막 행 위에 그려졌다),
        # 1열 퇴화에서만 캡이 돌아온다. 어느 regime 을 쟀는지 프로브가 함께 실으므로 단언도
        # 그것을 따라간다 — 한쪽 수치를 박아 두면 실창 폭이 바뀌는 날 거짓말이 된다.
        h = selftest_result["milestone_h_overlay"]
        w = h["workcard"]
        assert w["overflow_y"] == "auto"
        if w["narrow"]:
            assert w["max_height"] == "320px" and w["flex_grow"] == "0"
        else:
            assert w["max_height"] == "none" and w["flex_grow"] == "1"
        assert ("GulimChe" in w["font_family"]) or ("굴림체" in w["font_family"]), (
            f"카드가 f-gulimche 글꼴 선언을 추종하지 않습니다: {w['font_family']!r}"
        )
        assert w["dot_hit"] == ["24px", "24px"] and w["dot_mark"] == ["14px", "14px"]
        assert w["dots_overflow"] == "visible"
        p = h["popover_place"]
        assert (
            p["placement"] == "top" and p["in_viewport"] is True and p["origin"].endswith(" bottom")
        )
        assert p["radius"] == "12px" and p["shadow"] != "none"
        assert h["drag_closed"] is True and h["click_after_drag"] is True
        assert h["click_after_right"] is True
        assert h["focusout_closed"] is True and h["scroll_closed"] is True
        assert h["close_all_closed"] is True

    def test_milestone_h_modal_stack_ime_focus_and_short_viewport_render(
        self, selftest_result: dict
    ) -> None:
        h = selftest_result["milestone_h_overlay"]
        assert h["modal_closed_popover"] is True and h["z_order"] is True
        # 표적 모달 재겨눔(→ txtEditModal, F6 PR-B → promptModal, R4-02 — 위 참조).
        assert h["modal_focus_in"] == "promptModalInput"
        assert h["ime_escape_kept_open"] is True
        assert h["exit_blocks_pointer"] is True and h["menu_trigger_restored"] is True
        assert h["escape_one_layer"] is True
        short = h["short_viewport"]
        # pywebview의 OS 최소 창 높이가 요청한 500px를 약 564px로 clamp할 수 있으므로
        # CSS 100dvh와 같은 fractional viewport에서 2×16px inset을 뺀 계약으로 판정한다.
        assert short["viewport"] <= 600 and short["height"] <= short["viewport"] - 32
        assert short["scrollable"] is True and short["actions_reachable"] is True

    def test_editor_library_picker_renders_grouped_select(self, selftest_result: dict) -> None:
        # 에디터 1단계 피커 — 라이브러리가 관리 화면과 같은 그룹 구획(선택 전용)
        # 으로 실 WebView2 에 서는지. 접힌 그룹 행 제외·현 선택 표지·필터 고지·퇴화 평면 되읽기.
        e = selftest_result["editor_lib"]
        assert e.get("error") is None, f"고르기 화면 프로브 예외: {e.get('error')!r}"
        # ① 두 열이 각자 채널로 선다(U6-B #976). 구획 헤더는 U4 §2-30 에서 사라졌다.
        assert e["grp_heads"] == 0, f"그룹 헤더가 남아 있습니다: {e!r}"
        assert e["tpl_items"] == 3, f"좌 열 항목이 전부 서지 않았습니다: {e!r}"
        assert e["dat_items"] == 2, f"우 열 항목이 전부 서지 않았습니다: {e!r}"
        assert e["import_btn"] is True, "「파일 가져오기…」 어포던스가 없습니다."
        assert e["browse_btn"] is True, (
            "우 열 「파일 찾아보기…」가 없습니다 — 데이터를 고르는 문이 닫혀 있습니다."
        )
        # F6 PR-B 의 매체 고지 두 줄은 U6-B 에서 걷혔다(매체는 pill 하나가 말한다).
        assert e["filter_notice"] is False, (
            "퇴역한 매체 고지가 되살아났습니다 — 매체는 pill 이 말합니다."
        )
        # 변환 전 항목은 **숨기지 않고** 비활성 + 사유이고, 끌 수도 없다(U6 §2.3).
        assert e["blocked_shown"] is True, "변환 전 항목이 목록에서 사라졌습니다(조용한 은닉)."
        assert e["blocked_reason"] is True, (
            "비활성 항목의 부제가 사유를 지지 않습니다 — 왜 못 고르는지 화면이 말해야 합니다."
        )
        assert e["blocked_not_draggable"] is True, (
            "고를 수 없는 항목이 draggable 입니다 — 끌 수 있으면 놓을 수 있다고 읽힙니다."
        )
        # 긴 파일명이 선택 동작을 밀지 않게 이름 칸이 말줄임된다.
        assert e["fname_ellipsis"] == "ellipsis", (
            f"파일명 칸 말줄임 미적용: {e['fname_ellipsis']!r}"
        )
        # ② 클릭 둘 = 등록된 액션 둘(템플릿 먼저). 사이의 `mapping_reset_stakes` 는 **질의**다:
        #    확정 매핑이 걸린 데이터 교체는 고르기 **전에** 한 번 묻는다는 선행 규율이고,
        #    수치를 Python 이 지금 판정하므로(웹 지역 스냅샷 금지) 왕복이 하나 앞선다.
        #    순서가 계약이다 — 이 질의가 `use_pool_data` 뒤로 가면 파괴를 승인시킨 뒤 묻는 꼴이다.
        assert e["click_calls"] == [
            ["editor", "use_library_template"],
            ["editor", "mapping_reset_stakes"],
            ["editor", "use_pool_data"],
        ], f"클릭 둘이 발행한 액션이 계약과 다릅니다: {e['click_calls']!r}"
        # ③ 끌어 놓기 = **같은 액션 두 번**(새 액션 0). 형식·강조·정리까지 되읽는다.
        assert e["drag_payload"] == "tpl:c.hwpx", (
            f"dataTransfer 형식이 `<side>:<key>` 가 아닙니다: {e['drag_payload']!r}"
        )
        assert e["drag_over_accepted"] is True, "상대 열 항목 위에서 드롭이 허용되지 않습니다."
        assert e["drag_target_marked"] is True, "드롭 대상 강조(.drop-target)가 서지 않습니다."
        assert e["drag_target_cleared"] is True, "드롭 뒤 강조가 남았습니다."
        assert e["drop_matches_click"] is True, (
            "끌어 놓기가 클릭과 다른 액션을 발행했습니다"
            f" (클릭 {e['click_calls']!r} · 드롭 {e['drop_calls']!r})."
        )
        # ④ 같은 열끼리는 짝이 아니다 — 발신 0(음성 대조).
        assert e["same_side_drop_calls"] == 0, (
            f"같은 열 안에서 드롭이 발신을 냈습니다: {e['same_side_drop_calls']!r}"
        )
        # ⑤ 비활성 항목 클릭은 조용히 삼켜지지 않는다 — 발신 0 + 인라인 사유.
        assert e["blocked_click_calls"] == 0, (
            f"고를 수 없는 항목이 발신을 냈습니다: {e['blocked_click_calls']!r}"
        )
        assert e["blocked_notice"] is True, (
            "비활성 항목 클릭이 조용히 무시됐습니다 — 사유를 인라인으로 재진술해야 합니다."
        )
        # ⑥ 연결 카드는 Python 이 낸 수치·라벨 그대로다.
        assert "a.hwpx ⟷ 7월목록.xlsx" in e["card_text"], f"연결 카드 짝 표기: {e['card_text']!r}"
        assert "필드 12개 · 열 18개" in e["card_text"], f"연결 카드 규모: {e['card_text']!r}"
        assert "자동 연결 10" in e["card_text"] and "확인 필요 2" in e["card_text"], (
            f"연결 카드 수치(basis=preview 어휘): {e['card_text']!r}"
        )
        assert e["wire_live"] is True, "둘 다 골랐는데 연결선이 살아나지 않았습니다."
        assert e["cta_enabled"] is True, "둘 다 골랐는데 「연결 확인으로」가 잠겨 있습니다."
        assert "시트: 물품" in e["current_restated"], (
            f"현재 데이터가 시트를 재진술하지 않습니다: {e['current_restated']!r}"
        )
        assert "헤더 1행" in e["current_restated"] and "12행" in e["current_restated"], (
            f"현재 데이터가 헤더 행·행 수를 재진술하지 않습니다: {e['current_restated']!r}"
        )
        assert e["pool_current_marked"] == 1, (
            f"겨눈 풀 항목의 선택 표지가 다릅니다: {e['pool_current_marked']!r}"
        )
        # 이미 고른 항목 재선택은 **무동작**이다(리뷰 1) — 통과시키면 세션이 통째로 끊긴다.
        assert e["reselect_calls"] == 0, (
            f"이미 고른 템플릿을 다시 눌러 발신이 나갔습니다: {e['reselect_calls']!r}"
        )
        assert e["reselect_keeps_mark"] == 1, "재선택이 선택 표지를 흔들었습니다."
        # 관리 동사 연타는 한 번만 나간다(리뷰 6) — 두 벌 확인 모달·두 번 확정 금지.
        assert e["manage_verb_present"] is True, "우 열에 관리 동사가 서지 않았습니다."
        assert e["double_fire_calls"] == 1, (
            f"동사 연타가 두 번 발신됐습니다: {e['double_fire_calls']!r}"
        )
        # ⑦ 반쪽만 고르면 전진 게이트가 막고 **Python 이 낸 사유**가 선다.
        assert e["half_cta_disabled"] is True, (
            "데이터 없이 「연결 확인으로」가 열려 있습니다 — 1단계 게이트가 데이터를 요구합니다."
        )
        assert "오른쪽에서 데이터를 고르세요" in e["half_block_reason"], (
            f"전진 차단 사유가 Python 문안 그대로가 아닙니다: {e['half_block_reason']!r}"
        )

    def test_job_drift_replaces_mirror_with_blocking_banner(self, selftest_result: dict) -> None:
        # danger(구조 드리프트)는 본문 존 한 줄과 섞이지 않고 차단 배너 + 행동 링크로
        # **교체**된다(결정 36·S9). overlay 로 얹히는 게 아니라 실제로 교체돼 선다.
        j = probe(selftest_result, "job_mirror")
        assert j["drift_banner"] is True, "드리프트 차단 배너(role=alert)가 렌더되지 않았습니다."
        assert j["drift_fix_link"] is True, (
            "「편집에서 매핑 확정…」 행동 링크가 없습니다(막다른 경보 금지)."
        )
        # 「건강한 한 줄」·「N건 생성 재진술」과의 모순 대조는 그 두 표면이 존 재편에서
        # 걷히면서 함께 은퇴했다 — 부재는 위 배너 host 테스트가 한 번만 잰다.

    def test_job_overwrite_body_composes_counts_and_names(self, selftest_result: dict) -> None:
        # 파괴적 덮어쓰기 확인 본문 — 수치와 이름을 실 DOM에서 함께 검증한다.
        # 수치 배치(총량·파괴분·신규분)와 파일 이름 목록이 합성되는지 실 함수 출력으로 되읽는다.
        # count 스왑·이름 목록 누락이 조용히 배포돼 사용자가 축소된 그림 위에서 덮어쓰는 것을 막는다.
        body = probe(selftest_result, "job_mirror")["ow_body"]
        assert "10건을 생성합니다" in body, f"총량 미표기: {body!r}"
        assert "3건이 기존 파일을 덮어씁니다" in body, (
            f"파괴분 미표기(new_count 와 스왑?): {body!r}"
        )
        assert "나머지 7건은 새 파일" in body, f"신규분 미표기: {body!r}"
        assert "a.hwpx" in body and "b.hwpx" in body, f"덮어쓸 파일 이름 목록 누락: {body!r}"
        assert "외 5개" in body, f"초과분(conflict_more) 미표기: {body!r}"

    def test_theme_defaults_to_system_when_unpersisted(self, selftest_result: dict) -> None:
        # 저장된 테마 선택이 없으면 앱은 OS 를 따른다 — data-theme 속성이 없어야(=system) @media 지배.
        # 실수로 특정 테마가 강제되면(속성 상주) OS 추종이 깨지므로 되읽어 가드한다.
        tp = selftest_result["theme_persist"]
        assert tp["data_theme"] is None, f"미저장인데 data-theme 이 강제됨: {tp!r}"
        assert tp["a_card"] == "#ffffff", f"미저장 기본이 라이트 카드가 아님: {tp!r}"

    def test_personalization_defaults_render_in_real_webview(self, selftest_result: dict) -> None:
        p = selftest_result["personalization_persist"]
        assert p["font_scale"] == "normal" and p["root_px"] == "16px"
        # 폭 스플리터 DOM 소비처 0 — 마지막 소비처 「기안」도 사망(F6 PR-B). 설정값(master_width)
        # 영속·CSS 변수 배선은 남아 다음 master-detail 표면이 그대로 쓴다.
        assert p["master_width"] == 240 and p["splitters"] == 0
        # 토바 높이는 라이브러리 2-pane 계산이 소비하는 구조 치수 — 실 엔진 실측으로 핀한다.
        assert p["topbar_h"] == 64, f"토바 높이가 구조 치수(64px)와 다릅니다: {p!r}"
        assert p["body_overflow"] is False, f"기본 배율에서 가로 오버플로: {p!r}"
        assert p["selected_text"] == "선택 가능한 본문", f"본문 텍스트 선택 실패: {p!r}"

    def test_workbench_is_immersive_and_the_queue_degenerates(self, selftest_result: dict) -> None:
        """TXT 검토·복사 작업대(재작성 F6 PR-A) — 실 WebView2 되읽기.

        정적 계약이 통과시키는 세 가지를 실물로 잡는다: ①몰입 셸이 실제로 상단 2탭을
        덮는가 ②큐 퇴화가 순회 장치를 **실제로** 감추는가(스타일 계산까지) ③나가는 이동이
        가드를 **지나서** 화면을 바꾸는가(발신 순서 포함 — 배선·문안이 다 제자리여도
        성사 뒤 이어짐만 끊길 수 있고 그건 정적 계약이 못 본다, F7 1R 선례).
        """
        w = selftest_result["workbench"]
        assert w.get("error") is None, f"작업대 프로브 예외: {w.get('error')!r}"
        assert w["screen_on"] and w["nav_hidden"], (
            f"작업대가 몰입 표면으로 서지 않습니다(화면·셸 은닉): {w!r}"
        )
        # 머리·상태 — 값은 전부 Python 스냅샷 파생이라 표면이 다시 계산하지 않는다.
        assert w["title"] == "발주요청_기안"
        assert w["position"] == "1 / 3" and w["copied"] == "1 / 3"
        assert "연결 r4" in w["revision"]
        assert "1건" in w["dirty_note"], f"미저장 변경 수치가 안 보입니다: {w['dirty_note']!r}"
        assert "다시 확인" in w["review"], f"재확인 상태가 안 보입니다: {w['review']!r}"
        assert w["save_enabled"] is True
        # 좌 pane: 확정-비움은 입력칸이 아니라 **선언 표지**로 그려진다(결정 12).
        assert w["map_rows"] == 2 and w["declared"] == 1
        # 우 pane: 채움 표지 삼분이 공용 SegView 계약대로 그려진다.
        assert w["card_fill"] == 1 and w["card_blank"] == 1
        assert w["lint_shown"] is True
        # 린트 처방(전각 치환)이 **손잡이로** 서 있는가 — 승계는 표지가 아니라 행동까지다.
        assert w["lint_action"] == "on:전각으로 바꾸기", w["lint_action"]
        # 등록만 되고 아무도 못 부르던 seam 둘이 실제로 손잡이가 됐는가(4R P2).
        assert w["font_value"] == "malgun", w["font_value"]
        assert w["dots"] == ["7행 · 작업 중 · 다시 확인 필요", "4행 · 대기"], w["dots"]
        # 순회 경계는 Python 이 낸 값을 그대로 쓴다(2R P1): 표시 자리가 머리(1/3)인데도
        # 순회상 후미면 「이전」이 열리고 「다음」이 닫힌다 — 서수로 계산하면 정반대가 된다.
        assert (w["prev_disabled"], w["next_disabled"]) == (False, True), (
            f"이동 경계가 표시 서수로 계산됩니다: {w['prev_disabled']}/{w['next_disabled']}"
        )
        # 결과 → 규칙(계약 §11 · 지도 §10.15.2 E) — 오른쪽 결과 조각을 누르면 그 값을 만든
        # 왼쪽 규칙 행이 선다. 이 PR 이 스스로 정한 「작업대는 화면 안에서 겨눈다」의 이행이라
        # 없으면 사용자가 소유 행을 손으로 찾는다(8R P2). 신원(data-token)·착지(포커스)·
        # 표지(계산된 스타일) 셋이 다 서야 길이 열린 것이다 — 하나만 빠져도 정적으론 초록이다.
        assert w["card_tokens"] == 2, f"조각이 토큰 신원을 안 지고 나갑니다: {w['card_tokens']}"
        assert w["aim_row"] == "수신", (
            f"결과 조각이 소유 규칙 행을 겨누지 못합니다: {w['aim_row']!r}"
        )
        assert w["aim_marked"] not in ("", "none"), (
            f"겨눈 행이 아무 표지도 못 받습니다(표 클래스↔스타일시트 드리프트): {w['aim_marked']!r}"
        )
        # 큐 퇴화 — 1건이면 이전/다음·자동 전진이 사라진다.
        assert w["degen_prev"] == "none" and w["degen_adv"] == "none"
        # 이탈: 가드를 먼저 묻고(leave_guard) 세션을 닫은 뒤에야 화면이 바뀐다.
        assert w["leave_calls"] == ["leave_guard", "close"], (
            f"이탈이 가드를 지나지 않거나 순서가 다릅니다: {w['leave_calls']!r}"
        )
        assert w["landed"] is True, "이탈 뒤 「문서 만들기」로 착지하지 않았습니다."


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_theme_choice_persists_across_restart_without_flicker(tmp_path) -> None:
    """다크모드 선택이 프로세스 재시작을 넘어 유지되고 콜드부트 첫 페인트 전 적용된다(영속+무깜빡임, #74).

    #74 재목적화의 핵심 실증 — 테마 영속이 오리진(포트)에 의존하지 않음을. 두 콜드부트는 각자
    **랜덤 빈 포트**(private_mode=True 기본)를 잡아 오리진이 서로 다르다. localStorage 기반이면
    여기서 리셋됐겠지만, Python 설정(settings.json)은 오리진 비의존이라 유지된다 — 옛 게이트가
    포트를 인위 고정해야만 초록이던 유효성 공백(실사용 미반영)을 이 테스트가 닫는다:
      (1) 쓰기 프로세스가 실사용 경로(Theme.set('dark') → Bridge → api.set_theme)로
          settings.json 에 심고 정식 종료 — theme.js 홉까지 게이트 커버리지에 들어간다.
      (2) 같은 HWPXFILLER_HOME 으로 새 콜드부트(다른 포트) → loaded 핸들러가 show 전에
          data-theme='dark' 를 주입하고 --a-card 가 다크값으로 해소된다.
    유지 안 되면 data_theme=null(리셋), 주입 실패면 속성 부재로 각각 시끄럽게 실패한다.
    """
    import gen_design_tokens as gen

    home = tmp_path / "home"
    out_write = tmp_path / "write.json"
    out_read = tmp_path / "read.json"
    # 포트를 고정하지 않는다(#74) — 양 콜드부트가 각자 랜덤 포트=서로 다른 오리진이어도 영속이
    # 유지됨을 실증하는 게 이 테스트의 요점(영속은 이제 오리진 비의존 Python 설정에 있다).
    base = dict(os.environ, HWPXFILLER_HOME=str(home))

    # (1) 쓰기 단계 — 저장 테마를 심고 종료.
    w = _boot_selftest(
        dict(base, HWPX_SELFTEST_OUT=str(out_write), HWPX_SELFTEST_SET_THEME="dark"),
        out=out_write,
        what="테마 쓰기 단계",
    )
    assert out_write.exists(), (
        f"쓰기 단계 결과 미생성 — rc={w.returncode}\nstderr={_tail(w.stderr)}"
    )
    written = json.loads(out_write.read_text(encoding="utf-8"))
    assert written.get("set_result") == "dark", f"쓰기 단계 Theme.set 실패: {written}"

    # (2) 읽기 단계 — 같은 HWPXFILLER_HOME(다른 포트)으로 콜드부트, 주입 적용 결과 되읽기.
    r = _boot_selftest(
        dict(base, HWPX_SELFTEST_OUT=str(out_read)), out=out_read, what="테마 읽기 콜드부트"
    )
    assert out_read.exists(), (
        f"읽기 단계 결과 미생성 — rc={r.returncode}\nstderr={_tail(r.stderr)}"
    )
    tp = json.loads(out_read.read_text(encoding="utf-8"))["theme_persist"]
    assert tp["data_theme"] == "dark", (
        f"콜드부트에서 저장 테마 미적용 — Python 설정 영속 또는 loaded 주입 실패: {tp!r}"
    )
    dark_card = gen.load_tokens()["dark"]["color"]["card_bg"]
    assert tp["a_card"] == dark_card, f"다크 --a-card({dark_card}) 미해소: {tp!r}"


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
@pytest.mark.parametrize(("scale", "root_px"), [("large", "20px"), ("larger", "24px")])
def test_font_scale_persists_across_restart_without_major_overflow(
    tmp_path, scale: str, root_px: str
) -> None:
    """125/150%를 실 브리지로 저장한 뒤 콜드부트에서 적용·레이아웃을 되읽는다."""
    home = tmp_path / scale
    out_write = tmp_path / f"{scale}-write.json"
    out_read = tmp_path / f"{scale}-read.json"
    base = dict(os.environ, HWPXFILLER_HOME=str(home))
    written_proc = _boot_selftest(
        dict(
            base,
            HWPX_SELFTEST_OUT=str(out_write),
            HWPX_SELFTEST_SET_FONT_SCALE=scale,
        ),
        out=out_write,
        what=f"배율 쓰기 단계({scale})",
    )
    assert out_write.exists(), (
        f"배율 쓰기 실패 rc={written_proc.returncode}: {_tail(written_proc.stderr)}"
    )
    assert json.loads(out_write.read_text(encoding="utf-8"))["set_result"] == scale
    saved = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    saved.update(master_width=333)
    (home / "settings.json").write_text(json.dumps(saved), encoding="utf-8")

    read_proc = _boot_selftest(
        dict(base, HWPX_SELFTEST_OUT=str(out_read)), out=out_read, what="배율 되읽기 콜드부트"
    )
    assert out_read.exists(), (
        f"배율 되읽기 실패 rc={read_proc.returncode}: {_tail(read_proc.stderr)}"
    )
    p = json.loads(out_read.read_text(encoding="utf-8"))["personalization_persist"]
    assert p["font_scale"] == scale and p["root_px"] == root_px
    assert p["master_width"] == 333
    assert p["body_overflow"] is False, f"{scale}에서 주요 가로 오버플로: {p!r}"
    full = json.loads(out_read.read_text(encoding="utf-8"))
    # 큰 배율에서도 좁은 창의 탭 도달성과 넓은 창의 토바 전개가 유지된다(배율×셸 교차 회귀).
    assert full["grid_narrow"]["tabs"] == len(NAV_SCREENS)
    assert full["grid_narrow"]["overflow"] is False
    assert full["grid_wide"]["rows"] == 2 and full["grid_wide"]["tool_labels_visible"] is True


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
@pytest.mark.parametrize("mode", ["normal", "maximized", "offscreen"])
def test_window_geometry_restores_or_falls_back_in_real_webview(tmp_path, mode: str) -> None:
    """저장 크기·위치·최대화는 복원하고, 화면 밖 좌표는 기본 배치로 회수한다."""
    home = tmp_path / mode
    home.mkdir()
    geometry = {
        "x": 120 if mode != "offscreen" else 50_000,
        "y": 100,
        "width": 1000,
        "height": 700,
        "maximized": mode == "maximized",
    }
    (home / "settings.json").write_text(json.dumps({"window_geometry": geometry}), encoding="utf-8")
    out = tmp_path / f"geometry-{mode}.json"
    env = dict(
        os.environ,
        HWPXFILLER_HOME=str(home),
        HWPX_SELFTEST_OUT=str(out),
        HWPX_SELFTEST_GEOMETRY_ONLY="1",
    )
    proc = _boot_selftest(env, out=out, what="창 기하 되읽기")
    assert out.exists(), f"창 기하 부팅 실패 rc={proc.returncode}: {_tail(proc.stderr)}"
    actual = json.loads(out.read_text(encoding="utf-8"))["window_geometry"]
    if mode == "normal":
        # WinForms screenX/Y에는 DPI별 비클라이언트 프레임 오프셋이 붙는다.
        assert abs(actual["x"] - 120) <= 40 and abs(actual["y"] - 100) <= 40
        assert abs(actual["width"] - 1000) <= 40 and abs(actual["height"] - 700) <= 40
        assert actual["maximized_like"] is False
    elif mode == "maximized":
        assert actual["maximized_like"] is True, f"최대화 복원 실패: {actual!r}"
    else:
        assert actual["x"] < 50_000 and actual["maximized_like"] is False


# InPrivate 의미론이 바뀌어도 부팅마다 webview_root를 청소하고 고정 프로필을 새로 만든다.
# 재시작 간 공유 캐시·구판 잔재 차단은
# test_webapp_profile.test_prepare_purges_orphans_and_legacy_layout이 검증한다.


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_completed_boot_stamps_the_home_and_narrows_the_budget(tmp_path) -> None:
    """부팅을 완주하면 완주 스탬프가 홈에 남는다 — 다음 부팅부터 좁은 예산(#77).

    예산 판정은 순수 함수라 단위 테스트가 지지만, **loaded 가 실제로 발화하는 실 WebView2
    부팅에서 스탬프가 실제로 찍히는가**는 여기서만 확인된다: 핸들러가 안 불리거나 저장이
    조용히 실패하면 모든 부팅이 영구히 '첫 실행'이 되고(넓은 예산 상주), 그래도 단위
    테스트는 계속 초록이다 — 계측 층의 조용한 오류.
    """
    from hwpxfiller.webapp.boot_budget import COLD_BUDGET_SECONDS, WARM_BUDGET_SECONDS, decide

    home = tmp_path / "home"
    out = tmp_path / "boot.json"
    env = dict(os.environ, HWPXFILLER_HOME=str(home), HWPX_SELFTEST_OUT=str(out))
    proc = _boot_selftest(env, out=out, what="부팅 스탬프")
    assert out.exists(), f"부팅 실패 — rc={proc.returncode}\nstderr={_tail(proc.stderr)}"
    saved = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    stamp = saved.get("boot_completed_runtime")
    assert isinstance(stamp, str) and stamp, (
        f"완주 스탬프 미기록 — 모든 부팅이 첫 실행으로 남습니다(#77): {saved!r}"
    )
    # 첫 부팅은 넓은 예산이었고, 이 스탬프 뒤로는 좁은 예산이다(판정의 실 왕복).
    assert decide("", stamp)[0] == COLD_BUDGET_SECONDS
    assert decide(stamp, stamp)[0] == WARM_BUDGET_SECONDS


@pytest.fixture(scope="module")
def normal_window_evidence(tmp_path_factory) -> dict:
    """능력 **없는** 실 창을 모듈당 1회 띄워 비노출·전역 델타 증거를 함께 얻는다.

    WebView2 콜드스타트는 비싸고 이 기계에서 드물게 매달린다(환경 결함 — 같은 부팅을 여섯 번
    반복하면 0/6 이지만 전체 스위트처럼 창을 많이 띄운 뒤에는 한 번씩 90s 를 넘긴다). 그래서
    같은 창을 두 번 띄우지 않는다. 부수 효과로 두 단언이 **같은 창**을 말하게 돼 대조가 는다.
    """
    home = tmp_path_factory.mktemp("no-capability-home")
    out = tmp_path_factory.mktemp("no-capability") / "evidence.json"
    env = dict(
        os.environ,
        HWPXFILLER_HOME=str(home),
        HWPX_SELFTEST_OUT=str(out),
        HWPX_SELFTEST_NO_CAPABILITY="1",
    )
    proc = _boot_selftest(env, out=out, what="능력 없는 창(음성 대조)")
    assert out.exists(), f"음성 대조 부팅 실패 rc={proc.returncode}: {_tail(proc.stderr)}"
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert "error" not in evidence, evidence.get("error")
    return evidence


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_selftest_api_is_absent_without_the_capability_in_real_webview(
    normal_window_evidence: dict,
) -> None:
    """능력을 붙이지 않은 실 창에는 ``window.__hwpxTest`` 가 **없다**(#372 D-07).

    ``__hwpxTest`` 비노출을 정적으로 세는 검사는 여럿 있지만(소스에 문자열이 없다, 생산자가
    하나다), 전부 **선언**을 본다. 능력은 런타임에 조건부로 설치되므로 "정상 실행 창에 그
    전역이 실제로 없는가"는 실 창에서만 답할 수 있다 — 선언은 살고 결과는 죽는 그 결함류를
    여기서 닫는다.

    정상 실행에는 드라이버가 없어(``webview.start()`` 에 함수를 주지 않는다) 창 안을 들여다볼
    길이 없고, 그렇다고 정상 경로에 관측 통로를 새로 내면 그 통로 자체가 제품 표면이 된다.
    그래서 ``--selftest`` 의 드라이버는 빌리되 **파사드만 붙이지 않는다**: 능력이 없을 때의
    창은 정상 실행의 창과 같은 번들·같은 코드 경로다.

    부재만 재면 "능력이 없다"와 "페이지가 안 떴다"가 구별되지 않으므로 제품 API 존재를
    **양성 대조**로 같은 창에서 함께 잰다(계측 층의 부재판별력).
    """
    evidence = normal_window_evidence
    probed = evidence["non_exposure"]

    # 양성 대조 — 이것이 없으면 아래 부재 단언은 "페이지가 안 떴다"와 구별되지 않는다.
    assert probed["product_typeof"] == "object", (
        f"제품 API 가 없다 — 페이지가 뜨지 않았을 수 있다: {probed!r}"
    )

    # 음성 ① 전역 부재. own 프로퍼티로도 없어야 한다(만들었다 지우는 길은 두지 않는다).
    assert probed["selftest_own"] is False
    assert probed["selftest_typeof"] == "undefined"

    # 음성 ② 호스트 파사드 부재 — 능력의 **유일한** 활성화 조건이 실제로 빠져 있다.
    assert probed["host_claim_typeof"] == "undefined"

    # 음성 ③ URL 쿼리·해시로는 켜지지 않는다. 실제로 얹은 뒤 다시 물었다.
    assert "?selftest=1" in probed["url_after"] and probed["url_after"].endswith("#selftest")
    assert probed["selftest_own_after_query_hash"] is False
    assert probed["selftest_typeof_after_query_hash"] == "undefined"

    # ── N-10 전역 allowlist — 이름 하나의 부재가 아니라 **전수**를 센다 ──────────────
    #
    # 위 단언들은 "우리가 아는 이름이 없다"까지만 말한다. 정적 게이트가 `window.X =` 모양을
    # 다 세어도 번들러·동적 경로가 만드는 전역은 소스에 그 모양으로 적혀 있지 않다. 그래서
    # 실 엔진에서 own 전역 **이름 전수**를 뜨고, 판정은 엔진 판올림에 흔들리지 않는 축으로만
    # 세운다(엔진 전역 목록을 저장소에 못박으면 CI 의 WebView2 판이 다를 때 제품과 무관한
    # 이유로 빨개진다).
    delta = evidence["global_delta"]
    assert "added_globals_error" not in delta, delta["added_globals_error"]

    # 양성 대조 — 측정이 실제로 창을 봤다. 비면 아래 부재 단언은 전부 공짜로 통과한다.
    assert delta["total_own"] > 500, f"전역 전수 측정이 헛돌았습니다: {delta}"
    assert delta["has_document"] and delta["has_location"], "엔진 전역이 안 보입니다 — 측정 오염."

    # ① 제품 공개 API 는 있고(양성) ② 시험 API 는 없다(음성 — 능력이 없으므로).
    #    이름공간 **전수**로 물어 "우리가 아는 이름"의 한계를 넘는다: 모르는 형제 전역이
    #    생기면 목록이 달라진다(파수꾼 테스트가 이 축의 검출력을 증명한다).
    assert delta["hwpx_namespace"] == ["__hwpx"], (
        f"__hwpx 이름공간에 예상 밖 전역이 있습니다: {delta['hwpx_namespace']}"
    )

    # ③ 은퇴한 임시 별칭 스물일곱은 실 창에 **하나도** 없다 — N-10 의 본론이다. 정적 게이트가
    #    소스에서 세는 것과 달리 여기는 **번들이 실제로 만든 결과**를 센다.
    assert delta["retired_present"] == [], (
        f"은퇴한 임시 전역이 실 창에 살아 있습니다: {delta['retired_present']}"
    )
    assert len(_RETIRED_COMPAT_GLOBALS) == 27, (
        "은퇴 목록이 바뀌었습니다 — 프로브와 함께 고치십시오."
    )


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_global_allowlist_gate_actually_catches_a_planted_leak(tmp_path) -> None:
    """누수 파수꾼 — 전역 하나를 **일부러 심으면** allowlist 게이트가 실제로 잡는다.

    위 테스트의 전역 단언은 **부재를 재는 계측**이다. 그런 계측은 자기가 부재를 볼 줄 아는지
    먼저 증명해야 한다 — 아무것도 관측하지 못하는 프로브도 똑같이 "누수 0" 을 낸다. 이
    저장소가 이미 두 번 겪은 결함류다(계측 층의 조용한 오류).

    ``document``·``__hwpx`` 가 보인다는 사실이 약한 양성 대조이긴 하다. 그러나 그 이름들은
    **항상** 있으므로 "측정이 살아 있다"까지만 말하고 "**새로** 생긴 이름을 잡는다"는 말하지
    못한다. 이 테스트가 그 간극을 닫는다.

    심는 자리는 selftest 드라이버이지 제품이 아니다 — 정상 실행에는 이 코드로 가는 길이
    없고(``--selftest`` + 전용 환경변수), 제품 번들은 한 글자도 달라지지 않는다.
    """
    sentinel = "__hwpxLeakSentinel"
    home = tmp_path / "leak-sentinel-home"
    home.mkdir()
    out = tmp_path / "leak-sentinel.json"
    env = dict(
        os.environ,
        HWPXFILLER_HOME=str(home),
        HWPX_SELFTEST_OUT=str(out),
        HWPX_SELFTEST_NO_CAPABILITY="1",
        HWPX_SELFTEST_LEAK_SENTINEL=sentinel,
    )
    proc = _boot_selftest(env, out=out, what="누수 파수꾼")
    assert out.exists(), f"파수꾼 부팅 실패 rc={proc.returncode}: {_tail(proc.stderr)}"
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert "error" not in evidence, evidence.get("error")
    assert evidence["leak_sentinel"] == sentinel

    # 양성 대조 — 페이지는 실제로 떴다(부재/존재를 논하기 전에).
    assert evidence["non_exposure"]["product_typeof"] == "object"

    delta = evidence["global_delta"]
    assert sentinel in delta["hwpx_namespace"], (
        f"심은 누수를 측정이 못 봤습니다 — 전역 계측이 헛돕니다: {delta}"
    )

    # 그리고 그 순간 위 게이트의 이름공간 단언이 **실제로 깨진다**. 이 한 줄이 "본다"와
    # "실패한다"를 잇는다 — 관측만 하고 판정이 통과하면 게이트가 아니다.
    assert delta["hwpx_namespace"] != ["__hwpx"]


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_selftest_run_adds_exactly_one_global_over_a_normal_run(
    normal_window_evidence: dict, tmp_path
) -> None:
    """시험 실행이 정상 실행보다 더하는 전역은 **정확히 `__hwpxTest` 하나**다(#372 D-07).

    두 모드가 **같은 표현식**으로 잰 전역 전수를 뺄셈한다. 이름 하나의 존재/부재를 각각 묻던
    단언들과 다른 질문이다: 그쪽은 "우리가 아는 이름"만 보고, 시험 배선이 곁들여 심은 **모르는
    이름**은 아무도 말하지 않는다. selftest 는 프로브·러너·호스트 파사드를 창에 얹으므로 그
    곁들임이 실제로 생길 수 있는 자리이고, 그래서 차이를 집합으로 확인한다.

    같은 번들·같은 코드 경로다(별도 test bundle 0) — 차이의 원인은 호스트 능력 하나뿐이어야
    한다.

    측정은 ``full`` 실행이 아니라 전용 측정 모드가 낸다. ``full``·쓰기 모드 증거의 최상위 키
    수는 ``packaging/build.ps1`` 의 책임 게이트(43)가 못박은 값이라, 재는 것을 재어지는 것의
    자루에 넣으면 릴리스 빌드가 터진다.
    """
    # 능력 없는 쪽은 위 픽스처가 띄운 **같은 창**의 측정을 재사용한다(부팅을 늘리지 않는다).
    normal = normal_window_evidence["global_delta"]

    # 능력 있는 쪽만 새로 띄운다 — 같은 표현식, 다른 것은 호스트 능력 하나뿐이다.
    home = tmp_path / "delta-capability-home"
    home.mkdir()
    out = tmp_path / "delta-capability.json"
    env = dict(
        os.environ,
        HWPXFILLER_HOME=str(home),
        HWPX_SELFTEST_OUT=str(out),
        HWPX_SELFTEST_GLOBAL_DELTA="1",
    )
    proc = _boot_selftest(env, out=out, what="능력 켠 전역 델타 측정")
    assert out.exists(), f"능력 측정 실패 rc={proc.returncode}: {_tail(proc.stderr)}"
    capability_evidence = json.loads(out.read_text(encoding="utf-8"))
    assert "error" not in capability_evidence, capability_evidence.get("error")
    testing = capability_evidence["global_delta"]

    # 양성 대조 — 두 측정이 실제로 돌았다. 하나라도 오류면 아래 뺄셈은 무의미하다.
    assert "added_globals_error" not in normal, normal["added_globals_error"]
    assert "added_globals_error" not in testing, testing["added_globals_error"]
    assert normal["total_own"] > 500 and testing["total_own"] > 500

    # 능력 있는 창에서 `__hwpxTest` 를 뺀 집합의 정체가, 능력 없는 창의 집합 정체와 **같다**.
    # 이것이 "두 집합은 `__hwpxTest` 하나만 다르다"의 정확한 형태다 — 수량만 비교하면 하나가
    # 사라지고 둘이 생긴 경우를 놓친다.
    assert testing["digest_without_test"] == normal["digest"], (
        "시험 실행의 전역 집합이 정상 실행 + `__hwpxTest` 가 아닙니다 — "
        f"digest {testing['digest_without_test']} != {normal['digest']}"
    )
    assert testing["total_own"] == normal["total_own"] + 1
    assert testing["hwpx_namespace"] == ["__hwpx", "__hwpxTest"]
    assert normal["hwpx_namespace"] == ["__hwpx"]

    # 양성 대조 — digest 가 실제로 이름 집합에 반응한다(항상 같은 값을 내는 상수가 아니다).
    assert testing["digest"] != testing["digest_without_test"]


# --------------------------------------------------------- 예산 사슬 자체의 계약(#427)
# 아래 둘은 **게이트 밖**이다: 창을 띄우지 않고 수치와 문안만 본다. 실앱 게이트가 옵트아웃된
# 환경에서도 층화가 뒤집히는 것은 잡혀야 한다(그 뒤집힘이 곧 옵트아웃 없는 러너의 실패다).


def _cap_covers_layers_beneath(
    cap: float, python_budget: float, cold_budget: float, hard_stop_margin: float
) -> bool:
    """마지막 그물이 그 아래 그물보다 성긴가 — 순수 술어라 대조를 값으로 세울 수 있다."""
    return cap > python_budget + cold_budget + hard_stop_margin


def test_harness_cap_sits_above_every_budget_beneath_it() -> None:
    """마지막 그물은 그 아래 그물보다 **성겨야** 한다 — 아니면 순서가 뒤집힌다.

    예산 사슬의 의도는 값이 아니라 **발화 순서**다: JS 가 먼저 구조화된 실패를 내고, 그 다음
    파이썬이 시끄럽게 끝나고, 하니스는 마지막 그물이다. 하니스 상한이 아래 층의 합보다 작으면
    가장 진단이 빈약한 층이 가장 먼저 발화한다 — #427 에서 실제로 그랬다.

    음성 대조는 **조작한 수치**로 세운다(#428 리뷰 P2). 종전 상수 90 을 "아래 층의 합보다
    작아야 한다"고 단언하면 그 과거값이 생산 예산의 영구 하한이 된다 — 파이썬·콜드 예산을
    정당하게 줄여 합이 90 이하가 되는 순간, 불변식은 멀쩡한데 이 테스트만 붉어진다. 역사는
    계약이 아니다.
    """
    assert _cap_covers_layers_beneath(
        _SELFTEST_TIMEOUT,
        app_mod._SELFTEST_BUDGET_S,
        boot_budget.COLD_BUDGET_SECONDS,
        live_run.RUN_HARD_STOP_MARGIN_S,
    ), (
        f"하니스 상한 {_SELFTEST_TIMEOUT}s 가 아래 층의 합 "
        f"{app_mod._SELFTEST_BUDGET_S + boot_budget.COLD_BUDGET_SECONDS + live_run.RUN_HARD_STOP_MARGIN_S}s"
        " 보다 촘촘합니다 — "
        "가장 진단이 빈약한 층이 먼저 발화합니다."
    )
    # 술어가 뒤집힌 층화를 실제로 거절하는가 — #427 형상(90 < 80+60+60)이 그 표본이다.
    assert not _cap_covers_layers_beneath(90.0, 80.0, 60.0, 60.0)
    # 그리고 성긴 쪽은 통과시킨다(항상 거짓을 내는 술어가 아니다).
    assert _cap_covers_layers_beneath(201.0, 80.0, 60.0, 60.0)


def test_a_boot_timeout_reports_where_it_got_to(tmp_path) -> None:
    """시한 초과는 "N초 기다렸다"로 끝나지 않는다 — 어디까지 갔는지를 말한다.

    *느린 것*과 *매달린 것*은 원인도 조치도 다르다. 증거 파일의 유무가 그 둘을 가르는 가장
    싼 신호이므로(드라이버가 종결에 닿았는가), 두 경우의 문안이 실제로 달라지는지 본다.
    """
    expired = subprocess.TimeoutExpired(
        cmd=["python", "-m", "hwpxfiller.webapp.app", "--selftest"],
        timeout=_SELFTEST_TIMEOUT,
        output="",
        stderr="[hwpx] 마지막 한 줄",
    )
    missing = tmp_path / "absent.json"
    partial = tmp_path / "partial.json"
    reached = tmp_path / "present.json"
    partial.write_text("{", encoding="utf-8")
    reached.write_text("{}", encoding="utf-8")

    hung = _timeout_report(expired, out=missing, what="어떤 부팅", elapsed=170.4)
    writing = _timeout_report(expired, out=partial, what="어떤 부팅", elapsed=170.4)
    slow = _timeout_report(expired, out=reached, what="어떤 부팅", elapsed=170.4)

    assert "어떤 부팅" in hung and "170.4s" in hung
    assert "종결에 못 닿았다" in hung
    assert "쓰는 중 멎었다" in writing
    assert "결과를 쓴 뒤 프로세스 종료에 못 닿았다" in slow
    # 자식이 남긴 마지막 말이 실려야 한다 — 그것이 유일한 창 안쪽 단서일 때가 많다.
    assert "[hwpx] 마지막 한 줄" in hung
    # 예산 사슬 수치를 함께 적는다: 읽는 사람이 "이 상한이 왜 이 값인가"를 되짚을 수 있게.
    assert f"{app_mod._SELFTEST_BUDGET_S:.0f}s" in hung
    for code, target, event in (
        (live_run.RUN_HUNG_EXIT_CODE, missing, "run_hung"),
        (live_run.TEARDOWN_HUNG_EXIT_CODE, reached, "teardown_hung"),
    ):
        stopped = _process_failure_report(
            subprocess.CompletedProcess([], code, stdout="", stderr="hard stop"),
            out=target,
            what="어떤 부팅",
        )
        assert f"event={event} rc={code}" in stopped and "hard stop" in stopped


def test_aggregate_boot_budget_fails_fast_instead_of_burning_the_ci_job(monkeypatch) -> None:
    """전면 매달림에서 남은 부팅은 **기다리지 않는다** — 그 대기가 진단을 삼킨다.

    부팅 하나의 상한을 늘리면 최악의 경우가 곱해진다: 십수 회 × 상한이 CI 잡 상한을
    넘기면 러너가 잡을 죽이고, 그때 이 모듈이 남긴 진단도 커버리지 산출물도 회수되지 못한다
    (#428 리뷰 P1). 그래서 합계에도 상한이 있고, 소진되면 즉시 실패한다.
    """
    monkeypatch.setitem(_boot_waits, "spent_s", _AGGREGATE_BOOT_BUDGET_S)
    monkeypatch.setitem(_boot_waits, "timed_out", ["앞선 부팅"])
    started = time.monotonic()

    with pytest.raises(AssertionError) as excinfo:
        _boot_selftest({}, out=Path("nowhere.json"), what="뒤따르는 부팅")

    assert time.monotonic() - started < 5, "소진 뒤에도 기다렸다면 합계 상한이 무의미하다"
    message = str(excinfo.value)
    assert "합계 예산 소진" in message
    assert "기다리지 않고 실패" in message
    # 이 부팅의 잘못이 아니라는 것과, 먼저 무너진 자리가 어디인지 둘 다 말한다.
    assert "앞선 부팅" in message
    assert "전면 매달린" in message


def _aggregate_health_note(spent: float, boots: int) -> "str | None":
    """합계 상한 대비 정상 소진의 건강 소견 — **보고**용이고 게이트가 아니다(#477).

    기준은 임의의 비율이 아니라 **의미 있는 불변식**이다: 정상 실행이 부팅 하나 몫의 시한조차
    남기지 못하면, 고립된 매달림 한 번에도 합계가 소진돼 나머지가 통째로 실패한다. 다만 그
    소진을 만드는 것은 러너 속도라, 공유 CI 에서 이 문턱으로 머지를 막으면 제품이 아니라
    인프라를 재는 축이 거부권을 갖는다(#477 의 진단 그대로). 넘으면 시끄럽게 적는다 — 그것이
    합계 상한 재조정의 신호다.
    """
    if spent >= _AGGREGATE_BOOT_BUDGET_S - _SELFTEST_TIMEOUT:
        return (
            f"정상 실행({boots}부팅)이 {spent:.0f}s 를 썼습니다 — 합계 상한 "
            f"{_AGGREGATE_BOOT_BUDGET_S:.0f}s 에서 부팅 하나 몫({_SELFTEST_TIMEOUT:.0f}s)조차 "
            "남기지 못합니다. 고립된 매달림 한 번에 나머지가 통째로 실패합니다"
            " (#477 보고 축 — 차단하지 않습니다)."
        )
    return None


def test_the_aggregate_health_note_fires_and_stays_quiet_on_the_right_sides() -> None:
    """보고 술어의 양·음성 — 경보로 강등한 문턱이 실제로 무는지 합성 수치로 고정한다(#477).

    단언을 경보로 바꾸면 술어가 죽어도 아무도 모른다 — 침묵과 초록이 구별되지 않는다.
    게이트 밖 층이다: 창 없이 돈다.
    """
    line = _AGGREGATE_BOOT_BUDGET_S - _SELFTEST_TIMEOUT
    fired = _aggregate_health_note(line, boots=7)
    assert fired is not None and "차단하지 않습니다" in fired and "7부팅" in fired
    assert _aggregate_health_note(line - 1.0, boots=7) is None


@pytest.fixture(scope="module", autouse=True)
def _healthy_run_leaves_room_for_a_hang():
    """양성 대조 — 정상 실행이 합계 상한에 걸리면 그 상한은 매달림이 아니라 느린 러너를 잡는다.

    **세지 않고 잰다**(#428 리뷰 P2). 종전에는 소스에서 ``_boot_selftest(`` 호출 지점을
    정규식으로 세어 부팅 수를 추정했는데, 그 추정은 세 군데서 틀렸다: 파라미터화 배수를
    빠뜨렸고(글꼴 배율 ×2 가 두 곳, 기하 ×3), 프로세스를 띄우지 않는 fail-fast 단위 테스트까지
    셌다. 11 대 14 — 안전 여유를 과소평가한 채 초록이었다. 「파라미터화 포함」이라 적힌 주석은
    살고 그 결과는 죽어 있었던 셈이라, 실측으로 바꾼다.

    판정은 :func:`_aggregate_health_note` 가 들고, 여기서는 **경보로 낸다**(#477) — 문턱의
    불변식은 유효하지만 그것을 넘게 만드는 것은 러너 속도이고, 그 축은 차단하지 않는다.
    """
    yield
    if _boot_waits["timed_out"]:
        return  # 매달림이 있었던 실행은 「정상 실행」의 표본이 아니다
    spent = float(_boot_waits["spent_s"])
    boots = int(_boot_waits["boots"])
    if not boots:
        return  # 게이트 옵트아웃 — 부팅이 없었으므로 잴 것도 없다
    note = _aggregate_health_note(spent, boots)
    if note is not None:
        warnings.warn(note, stacklevel=1)


def test_a_dead_probe_names_itself_instead_of_raising_keyerror() -> None:
    """프로브 하나가 죽었을 때 **원인 한 줄**이 남는가 — 그림자 KeyError 열몇 개가 아니라.

    러너가 실패한 프로브의 키를 안 내는 것은 옳다(부분 결과 금지). 문제는 소비자 쪽이었다:
    ``evidence["job_mirror"]`` 로 곧장 읽으면 원인 하나가 ``KeyError`` 열몇 개로 번역돼
    로그에서 진짜 사유를 파묻는다(#429 — CI 로그 실패 11건 중 원인은 첫 줄 하나였다).
    """
    healthy = {"job_mirror": {"mirror_line": "x"}}
    assert probe(healthy, "job_mirror") == {"mirror_line": "x"}

    dead = {"error": "[job_mirror/run/deadline_exceeded] 시한 2500ms 초과"}
    with pytest.raises(AssertionError) as excinfo:
        probe(dead, "job_mirror")

    message = str(excinfo.value)
    assert "job_mirror" in message
    assert "그 프로브" in message, "이 테스트의 단언이 아니라는 것을 말해야 한다"
    assert "deadline_exceeded" in message, "러너가 남긴 사유가 실려야 한다"


def test_the_tightest_probe_budget_is_not_an_outlier() -> None:
    """가장 촘촘한 프로브 예산이 형제들과 **자릿수로** 벌어져 있지 않다.

    `job_mirror` 는 200ms 였다 — 같은 클러스터의 2500ms 형제들보다 두 자릿수 작았고, 그 값은
    레거시의 sleep 하나를 옮긴 것이지 이 프로브가 하는 일(277줄 동기 DOM 읽기)을 잰 값이
    아니었다(#429). 근거문이 그 사실을 스스로 적어 두고도 값은 그대로였다.
    """
    source = source_text("src", "selftest", "probes", "job.js")
    budgets = [int(value) for value in re.findall(r"deadlineMs:\s*(\d+)", source)]
    waiting = [value for value in budgets if value > 0]  # 0 = 동기 읽기, 대기 없음

    assert waiting, "대기하는 프로브가 하나도 없다면 이 대조가 무의미하다"
    assert min(waiting) * 10 >= max(waiting), (
        f"가장 촘촘한 예산 {min(waiting)}ms 가 가장 넉넉한 {max(waiting)}ms 와 자릿수로 "
        "벌어져 있습니다 — 그 값이 무엇을 재고 나온 것인지 근거문을 확인하세요."
    )
