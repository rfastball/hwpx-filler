"""실앱 WebView2 게이트 — ``--selftest`` 로 실 창을 띄워 렌더/브리지 DOM 을 되읽어 단언(#30 접근 A).

파이썬 ``html.parser`` 계약(:mod:`test_web_dom_contract`)은 배포 ``web/index.html`` 의 *정적*
구조(전역 id 유일성·화면 루트)만 본다 — 렌더 로직은 안 돈다. 이 모듈은 그 위층을 메운다:
실 :class:`~hwpxfiller.webapp.app.WebFrontend` + 실 컨트롤러 + 실 ``render()`` 를 pywebview 로
구동하고 ``evaluate_js`` 로 DOM 을 되읽어 **렌더 거동**(창 부팅·기본 화면·KPI 실렌더·내비 실체)을
CI 에서 가드한다. #29 봉합 검증에 쓴 일회용 드라이버를 커밋된 게이트로 승격한 것(#30 결정: 접근 A).

**Windows/WebView2 전용.** 데스크톱 세션이 없는 헤드리스 러너는 ``HWPX_SKIP_GUI_TESTS=1`` 로
명시 옵트아웃한다 — 런타임 부재를 자동 감지해 조용히 스킵하지 않는다(confirm-or-alarm: 커버리지
착시 금지). 실행 자리는 ``build.ps1``/``test.ps1`` (WebView2 존재). 이 경계는 "게이트 테스트"이지
클라우드-CI 헤드리스 커버가 아니다 — 잔여(#27·#28)가 애초에 Windows 앱 focus/scroll/layout
거동이라 정합적이다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# 게이트: Windows 아니거나 명시 옵트아웃이면 스킵. 자동 감지 스킵 아님(위 docstring).
_GUI_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_GUI_TESTS"))
_GATE_REASON = "실앱 WebView2 게이트 — Windows 데스크톱 세션 전용(HWPX_SKIP_GUI_TESTS=1 로 옵트아웃)"

# 창 부팅(WebView2 콜드스타트) + 드라이버 sleep(4.5s) + 되읽기 여유. 매달림은 실패로 시끄럽게.
_SELFTEST_TIMEOUT = 90


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
    proc = subprocess.run(
        [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SELFTEST_TIMEOUT,
    )
    assert out.exists(), (
        "selftest 결과 파일 미생성 — 창 부팅/렌더 실패 가능. "
        f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
class TestWebSelftestGate:
    """실 창을 띄워 되읽은 DOM 스냅샷에 대한 렌더 거동 계약."""

    def test_no_probe_error(self, selftest_result: dict) -> None:
        # evaluate_js 프로브가 예외 없이 전부 돌았는가(브리지/렌더 파이프 무결).
        assert "error" not in selftest_result, selftest_result.get("error")

    def test_document_title_rendered(self, selftest_result: dict) -> None:
        # 실 DOM 의 document.title 이 비어있지 않음 = 문서 부팅·셸 로드 확인.
        assert selftest_result["title_dom"]

    def test_all_nav_buttons_rendered(self, selftest_result: dict) -> None:
        # 7화면 내비(.navbtn) 가 실체로 그려짐 — 화면 소실 회귀 가드(+pool, #26 #4).
        assert selftest_result["nav_count"] == 7

    def test_home_is_default_screen(self, selftest_result: dict) -> None:
        # 허브(홈)가 기본 활성 화면으로 뜸(scr-home.on).
        assert selftest_result["home_on"] is True

    def test_pool_screen_actually_rendered(self, selftest_result: dict) -> None:
        # 데이터 관리 화면(#26 #4)이 실앱에서 init·렌더됨(빈 상태 문구도 렌더로 침).
        assert selftest_result["pool_rendered"] is True

    def test_pool_source_buttons_present(self, selftest_result: dict) -> None:
        # 2소스 진입점(#26 #6) — run·matrix·txt 의 '등록 데이터…' 버튼이 실 DOM 에 있다.
        assert selftest_result["pool_buttons"] is True

    def test_home_kpis_actually_rendered(self, selftest_result: dict) -> None:
        # home.js 가 push 스냅샷으로 KPI 타일을 실제 렌더 = Python→웹 관측 푸시 왕복 확인.
        assert selftest_result["home_kpi_count"] >= 1

    def test_modal_opens_with_initial_focus_inside(self, selftest_result: dict) -> None:
        # 커스텀 모달을 열면 hidden 해제 + 초기 포커스가 모달 안(pasteText)으로 들어간다(#27/#28).
        m = selftest_result["modal_a11y"]
        assert m["opened"] is True
        assert m["focus_in"] == "pasteText"

    def test_modal_escape_closes_and_restores_focus(self, selftest_result: dict) -> None:
        # Escape 로 닫히고, 포커스가 열기 직전 트리거로 복귀한다(조용한 포커스 유실 금지 — #28).
        m = selftest_result["modal_a11y"]
        assert m["closed_by_escape"] is True
        assert m["focus_restored"] == m["focus_before"]

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

    def test_responsive_layout_collapses_at_min_width(self, selftest_result: dict) -> None:
        # 최소폭(760<820 경계)에서 .app 이 세로 단일열(1 track)로 접힘 — 최소 크기 가로 오버플로 회귀 가드(#27).
        narrow = selftest_result["grid_narrow"]
        assert len(narrow.split()) == 1, f"최소폭에서 .app 이 단일열로 안 접힘: {narrow!r}"

    def test_responsive_layout_restores_two_panes_when_wide(self, selftest_result: dict) -> None:
        # 넓힐 때(경계 위) .app 이 2판(2 tracks, 레일+스테이지)으로 복귀 — 경계가 죽어 상시 적층되는 회귀 가드(#27).
        wide = selftest_result["grid_wide"]
        assert len(wide.split()) == 2, f"넓은 폭에서 .app 이 2판으로 안 펴짐: {wide!r}"

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
        # 4개 실화면이 shipped __push 경로로 실 스냅샷을 재렌더해도 던지지 않는다 —
        # Preserve.around 래핑이 실 render() 를 깨지 않음을 실 DOM 에서 가드(#28 완료기준).
        p = selftest_result["preserve_real"]
        for scr in ("txt", "editor", "run", "matrix"):
            assert p.get(scr) == "ok", f"{scr} 실화면 재렌더 실패: {p.get(scr)!r}"

    def test_real_screen_scroll_preserved_end_to_end(self, selftest_result: dict) -> None:
        # 실 txt 화면 프리뷰(#renderView)의 스크롤이 실 재렌더를 가로질러 유지된다(#28) —
        # 합성 픽스처가 아닌 shipped render() 경로의 end-to-end 보존 검증. 보존 없으면 재구성이
        # 0 으로 리셋하므로, 설정값 150 근처(DPI 서브픽셀 스냅 허용 ±2)면 복원된 것.
        p = selftest_result["preserve_real"]
        top = p["txt_scroll_top"]
        assert isinstance(top, (int, float)) and abs(top - 150) < 2, (
            f"실화면 스크롤 유실(재구성이 0 으로 리셋됐거나 예외): {top!r}"
        )

    def test_theme_defaults_to_system_when_unpersisted(self, selftest_result: dict) -> None:
        # 저장된 테마 선택이 없으면 앱은 OS 를 따른다 — data-theme 속성이 없어야(=system) @media 지배.
        # 실수로 특정 테마가 강제되면(속성 상주) OS 추종이 깨지므로 되읽어 가드한다.
        tp = selftest_result["theme_persist"]
        assert tp["data_theme"] is None, f"미저장인데 data-theme 이 강제됨: {tp!r}"
        assert tp["a_card"] == "#ffffff", f"미저장 기본이 라이트 카드가 아님: {tp!r}"


@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_theme_choice_persists_across_restart_without_flicker(tmp_path) -> None:
    """다크모드 선택이 프로세스 재시작을 넘어 유지되고 콜드부트 첫 페인트 전 적용된다(영속+무깜빡임, #74).

    #74 재목적화의 핵심 실증 — 테마 영속이 오리진(포트)에 의존하지 않음을. 두 콜드부트는 각자
    **랜덤 빈 포트**(private_mode=True 기본)를 잡아 오리진이 서로 다르다. localStorage 기반이면
    여기서 리셋됐겠지만, Python 설정(settings.json)은 오리진 비의존이라 유지된다 — 옛 게이트가
    포트를 인위 고정해야만 초록이던 유효성 공백(실사용 미반영)을 이 테스트가 닫는다:
      (1) 쓰기 프로세스가 set_theme('dark') 로 settings.json 에 심고 정식 종료.
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
    cmd = [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"]

    # (1) 쓰기 단계 — 저장 테마를 심고 종료.
    w = subprocess.run(
        cmd, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
        env=dict(base, HWPX_SELFTEST_OUT=str(out_write), HWPX_SELFTEST_SET_THEME="dark"),
    )
    assert out_write.exists(), (
        f"쓰기 단계 결과 미생성 — rc={w.returncode}\nstderr={w.stderr[-2000:]}")
    written = json.loads(out_write.read_text(encoding="utf-8"))
    assert written.get("set_result") == "dark", f"쓰기 단계 set_theme 실패: {written}"

    # (2) 읽기 단계 — 같은 HWPXFILLER_HOME(다른 포트)으로 콜드부트, 주입 적용 결과 되읽기.
    r = subprocess.run(
        cmd, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
        env=dict(base, HWPX_SELFTEST_OUT=str(out_read)),
    )
    assert out_read.exists(), (
        f"읽기 단계 결과 미생성 — rc={r.returncode}\nstderr={r.stderr[-2000:]}")
    tp = json.loads(out_read.read_text(encoding="utf-8"))["theme_persist"]
    assert tp["data_theme"] == "dark", (
        f"콜드부트에서 저장 테마 미적용 — Python 설정 영속 또는 loaded 주입 실패: {tp!r}")
    dark_card = gen.load_tokens()["dark"]["color"]["card_bg"]
    assert tp["a_card"] == dark_card, f"다크 --a-card({dark_card}) 미해소: {tp!r}"

# NOTE(#74): test_stale_cached_asset_not_served_across_restart 삭제 — private_mode=True(인메모리
# 프로필) 복원으로 재시작 간 공유 디스크 캐시가 없어 스테일 자산 서빙 실패모드가 구조적으로
# 불가능해졌다. 지키던 헬퍼 _purge_webview_http_cache 와 asset_stamp 프로브도 함께 은퇴(#69/#71).
