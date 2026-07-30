"""실앱 WebView2 게이트 — ``--selftest`` 로 실 창을 띄워 렌더/브리지 DOM 을 되읽어 단언(#30 접근 A).

파이썬 ``html.parser`` 계약(:mod:`test_web_dom_contract`)은 배포 ``web/index.html`` 의 *정적*
구조(전역 id 유일성·화면 루트)만 본다 — 렌더 로직은 안 돈다. 이 모듈은 그 위층을 메운다:
실 :class:`~hwpxfiller.webapp.app.WebFrontend` + 실 컨트롤러 + 실 ``render()`` 를 pywebview 로
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
import subprocess
import sys
from urllib.parse import quote

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
        # 내비(.navbtn) 가 실체로 그려짐 — 화면 소실 회귀 가드. 기대 수는 NAV_SCREENS가 소유한다.
        from test_web_dom_contract import NAV_SCREENS
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
        assert probe["rows"] == 2, probe
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

    def test_each_action_family_click_dispatches_and_returns_snapshot(
        self, selftest_result: dict,
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
            "all", "recent", "favorites", "needsAction",
        ]

    def test_display_order_axis_survives_the_push_rerender(self, selftest_result: dict) -> None:
        """재작성 F3 — 표시순서를 바꾸면 왕복 뒤에도 고른 값이 남는다.

        이 축의 결함류는 "왕복 중 도착한 push 가 선택기를 옛 값으로 되돌린다"이고, 정적
        계약은 요소 존재까지만 본다. 양성대조(`control_before`)가 먼저 선다 — 렌더가 실제로
        이 요소의 값을 쓴다는 증명이 없으면, 값이 안 바뀌는 프로브도 통과해 버린다.
        """
        v = selftest_result["view_order"]
        assert v.get("error") is None, f"표시순서 프로브 오류: {v!r}"
        assert v["present"] is True and v["options"] == ["sourceDesc", "sourceAsc"]
        assert v["control_before"] is True, "양성대조 실패 — 렌더가 선택기를 쓰지 않습니다."
        assert v["note_before"], "축 옆 재진술 문안이 비어 있습니다(판정 I)."
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

    def test_preview_drawer_renders_the_run_input_and_follows_state(
        self, selftest_result: dict
    ) -> None:
        """재작성 F5 — 드로어가 실제로 값·이름·증거를 그리고, 상태가 면을 여닫는다.

        **양성대조 선행**([[measurement-litmus]]): 데이터 없이 여는 미리보기는 거절이다
        (§18.11-6). 거절과 성사가 다른 값을 내야 이 프로브가 실물을 잰 것이다.

        정적 계약은 배선까지만 본다 — "면은 떴는데 값이 안 그려졌다 / 승인 버튼이 요구
        없이 서 있다 / Python 은 닫혔다는데 면이 남아 있다"는 렌더된 DOM 을 되읽어야 잡힌다
        (F2 PR-B 1R 이 `display:none` 인 채 배선만 있던 버튼을 놓친 자리와 같은 계열).
        """
        d = selftest_result["preview_drawer"]
        assert d.get("error") is None, f"미리보기 프로브 오류: {d!r}"
        assert d["present"] is True and d["hidden_before"] is True
        assert d["opened_without_data"] is False, (
            "데이터·작업 없이 미리보기가 열렸습니다 — 첫 레코드로 대신하지 않는다는 계약 위반."
        )
        assert d["opened"] is True, "성사 경로에서도 면이 열리지 않았습니다(프로브 무력)."
        # 자리는 표시순 서수 1-based 로 그린다.
        assert d["pos_text"] == "2 / 2"
        assert d["prev_disabled"] is False and d["next_disabled"] is True
        assert d["value_rows"] == 2 and d["evidence_rows"] == 1
        assert d["filename"] == "doc-002.hwpx"
        # 「적용 범위」 축은 실렌더에도 없다(U2 §2.3). 종전엔 "「기본 규칙」이라고만 말하고
        # 「이번 생성에만」을 암시하지 말라"였는데, runOverrides 기각·사망으로 값이 하나뿐인
        # 축이 되어 자리째 걷혔다 — 정적 계약이 못 보는 것은 JS 가 그 자리를 **다시 만들지
        # 않는가**이고, 그것은 실렌더에서만 확인된다.
        assert d["scope_axis"] is False, "실렌더에서 적용 범위 축이 재유입됐습니다."
        assert d["approve_shown"] is True and d["flag_shown"] is True
        # 원격 닫힘 — 상태의 진실은 DOM 이 아니라 스냅샷이다.
        assert d["closed_by_state"] is True, "Python 이 닫았는데 면이 남았습니다."
        assert d["focus_returned"] is True, "닫힌 뒤 포커스가 여는 트리거로 돌아오지 않았습니다."
        assert d["focus_on_body"] is False, (
            "초점이 문서 맨 앞으로 떨어졌습니다 — `focus()` 가 조용한 no-op 이 된 증상입니다."
        )

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

    def test_modal_opens_with_initial_focus_inside(self, selftest_result: dict) -> None:
        # 커스텀 모달을 열면 hidden 해제 + 초기 포커스가 모달 안(txtEditName)으로 들어간다.
        # (표적 모달은 draftSaveTplModal 사망으로 txtEditModal 로 재겨눔 — F6 PR-B.)
        m = selftest_result["modal_a11y"]
        assert m["opened"] is True
        assert m["focus_in"] == "txtEditName"

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
        assert m["confirm_display_closed_before"] == "none", "열기 전 confirmModal 이 이미 보입니다."
        assert m["confirm_opened"] is True, "Modal.confirm 이 hidden 을 해제하지 못했습니다."
        assert m["confirm_display_open"] == "flex", "열린 confirmModal 의 display 가 flex 가 아닙니다."
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

    def test_danger_confirm_toggles_visual_variant_without_leaking(self, selftest_result: dict) -> None:
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

    def test_responsive_shell_keeps_all_tabs_reachable_at_min_width(self, selftest_result: dict) -> None:
        # 최소폭(760<820 경계)에서 토바가 축약된다: 브랜드 워드마크는 접히고 탭 3개(기안 탭
        # 사망 — F6 PR-B)는 전부 남으며 가로 오버플로가 없다 — 좁은 창에서 탭이 잘려 화면에
        # 못 가는 것이 상단 셸의 진짜 회귀다(F2 PR-B, 지도 §10.9 4계약면 4행).
        from test_web_dom_contract import NAV_SCREENS
        narrow = selftest_result["grid_narrow"]
        assert narrow["tabs"] == len(NAV_SCREENS), f"최소폭에서 탭이 사라짐: {narrow!r}"
        assert narrow["brand_visible"] is False, f"최소폭에서 브랜드 워드마크가 안 접힘: {narrow!r}"
        assert narrow["overflow"] is False, f"최소폭에서 가로 오버플로: {narrow!r}"

    def test_responsive_shell_expands_topbar_when_wide(self, selftest_result: dict) -> None:
        # 넓힐 때(경계 위) 워드마크가 돌아오고 .app 은 여전히 2행(토바+스테이지)이다 —
        # 축약이 눌러앉아 상시 접힘이 되는 회귀 가드(#27 승계).
        from test_web_dom_contract import NAV_SCREENS
        wide = selftest_result["grid_wide"]
        assert wide["rows"] == 2, f"넓은 폭에서 .app 이 토바+스테이지 2행이 아님: {wide!r}"
        assert wide["brand_visible"] is True, f"넓은 폭에서 브랜드 워드마크가 안 펴짐: {wide!r}"
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

    def test_job_mirror_table_renders_four_state_rows(self, selftest_result: dict) -> None:
        # 「작업」 본문 존 거울 — 합성 스냅샷을 실 render() 에 흘려 필드
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
        # ④ 지문 변화 = 강등(파기 아님) — 실패분을 고르는 순간 결과가 사라지면 안 된다.
        assert j["stale_shown"] and j["alive_after_stale"], j
        # ⑤ 구획 행동은 생성 중 잠긴다(계약면 2) · ⑥ 닫기 뒤 포커스가 다음 행동에 착지.
        # 이름만 바뀐 경우는 **같은 작업**이라 행동이 그대로 남는다(3R P2) — 주체 추적이
        # 정체 변화를 따라오는지 실 렌더로 본다.
        assert j["renamed_rename_shown"] and j["renamed_failedsel_shown"], j
        # 작업 전환 뒤에는 결과가 남되 **행동만 걷힌다**(2R P2) — 편집 진입이 남의 작업을
        # 겨누거나 실패분 선택이 확실한 무동작이 되는 것을 표면에서 끊는다. 증거는 남는다.
        assert j["foreign_rename_hidden"] and j["foreign_failedsel_hidden"], j
        assert j["foreign_evidence_alive"] and j["foreign_stale_names_owner"], j
        assert j["busy_lock_declared"], j
        # 저장 폴더 줄의 숨김은 계산 스타일로 확인한다(display:flex 가 [hidden] 을 이기는
        # 결함 클래스 — 속성만 보는 계약은 이 결함을 통과시킨다).
        assert j["folder_hidden_while_running"] and j["folder_shown_on_result"], j
        # 닫기 뒤 포커스는 **실 DOM 에 착지**한다 — body 낙하가 결함이다. 게이트가 닫혀
        # 있으면 생성 버튼이 disabled 라 구획 자신이 받는다(방금 있던 문맥 유지).
        assert j["closed"] and j["close_focus"] in {"jobGenBtn", "jobResultZone"}, j
        # ⑦ 실행 전 거절은 3태가 아니라 rejected 태 — 눌렀는데 아무 일도 없는 것으로 읽히지 않게.
        assert j["reject_state"] == "rejected" and "빈 값" in j["reject_text"], j
        # ⑧ 실행 기록은 기본 접힘(노이즈 억제)이되 마지막 한 줄은 접힌 채로 보인다 —
        # 접힘이 소음 제거가 되면 이 화면의 유일한 비모달 사건 채널이 조용해진다.
        assert j["runlog_collapsed"] and j["runlog_last_visible"], j
        assert "빈 값" in j["runlog_last"], j

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
        # 행동이 붙은 캡션의 ⤢ 는 오른쪽 끝이다(리뷰 R5) — 규칙은 둘 다 살아 있고 **어느 쪽이
        # 이기는가**만 갈리는 자리라 정적 검사가 못 본다.
        cap = j["cap_actions"]
        assert cap, "행동 캡션(.zone-cap-actions)을 찾지 못했습니다 — 프로브 겨눔 소실."
        assert cap["display"] == "flex", (
            f"행동 캡션이 flex 를 잃었습니다({cap['display']!r}) — 블록 규칙이 곁의 규칙을 덮었습니다."
        )
        assert abs(cap["far_edge"]) <= 1, (
            f"⤢ 가 캡션 오른쪽 끝에서 {cap['far_edge']}px 떨어져 있습니다 — 제목 옆에 붙었습니다."
        )
        # 행동이 붙은 캡션의 ⤢ 는 오른쪽 끝이다(리뷰 R5) — 규칙은 둘 다 살아 있고 **어느 쪽이
        # 이기는가**만 갈리는 자리라 정적 검사가 못 본다.
        cap = j["cap_actions"]
        assert cap, "행동 캡션(.zone-cap-actions)을 찾지 못했습니다 — 프로브 겨눔 소실."
        assert cap["display"] == "flex", (
            f"행동 캡션이 flex 를 잃었습니다({cap['display']!r}) — 블록 규칙이 곁의 규칙을 덮었습니다."
        )
        assert abs(cap["far_edge"]) <= 1, (
            f"⤢ 가 캡션 오른쪽 끝에서 {cap['far_edge']}px 떨어져 있습니다 — 제목 옆에 붙었습니다."
        )
        assert j["cands_row_shown"] and j["cand_buttons"] == 2, j
        # 확인 필요·순위 밖은 후보 줄에서 수치 + 출구로만 말한다(슬라이스 3 구획 이사).
        assert j["cand_exit"] is True, "문서 탐색 출구가 후보 줄에 없습니다."
        assert j["cand_disabled_chips"] == 0, "확인 필요 비활성 칩이 후보 줄에 남아 있습니다."
        assert "2건" in j["cand_more_text"] and "1건" in j["cand_more_text"], j["cand_more_text"]
        assert "문서 작업을 선택하세요" in j["gate_text"], j["gate_text"]
        assert j["gen_disabled"] is True, "prework 상태에서 생성 버튼이 열려 있습니다."
        assert "문서 작업을 선택하면" in j["head_hint"], j["head_hint"]
        assert j["tbl_rows_order"] == ["1", "0"], f"표시순(최신 먼저)이 아닙니다: {j['tbl_rows_order']!r}"
        # #302 리뷰 P2 — prework 은 생성 재진술을 하지 않고(파일명·폴더 정의 불가 = 과진술),
        # 저장 폴더 선택은 작업 속성이라 비활성(선택이 기본값에 조용히 덮이는 창 봉쇄).
        assert j["restate_hidden"] is True, "prework 상태에서 생성 재진술이 노출됩니다."
        assert j["folder_pick_disabled"] is True, "prework 상태에서 폴더 선택이 열려 있습니다."

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
        # 문안은 **완주 스탬프**의 의미와 일치해야 한다(4R P2): 성공 뒤 실패 런이 있으면
        # 스탬프는 앞선 성공에 머무르므로 "마지막 실행"은 거짓이 된다.
        assert j["last_run_text"] == "마지막 성공 실행 2026-07-20", j["last_run_text"]
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
        assert j["fav_sync_sends"] == 0, j["fav_sync_sends"]     # 클릭 = 체인 진입
        assert j["fav_intents"] == "[]", j["fav_intents"]
        assert json.loads(j["fav_chain"])["inflight"] == 1, j["fav_chain"]  # 둘째 대기
        # 발신열 = ① 첫 카드(즐겨찾기 상태) 두 번 = false,true — 클릭 순서 = 쓰기 순서,
        # ② 둘째 카드(미즐겨찾기) 3연속 = true,false,true 뒤 **첫 왕복만 실패로 완료**된
        # 상태의 4번째 클릭 = false. 정리를 값 비교로 하면 최신 의도가 지워져 여기서
        # true 가 나오고(=껐다가 다시 켜짐) 사용자 의도가 소실된다(5R P2).
        assert json.loads(j["fav_order"]) == [
            False, True, True, False, True, False
        ], j["fav_order"]

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
        row = j["browse_rows"][0]      # flex gap 이라 textContent 에는 공백이 없다
        assert row.startswith("견적서") and "없는 열: 담당자" in row, row
        assert "2건" in j["browse_note"], j["browse_note"]
        assert j["browse_focus_is_query"] is True, "탐색 면 초기 포커스가 검색 입력이 아닙니다."
        # 왕복 경합(4R P2): 타이핑 중 도착한 옛 스냅샷은 입력을 덮지 않고, 포커스가 떠난
        # 뒤에는 서버 값으로 확정된다(데이터 존 검색과 같은 규칙).
        assert j["browse_query_kept"] == "견적요청", j["browse_query_kept"]
        assert j["browse_query_settled"] == "견적", j["browse_query_settled"]
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

    def test_job_density_and_expansion_sheets(self, selftest_result: dict) -> None:
        j = selftest_result["job_mirror"]
        assert j.get("error") is None, j
        assert j["mirror_capped"] and j["mirror_capstrip"], j
        assert j["confirm_moved"] and j["confirm_dispatch"] and j["confirm_restored"], j
        assert j["edit_closes_sheets"], j
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

    def test_job_restate_block_lists_selected_names(self, selftest_result: dict) -> None:
        # 재진술 블록 — 선택 2행의 이름 목록이 상시 블록으로 실렌더된다.
        j = selftest_result["job_mirror"]
        assert j["restate_shown"] is True, "재진술 블록이 표시되지 않았습니다(선택 있음)."
        assert j["restate_names"] == 2, f"재진술 이름 목록이 선택 수와 다릅니다: {j['restate_names']!r}"

    def test_job_filter_surface_renders_table_chips_strip(self, selftest_result: dict) -> None:
        # 필터 표면 — 합성 필터 스냅샷이 실 WebView2 에서:
        # 가시 1행 테이블 + <mark> 하이라이트(Python 세그먼트를 그대로 칠함) + 열 머리 필터
        # 아이콘 + 칩 줄(정의 재진술)·가지 ×(프루닝) + 필터 밖 선택 스트립(결정 3) + 선택
        # 유래 수치 병기(S4)로 되읽힌다.
        j = selftest_result["job_mirror"]
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
        assert "정의 매치 1" in j["sel_line"] and "정의 밖 1" in j["sel_line"], (
            f"선택 유래 수치 병기(S4) 누락: {j['sel_line']!r}"
        )

    def test_job_datazone_keeps_row_semantics_and_column_kinds(self, selftest_result: dict) -> None:
        """H-06: native 행/셀 의미와 Python 열 kind가 실 표 조판까지 도달한다."""
        j = selftest_result["job_mirror"]
        assert j["row_role"] is None, "tr에 checkbox role이 남아 native row 의미를 덮었습니다."
        assert j["row_selected"] == "true"
        assert j["row_checkbox"] is True
        assert j["row_doccell_display"] == "flex", "table-cell 대신 내부 래퍼가 flex를 소유해야 합니다."
        assert j["lead_hint"] == "선택하면 파일명이 정해집니다"
        assert j["repeated_placeholder"] == 0
        assert j["amount_align"] == "right"
        assert "tabular-nums" in j["amount_nums"]

    def test_job_row_toggle_is_optimistic_and_uses_live_state(self, selftest_result: dict) -> None:
        """I-217 R2: push를 미결로 둬도 표지가 즉시 뒤집히고 재클릭은 현 DOM 상태를 쓴다."""
        j = selftest_result["job_mirror"]
        assert j["row_optimistic_off"] is True, f"첫 행 토글이 즉시 해제 표지를 못 냈습니다: {j!r}"
        assert j["row_optimistic_on"] is True, f"push 전 재클릭이 즉시 재선택되지 않았습니다: {j!r}"
        assert j["row_toggle_values"] == [False, True], (
            f"재클릭 값이 화면의 현재 상태를 따르지 않습니다: {j['row_toggle_values']!r}"
        )

    def test_filter_panel_shell_appears_before_backend_response(self, selftest_result: dict) -> None:
        """I-217 R4: filter_panel 응답이 미결이어도 제목+로딩 껍데기는 클릭 프레임에 선다."""
        assert selftest_result["job_mirror"]["panel_shell_immediate"] is True

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
        # 세션 가드 확인 본문(결정 27 종류별 수치 재진술) — 합성 문안을 되읽어
        # 수치 배치·소실 목록(행 선택+필터 정의)이 조용히 드리프트하지 않게 한다(RC-02 짝 동형).
        body = selftest_result["job_mirror"]["guard_body"]
        assert "직접 선택 3행" in body, f"선택 수치 미표기: {body!r}"
        assert "정의 매치 2" in body and "정의 밖 1" in body, f"S4 델타 병기 누락: {body!r}"
        assert "데이터를 바꾸면" in body, f"전이 동사구 누락: {body!r}"
        assert "필터 정의(2개 조건)" in body, f"필터 소실 재진술 누락: {body!r}"
        # 실제 파기 집합과 일치(F1 §10.7.3): 빈 값 확인은 set_acquired 가 재평가로 지운다.
        assert "빈 값 확인 2개" in body, f"ack 소실 열거 누락: {body!r}"
        # 필터 정의는 직전 슬롯에 남지만 **소스 일치**를 요구한다 — 조건을 함께 말한다.
        assert "직전 필터 재적용" in body, f"필터 복원 조건 재진술 누락: {body!r}"
        no_ack = selftest_result["job_mirror"]["guard_body_no_ack"]
        assert "빈 값 확인" not in no_ack, f"없는 손실을 열거합니다(과경고): {no_ack!r}"
        assert "직전 필터 재적용" not in no_ack, (
            f"필터 정의가 없는데 복원 문구가 붙습니다(과경고): {no_ack!r}")
        # 데이터 재겨눔 사전 확인은 JS 전용 가드 지점이라 존재 자체를 핀한다.
        assert selftest_result["job_mirror"]["data_guard_wired"] is True, (
            "confirmDataSwapIfArmed 배선이 사라졌습니다 — 데이터 재겨눔 가드(결정 26) 회귀."
        )
        # 직전 필터 재적용 어포던스(결정 28) — 양 분기를 핀해 항상 떠 있는 죽은 버튼을 막는다.
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

    def test_tab_disposition_actually_continues_after_saving(
        self, selftest_result: dict
    ) -> None:
        # F7 1R P1 의 영구 가드 — 「저장하고 이동」은 **저장 뒤 이동까지** 가야 한다.
        # 정적 계약은 이 결함을 못 봤다: 배선·문안·판정이 전부 제자리이고 성사 뒤 **이어짐**만
        # 끊겼다(`doSave` 가 성공에 undefined 를 돌려줘 가드가 조기 반환). 실 클릭 → 실 모달 →
        # 실 재발신 순서를 그대로 밟아 발신 기록으로 센다.
        g = selftest_result["editor_guard"]
        assert g.get("error") is None, f"탭 가드 프로브 예외: {g.get('error')!r}"
        assert g.get("why") == "완료", f"3택 모달이 뜨지 않았습니다: {g!r}"
        assert g.get("modal_label") == "저장하고 이동", (
            f"3택 주 행동 라벨이 다릅니다: {g.get('modal_label')!r}"
        )
        assert g["calls"] == ["goto_section", "save", "goto_section:save"], (
            "저장하고 이동이 저장에서 멈췄습니다 — 사용자가 고른 처분이 절반만 일어납니다"
            f"(발신 기록: {g['calls']!r})."
        )

    def test_discard_confirm_settles_pending_edit_and_cancel_lands_coherently(
        self, selftest_result: dict
    ) -> None:
        # §2.17 2R P2 — 1R 이 버리기를 blur 전에 눌리게 열면서 생긴 자리. 정산 없이 확인을
        # 열면 큐에 든 `set_name` 이 모달이 떠 있는 사이 도착해 `#editor-foot` 을 갈아
        # 끼우고, 저장해 둔 트리거가 분리돼 **취소가 화면 루트로 떨어진다**(모달의 대안
        # 착지 — 키보드 사용자는 화면 처음에서 다시 걸어온다). 정적 계약은 못 본다:
        # 배선·문안·판정이 전부 제자리이고 **비동기 도착 순서**만 어긋나기 때문이다.
        d = selftest_result["editor_discard_cancel"]
        assert d.get("error") is None, f"버리기 취소 프로브 예외: {d.get('error')!r}"
        assert d.get("why") == "완료", f"버리기 확인이 열리지 않았습니다: {d!r}"
        assert d["discard_enabled_on_typing"] is True, (
            "타이핑 직후 버리기가 잠긴 채입니다 — 1R 계약(저장과 같은 술어)이 죽었습니다."
        )
        assert d["flushed_before_open"] is True, (
            "확인이 대기 편집 정산 **전에** 열렸습니다 — 큐의 발신이 모달 뒤에 도착해"
            f" 판정과 화면이 어긋납니다(발신 기록: {d.get('calls')!r})."
        )
        assert d["trigger_connected_at_open"] is True, (
            "확인이 열린 시점의 버리기 버튼이 문서에 붙어 있지 않습니다 — 되돌릴 자리가"
            " 이미 분리됐습니다."
        )
        assert d["focus_back_on_discard"] is True and d["focus_fell_to_screen_root"] is False, (
            "취소 뒤 초점이 버리기 버튼으로 돌아오지 않고 화면 루트로 떨어졌습니다"
            f" (활성 요소 판정: {d!r})."
        )
        # 취소는 **아무것도 버리지 않는다** — 친 값과 dirty 술어(두 버튼 활성)가 그대로다.
        assert d["name_value_after_cancel"] == "공고서 수정", (
            f"취소했는데 친 값이 사라졌습니다: {d['name_value_after_cancel']!r}"
        )
        assert d["discard_enabled_after_cancel"] is True and d["save_enabled_after_cancel"] is True, (
            f"취소 뒤 두 행동이 잠겼습니다 — 손댄 세션인데 버릴 길도 저장할 길도 없습니다: {d!r}"
        )
        assert d["discarded"] is False, "취소했는데 discard_patch 가 발신됐습니다."

    def test_editor_template_tab_renders_txt_band_and_two_txt_tabs(
        self, selftest_result: dict
    ) -> None:
        # F6 PR-B — 「기안」 화면 사망의 TXT 생성 경로 승계처가 실 DOM 에 서는지. 정적
        # 계약은 「배선했지만 영영 안 보이는」 상태를 통과시킨다(F2 PR-B 실증) — 밴드
        # 머리 2종·TXT 선택 버튼·TXT 세션 탭 2개(파일 이름 탭 부재, §3.2)를 실물로 센다.
        b = selftest_result["editor_txt_band"]
        assert b.get("error") is None, f"TXT 밴드 프로브 예외: {b.get('error')!r}"
        assert b.get("why") == "완료", f"TXT 밴드 프로브 미완주: {b!r}"
        assert sorted(b["bands"]) == ["HWPX 서식", "TXT 기안"], (
            f"템플릿 탭 매체 2밴드가 서지 않습니다: {b['bands']!r}"
        )
        assert b["txt_pick"] is True, (
            "TXT 행의 선택 버튼(use-library)이 없습니다 — 목록만 있고 생성 경로가 닫혀 있습니다."
        )
        assert b["txt_tabs"] == 2, (
            f"TXT 세션 탭 수가 2가 아닙니다(파일 이름 탭은 HWPX 속성): {b['txt_tabs']!r}"
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
        # 머리 — 이름은 안정 입력이고 저장 상태가 **판본을 말한다**(§10.13 판정 O 표시 자리 ①).
        assert j["name_input_value"] == "공고서", f"이름 입력이 값을 받지 않습니다: {j!r}"
        assert "r2" in j["save_state"] and "r5" in j["save_state"], (
            f"저장 상태가 판본을 말하지 않습니다 — 아무도 안 읽는 durable 은 조용히 틀린다: {j['save_state']!r}"
        )
        # 진입 문맥 — 자발적 진입이면 침묵, 사유가 있으면 증거·복귀 버튼과 함께 선다.
        assert j["ctx_hidden_when_voluntary"] is True, "할 말이 없는데 배너가 섰습니다."
        assert j["ctx_shown"] is True and j["ctx_return_btn"] is True, (
            f"진입 문맥 배너·복귀 버튼이 서지 않습니다: {j!r}"
        )
        assert "미리보기에서 열었습니다" in j["ctx_text"] and "4 / 12" in j["ctx_text"], (
            f"배너가 사유·증거를 말하지 않습니다: {j['ctx_text']!r}"
        )
        assert j["nav_back_after_leave"] is True, (
            "편집기를 나온 뒤에도 상단 2탭이 숨어 있습니다 — 몰입이 영구 은닉이 됐습니다."
        )

    def test_editor_chip_live_renders_ownership_and_toggle_chips(self, selftest_result: dict) -> None:
        # 매핑 분류 칩-라이브(결정 12·13) — 합성 매핑 스냅샷을 실
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
        assert e["auto_revert_option"] is True, "touched 행에 '자동 제안으로 되돌리기'(↻) 버튼이 없습니다(리뷰 R5)."
        # 그 버튼이 select 와 **같은 줄에** 서는가(U2 §2.6). 정적 CSS 검사로는 못 보고
        # 실렌더 기하로만 드러나는 결함이라 여기서 잰다: 버튼 있는 수동 행과 없는 제안
        # 행의 「데이터 열」 칸 높이가 같으면 줄바꿈이 없는 것이다.
        assert e["src_cell_h_manual"] == e["src_cell_h_suggested"], (
            "재제안 버튼이 select 를 둘째 줄로 밀었습니다 — 수동 행과 제안 행의 칸 높이가 "
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
        assert g["pattern_present"] is True, "파일명 패턴 입력이 없습니다 — 프로브가 겨눌 자리 소실."
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

    def test_editor_library_manage_renders_menus_and_dialog(self, selftest_result: dict) -> None:
        # F8(§10.17.2 판정 D) — 구 tpl 그룹 프로브의 승계 재작성: 관리 표면(그룹·⋮·칩·이동
        # 다이얼로그·행동 줄·결과 줄)이 편집기 「템플릿」 탭 실 WebView2 에 서는지 되읽는다
        # (부록 B-9 자동판 승계). 합성 editor 스냅샷을 실 render() 에 흘린다.
        t = selftest_result["editor_lib_manage"]
        assert t.get("error") is None, f"편집기 관리 표면 프로브 예외: {t.get('error')!r}"
        assert t["toolbar"] == [True, True, True, True], (
            "상단 행동 줄(가져오기·폴더에서 가져오기(#339)·새 TXT·새로고침 — .tpl-libbar"
            f" 승계) 소실: {t['toolbar']!r}"
        )
        assert t["grp_heads"] == 3, f"그룹 헤더 수가 다릅니다(입찰·계약·그룹없음): {t!r}"
        assert t["rows_visible"] == 4, f"접힌 그룹(계약) 행이 뷰에서 제외되지 않았습니다: {t!r}"
        assert t["grp_more"] == 2, "그룹 ⋮ 는 이름 그룹에만 있어야 합니다(「그룹 없음」 제외)."
        assert t["row_more"] == 4, f"행 ⋮ 수가 가시 행 수와 다릅니다(오류 행 포함 도달성): {t!r}"
        assert t["assign_chips"] == 2, "＋그룹지정 칩은 「그룹 없음」 행에만 노출돼야 합니다(결정 2)."
        assert t["fill_warn"] is True, "채움 완화 사전 고지(#154)가 행에 렌더되지 않았습니다."
        assert t["result_line"] is True, "결과 재진술 줄(#tplResult 승계)이 렌더되지 않았습니다."
        assert t["band_caption"] is True, "밴드 캡션(개수·루트 경로 — 점검표 10행)이 없습니다."
        # 그룹 있는 HWPX 행 ⋮ = [링1 상태 동사, 이동, 삭제] — 소비 동사 없음(행 버튼 소유,
        # 같은 동사 2벌 금지). TXT 무그룹 행 ⋮ = [내용 편집, 삭제](이동은 칩 소관).
        assert t["menu_shown"] is True, "행 ⋮ 클릭에 메뉴가 열리지 않았습니다."
        assert t["hwpx_menu_items"] == ["act:compile", "act:review", "move", "delete"], (
            f"그룹 있는 HWPX 행 ⋮ 구성이 [변환·검토·이동·삭제]와 다릅니다: {t['hwpx_menu_items']!r}"
        )
        assert t["menu_closed"] is True, "바깥 클릭에 메뉴가 닫히지 않았습니다."
        assert t["txt_menu_items"] == ["edit", "delete"], (
            f"무그룹 TXT 행 ⋮ 구성이 [내용 편집·삭제]와 다릅니다: {t['txt_menu_items']!r}"
        )
        assert t["group_menu_items"] == ["grp-rename", "grp-disband"], (
            f"그룹 헤더 ⋮ 구성이 [개명·해산]과 다릅니다: {t['group_menu_items']!r}"
        )
        # ＋그룹지정 칩 → 이동 다이얼로그 개폐(기존 #tplMoveModal DOM 재사용).
        assert t["move_hidden_before"] is True, "이동 다이얼로그가 기본 닫힘이 아닙니다."
        assert t["move_shown_after_chip"] is True, "＋그룹지정 칩이 이동 다이얼로그를 열지 않았습니다."
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
            # 「실행 기록」 = 결과 3태 구획이 결과 사건을 가져간 뒤 로그 상자에 남은 역할
            # (F4 판정 D) — 같은 존 안의 부캡션이라 이 목록에 함께 잡힌다.
            "현재 데이터", "본문 확인", "생성 결과", "실행 기록",
            # 「시작하기」 = 데이터·작업이 둘 다 없을 때만 서는 흡수처 출구(F2 PR-B 판정 C).
            # 이 프로브의 합성 상태가 바로 그 상태라 캡션 목록에 함께 잡힌다.
            "시작하기", "이 데이터에 사용할 문서", "선택한 작업", "생성 준비",
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

    def test_milestone_h_disabled_primary_and_pathtrack_hierarchy(self, selftest_result: dict) -> None:
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

    def test_milestone_h_overlay_root_scrollbar_and_sticky_material_render(self, selftest_result: dict) -> None:
        h = selftest_result["milestone_h_overlay"]
        assert h.get("error") is None, h.get("error")
        assert h["pending"] is False
        assert h["overlay_root_direct"] is True and h["overlay_children_owned"] is True
        assert h["scrollbar"] == {
            "width": "8px", "button_display": "none", "button_width": "0px", "button_height": "0px",
        }
        assert h["sticky_material"]["position"] == "sticky"
        assert "blur(14px)" in h["sticky_material"]["backdrop"]

    def test_milestone_h_workcard_and_popover_interactions_render(self, selftest_result: dict) -> None:
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
        assert p["placement"] == "top" and p["in_viewport"] is True and p["origin"].endswith(" bottom")
        assert p["radius"] == "12px" and p["shadow"] != "none"
        assert h["drag_closed"] is True and h["click_after_drag"] is True
        assert h["click_after_right"] is True
        assert h["focusout_closed"] is True and h["scroll_closed"] is True
        assert h["close_all_closed"] is True

    def test_milestone_h_modal_stack_ime_focus_and_short_viewport_render(self, selftest_result: dict) -> None:
        h = selftest_result["milestone_h_overlay"]
        assert h["modal_closed_popover"] is True and h["z_order"] is True
        # 표적 모달 재겨눔(draftSaveTplModal 사망 → txtEditModal, F6 PR-B).
        assert h["modal_focus_in"] == "txtEditName"
        assert h["ime_escape_kept_open"] is True
        assert h["exit_blocks_pointer"] is True and h["menu_trigger_restored"] is True
        assert h["escape_one_layer"] is True
        short = h["short_viewport"]
        # pywebview의 OS 최소 창 높이가 요청한 500px를 564px로 clamp할 수 있으므로 실제
        # innerHeight에서 2×16px inset을 뺀 계약으로 판정한다(720×500 캡처는 별도 시각 QA).
        assert short["viewport"] <= 600 and short["height"] <= short["viewport"] - 32
        assert short["scrollable"] is True and short["actions_reachable"] is True

    def test_editor_library_picker_renders_grouped_select(self, selftest_result: dict) -> None:
        # 에디터 1단계 피커 — 라이브러리가 관리 화면과 같은 그룹 구획(선택 전용)
        # 으로 실 WebView2 에 서는지. 접힌 그룹 행 제외·현 선택 표지·필터 고지·퇴화 평면 되읽기.
        e = selftest_result["editor_lib"]
        assert e.get("error") is None, f"에디터 피커 프로브 예외: {e.get('error')!r}"
        assert e["grp_heads"] == 3, f"그룹 헤더 수가 다릅니다(입찰·계약·그룹없음): {e!r}"
        assert e["rows_visible"] == 3, f"접힌 그룹(계약) 행이 뷰에서 제외되지 않았습니다: {e!r}"
        # 선택 전용 — 현 선택은 「선택됨」(버튼 아님), 나머지 가시 행만 「이 템플릿으로」.
        assert e["current_marked"] == 1, f"현 선택 표지가 다릅니다: {e!r}"
        assert e["pick_btns"] == 2, f"선택 버튼 수가 가시·미선택 행과 다릅니다: {e!r}"
        assert e["import_btn"] is True, "「가져오기…」 어포던스가 없습니다."
        # F6 PR-B — 단일 매체 고지(「HWPX 서식만」)는 2밴드 각자의 산출물 고지로 대체됐다.
        assert e["filter_notice"] is True, "매체 밴드 고지(파일 생성/복사)가 렌더되지 않았습니다."
        assert e["caret_collapsed"] == "visible", f"접힌 그룹 화살표가 상시 노출이 아닙니다: {e!r}"
        # 그룹 헤더 안정 id는 재렌더 뒤 Preserve 포커스 복원의 근거다.
        assert e["grp_head_has_id"] is True, "그룹 헤더에 안정 id 가 없어 토글 뒤 포커스가 사라집니다."
        # 긴 파일명이 선택 동작을 밀지 않게 이름 칸이 말줄임/축소된다.
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
        # 파괴적 덮어쓰기 확인 본문 — 수치와 이름을 실 DOM에서 함께 검증한다.
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

    def test_workbench_is_immersive_and_the_queue_degenerates(
        self, selftest_result: dict
    ) -> None:
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
        assert w["aim_row"] == "수신", f"결과 조각이 소유 규칙 행을 겨누지 못합니다: {w['aim_row']!r}"
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
    cmd = [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"]
    written_proc = subprocess.run(
        cmd, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
        env=dict(
            base,
            HWPX_SELFTEST_OUT=str(out_write),
            HWPX_SELFTEST_SET_FONT_SCALE=scale,
        ),
    )
    assert out_write.exists(), f"배율 쓰기 실패 rc={written_proc.returncode}: {written_proc.stderr[-2000:]}"
    assert json.loads(out_write.read_text(encoding="utf-8"))["set_result"] == scale
    saved = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    saved.update(master_width=333)
    (home / "settings.json").write_text(json.dumps(saved), encoding="utf-8")

    read_proc = subprocess.run(
        cmd, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
        env=dict(base, HWPX_SELFTEST_OUT=str(out_read)),
    )
    assert out_read.exists(), f"배율 되읽기 실패 rc={read_proc.returncode}: {read_proc.stderr[-2000:]}"
    p = json.loads(out_read.read_text(encoding="utf-8"))["personalization_persist"]
    assert p["font_scale"] == scale and p["root_px"] == root_px
    assert p["master_width"] == 333
    assert p["body_overflow"] is False, f"{scale}에서 주요 가로 오버플로: {p!r}"
    full = json.loads(out_read.read_text(encoding="utf-8"))
    # 큰 배율에서도 좁은 창의 탭 도달성과 넓은 창의 토바 전개가 유지된다(배율×셸 교차 회귀).
    from test_web_dom_contract import NAV_SCREENS
    assert full["grid_narrow"]["tabs"] == len(NAV_SCREENS)
    assert full["grid_narrow"]["overflow"] is False
    assert full["grid_wide"]["rows"] == 2 and full["grid_wide"]["brand_visible"] is True


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
    (home / "settings.json").write_text(
        json.dumps({"window_geometry": geometry}), encoding="utf-8"
    )
    out = tmp_path / f"geometry-{mode}.json"
    env = dict(
        os.environ,
        HWPXFILLER_HOME=str(home),
        HWPX_SELFTEST_OUT=str(out),
        HWPX_SELFTEST_GEOMETRY_ONLY="1",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "hwpxfiller.webapp.app", "--selftest"],
        env=env, timeout=_SELFTEST_TIMEOUT, capture_output=True, text=True,
    )
    assert out.exists(), f"창 기하 부팅 실패 rc={proc.returncode}: {proc.stderr[-2000:]}"
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
