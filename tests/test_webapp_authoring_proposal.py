"""저작 작업대 「데이터로 필드 찾기」(#1156) — ``propose_*`` 액션, 탭 스냅숏 ``proposal``, 연결 초안 정산."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.field_proposal import (
    FieldProposalState,
    LoadedRows,
    chosen_row,
    empty_view,
    normalize_rows,
)
from hwpxfiller.domain.dataset_reference import DatasetReference
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.webapp.authoring_proposal import PoolProposalData, pool_source_of
from hwpxfiller.webapp.screen_authoring import AuthoringController

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
STALE = "문서가 변경되었습니다"
NO_GROUP = "제안을 찾을 수 없습니다. 제안 목록에서 다시 고르세요."

ROWS = [
    {"공고명": "다른 사업", "추정가격": "1", "수요기관": None, "낙찰자결정방법": "", "계약방법": ""},
    {"공고명": "청사 보안 장비 구매", "추정가격": "170309180", "수요기관": "조달청", "낙찰자결정방법": "적격심사",
     "계약방법": "제한경쟁"},
]


class Port:
    def __init__(self, rows=ROWS, *, current=("k1", None), error: str = "") -> None:
        self.rows, self._current, self.error, self.loads = rows, current, error, 0

    def datasets(self) -> list[dict]:
        return [{"key": "k1", "name": "공고 목록"}]

    def load(self, key: str, sheet: str | None) -> LoadedRows:
        self.loads += 1
        return LoadedRows(error=self.error) if self.error else normalize_rows("공고 목록", self.rows)

    def current(self):
        return self._current


def p(*children: str) -> str:
    return "<hp:p><hp:run>" + "".join(f"<hp:t>{child}</hp:t>" if not child.startswith("<") else child
                                      for child in children) + "</hp:run></hp:p>"


def cell(text: str, col: int) -> str:
    return (f"<hp:tc><hp:subList>{p(text)}</hp:subList>"
            f'<hp:cellAddr colAddr="{col}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>')


NOTICE = (
    p("1. 입찰에 부치는 사항"),
    p("가. 공고명: 청사 보안 장비 구매"),
    p("나. 추정가격: 170,309,180원"),
    p("다. 수요기관: 조달청"),
    p("<hp:tbl><hp:tr>" + cell("낙찰자결정방법", 0) + cell("적격심사", 1) + "</hp:tr></hp:tbl>"),
    p("가. 낙찰자는 적격심사 결과로 정합니다."),
    p("나. 적격심사 서류를 냅니다."),
    p("다. 적격심사 일정은 따로 알립니다."),
)


def hwpx_bytes(*paragraphs: str) -> bytes:
    package = HwpxPackage()
    package.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    package.stored.add(MIMETYPE_NAME)
    body = "".join(paragraphs)
    package.entries["Contents/section0.xml"] = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{body}</hs:sec>'.encode()
    return package.to_bytes()


def controller(tmp_path: Path, port=None) -> AuthoringController:
    return AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home", proposal_data=port)


def hwpx_session(ctrl: AuthoringController, *paragraphs: str) -> str:
    opened = ctrl.dispatch("new", {"media": "hwpx", "content": base64.b64encode(hwpx_bytes(*paragraphs)).decode()})
    ctrl.sessions[opened["session_id"]].rhwp_editable = True
    return opened["session_id"]


def tab(ctrl: AuthoringController, sid: str) -> dict:
    return next(item for item in ctrl.snapshot()["tabs"] if item["id"] == sid)


def group(view: dict, column: str) -> dict:
    return next(item for item in view["groups"] if item["column"] == column)


def test_needs_data_without_a_pool_and_off_by_default(tmp_path: Path) -> None:
    ctrl = controller(tmp_path)
    sid = hwpx_session(ctrl, *NOTICE)
    assert tab(ctrl, sid)["proposal"] is None
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    assert (view["state"], view["datasets"], view["groups"], view["data"]) == ("needs_data", [], [], None)
    assert tab(ctrl, sid)["proposal"]["state"] == "needs_data"
    no_current = controller(tmp_path, Port(current=None))
    other = hwpx_session(no_current, *NOTICE)
    assert no_current.dispatch("propose_fields", {"session_id": other, "revision": 0})["datasets"] == [
        {"key": "k1", "name": "공고 목록"}]


def test_proposal_uses_the_job_data_and_the_best_row(tmp_path: Path) -> None:
    port = Port()
    ctrl = controller(tmp_path, port)
    sid = hwpx_session(ctrl, *NOTICE)
    with pytest.raises(ValueError, match=STALE):
        ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 3})
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    assert view["state"] == "ready" and view["revision"] == 0
    assert view["data"]["row"] == 2 and view["data"]["name"] == "공고 목록"
    assert view["data"]["rows"] == [{"index": 1, "label": "1행", "hint": "찾은 값 1개"},
                                    {"index": 2, "label": "2행", "hint": "찾은 값이 가장 많은 행 · 4개"}]
    assert view["data"]["rows_note"] == ""
    assert view["counts"] == {"proposal": 3, "held": 1}
    price = group(view, "추정가격")
    assert price["binding"] == {"type": "amount", "fmt": "{:,}", "label": "숫자"}
    assert price["value"] == "170,309,180원" and price["spots"][0]["entry"] == "Contents/section0.xml"
    judge = group(view, "낙찰자결정방법")
    assert judge["kind"] == "held" and judge["only_label"] == "표 칸 1곳만 필드로"
    assert view["missing"] == [{"column": "계약방법", "reason": "문서에서 같은 값을 찾지 못했습니다."}]
    # 행을 바꾸면 그 행의 값으로 다시 짓는다 — 데이터는 다시 읽지 않는다.
    first = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0, "row": 1})
    assert first["data"]["row"] == 1 and first["counts"] == {"proposal": 0, "held": 0} and port.loads == 1
    assert {item["column"] for item in first["missing"]} >= {"수요기관", "낙찰자결정방법"}


def test_failed_data_is_a_python_sentence(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port(error="등록 데이터를 불러올 수 없습니다: 없음"))
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0, "pool_key": "k1", "sheet": "표1"})
    assert view["state"] == "failed" and view["error"] == "등록 데이터를 불러올 수 없습니다: 없음"
    assert view["data"]["pool_key"] == "k1" and view["data"]["sheet"] == "표1"


def test_make_goes_through_the_preview_chain_and_records_the_draft(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    made = ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": group(view, "추정가격")["id"]})
    assert made["command"]["type"] == "create_field" and made["command"]["name"] == "추정가격"
    assert made["toast"] == "‘추정가격’ 필드를 만들고 연결 초안에 열과 표시형을 넣었습니다."
    assert made["created"]["name"] == "추정가격" and made["links_existing"] is False
    original = ctrl.dispatch("content", {"session_id": sid})["content"]
    # 표면의 적용 사슬: 같은 명령으로 다시 미리 본 뒤 그 문서를 확정한다.
    again = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": made["command"]})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": again["content"]})
    session = ctrl.sessions[sid]
    assert session.proposal_bindings == {"추정가격": {"source": "추정가격", "type": "amount", "fmt": "{:,}"}}
    assert session.values == {"추정가격": "170309180"}
    after = tab(ctrl, sid)["proposal"]
    assert after["revision"] == 1 and "추정가격" not in {item["column"] for item in after["groups"]}
    # 실행 취소(옛 문서로 돌아감)는 초안과 시험 값을 거두고, 다시 실행은 되살린다.
    ctrl.dispatch("update", {"session_id": sid, "revision": 1, "content": original})
    assert session.proposal_bindings == {} and session.values == {}
    ctrl.dispatch("update", {"session_id": sid, "revision": 2, "content": again["content"]})
    assert "추정가격" in session.proposal_bindings and session.values == {"추정가격": "170309180"}


def test_a_cancelled_make_does_not_record_a_draft(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": group(view, "공고명")["id"]})
    edited = base64.b64encode(hwpx_bytes(*NOTICE[:3])).decode()
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": edited})
    session = ctrl.sessions[sid]
    assert session.proposal_bindings == {} and session.values == {}


def test_a_manual_make_after_a_cancelled_proposal_does_not_inherit_the_draft(tmp_path: Path) -> None:
    """초안은 확정된 본문이 제안 미리보기 본문과 같을 때만 기록한다 — 「revision + 1」만으로는 아니다."""
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    title = group(view, "공고명")
    ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": title["id"]})
    # 사람이 제안을 접고, 같은 이름을 다른 범위(앞 두 글자)로 손수 만든다.
    spot = title["spots"][0]
    manual = {"type": "create_field", "name": "공고명", "entry": spot["entry"], "paragraph": spot["paragraph"],
              "start": spot["start"], "end": spot["start"] + 2}
    made = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": manual})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    session = ctrl.sessions[sid]
    assert [field["name"] for field in session.analysis["fields"]] == ["공고명"]
    assert session.proposal_bindings == {} and session.values == {}
    # 같은 제안을 다시 만들어 그 본문이 오면 그때 기록한다.
    ctrl.dispatch("update", {"session_id": sid, "revision": 1,
                             "content": ctrl.dispatch("content", {"session_id": sid})["content"]})
    assert session.proposal_bindings == {}


def test_the_draft_is_recorded_only_for_the_previewed_content(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    made = ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": group(view, "공고명")["id"]})
    # 그사이 다른 확정(편집 흘려보내기)이 와도 초안은 기다린다 — 제안 본문이 오면 기록한다.
    other = base64.b64encode(hwpx_bytes(*NOTICE, p("덧붙인 문단"))).decode()
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": other})
    session = ctrl.sessions[sid]
    assert session.proposal_bindings == {} and session.proposal_pending is not None
    ctrl.dispatch("update", {"session_id": sid, "revision": 1, "content": made["content"]})
    assert session.proposal_bindings == {"공고명": {"source": "공고명", "type": "text", "fmt": ""}}
    assert session.proposal_pending is None


def test_only_the_label_cell_of_a_held_group(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    judge = group(view, "낙찰자결정방법")
    made = ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": judge["id"],
                                          "spot_id": judge["only"]})
    assert "ranges" not in made["command"] and made["command"]["cell_path"]
    with pytest.raises(ValueError, match="고른 위치"):
        ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": judge["id"], "spot_id": "x"})
    with pytest.raises(ValueError, match=NO_GROUP):
        ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": "g_없음"})


def test_make_all_is_one_document_change(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    made = ctrl.dispatch("propose_make_all", {"session_id": sid, "revision": 0})
    assert made["command"]["type"] == "create_fields" and len(made["command"]["fields"]) == 3
    assert made["toast"] == "필드 3개를 만들고 연결 초안에 열과 표시형을 넣었습니다."
    assert made["label"] == "필드로 만들기" and made["confirm"] == "none"
    assert sorted(made["field_delta"]["added_fields"]) == ["공고명", "수요기관", "추정가격"]
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    session = ctrl.sessions[sid]
    assert sorted(session.proposal_bindings) == ["공고명", "수요기관", "추정가격"]
    assert tab(ctrl, sid)["proposal"]["counts"] == {"proposal": 0, "held": 1}
    with pytest.raises(ValueError, match="남은 제안이 없습니다."):
        ctrl.dispatch("propose_make_all", {"session_id": sid, "revision": 1})


def test_dismiss_survives_a_new_revision_and_off_forgets_everything(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    kept = ctrl.dispatch("propose_dismiss", {"session_id": sid, "revision": 0, "group_id": group(view, "공고명")["id"]})
    assert "공고명" not in {item["column"] for item in kept["groups"]} and kept["counts"]["proposal"] == 2
    made = ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": group(view, "수요기관")["id"]})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    assert "공고명" not in {item["column"] for item in tab(ctrl, sid)["proposal"]["groups"]}
    assert ctrl.dispatch("propose_off", {"session_id": sid}) == {"ok": True}
    assert tab(ctrl, sid)["proposal"] is None
    with pytest.raises(ValueError, match=NO_GROUP):
        ctrl.dispatch("propose_dismiss", {"session_id": sid, "revision": 1, "group_id": "g_공고명"})
    with pytest.raises(ValueError, match=NO_GROUP):
        ctrl.dispatch("propose_make_all", {"session_id": sid, "revision": 1})
    again = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 1})
    assert "공고명" in {item["column"] for item in again["groups"]}


def test_a_refused_preview_is_returned_as_is(tmp_path: Path) -> None:
    rows = [{"{{}}": "청사 보안 장비 구매", "추정가격": "170309180"}]
    ctrl = controller(tmp_path, Port(rows))
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    bad = group(view, "{{}}")
    assert bad["kind"] == "held" and bad["reason"] == "열 이름을 필드 이름으로 쓸 수 없습니다. 문구를 고르고 직접 필드로 만드세요."
    with pytest.raises(ValueError, match="열 이름을 필드 이름으로"):
        ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": bad["id"]})
    # 미리보기의 구조화된 거절(같은 이름의 다른 구조 등)은 그대로 돌려준다 — 초안을 기다리지 않는다.
    session = ctrl.sessions[sid]
    panel = ctrl._proposal
    refused = panel._prepared(session, {"type": "create_field", "name": "#", "entry": "Contents/section0.xml",
                                        "paragraph": 2, "start": 8, "end": 19}, [], "")
    assert refused["ok"] is False and session.proposal_pending is None
    assert ctrl.dispatch("propose_off", {"session_id": sid}) == {"ok": True}


def test_txt_sessions_use_editor_offsets(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port([{"공고명": "😀 보안 장비", "추정가격": "170309180"}]))
    sid = ctrl.dispatch("new", {"media": "txt", "content": "😀 보안 장비\n추정가격: 170,309,180원\n"})["session_id"]
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    assert group(view, "공고명")["spots"][0] | {"where": ""} == {
        "id": "s0_0", "start": 0, "end": 8, "text": "😀 보안 장비", "where": ""}
    made = ctrl.dispatch("propose_make_all", {"session_id": sid, "revision": 0})
    assert made["content"] == "{{공고명}}\n추정가격: {{추정가격}}원\n" and made["edits"] == []
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    assert ctrl.sessions[sid].values == {"공고명": "😀 보안 장비", "추정가격": "170309180"}


# ------------------------------------------------------------------ data port and application helpers
def test_pool_data_reads_the_registered_dataset(tmp_path: Path) -> None:
    registry = DatasetPoolRegistry(tmp_path / "pool")
    key = registry.add(DatasetReference(name="공고 목록", kind="excel", opts={"path": str(tmp_path / "a.xlsx")}))

    class Source:
        def records(self) -> list[dict]:
            return [{"공고명": "장비", "금액": 1500, "비고": None}]

    data = PoolProposalData(registry, lambda item, **_: Source(), current=lambda: (key, None))
    assert data.datasets() == [{"key": key, "name": "공고 목록"}]
    loaded = data.load(key, None)
    assert loaded.columns == ("공고명", "금액", "비고") and loaded.rows == ({"공고명": "장비", "금액": "1500", "비고": None},)
    assert data.load("없는키", None).error and data.current() == (key, None)

    class Zone:
        pool_key, sheet = "k", ""

    assert pool_source_of(Zone()) == ("k", None)
    Zone.pool_key = ""
    assert pool_source_of(Zone()) is None


def test_row_limits_and_fallbacks() -> None:
    loaded = normalize_rows("큰 목록", [{"번호": str(index)} for index in range(501)])
    assert len(loaded.rows) == 500 and loaded.truncated is True
    state = FieldProposalState(row=9)
    assert chosen_row(state, [0, 2, 2]) == 2
    view = empty_view("failed", 4, [], "실패", FieldProposalState(pool_key="k", loaded=loaded))
    assert view["data"] == {"pool_key": "k", "name": "큰 목록", "sheet": None, "row": None, "rows": [],
                            "rows_truncated": False, "rows_note": ""}


def test_rows_note_appears_only_when_the_pool_was_truncated(tmp_path: Path) -> None:
    many_rows = [{"공고명": "청사 보안 장비 구매", "추정가격": "170309180"} for _ in range(501)]
    ctrl = controller(tmp_path, Port(many_rows))
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    assert view["data"]["rows_truncated"] is True
    assert view["data"]["rows_note"] == "앞 500행만 맞춰 봅니다."


def test_a_group_of_many_spots_is_one_command_and_a_hand_edited_value_survives_undo(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE, p("청사 보안 장비 구매"))
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    title = group(view, "공고명")
    assert title["count_text"] == "2곳"
    assert title["only_label"] == "이 자리만"  # 제안 묶음 자리 2곳 이상
    made = ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": title["id"]})
    assert len(made["command"]["ranges"]) == 2 and made["confirm"] == "enter" and made["affected"] == 2
    original = ctrl.dispatch("content", {"session_id": sid})["content"]
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    ctrl.dispatch("trial_input", {"session_id": sid, "revision": 1, "values": {"공고명": "손으로 고친 값"},
                                  "selected": {}})
    ctrl.dispatch("update", {"session_id": sid, "revision": 1, "content": original})
    session = ctrl.sessions[sid]
    assert session.proposal_bindings == {} and session.values == {"공고명": "손으로 고친 값"}


def test_python_owns_the_popover_sentences(tmp_path: Path) -> None:
    ctrl = controller(tmp_path, Port())
    sid = hwpx_session(ctrl, *NOTICE)
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    price = group(view, "추정가격")
    assert price["source_text"] == "2행 ‘추정가격’ 열과 같은 값입니다."
    assert (price["links_note"], price["only_label"]) == ("", None)
    assert group(view, "낙찰자결정방법")["only_label"] == "표 칸 1곳만 필드로"
    # 한 자리만 만든 뒤 남은 같은 값 자리는 같은 이름 필드에 더해진다 — 그 한 줄도 Python 문장이다.
    ctrl2 = controller(tmp_path, Port())
    sid2 = hwpx_session(ctrl2, *NOTICE, p("청사 보안 장비 구매"))
    first = ctrl2.dispatch("propose_fields", {"session_id": sid2, "revision": 0})
    title = group(first, "공고명")
    one = ctrl2.dispatch("propose_make", {"session_id": sid2, "revision": 0, "group_id": title["id"],
                                          "spot_id": title["spots"][1]["id"]})
    ctrl2.dispatch("update", {"session_id": sid2, "revision": 0, "content": one["content"]})
    again = group(tab(ctrl2, sid2)["proposal"], "공고명")
    assert again["links_existing"] is True and again["links_note"] == "같은 이름 필드에 자리를 더합니다."


def test_pick_column_among_equal_values(tmp_path: Path) -> None:
    rows = [{"입찰공고번호": "R26BK01234567", "현행공고": "R26BK01234567", "추정가격": "170309180"}]
    ctrl = controller(tmp_path, Port(rows))
    sid = hwpx_session(ctrl, p("R26BK01234567"), p("나. 추정가격: 170,309,180원"))
    view = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    number = group(view, "입찰공고번호")
    assert number["kind"] == "held" and number["id"] == "g_입찰공고번호|현행공고"
    assert number["columns"] == [{"name": "현행공고", "note": "‘현행공고’ 열도 같은 값입니다."}]
    with pytest.raises(ValueError, match="이 값과 같은 열 가운데서 고르세요."):
        ctrl.dispatch("propose_pick_column", {"session_id": sid, "revision": 0, "group_id": number["id"],
                                              "column": "추정가격"})
    picked = ctrl.dispatch("propose_pick_column", {"session_id": sid, "revision": 0, "group_id": number["id"],
                                                   "column": "현행공고"})
    chosen = next(item for item in picked["groups"] if item["id"] == number["id"])
    assert (chosen["kind"], chosen["column"], chosen["name"]) == ("proposal", "현행공고", "현행공고")
    assert chosen["columns"] == [{"name": "입찰공고번호", "note": "‘입찰공고번호’ 열도 같은 값입니다."}]
    assert chosen["source_text"] == "1행 ‘현행공고’ 열과 같은 값입니다."
    # 문서가 바뀌어도 고른 열은 남고, 띠를 끄면 잊는다.
    price = group(picked, "추정가격")
    made = ctrl.dispatch("propose_make", {"session_id": sid, "revision": 0, "group_id": price["id"]})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    assert next(item for item in tab(ctrl, sid)["proposal"]["groups"] if item["id"] == number["id"])["column"] == "현행공고"
    ctrl.dispatch("propose_off", {"session_id": sid})
    fresh = ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 1})
    assert next(item for item in fresh["groups"] if item["id"] == number["id"])["column"] == "입찰공고번호"


# ------------------------------------------------------------------ 작업 적용 때 연결 초안 심기
def _seeded_setup(tmp_path: Path, *, mappings=(), authority: str = "job-mapping/v1"):
    from hwpxfiller.domain.job import Job
    from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
    from hwpxfiller.external.job_store import JobRegistry

    tmp_path.mkdir(parents=True, exist_ok=True)
    template = tmp_path / "공고.txt"
    template.write_text("공고명: 청사 보안 장비 구매\n추정가격: 170,309,180원\n담당: {{담당}}\n", encoding="utf-8")
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(Job(name="공고 작업", template_path=str(template), binding_authority=authority,
                      mapping=MappingProfile(mappings=[FieldMapping(*item) for item in mappings])))

    class Change:
        def check(self, name, request_id):
            return {"preparation": {"change_token": "t"}}

        def apply(self, name, token):
            return {"status": "applied", "current_template_application_epoch": 2, "is_current": True}

    rows = [{"공고명": "청사 보안 장비 구매", "추정가격": "170309180", "수요기관": "조달청"}]
    ctrl = AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home", proposal_data=Port(rows),
                               job_registry=registry, template_change=Change())
    sid = ctrl.open_path(template)["session_id"]
    return ctrl, sid, registry, template


def _make_all_and_save(ctrl: AuthoringController, sid: str, template: Path) -> int:
    ctrl.dispatch("propose_fields", {"session_id": sid, "revision": 0})
    made = ctrl.dispatch("propose_make_all", {"session_id": sid, "revision": 0})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": made["content"]})
    assert ctrl.save_to_path(sid, 1, template)["ok"] is True
    return 1


def _apply(ctrl: AuthoringController, sid: str, revision: int) -> dict:
    return ctrl.dispatch("apply_job", {"session_id": sid, "revision": revision, "job_name": "공고 작업",
                                       "change_token": "t"})


def test_apply_job_seeds_new_fields_from_drafts_only(tmp_path: Path) -> None:
    ctrl, sid, registry, template = _seeded_setup(tmp_path, mappings=[("공고명", "기존열", "text", "")])
    revision = _make_all_and_save(ctrl, sid, template)
    # 저장 뒤 같은 이름 아닌 초안 하나를 더 얹는다 — 적용한 템플릿에 없는 필드는 심지 않는다.
    ctrl.sessions[sid].proposal_bindings["없는필드"] = {"source": "수요기관", "type": "text", "fmt": ""}
    result = _apply(ctrl, sid, revision)
    assert (result["status"], result["seeded_bindings"]) == ("applied", 1)
    mappings = {item.template_field: item for item in registry.load("공고 작업").mapping.mappings}
    assert (mappings["공고명"].source, mappings["공고명"].type) == ("기존열", "text"), "기존 연결은 그대로다"
    price = mappings["추정가격"]
    assert (price.source, price.type, price.fmt) == ("추정가격", "amount", "{:,}")
    assert "없는필드" not in mappings and "담당" not in mappings
    again = _apply(ctrl, sid, revision)
    assert again["seeded_bindings"] == 0, "다시 적용해도 이미 연결된 필드는 건드리지 않는다"


def test_apply_job_without_drafts_or_with_another_authority_writes_nothing(tmp_path: Path) -> None:
    ctrl, sid, registry, template = _seeded_setup(tmp_path)
    assert ctrl.save_to_path(sid, 0, template)["ok"] is True
    before = registry.path_for("공고 작업").read_bytes()
    assert _apply(ctrl, sid, 0)["seeded_bindings"] == 0
    assert registry.path_for("공고 작업").read_bytes() == before, "초안이 없으면 저장하지 않는다"
    other, other_sid, other_registry, other_template = _seeded_setup(tmp_path / "legacy", authority="")
    revision = _make_all_and_save(other, other_sid, other_template)
    legacy_before = other_registry.path_for("공고 작업").read_bytes()
    assert _apply(other, other_sid, revision)["seeded_bindings"] == 0
    assert other_registry.path_for("공고 작업").read_bytes() == legacy_before, "연결 권위가 작업 연결이 아니면 쓰지 않는다"


def test_apply_job_does_not_seed_when_the_change_did_not_land(tmp_path: Path) -> None:
    ctrl, sid, registry, template = _seeded_setup(tmp_path)
    revision = _make_all_and_save(ctrl, sid, template)
    ctrl._template_change.apply = lambda name, token: {"status": "conflict", "is_current": False}
    assert _apply(ctrl, sid, revision)["seeded_bindings"] == 0
    assert registry.load("공고 작업").mapping.mappings == []
