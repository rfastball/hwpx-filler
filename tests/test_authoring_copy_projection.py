"""#1025 — 저작 작업대의 문장·문맥은 Python 투영이 짓는다(§7.2·§9.1·§13·§6.3).

- 사용 위치·검색 결과의 ``context`` 는 앞뒤 본문과 ``[이름]`` 표지뿐이며 필드 명령 문법이 없다.
  원문 글자는 ``raw`` 에만 남는다.
- 결과 시험 상태는 상태마다 짧은 칩(``trial_state_label``)과 문장(``trial_state_message``) 한 쌍이다.
- 전체 이름 변경 문장은 새 이름의 끝소리로 조사를 고른다.
- 검색 결과는 종류(``kind``)와 요약(``summary``)을 싣는다.
- 처음 여는 일반 문서에만 첫 필드 안내가 ``notice`` 로 실린다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.domain.template_authoring import (
    occurrence_context,
    rename_field_message,
    text_hit_context,
)
from hwpxfiller.external.hwpx_authoring import analyze_hwpx, search_hwpx
from hwpxfiller.webapp.screen_authoring import AuthoringController

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"
#: 한글이 누름틀에 적는 실제 명령 문자열 모양(template_v1 에서 옮김).
COMMAND = "Clickhere:set:50:Direction:wstring:8:{{수요기관}} HelpState:wstring:0:  "


def _controller(tmp_path: Path) -> AuthoringController:
    return AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home")


def _click_here_package() -> HwpxPackage:
    paragraph = (
        '<hp:p><hp:run charPrIDRef="0"><hp:t>계약 상대방 정보 수요기관: </hp:t></hp:run>'
        '<hp:run charPrIDRef="0"><hp:ctrl><hp:fieldBegin id="7" type="CLICK_HERE" name="수요기관"'
        ' editable="1" dirty="0" zorder="-1" fieldid="8" metaTag="">'
        '<hp:parameters cnt="3" name=""><hp:integerParam name="Prop">9</hp:integerParam>'
        f'<hp:stringParam name="Command" xml:space="preserve">{COMMAND}</hp:stringParam>'
        '<hp:stringParam name="Direction">{{수요기관}}</hp:stringParam></hp:parameters>'
        '</hp:fieldBegin></hp:ctrl></hp:run>'
        '<hp:run charPrIDRef="7"><hp:t>{{수요기관}}</hp:t></hp:run>'
        '<hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd beginIDRef="7" fieldid="8"/></hp:ctrl>'
        '<hp:t> (공공기관) 담당 부서와 연락처</hp:t></hp:run></hp:p>'
    )
    package = HwpxPackage()
    package.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    package.stored.add(MIMETYPE_NAME)
    package.entries["Contents/section0.xml"] = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{paragraph}</hs:sec>'
    ).encode("utf-8")
    return package


def _no_syntax(context: str) -> None:
    for fragment in ("Clickhere", "HelpState", "wstring", "{{", "}}"):
        assert fragment not in context, (fragment, context)


# ------------------------------------------------------------------ 사용 위치 문맥(§7.2)
def test_hwpx_occurrence_context_is_body_text_around_a_placeholder_not_the_field_command() -> None:
    occurrence = analyze_hwpx(_click_here_package())["fields"][0]["occurrences"][0]
    assert occurrence["context"] == "…대방 정보 수요기관: [수요기관] (공공기관) 담당 부…"
    _no_syntax(occurrence["context"])
    # 원문 글자(명령 매개변수 포함)는 raw 로만 옮겨 간다 — 원문 표기의 몫이다.
    assert COMMAND.strip() in occurrence["raw"]["text"]


def test_every_template_v1_occurrence_context_is_free_of_field_syntax() -> None:
    fields = analyze_hwpx(HwpxPackage.from_bytes(FIXTURE.read_bytes()))["fields"]
    occurrences = [occurrence for field in fields for occurrence in field["occurrences"]]
    assert occurrences
    for field in fields:
        for occurrence in field["occurrences"]:
            _no_syntax(occurrence["context"])
            assert f"[{field['name']}]" in occurrence["context"]
    first = next(field for field in fields if field["name"] == "진행상태")["occurrences"][0]
    assert first["context"] == "[진행상태] - 누름틀"
    assert "Clickhere" in first["raw"]["text"]


def test_hwpx_search_hits_carry_kind_and_a_body_excerpt() -> None:
    package = _click_here_package()
    text = search_hwpx(package, "공공기관", "text")["hits"]
    # 본문 안의 필드 값(템플릿의 「{{수요기관}}」 표시)도 문맥에서는 표지로 접힌다.
    assert [(hit["kind"], hit["context"]) for hit in text] == [
        ("text", "…기관: [수요기관] (공공기관) 담당 부서와 연락처")]
    inside = search_hwpx(package, "요기", "text")["hits"]
    assert [hit["context"] for hit in inside] == [
        "계약 상대방 정보 수요기관: [수요기관] (공…", "…대방 정보 수요기관: [수요기관] (공공기관) 담당 부…"]
    field = search_hwpx(package, "수요", "field")["hits"]
    assert [hit["kind"] for hit in field] == ["field"]
    _no_syntax(field[0]["context"])


def test_txt_occurrence_and_text_hit_contexts_hide_the_token_grammar(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt",
                                   "content": "머리말\n계약 상대방 수요기관: {{수요기관}} 담당자 {{담당자}} 연락처\n끝"})
    fields = {field["name"]: field for field in opened["analysis"]["fields"]}
    assert fields["수요기관"]["occurrences"][0]["context"] == "…약 상대방 수요기관: [수요기관] 담당자 [담당자] 연…"
    assert fields["담당자"]["occurrences"][0]["context"] == "… [수요기관] 담당자 [담당자] 연락처"
    assert fields["담당자"]["occurrences"][0]["raw"]["text"] == "계약 상대방 수요기관: {{수요기관}} 담당자 {{담당자}} 연락처"
    hits = ctrl.dispatch("search", {"session_id": opened["session_id"], "revision": 0,
                                    "query": "담당자", "kind": "body"})["hits"]
    # 두 번째 결과는 필드 토큰 안의 글자다 — 토큰 전체가 표지로 서고 문법 조각은 새지 않는다.
    assert [hit["context"] for hit in hits] == ["…요기관: [수요기관] 담당자 [담당자] 연락처",
                                                "… [수요기관] 담당자 [담당자] 연락처"]


def test_context_helpers_trim_to_twelve_characters_and_stay_on_one_line() -> None:
    assert occurrence_context("짧은 앞", "[이름]", "뒤") == "짧은 앞[이름]뒤"
    assert occurrence_context("가" * 20, "[이름]", "나" * 20) == "…" + "가" * 12 + "[이름]" + "나" * 12 + "…"
    assert occurrence_context("앞\t\t말  ", "[x]", "  뒤\n말") == "앞 말 [x] 뒤 말"
    assert text_hit_context("첫 줄\n앞 {{이름}} 공고 뒤\n끝", 13, 15) == "앞 [이름] 공고 뒤"


# ------------------------------------------------------------------ 전체 이름 변경 문장(§13)
@pytest.mark.parametrize(("name", "sentence"), [
    ("주소", "현재 문서의 사용 위치 2곳이 ‘주소’로 변경됩니다."),
    ("사업명", "현재 문서의 사용 위치 2곳이 ‘사업명’으로 변경됩니다."),
    ("서울", "현재 문서의 사용 위치 2곳이 ‘서울’로 변경됩니다."),
])
def test_rename_preview_sentence_picks_the_particle_by_final_consonant(
        tmp_path: Path, name: str, sentence: str) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": "{{이름}} 그리고 {{이름}}"})
    preview = ctrl.dispatch("preview", {"session_id": opened["session_id"], "revision": 0,
                                        "command": {"type": "rename_field", "old_name": "이름", "name": name}})
    assert preview["message"] == sentence


def test_rename_sentence_falls_back_to_the_paired_particle_for_non_hangul_names() -> None:
    assert rename_field_message(1, "ABC") == "현재 문서의 사용 위치 1곳이 ‘ABC’(으)로 변경됩니다."
    assert rename_field_message(3, "공고일") == "현재 문서의 사용 위치 3곳이 ‘공고일’로 변경됩니다."


def test_only_rename_field_previews_carry_the_sentence(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": "앞 본문 뒤"})
    preview = ctrl.dispatch("preview", {"session_id": opened["session_id"], "revision": 0,
                                        "command": {"type": "create_field", "start": 2, "end": 4, "name": "내용"}})
    assert "message" not in preview


# ------------------------------------------------------------------ 결과 시험 상태(P09·§9.1)
def test_each_trial_state_has_one_label_and_one_sentence(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt", "content": "{{이름}}"})
    session = ctrl.sessions[opened["session_id"]]

    def tab() -> dict:
        return ctrl.snapshot()["tabs"][0]

    def seen() -> tuple[str, str, str]:
        current = tab()
        return current["trial_state"], current["trial_state_label"], current["trial_state_message"]

    assert seen() == ("untried", "시험 전", "아직 시험하지 않았습니다.")
    session.trial_result = {"report": {"missing_fields": [], "errors": []}}
    session.trial_document_revision = session.revision
    session.trial_values_revision = session.trial_input_revision
    assert seen() == ("current", "현재 구성 통과", "현재 시험 구성 통과")
    session.trial_document_revision = session.revision - 1
    assert seen() == ("stale", "마지막 시험 이후 변경됨", "마지막 시험 이후 문서 또는 입력이 바뀌었습니다.")
    session.trial_document_revision = session.revision
    session.trial_result = {"report": {"missing_fields": ["이름"], "errors": []}}
    assert seen() == ("failed", "시험 실패", "시험 실패")
    session.trial_error = "시험 결과를 만들 수 없습니다: 손상"
    assert seen() == ("failed", "시험 실패", "시험 결과를 만들 수 없습니다: 손상")
    labels = {"시험 전", "현재 구성 통과", "마지막 시험 이후 변경됨", "시험 실패"}
    assert len(labels) == 4


# ------------------------------------------------------------------ 검색 요약(§6.3)
def test_search_summary_counts_body_field_and_structure_hits(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.dispatch("new", {"media": "txt",
                                   "content": "{{#항목 공고 구분}}\n{{#선택 공고안}}\n공고명 {{공고명}}\n{{/선택}}\n{{/항목}}\n"})
    result = ctrl.dispatch("search", {"session_id": opened["session_id"], "revision": 0,
                                      "query": "공고", "kind": "all"})
    kinds = [hit["kind"] for hit in result["hits"]]
    body = kinds.count("text")
    structure = kinds.count("slot") + kinds.count("option")
    assert kinds.count("field") == 1 and structure == 2 and body >= 1
    assert result["summary"] == f"총 {len(kinds)}건 · 본문 {body} · 필드 1 · 항목·선택 2"
    empty = ctrl.dispatch("search", {"session_id": opened["session_id"], "revision": 0,
                                     "query": "없는말", "kind": "all"})
    assert empty == {"hits": [], "summary": "총 0건 · 본문 0 · 필드 0 · 항목·선택 0"}
    assert ctrl.dispatch("search", {"session_id": opened["session_id"], "revision": 0,
                                    "query": "", "kind": "all"}) == {"hits": [], "summary": None}


def test_hwpx_search_summary_includes_the_body_kind(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(FIXTURE)
    result = ctrl.dispatch("search", {"session_id": opened["session_id"], "revision": 0,
                                      "query": "누름틀", "kind": "all"})
    assert result["hits"] and all(hit["kind"] == "text" for hit in result["hits"])
    assert result["summary"] == f"총 {len(result['hits'])}건 · 본문 {len(result['hits'])} · 필드 0 · 항목·선택 0"


# ------------------------------------------------------------------ 첫 필드 안내(§13)
def test_first_field_hint_is_a_notice_only_for_a_general_document_without_meaning(tmp_path: Path) -> None:
    plain = tmp_path / "plain.txt"
    plain.write_text("계약 상대방 정보", encoding="utf-8")
    template = tmp_path / "template.txt"
    template.write_text("계약 상대방 {{수요기관}}", encoding="utf-8")
    ctrl = _controller(tmp_path)
    assert ctrl.open_path(plain, as_template=False)["notice"] == "변경할 문구를 선택해 필드로 만들어 보세요."
    assert ctrl.open_path(template, as_template=False)["notice"] is None
    again = _controller(tmp_path / "second")
    assert again.open_path(plain, as_template=True)["notice"] is None
