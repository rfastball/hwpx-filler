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
        # 6화면 내비(.navbtn) 가 실체로 그려짐 — 화면 소실 회귀 가드(matrix 제거 후 F9;
        # +「작업」 화면 #90 → 7, 실행 화면 사망(슬라이스 3, 레일 「실행」 제거) → 6).
        assert selftest_result["nav_count"] == 6

    def test_home_is_default_screen(self, selftest_result: dict) -> None:
        # 허브(홈)가 기본 활성 화면으로 뜸(scr-home.on).
        assert selftest_result["home_on"] is True

    def test_pool_screen_actually_rendered(self, selftest_result: dict) -> None:
        # 데이터 관리 화면(#26 #4)이 실앱에서 init·렌더됨(빈 상태 문구도 렌더로 침).
        assert selftest_result["pool_rendered"] is True

    def test_pool_source_buttons_present(self, selftest_result: dict) -> None:
        # 2소스 진입점(#26 #6) — 작업·txt 의 '등록 데이터…' 버튼이 실 DOM 에 있다.
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

    def test_confirm_modal_toggles_display_and_focuses_cancel(self, selftest_result: dict) -> None:
        # #86/부록 B-9: 네이티브 confirm 대체 모달이 실 앱에서 실제로 열리고 닫히는지 계산 스타일로
        # 확인한다 — .modal{display:flex} 가 hidden 을 덮으면(B-9 결함 클래스) 닫아도 계속 보인다.
        m = selftest_result["modal_a11y"]
        assert m["confirm_display_closed_before"] == "none", "열기 전 confirmModal 이 이미 보입니다."
        assert m["confirm_opened"] is True, "Modal.confirm 이 hidden 을 해제하지 못했습니다."
        assert m["confirm_display_open"] == "flex", "열린 confirmModal 의 display 가 flex 가 아닙니다."
        # 기본 포커스=취소(머무르기) — Enter-반사 파괴 차단(F7, 결정 27/36/38).
        assert m["confirm_focus"] == "confirmModalCancel", (
            f"확인 모달 초기 포커스가 취소가 아닙니다(현재: {m['confirm_focus']!r})."
        )
        assert m["confirm_closed"] is True, "확인 클릭 후 confirmModal 이 다시 hidden 이 아닙니다."
        assert m["confirm_display_closed"] == "none", (
            "닫힌 confirmModal 의 display 가 none 이 아닙니다 — .modal.hidden 이 display:flex 를 "
            "이기지 못합니다(부록 B-9 결함 재발)."
        )

    def test_confirm_modal_serializes_single_inflight(self, selftest_result: dict) -> None:
        # PR #92 리뷰 #1: promise 다이얼로그는 동시 1건 — 미결 confirm 위에 두 번째 confirm 을
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
        # PR #92 리뷰 #1: 포커스 트랩 — 모달의 마지막 포커서블(확인)에서 Tab 이 배경 버튼으로
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
        # 3개 실화면이 shipped __push 경로로 실 스냅샷을 재렌더해도 던지지 않는다 —
        # Preserve.around 래핑이 실 render() 를 깨지 않음을 실 DOM 에서 가드(#28 완료기준).
        p = selftest_result["preserve_real"]
        for scr in ("txt", "editor", "job"):
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

    def test_job_mirror_table_renders_four_state_rows(self, selftest_result: dict) -> None:
        # 「작업」 본문 존 거울(블록 6 ⓑ, 슬라이스 2) — 합성 스냅샷을 실 render() 에 흘려 필드
        # 채움 테이블이 실 WebView2 에서 4행(채움·채움+표시형·미입력·빈칸)으로 그려지고 미입력
        # 행이 클릭형(role=button)인지 되읽는다. 배지=거울의 행(별도 UI 아님)의 실물 검증.
        j = selftest_result["job_mirror"]
        assert j.get("error") is None, f"거울 프로브 예외: {j.get('error')!r}"
        assert j["mirror_rows"] == 4, f"거울 행이 4개가 아닙니다: {j!r}"
        assert j["miss_clickable"] is True, "미입력 거울 행이 클릭형(role=button)이 아닙니다(ADR-E)."
        chips = j["chips"]
        assert any("채움 · 표시형" in c for c in chips), f"표시형 칩 미렌더: {chips!r}"
        assert any("미입력 · 클릭=확인" in c for c in chips), f"미입력 칩 미렌더: {chips!r}"
        assert any("빈칸 선언" in c for c in chips), f"의도적 빈칸 칩 미렌더: {chips!r}"

    def test_job_restate_block_lists_selected_names(self, selftest_result: dict) -> None:
        # 재진술 블록(블록 6 D1-B, 슬라이스 2) — 선택 2행의 이름 목록이 상시 블록으로 실렌더된다.
        j = selftest_result["job_mirror"]
        assert j["restate_shown"] is True, "재진술 블록이 표시되지 않았습니다(선택 있음)."
        assert j["restate_names"] == 2, f"재진술 이름 목록이 선택 수와 다릅니다: {j['restate_names']!r}"

    def test_job_filter_surface_renders_table_chips_strip(self, selftest_result: dict) -> None:
        # 필터 표면(블록 4, 슬라이스 4 PR-2b) — 합성 필터 스냅샷이 실 WebView2 에서:
        # 가시 1행 테이블 + <mark> 하이라이트(Python 세그먼트를 그대로 칠함) + 열 머리 필터
        # 아이콘 + 칩 줄(정의 재진술)·가지 ×(프루닝) + 필터 밖 선택 스트립(결정 3) + 선택
        # 유래 수치 병기(S4)로 되읽힌다.
        j = selftest_result["job_mirror"]
        assert j["tbl_rows"] == 1, f"가시 행 렌더 수가 다릅니다: {j['tbl_rows']!r}"
        assert j["tbl_mark"] == "전산", f"하이라이트 세그먼트 미렌더: {j['tbl_mark']!r}"
        assert j["ficos"] == 2, f"열 머리 필터 아이콘 수가 다릅니다: {j['ficos']!r}"
        assert "「전산」" in j["chips_text"], f"칩 줄 정의 재진술 누락: {j['chips_text']!r}"
        assert j["branch_prune"] is True, "가지 칩 × 프루닝 어포던스가 없습니다."
        assert j["strip_shown"] is True, "필터 밖 선택 스트립이 표시되지 않았습니다(결정 3)."
        assert "1행" in j["strip_text"] and "doc-002.hwpx" in j["strip_text"], (
            f"스트립이 필터 밖 선택을 재진술하지 않습니다: {j['strip_text']!r}"
        )
        assert j["strip_unsel"] is True, (
            "스트립에 항목별 × 해제 어포던스가 없습니다 — 필터 밖 선택을 개별로 뺄 수 없다."
        )
        assert "정의 매치 1" in j["sel_line"] and "정의 밖 1" in j["sel_line"], (
            f"선택 유래 수치 병기(S4) 누락: {j['sel_line']!r}"
        )

    def test_job_filter_panel_hidden_beats_flex(self, selftest_result: dict) -> None:
        # 열 필터 패널 기본 닫힘 — [hidden] 이 .colpanel 의 display:flex 를 실제로 이긴다
        # (부록 B-9 overlay/hidden 충돌 결함류의 자동 눈검증 — 시연에서 실증된 그 결함).
        j = selftest_result["job_mirror"]
        assert j["panel_hidden"] is True, "colpanel [hidden] 이 display:flex 에 져서 항시 떠 있습니다."

    def test_job_guard_body_composes_counts_and_losses(self, selftest_result: dict) -> None:
        # 세션 가드 확인 본문(결정 27 종류별 수치 재진술, 슬라이스 4 PR-3) — 합성 문안을 되읽어
        # 수치 배치·소실 목록(행 선택+필터 정의)이 조용히 드리프트하지 않게 한다(RC-02 짝 동형).
        body = selftest_result["job_mirror"]["guard_body"]
        assert "직접 선택 3행" in body, f"선택 수치 미표기: {body!r}"
        assert "정의 매치 2" in body and "정의 밖 1" in body, f"S4 델타 병기 누락: {body!r}"
        assert "작업을 전환하면" in body, f"전이 동사구 누락: {body!r}"
        assert "필터 정의(2개 조건)" in body, f"필터 소실 재진술 누락: {body!r}"
        # 데이터 재겨눔 사전 확인은 JS 전용 가드 지점 — 존재 핀(삭제 = 결정 26 절반의 조용한
        # 회귀인데 다른 테스트가 못 잡는다, 리뷰 #6).
        assert selftest_result["job_mirror"]["data_guard_wired"] is True, (
            "confirmDataSwapIfArmed 배선이 사라졌습니다 — 데이터 재겨눔 가드(결정 26) 회귀."
        )
        # 직전 필터 재적용 어포던스(결정 28) — 양 분기 핀(켜짐만 고정하면 "항상 떠 있는
        # 죽은 버튼" 회귀가 초록으로 샌다, 리뷰 #3).
        assert selftest_result["job_mirror"]["reapply_shown"] is True, (
            "reapply_available=true 인데 「직전 필터 재적용」 버튼이 표시되지 않았습니다."
        )
        assert selftest_result["job_mirror"]["reapply_hidden"] is True, (
            "reapply_available=false 인데 「직전 필터 재적용」 버튼이 계속 떠 있습니다."
        )

    def test_job_edit_mode_hosts_definition_surface(self, selftest_result: dict) -> None:
        # 에디터 흡수(블록 2 개정, 결정 39~41) — 편집 모드 전환이 실 WebView2 에서 편집 호스트를
        # 켜고 세션 4존을 숨기며(배타 표시 = B-9 overlay/hidden 눈검증의 자동판), 이사한 정의
        # surface 가 같은 3분류를 신규=단계(번호 표지)·편집=탭(자유 이동 버튼)으로 갈라 렌더한다.
        j = selftest_result["job_editmode"]
        assert j.get("error") is None, f"편집 모드 프로브 예외: {j.get('error')!r}"
        assert j["edit_host_shown"] is True and j["zones_hidden"] is True, (
            f"두 모드 배타 표시 실패(호스트/존 동시 표시·동시 은닉): {j!r}"
        )
        assert j["status_text"] == "편집 모드", f"상태 pill 이 편집 모드를 말하지 않습니다: {j['status_text']!r}"
        assert j["wizard_steps"] == 3, f"신규 마법사 단계 표지(번호) 수: {j['wizard_steps']!r}"
        assert j["foot_shown_new"] is True, "신규 마법사 푸터(뒤로/다음)가 표시되지 않았습니다."
        assert j["edit_tabs"] == 3, f"편집 탭 버튼 수: {j['edit_tabs']!r}"
        assert j["foot_hidden_edit"] is True, (
            "편집(탭)의 비저장 탭에서 푸터가 숨지 않았습니다 — 고아 경계선/죽은 내비 잔존."
        )

    def test_editor_chip_live_renders_ownership_and_toggle_chips(self, selftest_result: dict) -> None:
        # 매핑 분류 칩-라이브(블록 2 결정 12·13, 슬라이스 5 PR-3) — 합성 매핑 스냅샷을 실
        # render() 에 흘려 사용할 헤더가 즉시 토글 칩(체크박스 스테이징 소거)으로, 미사용
        # 구역이 펼쳐지고, 소유권 태그 4종과 touched 행 ↩(자동 제안 복귀)가 흡수된 편집
        # 호스트(#jobEditHost) 실 WebView2 에 그려지는지 되읽는다(백엔드는 test_mapping_state).
        e = selftest_result["editor_chip"]
        assert e.get("error") is None, f"칩-라이브 프로브 예외: {e.get('error')!r}"
        assert e["active_chips"] == 3, f"활성 칩(즉시 토글)이 3개가 아닙니다: {e!r}"
        assert e["has_checkbox_staging"] is False, "체크박스 스테이징이 남아 있습니다 — 결정 13 소거 위반."
        assert e["ignored_chip"] is True, "미사용 칩(토글형)이 없습니다."
        assert e["ignored_fold_open"] is True, "ignored_expanded 인데 미사용 구역이 펼쳐지지 않았습니다(결정 13)."
        assert e["use_none_btn"] is True, "'전체 미사용' 버튼이 없습니다(결정 13 대칭쌍)."
        tags = e["tags"]
        for want in ("확정", "수동", "제안", "후보 없음"):
            assert want in tags, f"소유권 태그 '{want}' 미렌더(칩-라이브 결정 12): {tags!r}"
        assert e["auto_revert_option"] is True, "touched 행에 '자동 제안으로 되돌리기'(↩) 버튼이 없습니다(리뷰 R5)."

    def test_job_drift_replaces_mirror_with_blocking_banner(self, selftest_result: dict) -> None:
        # danger(구조 드리프트)는 거울 표와 섞이지 않고 차단 배너 + 행동 링크로 **교체**된다
        # (결정 36·S9). overlay 로 표 위에 얹히는 게 아니라 실제로 표가 사라지고 배너가 선다.
        j = selftest_result["job_mirror"]
        assert j["drift_banner"] is True, "드리프트 차단 배너(role=alert)가 렌더되지 않았습니다."
        assert j["drift_fix_link"] is True, "「편집에서 매핑 확정…」 행동 링크가 없습니다(막다른 경보 금지)."
        assert j["drift_no_table"] is True, "드리프트인데 거울 표가 남아 있습니다(배너로 교체 안 됨)."
        # 재진술 블록은 danger 차단(드리프트 등) 중 숨는다 — "N건 생성" 진술이 차단 배너와 모순 금지.
        assert j["restate_hidden_on_drift"] is True, (
            "danger 차단인데 재진술 블록이 계속 '문서 N건 생성'을 진술합니다 — 차단 배너와 모순."
        )

    def test_job_overwrite_body_composes_counts_and_names(self, selftest_result: dict) -> None:
        # 파괴적 덮어쓰기 확인 본문(A-2-22) — 백엔드 overwrite_text 단언 폐기의 커버리지 짝(리뷰).
        # 수치 배치(총량·파괴분·신규분)와 파일 이름 목록이 합성되는지 실 함수 출력으로 되읽는다.
        # count 스왑·이름 목록 누락이 조용히 배포돼 사용자가 축소된 그림 위에서 덮어쓰는 것을 막는다.
        body = selftest_result["job_mirror"]["ow_body"]
        assert "10건을 생성합니다" in body, f"총량 미표기: {body!r}"
        assert "3건이 기존 파일을 덮어씁니다" in body, f"파괴분 미표기(new_count 와 스왑?): {body!r}"
        assert "나머지 7건은 새 파일" in body, f"신규분 미표기: {body!r}"
        assert "a.hwpx" in body and "b.hwpx" in body, f"덮어쓸 파일 이름 목록 누락: {body!r}"
        assert "외 5개" in body, f"초과분(conflict_more) 미표기: {body!r}"

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
    cmd = [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"]

    # (1) 쓰기 단계 — 저장 테마를 심고 종료.
    w = subprocess.run(
        cmd, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
        env=dict(base, HWPX_SELFTEST_OUT=str(out_write), HWPX_SELFTEST_SET_THEME="dark"),
    )
    assert out_write.exists(), (
        f"쓰기 단계 결과 미생성 — rc={w.returncode}\nstderr={w.stderr[-2000:]}")
    written = json.loads(out_write.read_text(encoding="utf-8"))
    assert written.get("set_result") == "dark", f"쓰기 단계 Theme.set 실패: {written}"

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
# 리뷰3(#74) 보강: InPrivate 의미론이 미래 pywebview/WebView2 에서 변해도, 부팅마다 webview_root
# 를 통째 청소하고 고정 프로필을 새로 만들므로(단일 인스턴스 가드가 이 홈에 우리뿐임을 보장)
# 재시작 간 공유 캐시·구판 잔재는 우리 코드 층에서 이중 차단된다 — 부팅 청소 가드는
# test_webapp_profile.test_prepare_purges_orphans_and_legacy_layout.
