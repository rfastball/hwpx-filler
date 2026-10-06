"""작업대 본문 카드의 표식·행별 임시 편집 — 순수 판정기 단위 계약(#1148 PR B).

여기서 재는 것은 :mod:`hwpxfiller.viewmodel.txt_card_edit` 가 혼자 내는 판정이다. 컨트롤러
결선(``set_card_text``/``revert_card``·스냅샷 ``text``/``marks``)은 ``tests/test_webapp_workbench.py``
소관이고, 물질화 대조는 ``tests/test_txt_materialization.py`` 소관이다 — 여기는 사상 규칙
(:mod:`~hwpxfiller.viewmodel.txt_card_diff`)과 채움·해소 판정만 격리해서 본다.
"""
from __future__ import annotations

from hwpxfiller.domain.text_render import render_segments
from hwpxfiller.viewmodel.txt_card_edit import (
    CardEdits,
    CardMark,
    base_marks,
    edit_card,
    plain_edit,
    raw_card,
    utf16_marks,
)


# ------------------------------------------------------------------ base_marks
def test_base_marks_splits_declared_blank_from_data_blank_and_covers_missing_and_fill():
    """렌더 세그먼트 → 표식: 선언된 비움(``declared``)과 데이터 빈 값(``blank``)이 갈린다.

    그 구분의 단일 출처는 ``declared`` 집합(:meth:`MappingModel.declared_empty_fields` 승계)
    하나다 — 렌더 세그먼트 자체는 둘 다 ``SEG_BLANK`` 로 같다.
    """
    template = "{{a}} {{b}} {{c}} {{d}}"
    record = {"a": "", "b": "", "c": "값"}  # d 는 레코드에 아예 없다(미치환)
    segments, _report = render_segments(template, record)

    marks = base_marks(segments, frozenset({"a"}))

    kinds = {m.name: m.kind for m in marks}
    assert kinds == {"a": "declared", "b": "blank", "c": "fill", "d": "missing"}


def test_base_marks_skips_literal_text():
    """리터럴(토큰 밖 원문)은 표식이 아니다 — 편집기가 장식을 달 자리가 없다."""
    template = "머리말 {{x}} 꼬리말"
    segments, _report = render_segments(template, {"x": "값"})

    marks = base_marks(segments, frozenset())

    assert [m.name for m in marks] == ["x"]


# ------------------------------------------------------------------ edit_card: 채움
def test_typing_into_a_zero_length_blank_fills_it_and_maps_the_inserted_range():
    """빈 값(길이 0) 자리에 친 글자는 그 표식의 범위가 되고, 채웠다로 판정된다."""
    base = "안녕"
    marks = (CardMark("blank", "X", 2, 2),)
    edited = base + "하세요"

    result = edit_card(base, marks, edited, fullwidth=False)

    assert result.filled == {"X"}
    mark = result.marks[0]
    assert edited[mark.start:mark.end] == "하세요"


def test_typing_only_whitespace_into_a_blank_does_not_count_as_filled():
    """공백만 채운 자리는 「채웠다」가 아니다 — 여전히 빈 값과 같은 사실이다."""
    base = "값:"
    marks = (CardMark("blank", "X", 2, 2),)
    edited = base + "   "

    result = edit_card(base, marks, edited, fullwidth=False)

    assert result.filled == frozenset()


def test_declared_blank_can_also_be_filled_by_typing():
    """비워 둠 선언 자리도 편집은 받는다 — 채우면 같은 판정(``filled``)이 선다."""
    base = "값:"
    marks = (CardMark("declared", "X", 2, 2),)
    edited = base + "그래도 채움"

    result = edit_card(base, marks, edited, fullwidth=False)

    assert result.filled == {"X"}


# ------------------------------------------------------------------ edit_card: 미치환 해소
def test_editing_a_missing_token_resolves_it_but_leaving_it_untouched_does_not():
    """미치환 토큰(``{{이름}}``)은 그 글자가 바뀌어야 「고쳤다」다 — 그대로면 여전히 미치환."""
    base = "앞{{D}}뒤"
    marks = (CardMark("missing", "D", 1, 6),)  # "{{D}}" = 5자

    untouched = edit_card(base, marks, base, fullwidth=False)
    assert untouched.resolved == frozenset()

    edited = "앞실제값뒤"
    resolved = edit_card(base, marks, edited, fullwidth=False)
    assert resolved.resolved == {"D"}


# ------------------------------------------------------------------ edit_card: 사상(마주한 편집)
def test_fill_marks_shift_when_text_is_inserted_before_them():
    """표식 앞에 글자가 끼어들면 표식 범위 전체가 그만큼 밀린다 — 값 자체는 그대로다."""
    base = "A: 1, B: 2"
    marks = (CardMark("fill", "A", 3, 4), CardMark("fill", "B", 9, 10))
    edited = "// " + base  # 맨 앞에 3자 삽입

    result = edit_card(base, marks, edited, fullwidth=False)

    assert len(result.marks) == 2
    for mark in result.marks:
        original = next(m for m in marks if m.name == mark.name)
        assert edited[mark.start:mark.end] == base[original.start:original.end]


def test_fill_marks_survive_an_edit_inside_an_unrelated_region():
    """상관없는 자리를 고쳐도 다른 표식의 값 추출은 안 흔들린다."""
    base = "수신: 회계과, 건명: 복사기"
    marks = (CardMark("fill", "수신", 4, 7), CardMark("fill", "건명", 13, 16))
    edited = base.replace("회계과", "회계과(수정)")

    result = edit_card(base, marks, edited, fullwidth=False)

    by_name = {m.name: m for m in result.marks}
    assert edited[by_name["수신"].start:by_name["수신"].end] == "회계과(수정)"
    assert edited[by_name["건명"].start:by_name["건명"].end] == "복사기"


# ------------------------------------------------------------------ edit_card: 전각 정렬
def test_fullwidth_aligns_only_outside_marks_and_keeps_marks_consistent():
    """전각 정렬은 표식 **밖**(템플릿 원문 자리)에만 건다 — 값 안의 연속 공백은 데이터 사실."""
    prefix, gap1 = "가", "  "
    value = "나  나"  # 값 안의 연속 공백 — 안 건드린다
    gap2, suffix = "  ", "다"
    base = prefix + gap1 + value + gap2 + suffix
    mark = CardMark(
        "fill", "필드", len(prefix) + len(gap1), len(prefix) + len(gap1) + len(value)
    )

    result = edit_card(base, (mark,), base, fullwidth=True)

    assert len(result.marks) == 1
    shown = result.marks[0]
    assert result.text[shown.start:shown.end] == value       # 표식 안은 원문 그대로
    before, after = result.text[:shown.start], result.text[shown.end:]
    assert "  " not in before and "  " not in after           # 표식 밖엔 반각 연속 공백이 없다
    assert "　" in before and "　" in after            # 전각 공백으로 바뀌었다


def test_fullwidth_off_leaves_consecutive_spaces_untouched():
    """``fullwidth=False`` 면 표식 밖도 치환하지 않는다 — 치환은 세션 옵션일 때만."""
    base = "가  나  다"
    marks = (CardMark("fill", "필드", 3, 4),)

    result = edit_card(base, marks, base, fullwidth=False)

    assert result.text == base
    assert result.space_run is True  # 런 자체는 여전히 참(치환 전 글자로 잰다)


# ------------------------------------------------------------------ utf16_marks
def test_utf16_marks_accounts_for_a_non_bmp_character_before_a_mark():
    """BMP 밖 글자(예: 이모지)는 UTF-16 로 2 코드 단위다 — JS 오프셋은 그 단위를 센다."""
    text = "😀X"
    marks = (CardMark("fill", "f", 1, 2),)  # 코드 포인트 좌표(파이썬 str 인덱스)

    out = utf16_marks(text, marks)

    assert out == [{"kind": "fill", "name": "f", "start": 2, "end": 3}]


def test_utf16_marks_matches_python_offsets_for_bmp_only_text():
    """BMP 안쪽(한글 포함) 텍스트는 코드 포인트 좌표와 UTF-16 좌표가 같다."""
    text = "안녕X"
    marks = (CardMark("fill", "f", 2, 3),)

    out = utf16_marks(text, marks)

    assert out == [{"kind": "fill", "name": "f", "start": 2, "end": 3}]


# ------------------------------------------------------------------ raw_card
def test_raw_card_shows_tokens_unfilled_and_marks_them_missing():
    """원문 보기 — 토큰을 채우지 않고 ``{{이름}}`` 그대로, 전부 미치환 표식이다."""
    text, marks = raw_card("수신: {{수신}}\n건명: {{건명}}")

    assert "{{수신}}" in text and "{{건명}}" in text
    assert [m.kind for m in marks] == ["missing", "missing"]
    assert [m.name for m in marks] == ["수신", "건명"]
    for m in marks:
        assert text[m.start:m.end] == "{{" + m.name + "}}"


# ------------------------------------------------------------------ CardEdits
def test_card_edits_put_clears_when_the_edit_matches_the_unedited_text():
    """원문과 같아지면 편집이 없는 것으로 접는다 — 되돌리기를 치지 않아도 빈 편집은 안 남는다."""
    edits = CardEdits()
    edits.put(0, "고친 글", "원문")
    assert 0 in edits and edits.get(0) == "고친 글"

    edits.put(0, "원문", "원문")  # 다시 원문과 같아졌다
    assert 0 not in edits and edits.get(0) is None


def test_card_edits_revert_only_bumps_epoch_when_an_edit_existed():
    """세대는 표면이 문서를 갈아 끼워야 할 때만 오른다 — 지울 것이 없으면 조용히 무동작."""
    edits = CardEdits()
    before = edits.epoch

    edits.revert(0)  # 편집이 없던 행
    assert edits.epoch == before

    edits.put(0, "고침", "원문")
    edits.revert(0)
    assert edits.epoch == before + 1
    assert 0 not in edits


def test_card_edits_signature_differs_with_the_edit_and_is_stable_without_it():
    """지문은 규칙 + 그 행의 편집본을 함께 담는다 — 편집만 달라져도 지문이 갈린다."""
    edits = CardEdits()
    rules = "규칙-지문"

    base_sig = edits.signature(0, rules)
    assert edits.signature(0, rules) == base_sig  # 같은 입력 — 같은 지문(순수 함수)

    edits.put(0, "고침", "원문")
    assert edits.signature(0, rules) != base_sig
    assert edits.signature(1, rules) == base_sig  # 다른 행은 영향받지 않는다


# ------------------------------------------------------------------ 보수 판정(#1153 리뷰 후속)
def test_a_repeated_blank_counts_as_filled_only_when_every_occurrence_is_filled():
    """같은 이름의 빈 자리가 둘이면 **둘 다** 채워야 채운 것이다(Codex 4182765550).

    하나만 채우고 이름째 게이트에서 빼면, 나머지 〈빈 값〉이 그대로인데 복사 전 확인이 묻지 않는다.
    """
    base = " / "
    marks = (CardMark("blank", "x", 0, 0), CardMark("blank", "x", 3, 3))

    assert edit_card(base, marks, "v / ", fullwidth=False).filled == frozenset()
    assert edit_card(base, marks, "v / w", fullwidth=False).filled == {"x"}


def test_text_typed_next_to_a_missing_token_does_not_resolve_it():
    """미치환 토큰 옆에 친 글자로는 해소되지 않는다 — 토큰 글자가 사라져야 한다(Codex 4182765572)."""
    base = "{{x}} end"
    marks = (CardMark("missing", "x", 0, 5),)

    for edited in ("{{x}}! end", "!{{x}} end", "{{x}}{{x}} end"):
        result = edit_card(base, marks, edited, fullwidth=False)
        assert result.resolved == frozenset(), edited
        mark = result.marks[0]
        assert edited[mark.start:mark.end] == "{{x}}", edited  # 표식은 토큰만 덮는다

    assert edit_card(base, marks, "값 end", fullwidth=False).resolved == {"x"}
    # 다른 글자로 바꿔 쳤으면 x 의 토큰은 복사본에 없다 — x 는 고친 것이다.
    assert edit_card(base, marks, "{{y}} end", fullwidth=False).resolved == {"x"}


def test_replacing_literal_text_beside_a_blank_does_not_fill_the_blank():
    """빈 자리 옆 원문 글자를 바꾼 편집은 그 빈 자리를 채운 것이 아니다(리뷰 미보고 동류)."""
    base = "금액:원"
    marks = (CardMark("blank", "amt", 3, 3),)

    replaced = edit_card(base, marks, "금액;원", fullwidth=False)
    assert replaced.filled == frozenset()
    assert (replaced.marks[0].start, replaced.marks[0].end) == (3, 3)

    assert edit_card(base, marks, "금액:5원", fullwidth=False).filled == {"amt"}


def test_repeated_literal_text_still_anchors_an_unambiguous_insertion():
    """되풀이 글자 사이 삽입도 덜 고친 정렬로 자리를 찾는다(Codex 4182765581 재현)."""
    base = "AAA"  # A{{x}}A{{y}}A, 둘 다 빈 값
    marks = (CardMark("blank", "x", 1, 1), CardMark("blank", "y", 2, 2))

    result = edit_card(base, marks, "ABAA", fullwidth=False)

    assert result.filled == {"x"}
    by_name = {m.name: m for m in result.marks}
    assert "ABAA"[by_name["x"].start:by_name["x"].end] == "B"
    assert by_name["y"].start == by_name["y"].end == 3


def test_ambiguous_insertions_never_count_as_filled():
    """어느 자리의 글자인지 단정할 수 없으면 채우지 않은 것으로 남긴다 — 확인이 계속 묻는다."""
    adjacent = (CardMark("blank", "x", 2, 2), CardMark("blank", "y", 2, 2))  # {{x}}{{y}}
    assert edit_card("가 끝", adjacent, "가 값끝", fullwidth=False).filled == frozenset()

    slides = (CardMark("blank", "x", 2, 2),)  # "AA" 사이 빈 자리에 "A" — 옆 원문과 구별 불가
    assert edit_card("AAAA", slides, "AAAAA", fullwidth=False).filled == frozenset()

    beside_value = (CardMark("fill", "a", 0, 1), CardMark("blank", "b", 1, 1))  # {{a}}{{b}}
    assert edit_card("값 끝", beside_value, "값추가 끝", fullwidth=False).filled == frozenset()


def test_filling_several_blanks_in_one_card_still_counts_each():
    """한 카드에서 빈 자리 여럿을 채우는 보통의 편집은 보수 판정 뒤에도 각각 채움이다."""
    base = "수신: \n건명: \n끝"
    marks = (CardMark("blank", "a", 4, 4), CardMark("blank", "b", 9, 9))
    edited = "수신: 총무과\n건명: 복사기\n끝"

    result = edit_card(base, marks, edited, fullwidth=False)

    assert result.filled == {"a", "b"}
    assert [edited[m.start:m.end] for m in result.marks] == ["총무과", "복사기"]


# ------------------------------------------------------------------ plain_edit(전각 정렬 되돌림)
def test_plain_edit_restores_alignment_spaces_and_keeps_typed_characters():
    """정렬된 표시본을 고친 글 → 정렬 전 글(Codex 4182765557).

    앱이 넣은 전각 공백은 반각 둘로 돌아가고, 사용자가 친 전각 공백은 친 그대로 남는다.
    """
    plain = "항목:    값 V"
    marks = (CardMark("fill", "v", 9, 10),)
    shown = edit_card(plain, marks, plain, fullwidth=True).text
    assert shown == "항목:　　값 V"

    assert plain_edit(shown, plain, shown + "!") == plain + "!"
    assert plain_edit(shown, plain, shown) == plain           # 쳤다 지운 편집은 원문 그대로
    assert plain_edit(shown, plain, shown.replace("값", "　값")) == "항목:    　값 V"
    assert plain_edit(plain, plain, plain + "!") == plain + "!"  # 정렬이 꺼져 있으면 그대로


# ------------------------------------------------------------------ CardEdits.text_rev
def test_text_rev_rises_only_when_an_unedited_row_shows_new_text():
    """편집이 없는 행의 원문이 바뀌면 세대가 오르고, 편집 중인 행·접힌 행은 그대로다(Codex 4182765591)."""
    edits = CardEdits()
    first = edits.text_rev(0, "09:00")
    assert edits.text_rev(0, "09:00") == first          # 같은 원문 — 같은 세대

    second = edits.text_rev(0, "09:01")                 # 분 경계 — 표면이 문서를 갈아 끼운다
    assert second != first

    edits.put(0, "09:01 고침", "09:01")
    assert edits.text_rev(0, "09:02") == second         # 편집 중인 행은 표면 문서가 정본

    edits.put(0, "09:02", "09:02")                      # 지금 원문과 같아져 접혔다
    assert edits.text_rev(0, "09:02") == second         # 표면 문서가 이미 그 글 — 다시 끼우지 않는다
    assert edits.text_rev(None, "x") == 0
