"""ordinary Field v1 grammar fixtures shared with the resolver tests."""

from __future__ import annotations

from typing import NamedTuple

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
FOREIGN_NS = "urn:unsupported-field"
_FIELD_ID = "627272811"  # representative named CLICK_HERE value; not pair identity.
_CORPUS_PARAMETERS = (
    '<hp:parameters cnt="3" name=""><hp:integerParam name="Prop">9</hp:integerParam>'
    '<hp:stringParam name="Command" xml:space="preserve">Clickhere:set:53:'
    "Direction:wstring:10:{{입찰공고번호}} HelpState:wstring:0:  </hp:stringParam>"
    '<hp:stringParam name="Direction">{{입찰공고번호}}</hp:stringParam></hp:parameters>'
)


class FieldGrammarCase(NamedTuple):
    entry: str
    xml: bytes
    raw_names: "tuple[str, ...]" = ()
    unsupported_kind: "str | None" = None


def _entry(body: str) -> bytes:
    return (
        f'<hs:sec xmlns:hs="{HS_NS}" xmlns:hp="{HP_NS}" xmlns:x="{FOREIGN_NS}">'
        f"{body}</hs:sec>"
    ).encode("utf-8")


def _run(body: str) -> str:
    return f"<hp:run>{body}</hp:run>"


def _paragraph(body: str) -> str:
    return f"<hp:p>{body}</hp:p>"


def _begin(
    pair_id: int, name: str, *, prefix: str = "hp", parameters: str = ""
) -> str:
    start = (
        f"<{prefix}:ctrl><{prefix}:fieldBegin id=\"{pair_id}\" type=\"CLICK_HERE\" "
        f'name="{name}" editable="1" dirty="1" zorder="-1" '
        f'fieldid="{_FIELD_ID}" metaTag=""'
    )
    if parameters:
        return f"{start}>{parameters}</{prefix}:fieldBegin></{prefix}:ctrl>"
    return f"{start}/></{prefix}:ctrl>"


def _end(pair_id: int) -> str:
    return (
        f'<hp:ctrl><hp:fieldEnd beginIDRef="{pair_id}" '
        f'fieldid="{_FIELD_ID}"/></hp:ctrl>'
    )


def _field(pair_id: int, name: str, value: str = "값") -> str:
    return _run(_begin(pair_id, name)) + _run(f"<hp:t>{value}</hp:t>") + _run(
        _end(pair_id)
    )


SUPPORTED_FIELD_GRAMMAR = {
    "top_level_paragraph": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                _run(_begin(1, "입찰공고번호", parameters=_CORPUS_PARAMETERS))
                + _run("<hp:t>{{입찰공고번호}}</hp:t>")
                + _run(_end(1))
            )
        ),
        ("입찰공고번호",),
    ),
    "header_body_paragraph": FieldGrammarCase(
        "Contents/header0.xml",
        _entry(_paragraph(_field(2, "머리말"))),
        ("머리말",),
    ),
    "footer_body_paragraph": FieldGrammarCase(
        "Contents/footer0.xml",
        _entry(_paragraph(_field(3, "꼬리말"))),
        ("꼬리말",),
    ),
    "table_cell_sublist_paragraph": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                _run(
                    "<hp:tbl><hp:tr><hp:tc><hp:subList>"
                    + _paragraph(_field(4, "표셀"))
                    + "</hp:subList></hp:tc></hp:tr></hp:tbl>"
                )
            )
        ),
        ("표셀",),
    ),
    "multiple_runs_and_value_fragments": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                _run(_begin(5, "파편"))
                + _run("<hp:t>정보</hp:t>")
                + _run("<hp:t>시스템</hp:t><hp:t> 구축</hp:t>")
                + _run(_end(5))
            )
        ),
        ("파편",),
    ),
    "multiple_fields_in_one_paragraph": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(_paragraph(_field(6, "첫째") + _field(7, "둘째"))),
        ("첫째", "둘째"),
    ),
    "begin_end_in_same_run": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(_paragraph(_run(_begin(8, "한런") + "<hp:t>값</hp:t>" + _end(8)))),
        ("한런",),
    ),
    "empty_field": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(_paragraph(_run(_begin(9, "빈필드")) + _run(_end(9)))),
        ("빈필드",),
    ),
}


UNSUPPORTED_FIELD_GRAMMAR = {
    "paragraph_crossing": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(_run(_begin(20, "문단횡단")))
            + _paragraph(_run("<hp:t>값</hp:t>") + _run(_end(20)))
        ),
        ("문단횡단",),
        "paragraph-crossing",
    ),
    "container_crossing": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                _run(
                    "<hp:tbl><hp:tr><hp:tc><hp:subList>"
                    + _paragraph(_run(_begin(21, "컨테이너횡단")))
                    + "</hp:subList></hp:tc></hp:tr></hp:tbl>"
                )
                + _run(_end(21))
            )
        ),
        ("컨테이너횡단",),
        "unsupported-container-crossing",
    ),
    "nested_fields": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                _run(_begin(22, "바깥"))
                + _run(_begin(23, "안쪽"))
                + _run("<hp:t>값</hp:t>")
                + _run(_end(23))
                + _run(_end(22))
            )
        ),
        ("바깥", "안쪽"),
        "nested-field",
    ),
    "ambiguous_end": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                _run(_begin(24, "첫째"))
                + _run(_begin(24, "둘째"))
                + _run(_end(24))
            )
        ),
        ("첫째", "둘째"),
        "ambiguous-end",
    ),
    "foreign_namespace": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(_paragraph(_run(_begin(25, "외부", prefix="x")) + _run(_end(25)))),
        ("외부",),
        "non-native-field-control",
    ),
    "marker_outside_control": FieldGrammarCase(
        "Contents/section0.xml",
        _entry(
            _paragraph(
                '<hp:fieldBegin id="26" type="CLICK_HERE" name="제어밖" '
                f'fieldid="{_FIELD_ID}"/>'
                + _run(_end(26))
            )
        ),
        ("제어밖",),
        "unsupported-control-shape",
    ),
}
