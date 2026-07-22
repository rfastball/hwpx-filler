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
        # 내비(.navbtn) 가 실체로 그려짐 — 화면 소실 회귀 가드. 기대 수는 NAV_SCREENS
        # 단일 출처(PR-5 리뷰 F7): matrix 제거 F9 → 실행 사망(슬라이스 3) → 작업 에디터
        # 흡수 사망(슬라이스 5, 결정 39)의 역사는 그 목록의 주석이 진다.
        from test_web_dom_contract import NAV_SCREENS
        assert selftest_result["nav_count"] == len(NAV_SCREENS)

    def test_home_is_default_screen(self, selftest_result: dict) -> None:
        # 허브(홈)가 기본 활성 화면으로 뜸(scr-home.on).
        assert selftest_result["home_on"] is True

    def test_pool_screen_actually_rendered(self, selftest_result: dict) -> None:
        # 데이터 관리 화면(#26 #4)이 실앱에서 init·렌더됨(빈 상태 문구도 렌더로 침).
        assert selftest_result["pool_rendered"] is True

    def test_pool_source_buttons_present(self, selftest_result: dict) -> None:
        # 2소스 진입점(#26 #6) — 작업·기안(구 txt 흡수, 슬라이스 6)의 '등록 데이터…' 버튼이 실 DOM 에 있다.
        assert selftest_result["pool_buttons"] is True

    def test_home_kpis_actually_rendered(self, selftest_result: dict) -> None:
        # home.js 가 push 스냅샷으로 KPI 타일을 실제 렌더 = Python→웹 관측 푸시 왕복 확인.
        assert selftest_result["home_kpi_count"] >= 1

    def test_modal_opens_with_initial_focus_inside(self, selftest_result: dict) -> None:
        # 커스텀 모달을 열면 hidden 해제 + 초기 포커스가 모달 안(draftSaveTplName)으로 들어간다
        # (#27/#28 — 구 pasteModal 은 슬라이스 6 삭제, 같은 Modal 헬퍼 쓰는 생존 모달로 재겨눔).
        m = selftest_result["modal_a11y"]
        assert m["opened"] is True
        assert m["focus_in"] == "draftSaveTplName"

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

    def test_modal_open_rejects_non_modal_target_loudly(self, selftest_result: dict) -> None:
        # #132.4: 이 앱의 숨김 규칙은 `.modal.hidden` 뿐이라, .modal 없는 요소에 Modal.open 하면
        # `.hidden` 토글이 조용한 no-op(뜨지도 숨지도 않음)이 된다. confirm-or-alarm: 조용히
        # 삼키지 말고 loud(console.error) 거절 + 열지 않아야(요소가 hidden 유지) 한다.
        m = selftest_result["modal_a11y"]
        assert m["non_modal_open_rejected_loud"] is True, (
            "Modal.open 이 .modal 없는 요소를 조용히 삼켰습니다 — loud 거절(console.error)+미개방 기대."
        )

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
        # (구 txt 는 슬라이스 6 삭제 — 같은 세션 팩토리를 쓰는 「기안」으로 재겨눔.)
        p = selftest_result["preserve_real"]
        for scr in ("draft", "editor", "job"):
            assert p.get(scr) == "ok", f"{scr} 실화면 재렌더 실패: {p.get(scr)!r}"

    def test_real_screen_scroll_preserved_end_to_end(self, selftest_result: dict) -> None:
        # 실 기안 맞추기 표 패널(#draftTokPanel, max-height 180px·overflow auto)의 스크롤이 실
        # 재렌더를 가로질러 유지된다(#28) — 합성 픽스처가 아닌 shipped render() 경로의 end-to-end
        # 보존 검증. 카드 렌더는 master-detail 우측 패널이 통째로 스크롤하는 설계라(구 txt 전체화면과
        # 다름) 내부 스크롤 요소인 토큰 패널로 겨눈다. 보존 없으면 재구성이 0 으로 리셋하므로,
        # 설정값 60 근처(DPI 서브픽셀 스냅 허용 ±2)면 복원된 것.
        p = selftest_result["preserve_real"]
        top = p["draft_scroll_top"]
        assert isinstance(top, (int, float)) and abs(top - 60) < 2, (
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
        assert any("빈 값 · 클릭=확인" in c for c in chips), f"미입력 칩 미렌더: {chips!r}"
        assert any("비움 확정" in c for c in chips), f"의도적 빈칸 칩 미렌더: {chips!r}"

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

    def test_job_filename_token_danger_blocks_with_an_exit(self, selftest_result: dict) -> None:
        # #128 — 파일명 토큰 danger 는 드리프트와 **같은 자격**이라 같은 자리에서 차단 배너 +
        # 행동 링크로 선다. 종전엔 거울이 「채움」 표를 그려 문서가 건강해 보이고, 재진술은
        # danger 라 말없이 사라지고, 남는 신호는 하단 회색 캡션 한 줄뿐인 막다른 경보였다.
        j = selftest_result["job_mirror"]
        assert j["token_banner"] is True, "미해소 파일명 토큰에 차단 배너가 서지 않았습니다."
        assert j["token_no_table"] is True, (
            "차단 중인데 거울 표가 그대로 남아 문서가 건강해 보입니다(전 행 「채움」)."
        )
        assert j["token_fix_link"] is True, (
            "배너에 행동 링크가 없습니다 — 막다른 경보 금지(결정 36)."
        )
        assert "납품기한" in j["token_banner_text"], (
            f"배너가 남는 토큰을 재진술하지 않습니다: {j['token_banner_text']!r}"
        )
        assert j["token_restate_hidden"] is True, (
            "danger 차단 중 재진술 블록이 떠 있습니다 — '생성 불가'와 'N건 생성'의 모순."
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
        # 무엇이 설치되는지 업고 있는가(#127) — 게이트를 3연언으로 좁혀 파괴는 막았지만,
        # 버튼이 여전히 "직전 필터"라고만 말하면 사용자는 누르기 전엔 알 수 없다.
        assert "(공고명) 포함 「전산」" in selftest_result["job_mirror"]["reapply_title"], (
            "「직전 필터 재적용」 버튼이 설치할 정의를 업고 있지 않습니다: "
            f"{selftest_result['job_mirror']['reapply_title']!r}"
        )

    def test_job_list_groups_render_collapse_and_menu(self, selftest_result: dict) -> None:
        # 좌 목록 그룹·관리 메뉴(결정 43, A안: 구획 안 그룹) — 합성 구획 스냅샷을 실 render()
        # 에 흘려 그룹 헤더 3개(이름 그룹 2 + 「그룹 없음」)·접힌 그룹 행 뷰 제외·행/그룹 ⋮·
        # 접힘 화살표 가시성 계약(결정 5: 접힌 그룹만 상시 노출)·메뉴 개폐를 되읽는다.
        j = selftest_result["job_list_groups"]
        assert j.get("error") is None, f"그룹 목록 프로브 예외: {j.get('error')!r}"
        assert j["grp_heads"] == 3, f"그룹 헤더 수가 다릅니다: {j!r}"
        assert j["rows_visible"] == 3, f"접힌 그룹 행이 뷰에서 제외되지 않았습니다: {j!r}"
        assert j["grp_more"] == 2, "그룹 ⋮ 는 이름 그룹에만 있어야 합니다(「그룹 없음」 제외)."
        assert j["row_more"] == 3, f"행 ⋮ 수가 가시 행 수와 다릅니다: {j!r}"
        # 접힘 화살표: 접힌 그룹=상시 노출, 펼친 그룹=호버 전 은닉(결정 5 — visibility 자동 눈검증).
        assert j["caret_collapsed"] == "visible", f"접힌 그룹 화살표가 상시 노출이 아닙니다: {j!r}"
        assert j["caret_expanded"] == "hidden", f"펼친 그룹 화살표가 호버 전에 보입니다: {j!r}"
        # 행 ⋮ 메뉴 — 실개방(항목 구성 포함) + 바깥 pointerdown 닫기.
        assert j["menu_shown"] is True, "행 ⋮ 클릭에 메뉴가 열리지 않았습니다."
        assert j["menu_items"] == ["edit", "clone", "rename", "move", "delete"], (
            f"메뉴 항목 구성이 결정 43(편집·복제·이름 변경·그룹 이동·삭제)과 다릅니다: {j['menu_items']!r}"
        )
        assert j["menu_closed"] is True, "바깥 클릭에 메뉴가 닫히지 않았습니다."
        assert j["move_modal_hidden"] is True, "그룹 이동 다이얼로그가 기본 닫힘이 아닙니다."
        # 퇴화 불변식(결정 5) — 그룹 0개면 헤더·들여쓰기 없는 평면.
        assert j["flat_heads"] == 0 and j["flat_rows"] == 1, f"퇴화 평면 위반: {j!r}"

    def test_draft_list_groups_render_and_menu(self, selftest_result: dict) -> None:
        # 「기안」 좌 목록(#148 슬라이스 2b) — 「작업」과 같은 그룹 구획 스캐폴드 + 공용
        # grouplist.js 팩토리(⋮ 메뉴·이동 다이얼로그)의 3번째 소비자를 실 render 로 되읽는다.
        # 화면별 id 격리(draftList·draftRowMenu·draftMoveModal)로 job/tpl 과 리스너 충돌 없음.
        d = selftest_result["draft_list"]
        assert d.get("error") is None, f"기안 목록 프로브 예외: {d.get('error')!r}"
        assert d["grp_heads"] == 3, f"그룹 헤더 수가 다릅니다: {d!r}"
        assert d["rows_visible"] == 3, f"접힌 그룹 행이 뷰에서 제외되지 않았습니다: {d!r}"
        assert d["grp_more"] == 2, "그룹 ⋮ 는 이름 그룹에만 있어야 합니다(「그룹 없음」 제외)."
        assert d["row_more"] == 3, f"행 ⋮ 수가 가시 행 수와 다릅니다: {d!r}"
        # 미선택 = **휘발 세션 4존**(결정 5, 슬라이스 3a). 저장/휘발 한 패널(슬라이스 5a — 껍데기
        # stub 폐기, 선택이 실제 복원이 되며 사라졌다). 상시 「이번 세션」 행이 휘발 귀환구.
        assert d["session_shown"] is True, "미선택 상세에 휘발 세션 4존이 서지 않았습니다."
        assert d["vol_row_present"] is True, "상시 「이번 세션」 행(휘발 귀환구)이 없습니다."
        assert d["vol_row_current"] is True, "미결속인데 「이번 세션」 행이 결속 표시(aria-current)가 아닙니다."
        # 행 ⋮ 메뉴 — 골격은 편집 미노출(세션 슬라이스 3): 복제·이름변경·이동·삭제만.
        assert d["menu_shown"] is True, "행 ⋮ 클릭에 메뉴가 열리지 않았습니다."
        assert d["menu_items"] == ["clone", "rename", "move", "delete"], (
            f"골격 메뉴는 편집 미노출(복제·이름변경·이동·삭제)이어야 합니다: {d['menu_items']!r}"
        )
        # 이동 다이얼로그(공용 moveDialog 팩토리 3번째 소비) — ⋮→이동에 열리고 라디오 조립·닫힘.
        assert d["move_shown"] is True, "⋮→이동에 이동 다이얼로그가 열리지 않았습니다."
        assert d["move_opts"] == 4, f"이동 옵션(그룹 2 + 없음 + 새 그룹)이 다릅니다: {d!r}"
        assert d["move_has_new"] is True, "새 그룹 라디오(data-new)가 없습니다."
        assert d["move_closed"] is True, "취소에 이동 다이얼로그가 닫히지 않았습니다."
        # 퇴화 불변식 — 그룹 0개면 헤더 없는 평면.
        assert d["flat_heads"] == 0 and d["flat_rows"] == 1, f"퇴화 평면 위반: {d!r}"

    def test_draft_session_zones_render(self, selftest_result: dict) -> None:
        """「기안」 휘발 세션 4존(#148 슬라이스 3a) — 공용 팩토리의 두 번째 소비 인스턴스 실렌더.

        같은 팩토리를 써도 **id 맵이 어긋나면 이 화면에서만 조용히 죽는다**(getElementById 는
        화면 은닉과 무관하게 해소 — poolList 전례). 존별로 하나씩 실 WebView2 로 되읽는다.
        """
        d = selftest_result["draft_session"]
        assert d.get("error") is None, f"기안 세션 프로브 예외: {d.get('error')!r}"
        # ① 데이터 존 — 승계 계약(필터 좁힘·하이라이트·관통 스트립). 스트립을 떨어뜨리면
        # "필터 밖 선택은 숨기지 않는다"가 거짓이 되어 큐가 거짓말을 한다(결정 7 승계 의무).
        assert d["rows"] == 1, f"필터 적용 가시 행이 1이 아닙니다: {d!r}"
        assert d["mark"] == "전산", f"검색어 하이라이트(<mark>)가 서지 않았습니다: {d!r}"
        assert d["strip_shown"] is True, "필터 밖 선택 스트립이 서지 않았습니다(관통 계약 파손)."
        assert "전산" in d["chips_text"], f"필터 칩 정의줄이 비었습니다: {d['chips_text']!r}"
        # 데이터 해제 버튼(R-flow 결정 30, 리뷰 F — 구 「빠른 기안」 승계) — 데이터 있으면 뜨고,
        # 무데이터(퇴화)면 숨는다. 삭제는 의무를 상속한다: 이 어포던스가 조용히 사라지지 않았음을 못박음.
        assert d["clear_shown"] is True, "데이터가 물렸는데 「데이터 해제」 버튼이 없습니다(어포던스 소실)."
        assert d["clear_hidden"] is True, "무데이터인데 「데이터 해제」 버튼이 남아 있습니다(dead control)."
        # ② 맞추기 표(#148 슬라이스 3b) — 결속(소유권 색)·결속 빈값 미리보기·근사 제안·값 직접
        # 입력을 실 WebView2 로 되읽는다. 표를 조용히 떨어뜨리면 항등 매핑으로 되돌아가(토큰명==
        # 열명 강제) 합병의 정밀도 절반이 사라진다.
        assert d["map_rows"] == 4, f"맞추기 표 행 수가 다릅니다: {d!r}"
        assert d["map_own_auto"] == 2, f"소유권 색 점(결속=auto)이 어긋납니다: {d!r}"
        assert d["map_val_inputs"] == 4, f"값 셀이 전 행 편집 가능(결속 값 고침→상수)이 아닙니다: {d!r}"
        assert d["map_bound_value"] is True, "결속 값 입력에 현재 행의 데이터 값이 차 있지 않습니다."
        assert d["map_suggest"] is True, "무결속 자리의 근사 제안 버튼이 없습니다(결정 30)."
        assert d["map_src_options"] == 4, f"결속 드롭다운 후보((직접 입력)+열 3)가 다릅니다: {d!r}"
        # Codex F1 — 상수(man)인데 소스를 기억한 자리의 드롭다운은 「(직접 입력)」(빈 값). 옛 열이
        # selected 로 이겨 결속된 듯 보이면 표시 ≠ 실제 상태(지배 결함류)다.
        assert d["map_man_src_value"] == "", (
            f"man(소스 기억) 드롭다운이 「(직접 입력)」이 아니라 옛 열을 보입니다(F1): {d['map_man_src_value']!r}"
        )
        # ② 유형·확정 열(#148 슬라이스 4, 결정 12) — 유형 셀렉트는 결속(auto) 행에만(운반 유형이
        # 뜻 있는 자리), 확정 체크박스는 전 행. 판정은 서버 토큰(fmt_kind·confirmed)이고 여긴 되읽기.
        assert d["map_type_selects"] == 2, f"유형 셀렉트가 auto 행에만 뜨지 않았습니다: {d!r}"
        assert d["map_type_options"] == 3, f"유형 후보(텍스트·날짜·금액)가 3 이 아닙니다: {d!r}"
        assert d["map_type_value"] == "amount", (
            f"유형 셀렉트의 유효 선택이 서버 fmt_kind(amount)를 따르지 않습니다: {d['map_type_value']!r}"
        )
        assert d["map_confirmed_checks"] == 4, f"확정 체크박스가 전 행에 뜨지 않았습니다: {d!r}"
        assert d["map_confirmed_checked"] is True, "확정 토큰(공고명)의 체크박스가 체크되지 않았습니다."
        assert d["map_unconfirmed"] is True, "미확정 토큰(비고)의 체크박스가 체크돼 있습니다(표시≠상태)."
        # 확정-비움(결정 12) — 값 셀이 「비워둠(선언)」(「아직 안 씀」 아님)이고 textarea 가 없으며
        # 행이 blank 로 표지된다. 게이트 제외는 Python(pytest)이 잡고 여긴 표면 정직성만.
        assert d["blank_declared_marker"] == "비움 확정", (
            f"확정-비움 값 셀이 「비움 확정」이 아닙니다(문안≠집합): {d['blank_declared_marker']!r}"
        )
        assert d["blank_declared_no_textarea"] is True, "확정-비움 자리에 값 입력 textarea 가 남아 있습니다."
        assert d["blank_declared_row"] is True, "확정-비움 행이 blank 로 표지되지 않았습니다."
        # ③ 원문 뷰 전환(결정 34) — 채운 모습 ↔ 원문(같은 칸의 두 모습). 원문은 휘발 세션의
        # 입력구고 배타 표시다(둘이 동시에 서면 무엇이 진실인지 모른다).
        assert d["view_default_filled"] is True, "기본 보기가 「채운 모습」이 아닙니다(원문 뷰 노출)."
        assert d["view_source_shown"] is True, "「원문」 전환이 배타 표시로 서지 않았습니다."
        assert d["src_has_text"] is True, "원문 뷰 textarea 에 템플릿 원문이 실리지 않았습니다."
        # ③ 미리보기 — 채움 표지 삼분 · 상태 색인 점(빈칸 지도) · 선언 글꼴 추종 · 정렬 린트.
        assert "전산장비 구매" in d["card_render"], f"카드 렌더에 채움 값이 없습니다: {d!r}"
        assert d["card_fill"] is True and d["card_blank"] is True, f"표지 삼분 파손: {d!r}"
        assert d["card_dots"] == 2 and d["card_gap_dot"] is True, f"상태 색인 점 파손: {d!r}"
        assert "작업점 1/2" in d["card_readout"], f"상태 재진술이 다릅니다: {d['card_readout']!r}"
        assert d["font_sel"] == "malgun" and "f-malgun" in d["font_class"], (
            f"대상 글꼴 선언을 렌더가 추종하지 않습니다: {d!r}"
        )
        assert d["lint_shown"] is True and d["lint_fix"] == "fix", f"정렬 린트 파손: {d!r}"
        # ④ 완료 — 복사 동사 + 자유 이동(경계 잠금 포함). 미루기는 **없다**(결정 10 사망 —
        # 죽을 것을 새 표면에 짓지 않는다. 대체 어포던스가 ◀▶·점 클릭이다).
        assert d["copy_enabled"] is True, "작업점이 있는데 복사가 잠겨 있습니다."
        assert d["prev_disabled"] is True and d["next_enabled"] is True, (
            f"자유 이동 경계 잠금이 어긋납니다: {d!r}"
        )
        assert d["defer_absent"] is True, "「기안」에 미루기 버튼이 있습니다(결정 10 사망 위반)."
        # ④ 「템플릿으로 저장」(#148 슬라이스 6, #135) — 구 「빠른 기안」에서 흡수한 두 번째 승격
        # 동사가 실제로 뜬다(붙여넣기 세션에서 「기안으로 저장」 비활성 사유가 가리키는 그 버튼).
        # 휘발 세션 + 원문이면 뜨고, 플래그가 거짓이면(저장 결속·빈손) 숨는다 — 표시≠상태를 실렌더로 못박는다.
        assert d["savetpl_shown"] is True, "휘발 세션에서 「템플릿으로 저장」 버튼이 뜨지 않았습니다(어포던스 소실)."
        assert d["savetpl_hidden"] is True, "플래그 거짓(저장 결속·빈손)인데 「템플릿으로 저장」이 남아 있습니다(dead button)."
        # 큐 퇴화(결정 8·14) — 유효 큐 ≤ 1건(단건·무데이터 가상 1건)이면 큐 장치 3종(진행 색인·
        # ◀▶ 다음 카드·자동 전진)이 숨는다. 무데이터 가상 카드는 작업점 없이도 복사 가능하고,
        # 맞추기 표 값 머리가 「지금 행의 값」→「값」으로 바뀐다. 비퇴화 복귀도 함께 못박는다.
        assert d["degen_dots_hidden"] is True, "퇴화 시 진행 색인 점이 숨지 않았습니다."
        assert d["degen_prev_hidden"] is True and d["degen_next_hidden"] is True, (
            f"퇴화 시 ◀▶ 다음 카드가 숨지 않았습니다: {d!r}"
        )
        assert d["degen_advance_hidden"] is True, "퇴화 시 자동 전진 토글이 숨지 않았습니다."
        assert d["degen_copy_enabled"] is True, "무데이터 가상 카드가 복사 불가입니다(결정 14 위반)."
        assert d["degen_val_head"] == "값", f"무데이터 값 열 머리가 「값」이 아닙니다: {d['degen_val_head']!r}"
        assert d["degen_src_options"] == 1, (
            f"무데이터 결속 드롭다운이 「직접 입력」만이 아닙니다(열 후보 누출): {d['degen_src_options']!r}"
        )
        assert d["nondegen_dots_shown"] is True, "비퇴화(≥2건) 복귀에 진행 색인이 돌아오지 않았습니다."
        # (구 txt_leak 격리 단언은 슬라이스 6 에서 소멸 — 두 번째 인스턴스였던 txt 화면 DOM 이
        # 삭제돼 누출 대상 자체가 없다. datazone 팩토리 격리는 test_web_datazone 이 정적으로 가드.)
        # 유래별 열 게이팅(#148 슬라이스 5a, 결정 7) — 휘발 모드에선 유형·확정(.persist) 열이 숨고
        # 휘발 note 가 뜬다. 저장 기안 선택 → 세션 패널은 그대로 서고(껍데기 없음) 열이 뜨며 원문은
        # 읽기 전용, note 는 사라진다. 겨눔 해제(휘발 귀환) → 패널 유지·열 재숨김(두 세션 병존).
        assert d["persist_hidden_volatile"] is True, "휘발 모드인데 유형·확정 열이 숨지 않았습니다."
        assert d["volatile_note_shown"] is True, "휘발 모드에 「유형·확정은 묻지 않습니다」 note 가 없습니다."
        assert d["saved_session_shown"] is True, "저장 기안 선택에 세션 패널이 사라졌습니다(껍데기 회귀)."
        assert d["saved_persist_shown"] is True, "저장 모드인데 유형·확정 열이 뜨지 않았습니다."
        assert d["saved_src_readonly"] is True, "저장 모드 원문이 읽기 전용이 아닙니다(정의 조용한 분기 위험)."
        assert d["saved_note_absent"] is True, "저장 모드인데 휘발 note 가 남아 있습니다."
        assert d["vol_row_current_saved"] is True, "저장 결속 중인데 「이번 세션」 행이 결속 표시로 남았습니다."
        # 원문바(#148 슬라이스 5b) — 저장 모드: 「사본으로 편집」이 읽기 전용의 유일 출구로 뜨고,
        # 수정됨 표지는 없다(깨끗한 저장 정의). 포크(휘발+수정됨): 사본 버튼 숨고 표지 뜨고 편집 가능.
        assert d["saved_fork_shown"] is True, "저장 모드에 「사본으로 편집」이 없습니다(읽기 전용 막다른 상태)."
        assert d["saved_modbadge_hidden"] is True, "깨끗한 저장 정의인데 수정됨 표지가 떴습니다."
        assert d["saved_srcname"] == "착수계", f"원문바 이름이 템플릿명이 아닙니다: {d['saved_srcname']!r}"
        assert d["fork_fork_hidden"] is True, "휘발(사본)인데 「사본으로 편집」이 남아 있습니다(dead control)."
        assert d["fork_modbadge_shown"] is True, "사본(수정됨)인데 수정됨 표지가 뜨지 않았습니다."
        assert d["fork_src_editable"] is True, "사본인데 원문이 편집 불가입니다(포크 = 읽기 전용 해제)."
        # 저장 모드 원문 정의 잠금(리뷰 5a P1) — 콤보·붙여넣기까지(textarea 만이 아니라). 데이터
        # 컨트롤은 안 잠근다. 휘발 귀환 시 다시 풀린다(조용한 정의 교체 차단 = 계약 거짓말 봉합).
        assert d["saved_tpl_locked"] is True, "저장 모드인데 템플릿 콤보·붙여넣기가 잠기지 않았습니다(원문 조용한 교체)."
        assert d["saved_data_unlocked"] is True, "저장 모드인데 데이터 컨트롤까지 잠겼습니다(과잉 잠금)."
        assert d["back_restores_session"] is True, "휘발 귀환에 세션 패널이 서지 않았습니다."
        assert d["back_persist_hidden"] is True, "휘발 귀환에 유형·확정 열이 다시 숨지 않았습니다."
        assert d["vol_tpl_unlocked"] is True, "휘발 귀환에 템플릿 콤보·붙여넣기가 다시 풀리지 않았습니다."
        # 복원 결속 정직 표시(리뷰 5a P2) — 데이터 미연결이어도 결속된 열이 드롭다운에 selected.
        assert d["restored_bind_option"] == "selected", (
            f"복원 결속(데이터 미연결)이 드롭다운에 정직히 표시되지 않았습니다: {d['restored_bind_option']!r}"
        )
        # 「기안으로 저장」 승격 버튼(#148 슬라이스 5c, #135) — 라이브러리 배접만 활성, 아니면
        # 비활성 + 사유(dead button 금지). 라벨은 유래로 갈린다(휘발/저장).
        assert d["save_disabled_unbacked"] is True, "미배접(붙여넣기)인데 「기안으로 저장」이 활성입니다(dead button)."
        assert d["save_note_shown"] is True, "저장 비활성인데 사유가 없습니다(#133 위반)."
        assert d["save_enabled_backed"] is True, "라이브러리 배접인데 「기안으로 저장」이 비활성입니다."
        assert d["save_note_hidden"] is True, "저장 활성인데 비활성 사유가 남아 있습니다."
        assert d["save_label_volatile"] == "기안으로 저장", f"휘발 라벨이 다릅니다: {d['save_label_volatile']!r}"
        assert d["save_label_saved"] == "다른 이름으로 저장", f"저장 라벨이 다릅니다: {d['save_label_saved']!r}"
        # 세션 교체 가드 문안(리뷰 F6) — 「새 기안」은 세션을 교체하므로 미저장 매핑 편집만으로
        # 무장해도 그 편집을 열거해야 "사라지는 것: ."(빈 목록)이 되지 않는다. 데이터 스왑은 매핑을
        # 유지하므로 같은 상태에서 매핑 편집을 열거하면 over-warn(문안≠집합 결함류 양방향).
        assert "미저장 매핑 편집" in d["guard_body_new_draft"], (
            f"새 기안 가드가 미저장 매핑 편집을 열거하지 않습니다(F6 빈 목록): {d['guard_body_new_draft']!r}"
        )
        assert "사라지는 것: ." not in d["guard_body_new_draft"], (
            f"새 기안 가드 소실 목록이 비었습니다(F6): {d['guard_body_new_draft']!r}"
        )
        assert "미저장 매핑 편집" not in d["guard_body_data_swap"], (
            f"데이터 스왑 가드가 매핑 편집을 열거합니다(over-warn — 스왑은 유지): {d['guard_body_data_swap']!r}"
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

    def test_tpl_media_groups_render_collapse_and_menu(self, selftest_result: dict) -> None:
        # 템플릿 관리(#108) — 매체 구획 + 그 안 그룹(작업 모델 재사용)이 실 WebView2 에서 서는지.
        # 합성 스냅샷을 실 render() 에 흘려 그룹 헤더 3개·접힌 그룹 카드 제외·그룹/카드 ⋮·＋그룹지정
        # 칩(「그룹 없음」에만)·접힘 캐럿 가시성·이동 다이얼로그 개폐를 되읽는다(부록 B-9 자동판).
        t = selftest_result["tpl_groups"]
        assert t.get("error") is None, f"템플릿 그룹 프로브 예외: {t.get('error')!r}"
        assert t["grp_heads"] == 3, f"그룹 헤더 수가 다릅니다(입찰·계약·그룹없음): {t!r}"
        assert t["cards_visible"] == 3, f"접힌 그룹(계약) 카드가 뷰에서 제외되지 않았습니다: {t!r}"
        assert t["grp_more"] == 2, "그룹 ⋮ 는 이름 그룹에만 있어야 합니다(「그룹 없음」 제외)."
        assert t["card_more"] == 3, f"카드 ⋮ 수가 가시 카드 수와 다릅니다: {t!r}"
        assert t["assign_chips"] == 1, "＋그룹지정 칩은 「그룹 없음」 카드에만 노출돼야 합니다(결정 2)."
        # 접힘 화살표: 접힌 그룹=상시 노출, 펼친 그룹=호버 전 은닉(결정 5, job 목록 동형).
        assert t["caret_collapsed"] == "visible", f"접힌 그룹 화살표가 상시 노출이 아닙니다: {t!r}"
        assert t["caret_expanded"] == "hidden", f"펼친 그룹 화살표가 호버 전에 보입니다: {t!r}"
        # 그룹에 속한 카드 ⋮ = [이동, 삭제] · 그룹 헤더 ⋮ = [개명, 해산].
        assert t["menu_shown"] is True, "카드 ⋮ 클릭에 메뉴가 열리지 않았습니다."
        assert t["card_menu_items"] == ["move", "delete"], (
            f"그룹 있는 카드 ⋮ 구성이 [이동·삭제]와 다릅니다: {t['card_menu_items']!r}"
        )
        assert t["menu_closed"] is True, "바깥 클릭에 메뉴가 닫히지 않았습니다."
        assert t["group_menu_items"] == ["grp-rename", "grp-disband"], (
            f"그룹 헤더 ⋮ 구성이 [개명·해산]과 다릅니다: {t['group_menu_items']!r}"
        )
        # ＋그룹지정 칩 → 이동 다이얼로그 개폐.
        assert t["move_hidden_before"] is True, "이동 다이얼로그가 기본 닫힘이 아닙니다."
        assert t["move_shown_after_chip"] is True, "＋그룹지정 칩이 이동 다이얼로그를 열지 않았습니다."
        # 퇴화 불변식(결정 5) — 그룹 0개면 헤더 없는 평면.
        assert t["flat_heads"] == 0 and t["flat_cards"] == 1, f"퇴화 평면 위반: {t!r}"

    def test_editor_library_picker_renders_grouped_select(self, selftest_result: dict) -> None:
        # 에디터 1단계 피커(#108 슬라이스 3) — 라이브러리가 관리 화면과 같은 그룹 구획(선택 전용)
        # 으로 실 WebView2 에 서는지. 접힌 그룹 행 제외·현 선택 표지·필터 고지·퇴화 평면 되읽기.
        e = selftest_result["editor_lib"]
        assert e.get("error") is None, f"에디터 피커 프로브 예외: {e.get('error')!r}"
        assert e["grp_heads"] == 3, f"그룹 헤더 수가 다릅니다(입찰·계약·그룹없음): {e!r}"
        assert e["rows_visible"] == 3, f"접힌 그룹(계약) 행이 뷰에서 제외되지 않았습니다: {e!r}"
        # 선택 전용 — 현 선택은 「선택됨」(버튼 아님), 나머지 가시 행만 「이 템플릿으로」.
        assert e["current_marked"] == 1, f"현 선택 표지가 다릅니다: {e!r}"
        assert e["pick_btns"] == 2, f"선택 버튼 수가 가시·미선택 행과 다릅니다: {e!r}"
        assert e["import_btn"] is True, "「가져오기…」 어포던스가 없습니다."
        assert e["filter_notice"] is True, "매체 자동 필터 고지가 렌더되지 않았습니다(결정 6)."
        assert e["caret_collapsed"] == "visible", f"접힌 그룹 화살표가 상시 노출이 아닙니다: {e!r}"
        # #138 리뷰 F13 — 그룹 헤더 안정 id(재렌더 뒤 Preserve 포커스 복원 근거).
        assert e["grp_head_has_id"] is True, "그룹 헤더에 안정 id 가 없어 토글 뒤 포커스가 사라집니다."
        # #138 리뷰 F14 — 긴 파일명이 선택 동작을 밀지 않게 이름 칸이 말줄임/축소된다.
        assert e["fname_ellipsis"] == "ellipsis", f"파일명 칸 말줄임 미적용: {e['fname_ellipsis']!r}"
        assert e["fname_minwidth"] == "0px", f"파일명 칸 min-width:0 미적용: {e['fname_minwidth']!r}"
        # 퇴화 불변식 — 그룹 0개면 헤더 없는 평면.
        assert e["flat_heads"] == 0 and e["flat_rows"] == 1, f"퇴화 평면 위반: {e!r}"

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
    proc = subprocess.run(
        [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"],
        env=env, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
    )
    assert out.exists(), f"부팅 실패 — rc={proc.returncode}\nstderr={proc.stderr[-2000:]}"
    saved = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    stamp = saved.get("boot_completed_runtime")
    assert isinstance(stamp, str) and stamp, (
        f"완주 스탬프 미기록 — 모든 부팅이 첫 실행으로 남습니다(#77): {saved!r}")
    # 첫 부팅은 넓은 예산이었고, 이 스탬프 뒤로는 좁은 예산이다(판정의 실 왕복).
    assert decide("", stamp)[0] == COLD_BUDGET_SECONDS
    assert decide(stamp, stamp)[0] == WARM_BUDGET_SECONDS
