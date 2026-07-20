"""코드리뷰 3차(pool 클러스터) 회귀 가드 — C3·C7·N1·C6.

C3: 동명 확정 재등록이 항목을 통째 교체해 보관이 조용히 active 로 복귀(실행 후보
    재등장)하고 note·created_at 이 소실됐다. 참조(opts)만 갱신하고 수명을 보존한다
    (에디터 ``_do_save`` 미러) + 비활성 상태면 확인 문구가 보존 계약을 재진술한다.
C7: pool.js 액션이 try/catch 없는 await/fire-and-forget 이라 stale 카드(다른 표면에서
    삭제된 항목)의 FileNotFoundError 가 unhandled rejection 으로 삼켜져 버튼 무반응.
    JS 는 loud 재진술(home.js 미러), 백엔드는 stale 을 danger 문구+재스캔으로,
    저장 OSError 는 결과 문구로 표면화한다.
N1: ``poolRefresh``/``tplRefresh`` 배선의 fire-and-forget ``Bridge.call`` — 같은 삼켜짐
    부류. try/catch 표면화를 정적으로 가드한다.
C6: 화면 전환 시 부팅 스냅샷 고착 — "데이터 'X' 등록됨" 직후 데이터 관리로 옮겨도 X 가
    안 보였다. app.js ``Nav.go`` 가 ``_do_refresh`` 보유 화면(화이트리스트)에 자동
    refresh 를 dispatch 한다(실패는 loud, 수동 버튼 유지).

JS 지점은 순수 브라우저 코드라 정적 계약 테스트로 가드한다(test_r3_js 관례).
"""
from __future__ import annotations

import re
from pathlib import Path

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.webapp.screen_home import HomeController
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_pool import PoolController
from hwpxfiller.webapp.screen_template import TemplateController

ROOT = Path(__file__).resolve().parents[1]
WEB_JS = ROOT / "web" / "js"


def _controller(tmp_path: Path) -> "tuple[PoolController, DatasetPoolRegistry]":
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    return PoolController(reg, lambda s, snap: None), reg


# ================================================================== C3
def test_confirmed_reregister_preserves_status_note_created_at(tmp_path):
    """동명 확정 재등록 = 참조 교체만 — 보관 상태·메모·생성시각은 보존(조용한 재활성화 금지)."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "발주", "path": "C:/d/a.xlsx", "note": "6월분"})
    # created_at 을 심어 보존을 관측 가능하게(등록 경로는 현재 created_at 을 채우지 않음).
    item = reg.load("발주")
    item.created_at = "2026-07-01T00:00:00"
    reg.save(item, allow_overwrite=True)
    ctrl.dispatch("archive", {"name": "발주"})

    # 1차: 비활성 상태 재등록 확인 문구가 수명 보존 계약을 재진술한다.
    res1 = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/b.xlsx"})
    assert res1["needs_confirm"] is True
    assert "보관 상태는 유지됩니다" in res1["confirm_text"]
    assert "활성화" in res1["confirm_text"]  # 되돌리는 명시 경로 안내

    # 2차(confirm): 참조만 바뀌고 상태·메모·생성시각은 그대로.
    res2 = ctrl.dispatch(
        "register_excel", {"name": "발주", "path": "C:/d/b.xlsx", "confirm": True})
    assert res2["ok"] is True
    after = reg.load("발주")
    assert after.opts["path"] == "C:/d/b.xlsx"
    assert after.status == "archived"                    # 실행 후보 조용한 재등장 금지
    assert after.note == "6월분"                          # 빈 입력 = 진술 없음 → 보존
    assert after.created_at == "2026-07-01T00:00:00"


def test_active_reregister_confirm_text_omits_state_clause(tmp_path):
    """활성 항목 재등록 확인 문구에는 보관 보존 문구가 붙지 않는다(불필요한 소음 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    res = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/b.xlsx"})
    assert res["needs_confirm"] is True
    assert "보관 상태는 유지됩니다" not in res["confirm_text"]


def test_confirmed_reregister_with_note_replaces_note_only(tmp_path):
    """재등록에서 메모를 입력하면 명시 갱신 — 입력이 비면 보존(조용한 소거·조용한 드롭 둘 다 금지)."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "발주", "path": "C:/d/a.xlsx", "note": "6월분"})
    ctrl.dispatch("register_excel",
                  {"name": "발주", "path": "C:/d/b.xlsx", "note": "7월분", "confirm": True})
    after = reg.load("발주")
    assert after.note == "7월분" and after.opts["path"] == "C:/d/b.xlsx"


def test_confirmed_reregister_updates_sheet_pointer(tmp_path):
    """재등록 opts 갱신에 확정 시트가 동봉된다 — 낡은 시트 포인터 잔존 금지(참조 통째 교체)."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "낙찰", "path": "C:/d/a.xlsx", "sheet": "1월"})
    ctrl.dispatch("register_excel",
                  {"name": "낙찰", "path": "C:/d/b.csv", "confirm": True})
    after = reg.load("낙찰")
    assert after.opts == {"path": "C:/d/b.csv"}  # 시트 없는 새 참조 — 옛 시트 미잔존


def test_cross_kind_reregister_normalizes_kind_and_restates_transition(tmp_path):
    """r4: 동명 비-excel 항목에 엑셀 재등록 확정 = kind 도 excel 로 정규화 + 전이 재진술.

    opts 만 갈아끼우면 kind=nara + opts={path} 하이브리드 손상 항목이 생겨 겨눔 시
    나라 동결 문구로 거절되고(방금 엑셀을 등록했는데!) 요약이 "기간 ?~?" 가 된다.
    확인 문구도 종류 전이를 재진술해야 승인 내용=착지 상태(confirm-or-alarm).
    """
    ctrl, reg = _controller(tmp_path)
    reg.save(DatasetPoolItem(
        name="계약", kind="nara",
        opts={"bgn_dt": "202601010000", "end_dt": "202601310000"}))

    # 1차: 확인 문구가 종류 전이(나라장터→엑셀/CSV)와 기존 참조 소실을 재진술한다.
    res1 = ctrl.dispatch("register_excel", {"name": "계약", "path": "C:/d/a.xlsx"})
    assert res1["needs_confirm"] is True
    assert "나라장터 → 엑셀/CSV" in res1["confirm_text"]
    assert "사라집니다" in res1["confirm_text"]

    # 2차(confirm): kind/opts 정합 착지 — 하이브리드 손상 금지.
    ctrl.dispatch("register_excel",
                  {"name": "계약", "path": "C:/d/a.xlsx", "confirm": True})
    after = reg.load("계약")
    assert after.kind == "excel"
    assert after.opts == {"path": "C:/d/a.xlsx"}


def test_same_kind_reregister_confirm_text_omits_transition_clause(tmp_path):
    """excel→excel 재등록에는 종류 전이 문구가 붙지 않는다(불필요한 소음 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    res = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/b.xlsx"})
    assert res["needs_confirm"] is True
    assert "종류도" not in res["confirm_text"]


# ================================================================== C7(백엔드)
def test_stale_transition_is_loud_and_resyncs(tmp_path):
    """stale 카드 전이 — FileNotFoundError 전파(웹에서 무반응) 대신 danger 재진술+재스캔."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    reg.path_for("발주").unlink()  # 다른 표면(CLI 등)에서 삭제 — 화면 카드는 stale

    for act in ("archive", "activate"):
        res = ctrl.dispatch(act, {"name": "발주"})
        assert res["ok"] is False and "찾을 수 없습니다" in res["error"]
    snap = ctrl.snapshot()
    assert snap["result"]["level"] == "danger"
    assert snap["rows"] == []  # 재스캔으로 stale 카드 소거(화면=실상)


def test_stale_delete_first_phase_is_loud_not_raised(tmp_path):
    """삭제 1차(재진술 로드)도 stale 이면 예외 전파 대신 danger 문구+재스캔."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    reg.path_for("발주").unlink()

    res = ctrl.dispatch("delete", {"name": "발주"})
    assert res["ok"] is False and "찾을 수 없습니다" in res["error"]
    assert ctrl.snapshot()["rows"] == []


def test_register_save_oserror_is_worded_not_raised(tmp_path):
    """저장 OSError(디렉터리 자리 점유 등) — 날것 전파 대신 결과 문구로 loud 재진술."""
    blocked = tmp_path / "f"
    blocked.write_text("디렉터리 자리를 점유한 파일", encoding="utf-8")
    ctrl = PoolController(
        DatasetPoolRegistry(blocked / "datasets"), lambda s, snap: None)

    res = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    assert res["ok"] is False and "저장에 실패" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"


# ================================================================== C7·N1(JS 정적 계약)
def _js(rel: str) -> str:
    return (WEB_JS / rel).read_text(encoding="utf-8")


def _segment(src: str, start: str, end: str) -> str:
    """start 마커부터 end 마커 전까지 — 함수 단위 정적 검사용 절단."""
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_pool_js_list_actions_are_guarded():
    """onListClick — try/catch + alert 재진술, 전이도 await(fire-and-forget 금지)."""
    seg = _segment(_js("screens/pool.js"), "function onListClick", "function openRegModal")
    assert "try {" in seg and "catch" in seg and "window.alert" in seg, (
        "pool.js onListClick 이 무방비 await/fire-and-forget 으로 회귀(C7)."
    )
    assert not re.search(r"(?<!await )Bridge\.call\(", seg), (
        "pool.js onListClick 에 await 없는 Bridge.call 이 남아 있습니다 — "
        "rejection 이 try/catch 를 우회합니다(C7)."
    )


def test_pool_js_register_modal_is_guarded():
    """submitRegModal — 브리지 예외를 try/catch 로 표면화(버튼 무반응 금지)."""
    seg = _segment(_js("screens/pool.js"), "function submitRegModal", "function wire")
    assert "try {" in seg and "catch" in seg and "window.alert" in seg, (
        "pool.js submitRegModal 이 무방비 await 로 회귀(C7)."
    )


def test_refresh_buttons_are_guarded():
    """poolRefresh·tplRefresh — fire-and-forget refresh 배선 금지(N1)."""
    wiring = (
        ("screens/pool.js", "poolRefresh", '$("poolList")'),
        ("screens/template.js", "tplRefresh", '$("tplHwpxGroups")'),
    )
    for rel, btn, nxt in wiring:
        src = _js(rel)
        assert '() => Bridge.call(SCREEN, "refresh"' not in src, (
            f"{rel} 의 {btn} 이 무방비 fire-and-forget 으로 회귀(N1)."
        )
        seg = _segment(src, f'$("{btn}")', nxt)  # 다음 배선 줄 전까지 = 버튼 핸들러
        assert "catch" in seg, f"{rel} 의 {btn} 배선에 catch 표면화가 없습니다(N1)."


# ================================================================== C6
def test_appjs_nav_autorefresh_whitelist_matches_backend():
    """Nav.go 전환 시 자동 refresh — 화이트리스트가 존재하고 백엔드 계약과 일치(C6).

    화이트리스트의 각 화면은 실제로 ``_do_refresh`` 를 가진 컨트롤러여야 한다(미지 액션은
    dispatch 가 loud 거절하므로, 이름만 넣고 백엔드가 없으면 전환마다 경보가 울린다).
    """
    src = _js("app.js")
    m = re.search(r"REFRESH_ON_NAV\s*=\s*\[([^\]]*)\]", src)
    assert m, "app.js 에 REFRESH_ON_NAV 화이트리스트가 없습니다 — 전환 시 스냅샷 고착 회귀(C6)."
    listed = set(re.findall(r'"(\w+)"', m.group(1)))
    # job 포함 — 레지스트리 파생 작업 목록을 스냅샷으로 그리는 유일 생성 표면이 빠지면
    # 에디터에서 막 저장한 작업이 좌 목록에 안 보인다(전환 시 스냅샷 고착). run 은 사망(슬라이스 3).
    assert listed == {"home", "pool", "tpl", "job"}

    # go() 안에서 화이트리스트 판정 후 refresh dispatch + 실패 표면화(.catch).
    seg = _segment(src, "function go(id)", "window.Nav")
    assert "REFRESH_ON_NAV.includes(id)" in seg
    assert re.search(r'Bridge\.call\(id,\s*"refresh"', seg), "전환 자동 refresh dispatch 부재(C6)."
    assert ".catch" in seg, "전환 자동 refresh 실패가 조용히 삼켜집니다(C6·confirm-or-alarm)."

    # 백엔드 상호 검증 — 화이트리스트 화면명 == 컨트롤러 name, 전부 _do_refresh 보유.
    ctrls = {c.name: c for c in (
        HomeController, PoolController, TemplateController, JobController,
    )}
    assert set(ctrls) == listed
    for cls in ctrls.values():
        assert callable(getattr(cls, "_do_refresh", None)), (
            f"{cls.__name__} 에 _do_refresh 가 없습니다 — 화이트리스트와 백엔드 계약 불일치(C6)."
        )


def test_manual_refresh_buttons_kept():
    """자동 refresh 가 수동 새로고침 버튼을 대체하지 않는다 — 명시적 재스캔 경로 유지(C6)."""
    assert '$("poolRefresh")' in _js("screens/pool.js")
    assert '$("tplRefresh")' in _js("screens/template.js")
