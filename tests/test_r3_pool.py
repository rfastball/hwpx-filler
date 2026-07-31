"""코드리뷰 3차(pool 클러스터) 회귀 가드 — C3·C7·N1·C6.

C3: 확정 참조 교체가 항목을 통째 교체해 보관이 조용히 active 로 복귀(실행 후보
    재등장)하고 note·created_at 이 소실됐다. 참조(opts)만 갱신하고 수명을 보존한다.
    (#347 §5.3 재편 뒤 이 경로의 거처는 동명 재등록이 아니라 `relink` 액션이다 —
    같은 슬롯의 참조 교체. 수명 보존 계약은 그대로 승계된다.)
C7: pool.js 액션이 try/catch 없는 await/fire-and-forget 이라 stale 카드(다른 표면에서
    삭제된 항목)의 FileNotFoundError 가 unhandled rejection 으로 삼켜져 버튼 무반응.
    JS 는 loud 재진술(library.js 미러), 백엔드는 stale 을 danger 문구+재스캔으로,
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

from _web_source import SOURCE_INDEX, SOURCE_JS_DIR
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.webapp.screen_library import LibraryController
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_pool import PoolController
from hwpxfiller.webapp.screen_template import TemplateController

WEB_JS = SOURCE_JS_DIR


def _controller(tmp_path: Path) -> "tuple[PoolController, DatasetPoolRegistry]":
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    return PoolController(reg, lambda s, snap: None), reg


# ================================================================== C3(→ relink 승계)
def test_confirmed_relink_preserves_status_note_created_at(tmp_path):
    """확정 다시 연결 = 참조 교체만 — 보관 상태·메모·생성시각은 보존(조용한 재활성화 금지)."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "발주", "path": "C:/d/a.xlsx", "note": "6월분"})
    key = ctrl.snapshot()["rows"][0]["key"]
    # created_at 을 심어 보존을 관측 가능하게(등록 경로는 현재 created_at 을 채우지 않음).
    def stamp(item):
        item.created_at = "2026-07-01T00:00:00"
    reg.mutate(key, stamp)
    ctrl.dispatch("archive", {"key": key})

    # 1차: 기존→새 참조 재진술 확인(무변형).
    res1 = ctrl.dispatch("relink", {"key": key, "path": "C:/d/b.xlsx", "sheet": ""})
    assert res1["needs_confirm"] is True
    assert "a.xlsx" in res1["confirm_text"] and "b.xlsx" in res1["confirm_text"]

    # 2차(confirm): 1차가 보여준 상태의 지문에 결속해 확정 — 참조만 바뀌고 상태·메모·
    # 생성시각은 그대로(코덱스 2R P2: basis 미동봉은 fail-closed 거절).
    res2 = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/b.xlsx", "sheet": "",
                   "confirm": True, "basis": res1["basis"]})
    assert res2["ok"] is True
    after = reg.load(key)
    assert after.opts["path"] == "C:/d/b.xlsx"
    assert after.status == "archived"                    # 실행 후보 조용한 재등장 금지
    assert after.note == "6월분"                          # 빈 입력 = 진술 없음 → 보존
    assert after.created_at == "2026-07-01T00:00:00"


def test_confirmed_relink_with_note_replaces_note_only(tmp_path):
    """다시 연결에서 메모를 입력하면 명시 갱신 — 입력이 비면 보존(조용한 소거·드롭 둘 다 금지)."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "발주", "path": "C:/d/a.xlsx", "note": "6월분"})
    key = ctrl.snapshot()["rows"][0]["key"]
    first = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/b.xlsx", "sheet": "", "note": "7월분"})
    ctrl.dispatch("relink",
                  {"key": key, "path": "C:/d/b.xlsx", "sheet": "", "note": "7월분",
                   "confirm": True, "basis": first["basis"]})
    after = reg.load(key)
    assert after.note == "7월분" and after.opts["path"] == "C:/d/b.xlsx"


def test_confirmed_relink_updates_sheet_pointer(tmp_path):
    """다시 연결 opts 갱신에 확정 시트가 동봉된다 — 낡은 시트 포인터 잔존 금지(참조 통째 교체)."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "낙찰", "path": "C:/d/a.xlsx", "sheet": "1월"})
    key = ctrl.snapshot()["rows"][0]["key"]
    csv = tmp_path / "b.csv"
    csv.write_text("a\n1\n", encoding="utf-8")           # CSV = 시트 축 없음(#33 게이트 통과)
    first = ctrl.dispatch("relink", {"key": key, "path": str(csv), "sheet": ""})
    ctrl.dispatch("relink", {"key": key, "path": str(csv), "sheet": "",
                             "confirm": True, "basis": first["basis"]})
    after = reg.load(key)
    assert after.opts == {"path": str(csv)}  # 시트 없는 새 참조 — 옛 시트 미잔존


def test_cross_kind_relink_normalizes_kind_and_restates_transition(tmp_path):
    """r4: 비-excel 슬롯의 엑셀 다시 연결 확정 = kind 도 excel 로 정규화 + 전이 재진술.

    opts 만 갈아끼우면 kind=nara + opts={path} 하이브리드 손상 항목이 생겨 겨눔 시
    나라 동결 문구로 거절되고(방금 엑셀을 연결했는데!) 요약이 "기간 ?~?" 가 된다.
    확인 문구도 종류 전이를 재진술해야 승인 내용=착지 상태(confirm-or-alarm).
    """
    ctrl, reg = _controller(tmp_path)
    key = reg.add(DatasetPoolItem(
        name="계약", kind="nara",
        opts={"bgn_dt": "202601010000", "end_dt": "202601310000"}))
    ctrl.dispatch("refresh", {})

    # 1차: 확인 문구가 종류 전이(나라장터→엑셀/CSV)와 기존 참조 소실을 재진술한다.
    res1 = ctrl.dispatch("relink", {"key": key, "path": "C:/d/a.xlsx", "sheet": ""})
    assert res1["needs_confirm"] is True
    assert "나라장터 → 엑셀/CSV" in res1["confirm_text"]
    assert "사라집니다" in res1["confirm_text"]

    # 2차(confirm): kind/opts 정합 착지 — 하이브리드 손상 금지.
    ctrl.dispatch("relink", {"key": key, "path": "C:/d/a.xlsx", "sheet": "",
                             "confirm": True, "basis": res1["basis"]})
    after = reg.load(key)
    assert after.kind == "excel"
    assert after.opts == {"path": "C:/d/a.xlsx"}


def test_same_kind_relink_confirm_text_omits_transition_clause(tmp_path):
    """excel→excel 다시 연결에는 종류 전이 문구가 붙지 않는다(불필요한 소음 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res = ctrl.dispatch("relink", {"key": key, "path": "C:/d/b.xlsx", "sheet": ""})
    assert res["needs_confirm"] is True
    assert "종류도" not in res["confirm_text"]


# ================================================================== C7(백엔드)
def test_stale_transition_is_loud_and_resyncs(tmp_path):
    """stale 카드 전이 — FileNotFoundError 전파(웹에서 무반응) 대신 danger 재진술+재스캔."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    reg.slot_path(key).unlink()  # 다른 표면(CLI 등)에서 삭제 — 화면 카드는 stale

    for act in ("archive", "activate"):
        res = ctrl.dispatch(act, {"key": key})
        assert res["ok"] is False and "찾을 수 없습니다" in res["error"]
    snap = ctrl.snapshot()
    assert snap["result"]["level"] == "danger"
    assert snap["rows"] == []  # 재스캔으로 stale 카드 소거(화면=실상)


def test_stale_delete_first_phase_is_loud_not_raised(tmp_path):
    """삭제 1차(재진술 로드)도 stale 이면 예외 전파 대신 danger 문구+재스캔."""
    ctrl, reg = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    reg.slot_path(key).unlink()

    res = ctrl.dispatch("delete", {"key": key})
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


def test_data_picker_row_actions_are_guarded():
    """행 수명 관리(보관·활성화·삭제) — try/catch + 면 안 재진술, 전이도 await(C7 승계).

    구 `pool` 화면 ``onListClick`` 의 의무를 데이터 선택 다이얼로그가 승계한다(재작성 F1).
    재진술 채널만 바뀐다: 화면이 없으니 alert 이 아니라 **면 안 상태줄**이다(오버레이의
    실패 경로 문맥 보존 — 지도 §10.7.1 계약면 4).
    """
    seg = _segment(_js("data_picker.js"), "async function onPinnedClick", "function openRegDialog")
    assert "try {" in seg and "catch" in seg and "setStatus(" in seg, (
        "data_picker.js onPinnedClick 이 무방비 await/fire-and-forget 으로 회귀(C7)."
    )
    assert not re.search(r"(?<!await )Bridge\.call\(", seg), (
        "data_picker.js onPinnedClick 에 await 없는 Bridge.call 이 남아 있습니다 — "
        "rejection 이 try/catch 를 우회합니다(C7)."
    )


def test_data_picker_register_dialog_is_guarded():
    """고정·등록 확정 — 브리지 예외를 try/catch 로 표면화(버튼 무반응 금지)."""
    seg = _segment(_js("data_picker.js"), "async function submitRegDialog", "function onEscCapture")
    assert "try {" in seg and "catch" in seg and "window.alert" in seg, (
        "data_picker.js submitRegDialog 이 무방비 await 로 회귀(C7)."
    )


def test_pool_rescan_is_guarded():
    """풀 재스캔 배선 — fire-and-forget refresh 금지(N1). 재스캔의 거처는 **면을 여는 순간**이다.

    수동 「새로고침」 제거(U2 §2.3) 뒤 재스캔 호출은 `open()` 하나뿐이라, 그 한 자리의
    실패 표면화가 곧 계약의 전부다. 조용히 실패하면 면은 낡은 목록을 새 목록인 양 보인다.
    """
    src = _js("data_picker.js")
    assert '() => Bridge.call(SCREEN, "refresh"' not in src, (
        "data_picker.js 의 풀 재스캔이 무방비 fire-and-forget 으로 회귀(N1)."
    )
    seg = _segment(src, 'bridge.call("pool", "refresh"', "function build()")
    assert "catch" in seg, "풀 재스캔 배선에 catch 표면화가 없습니다(N1)."
    # (tpl 새로고침은 화면 사망(F8 §10.17)으로 편집기 lib-refresh 로 이주 — 그 배선은
    #  editor.js onClick 디스패처의 공용 try/catch 가드가 상속한다: test_r3_editor 의
    #  test_editor_js_click_dispatch_guards_bridge_rejection 소관.)


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
    # job 포함 — 레지스트리 파생 작업 목록을 스냅샷으로 그리는 표면이 빠지면 에디터에서 막
    # 저장한 작업이 좌 목록에 안 보인다(전환 시 스냅샷 고착). run 은 사망(슬라이스 3).
    # draft 는 화면 사망(F6 PR-B) — TXT 작업도 job 목록이 승계한다.
    # pool 은 화면 사망(재작성 F1)이라 빠진다 — 등록 데이터 재스캔은 라우팅이 아니라 데이터
    # 선택 다이얼로그가 **열 때** 지불한다(안 여는 세션이 풀 I/O 를 물지 않는다).
    # tpl 은 화면 사망(F8 §10.17)이라 빠진다 — 편집기는 몰입 표면이라 nav 재당김 대상이
    # 아니고, 템플릿 탭 재진입 재스캔 + tpl push 재당김 구독이 그 역할을 진다.
    assert listed == {"library", "job"}

    # 재당김의 **단일 정의**(8R 근본 조치) — 화이트리스트 판정 + refresh dispatch 가 한 자리에
    # 살고, 전환은 그것을 소비하며 실패를 표면화한다(.catch). 정의가 둘이면 한쪽만 고쳐진다.
    defn = _segment(src, "function refresh(id)", "function go(id, opts)")
    assert "REFRESH_ON_NAV.includes(id)" in defn
    assert re.search(r'Bridge\.call\(id,\s*"refresh"', defn), "재당김 refresh dispatch 부재(C6)."
    seg = _segment(src, "function go(id, opts)", "window.Nav")
    assert re.search(r"refresh\(id\)\.catch", seg), (
        "전환 자동 refresh 실패가 조용히 삼켜집니다(C6·confirm-or-alarm)."
    )
    assert not re.search(r'Bridge\.call\(id,\s*"refresh"', seg), (
        "전환이 재당김을 자체 조립합니다 — 정의가 두 벌이면 한 경로만 고쳐집니다(8R)."
    )

    # 백엔드 상호 검증 — 화이트리스트 화면명 == 컨트롤러 name, 전부 _do_refresh 보유.
    # (TemplateController 는 화면 사망(F8)으로 nav 재당김 목록에서 빠졌다 — 채널은 생존하나
    #  탭이 없어 Nav.go 대상이 아니고, 재스캔은 편집기 lib-refresh·탭 재진입이 진다.)
    ctrls = {c.name: c for c in (LibraryController, JobController)}
    assert set(ctrls) == listed
    for cls in ctrls.values():
        assert callable(getattr(cls, "_do_refresh", None)), (
            f"{cls.__name__} 에 _do_refresh 가 없습니다 — 화이트리스트와 백엔드 계약 불일치(C6)."
        )


def test_pool_rescan_rides_on_opening_the_dialog():
    """데이터 선택 면의 재스캔은 **여는 행위**가 지불한다 — 수동 버튼은 없다(U2 §2.3).

    **뒤집힌 선언이다.** 종전 이름은 `test_manual_refresh_buttons_kept` 였고 "자동 refresh
    가 수동 새로고침 버튼을 대체하지 않는다"(C6)를 지켰다. 그 판정을 U2 에서 되깎았다:
    `open()` 이 열 때마다 `pool.refresh` 를 부르므로 면에 들어온 목록은 **이미 방금 읽은
    것**이고, 버튼에 남는 고유 쓸모는 「모달을 띄워 둔 채 외부에서 바뀐 것」 하나뿐이었다.
    그 하나를 위해 상시 버튼을 두면 목록이 낡았을 수 있다는 인상을 매번 준다.

    **잃은 것을 적어 둔다**(조용한 축소 금지): 면을 열어 둔 채 다른 표면·CLI 가 풀을 바꾸면
    이제 다시 열기 전까지 반영되지 않는다. 손상 격리 판정(`corrupted`)도 같은 호출로만
    갱신되므로 같은 창을 공유한다.

    tpl 축은 무관하다 — 화면 사망(F8)으로 편집기 「템플릿」 탭 lib-refresh 가 승계했고,
    거기는 여는 행위와 별개의 목록이라 수동 재스캔이 계속 산다.
    """
    src = _js("data_picker.js")
    assert "dataPickerRefresh" not in src, (
        "수동 새로고침 버튼이 재유입됐습니다 — open() 이 이미 재스캔합니다."
    )
    index = SOURCE_INDEX.read_text(encoding="utf-8")
    assert 'id="dataPickerRefresh"' not in index, "셸에 새로고침 버튼 DOM 이 남아 있습니다."
    seg = _segment(src, "function open(", "function build()")
    assert 'bridge.call("pool", "refresh"' in seg, (
        "여는 경로의 재스캔이 사라졌습니다 — 수동 버튼도 없으므로 목록을 갱신할 길이 없습니다."
    )
    # tpl 수동 새로고침은 편집기 「템플릿」 탭 상단 행동 줄(lib-refresh)로 이주(F8) — 존속.
    assert 'data-act="lib-refresh"' in _js("screens/editor.js")
