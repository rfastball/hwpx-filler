"""원인 자리 문제(IDE-05 #1051) — 문제의 문서 차례, 위치 줄 메시지의 원천(`problems_here`), 저작 lint.

저작 lint 는 두 가지다. ① 공백만 다른 필드 이름(`lint.near_duplicate_pairs`), ② HWPX 본문에 평문으로 남은
``{{이름}}``(판정 원천 `schema.stray_tokens`, 좌표 `stray_sites`, 행동은 기존 「누름틀 변환」 한 토큰). 둘 다
경고이며 초안/사용 준비 판정을 바꾸지 않는다.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest

from hwpxcore.package import HwpxPackage
from hwpxfiller.domain.authoring import compile_document, scan_tokens
from hwpxfiller.domain.schema import extract_schema
from hwpxfiller.webapp.screen_authoring import AuthoringController

_PRACTICE = Path(__file__).resolve().parent.parent / "examples" / "onboarding" / "templates" / "공고서_연습.hwpx"
_PRACTICE_TOKENS = ["공고번호", "수요기관", "품명", "계약방법", "납품조건"]


def _controller(tmp_path: Path) -> AuthoringController:
    return AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home")


def _tab(ctrl: AuthoringController, sid: str) -> dict:
    return next(item for item in ctrl.snapshot()["tabs"] if item["id"] == sid)


def _practice(tmp_path: Path) -> Path:
    copy = tmp_path / "공고서_연습.hwpx"
    shutil.copyfile(_PRACTICE, copy)
    return copy


def test_txt_problems_come_in_document_order_and_locate_reports_the_problem_under_the_caret(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    # 구조 진단(분석 순서상 먼저)은 둘째 줄, 저작 경고는 첫 줄이다 — 문제 목록은 문서 차례다.
    content = "{{공고명}} {{공고 명}}\n{{#항목 a}}\n본문\n"
    sid = ctrl.dispatch("new", {"media": "txt", "content": content})["session_id"]
    tab = _tab(ctrl, sid)
    assert [(item["category"], item["severity"]) for item in tab["problems"]] == [
        ("authoring", "warning"), ("structure", "error")]
    assert [item["location"]["start"] for item in tab["problems"]] == [8, 17]
    # 경고는 준비 판정을 바꾸지 않는다 — 수만 더한다(IDE-01 규칙, 수는 problems 에서 센다).
    assert tab["readiness"] == {"state": "draft", "errors": 1, "warnings": 1,
                                "message": "사용 전에 구조 오류 1개를 확인하세요."}

    def here(start: int, end: int | None = None) -> list[int]:
        return ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                        "selection": {"start": start, "end": start if end is None else end}}
                             )["problems_here"]

    assert here(20) == [1], "짝 없는 표지 줄 위의 캐럿"
    assert here(17) == [1], "줄 머리"
    assert here(16) == [0], "자리 바로 뒤의 캐럿은 그 자리다(줄바꿈 전)"
    assert here(3) == [], "다른 필드 위"
    assert here(4, 20) == [0, 1], "여러 자리에 걸친 선택"
    assert here(29) == [], "줄 자리의 끝(줄바꿈 뒤)은 다음 줄 머리다"
    # 대상을 고른 locate(구조 목록·검색)도 같은 칸을 싣는다.
    located = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                       "selection": {"start": 8, "end": 16},
                                       "target": {"kind": "occurrence", "name": "공고 명"}})
    assert located["problems_here"] == [0]


def test_whitespace_variant_field_name_is_one_authoring_warning_with_a_relink_action(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    content = "공고: {{공고명}}\n다시: {{공고 명}}\n끝: {{공고명}}\n"
    sid = ctrl.dispatch("new", {"media": "txt", "content": content})["session_id"]
    tab = _tab(ctrl, sid)
    [problem] = tab["problems"]
    occurrence = next(item for item in tab["analysis"]["fields"] if item["name"] == "공고 명")["occurrences"][0]
    assert problem == {
        "kind": "near_duplicate", "severity": "warning", "category": "authoring",
        "message": "공백만 다른 필드 이름이 있습니다.", "target": "공고 명",
        "location": {"line": 1, "start": occurrence["start"], "end": occurrence["end"]},
        "actions": [
            {"label": "원문으로 이동", "kind": "navigate",
             "location": {"line": 1, "start": occurrence["start"], "end": occurrence["end"]}},
            {"label": "필드 연결 변경", "kind": "command",
             "command": {"type": "relink_field", "start": occurrence["start"], "end": occurrence["end"],
                         "name": "공고명"}},
        ],
    }
    assert tab["readiness"] == {"state": "ready", "errors": 0, "warnings": 1, "message": None}
    # 행동을 실행하면(미리보기 → 확정) 오타 필드가 다른 쪽 이름으로 이어지고 경고가 걷힌다.
    preview = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": problem["actions"][1]["command"]})
    assert (preview["before"], preview["after"]) == ("{{공고 명}}", "{{공고명}}")
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": preview["content"]})
    tab = _tab(ctrl, sid)
    assert tab["problems"] == []
    assert [item["name"] for item in tab["analysis"]["fields"]] == ["공고명"]


def test_near_duplicate_target_is_the_less_used_name_and_a_many_use_target_gets_no_command(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    # 「공고 명」이 두 곳, 「공고명」이 한 곳 — 대상은 사용이 적은 쪽이다.
    sid = ctrl.dispatch("new", {"media": "txt", "content": "{{공고 명}} {{공고 명}} {{공고명}}\n"})["session_id"]
    [problem] = _tab(ctrl, sid)["problems"]
    assert problem["target"] == "공고명"
    assert [action["kind"] for action in problem["actions"]] == ["navigate", "command"]
    # 둘 다 여러 곳이면 연결 변경은 사용 위치 한 곳마다의 명령이라 싣지 않는다 — 이동만 남는다.
    sid = ctrl.dispatch("new", {"media": "txt", "content": "{{공고 명}} {{공고 명}} {{공고명}} {{공고명}}\n"})["session_id"]
    [problem] = _tab(ctrl, sid)["problems"]
    assert problem["target"] == "공고명", "같으면 나중에 처음 나온 이름"
    assert [action["kind"] for action in problem["actions"]] == ["navigate"]


def test_scan_tokens_carry_coordinates_and_compile_document_converts_only_the_named_token() -> None:
    package = HwpxPackage.from_bytes(_PRACTICE.read_bytes())
    sites = scan_tokens(package)
    assert [site.name for site in sites] == _PRACTICE_TOKENS
    assert all(site.compilable and site.entry == "Contents/section0.xml" and site.paragraph_path
               and 0 <= site.start < site.end for site in sites)
    # 좌표는 판정·리포트 모양을 바꾸지 않는다(비교·사전 밖).
    assert sites[0].to_dict() == {"name": "공고번호", "context": sites[0].context, "compilable": True, "reason": ""}
    target = sites[1]
    _, report = compile_document(package, only=(target.entry, target.paragraph_path, target.start))
    assert report.compiled == ["수요기관"]
    assert extract_schema(package).field_names() == ["수요기관"]
    assert [site.name for site in scan_tokens(package)] == [name for name in _PRACTICE_TOKENS if name != "수요기관"]
    # 그 자리에 바꿀 토큰이 더는 없으면 아무것도 바꾸지 않는다.
    before = dict(package.entries)
    _, report = compile_document(package, only=(target.entry, target.paragraph_path, target.start))
    assert report.compiled == [] and package.entries == before
    _, report = compile_document(package, only=(target.entry, "/hs:sec/hp:p[999]", 0))
    assert report.compiled == [] and package.entries == before


def test_stray_token_problems_match_schema_stray_tokens(tmp_path: Path) -> None:
    """교차 일관성: 같은 문서에서 `schema.stray_tokens` 이름 집합 == 저작 문제 ② 대상 집합."""
    ctrl = _controller(tmp_path)
    sid = ctrl.open_path(_practice(tmp_path))["session_id"]
    tab = _tab(ctrl, sid)
    stray = extract_schema(HwpxPackage.from_bytes(_PRACTICE.read_bytes())).stray_tokens
    plain = [item for item in tab["problems"] if item["kind"] == "stray_token"]
    assert {item["target"] for item in plain} == set(stray) == set(_PRACTICE_TOKENS)
    assert [item["target"] for item in plain] == _PRACTICE_TOKENS, "문서 차례"


def test_plain_hwpx_token_warns_with_the_existing_nurumtl_conversion_and_converting_it_clears_the_warning(
        tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(_practice(tmp_path))
    sid = opened["session_id"]
    tab = _tab(ctrl, sid)
    assert tab["readiness"] == {"state": "ready", "errors": 0, "warnings": 5, "message": None}
    problem = next(item for item in tab["problems"] if item["target"] == "수요기관")
    assert (problem["severity"], problem["category"], problem["message"]) == (
        "warning", "authoring", "평문으로 남은 필드 표기입니다.")
    location = problem["location"]
    assert location["entry"] == "Contents/section0.xml" and location["end"] - location["start"] == len("{{수요기관}}")
    navigate, convert = problem["actions"]
    assert navigate == {"label": "원문으로 이동", "kind": "navigate", "location": location}
    assert convert["label"] == "누름틀 변환" and convert["command"]["type"] == "compile_token"
    # 원인 자리에서 그 문제가 위치 줄 메시지의 원천이 된다(locate 는 매체 공통).
    here = ctrl.dispatch("locate", {"session_id": sid, "revision": 0,
                                    "selection": {**location, "start": location["start"] + 3,
                                                  "end": location["start"] + 3}})["problems_here"]
    assert [tab["problems"][index]["target"] for index in here] == ["수요기관"]
    assert ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0,
                                                       "content": opened["content"]})["editable"] is True
    preview = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": convert["command"]})
    assert (preview["before"], preview["after"], preview["label"]) == ("{{수요기관}}", "[ 수요기관 ]", "‘수요기관’ 누름틀 변환")
    assert preview["field_delta"] == {"added_fields": ["수요기관"], "removed_fields": []}
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": preview["content"]})
    tab = _tab(ctrl, sid)
    assert [item["name"] for item in tab["analysis"]["fields"]] == ["수요기관"], "필드가 하나 는다"
    assert [item["target"] for item in tab["problems"]] == [name for name in _PRACTICE_TOKENS if name != "수요기관"]
    assert tab["readiness"] == {"state": "ready", "errors": 0, "warnings": 4, "message": None}
    # 누름틀 변환 그대로다 — 값은 채우기 전까지 보이는 원래 표기이고(코퍼스 관례), 그래서 평문 잔존이 아니다.
    package = HwpxPackage.from_bytes(base64.b64decode(preview["content"]))
    assert extract_schema(package).stray_tokens == [name for name in _PRACTICE_TOKENS if name != "수요기관"]
    assert tab["analysis"]["fields"][0]["occurrences"][0]["raw"]["value"] == "{{수요기관}}"


def test_stale_conversion_is_refused_without_touching_the_document(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(_practice(tmp_path))
    sid = opened["session_id"]
    ctrl.dispatch("rhwp_roundtrip_preflight", {"session_id": sid, "revision": 0, "content": opened["content"]})
    command = next(item for item in _tab(ctrl, sid)["problems"] if item["target"] == "수요기관")["actions"][1]["command"]
    preview = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": command})
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": preview["content"]})
    # 이미 바뀐 자리의 행동은 늦게 와도 다른 토큰을 바꾸지 않는다 — 기존 자동 수정 거절 문장이다.
    with pytest.raises(ValueError, match="자동 수정이 더는 적용되지 않습니다"):
        ctrl.dispatch("preview", {"session_id": sid, "revision": 1, "command": command})
    with pytest.raises(ValueError, match="자동 수정이 더는 적용되지 않습니다"):
        ctrl.dispatch("preview", {"session_id": sid, "revision": 1,
                                  "command": {**command, "name": "다른이름", "paragraph_path": "/hs:sec/hp:p[6]"}})


def test_problems_with_a_location_precede_the_locationless_compatibility_warnings(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path)
    opened = ctrl.open_path(_practice(tmp_path))
    sid = opened["session_id"]
    changed = HwpxPackage.from_bytes(_PRACTICE.read_bytes())
    changed.entries["Contents/header.xml"] = changed.entries["Contents/header.xml"].replace(b"paraPr", b"paraXX", 1)
    blocked = ctrl.dispatch("rhwp_roundtrip_preflight", {
        "session_id": sid, "revision": 0, "content": base64.b64encode(changed.to_bytes()).decode("ascii")})
    assert blocked["editable"] is False
    problems = _tab(ctrl, sid)["problems"]
    assert [item["category"] for item in problems] == ["authoring"] * 5 + ["compatibility"] * (1 + len(blocked["diagnostics"]))
    assert all(item["location"] is None for item in problems[5:])
