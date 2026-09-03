"""매핑 위저드 행 상태 모델 — Qt 비의존 순수 파이썬(헤드리스 단위 테스트 대상).

``suggest_mappings`` 초안과 사람의 확정 사이를 잇는 계층. **명시성 원칙**
([[hwpx-filler-scope]]): 자동 제안은 초안일 뿐이므로 초안이 채워져 있어도 모든 행은
``confirmed=False`` 로 시작하고, 사람이 행별로 확정해야 ``is_complete()`` 가 True 가
된다 — 위저드는 이 게이트를 통과해야만 다음(저장) 단계로 넘어간다.

행 편집(소스/유형/상수 변경)은 확정을 해제한다 — 확정 후 바뀐 행은
다시 사람의 눈을 거쳐야 한다. 저장된 프로파일의 로드(``apply_profile``)만 예외로
확정 상태로 도착한다: 프로파일 자체가 과거에 사람이 확정한 산출물이기 때문이다.

**엄격한 1:1 계약**(코어 미러). 한 템플릿 필드는 정확히 한 소스 키(``source``)에서
값을 취한다 — N→1 결합·구분자(sep)는 없다. 날짜+시각처럼 예전에 두 키를 합치던
자리는 소스가 이미 합쳐진 단일 키를 주거나 각각 별도 필드로 매핑한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..domain.authoring import scan_tokens
from ..domain.format_engine import presets as format_presets
from ..domain.job import MISSING_MARKER
from ..domain.lint import similarity
from ..domain.mapping import (
    SUGGEST_THRESHOLD,
    TYPES,
    FieldMapping,
    MappingProfile,
    suggest_mappings,
)
from ..domain.schema import FieldSpec, TemplateSchema, extract_schema, infer_type
from ..domain.template_status import CompileState, TemplateStatus, compile_status

if TYPE_CHECKING:
    from datetime import datetime

# inferred_type → 기본 값 유형. 명시 없는 타입은 text(그대로).
_DEFAULT_TYPE = {"date": "date", "amount": "amount"}

# RAW(필드 0개) 차단 사유의 **단일 원천**(UD-21). 위저드 1단계와 PartialGate.message()
# 가 같은 문구를 쓰도록 여기 한 곳에서만 정의한다 — 뷰·VM 이중화(문구 드리프트) 금지.
RAW_BLOCK_MESSAGE = (
    "이 템플릿에는 누름틀 필드가 없어 진행할 수 없습니다.\n"
    "한글에서 누름틀을 삽입하거나 누름틀 변환으로 토큰을 바꾼 템플릿을 쓰세요."
)

# 잔존 구간 표기 차단 사유의 **단일 원천**(S8-04 #835). 편집 게이트
# (:meth:`PartialGate.message`)와 생성 admission(`webapp.screen_job._ADMISSION_REJECT_TEXT`)
# 이 같은 차단을 같은 문장으로 말한다 — 같은 상태를 두 표면이 따로 문안화하면 사용자는
# 한 결함을 두 이름으로 배운다. 문형은 COPY_STYLE_GUIDE(오류=① 문제 ② 조치 2문장,
# em dash 금지, 낫표 대신 작은따옴표) 준수.
STRUCTURE_NOTATION_BLOCK_MESSAGE = (
    "구간 표기가 아직 변환되지 않았습니다. "
    "'템플릿' 탭에서 '누름틀·구간 변환'을 먼저 실행하세요."
)

#: 행 상태 4태 → 사용자가 볼 배지 문안(U6-C #977). **닫힌 집합**이고 라벨의 단일 출처다 —
#: 종전에는 링2 표면이 `confirmed`/`touched`/`source` 세 값에서 「확정/수동/제안/후보 없음」을
#: 스스로 조립했다. 그러면 같은 상태를 두 곳이 판정하고, 링1 이 술어를 고쳐도 표면만 옛말을
#: 계속 한다. `edited` 와 `needs_source` 가 같은 문안인 것은 의도다: 사람이 할 일이 같다
#: (이 행을 보고 확인해야 한다). 갈리는 것은 **왜 그런가**이고 그것은 데이터 열 칸이 말한다.
ROW_STATUS_LABEL = {
    "suggested": "제안",
    "edited": "확인 필요",
    "confirmed": "확인",
    "needs_source": "확인 필요",
}

#: 데이터 열 select 의 **특수 항목** 문안(U6-C #977). 실제 열 이름 공간과 섞이지 않는다 —
#: 이 셋은 열이 아니라 「값을 어디서 얻는가」의 다른 답이고, 표면은 열 선택(`set_source`)이
#: 아니라 `set_display`/`set_blank` 로 갈라 발행한다(센티넬을 소스 값에 얹으면 동명 실열과
#: 충돌해 그 열을 영영 못 겨눈다 — 리뷰 R5 의 근거가 그대로 산다).
SPECIAL_SOURCE_LABEL = {
    "const": "고정값…",
    "today": "오늘 날짜",
    "blank": "비워 둠",
}

#: 무결속 행의 열 placeholder — 「고르세요」는 문안이지 상태가 아니다(상태는 배지가 낸다).
NO_SOURCE_LABEL = "열을 고르세요"

#: 표시형 select 의 **유형 그룹** 라벨(U6-C 리뷰 1). 유형 열이 걷히면서 「이 값을 무엇으로
#: 볼 것인가」의 축이 갈 곳을 잃었다 — `infer_type` 은 이름 키워드 휴리스틱이라 「계약일」이
#: text 로 추정되면 날짜 서식을 **영영** 못 고른다. 그 축을 표시형 select 가 흡수한다:
#: 옵션이 유형별로 묶이고 한 번 고르면 (유형, 표시형) 한 쌍이 원자적으로 선다.
TYPE_GROUP_LABEL = {
    "text": "텍스트",
    "date": "날짜",
    "amount": "금액",
    "today": "오늘 날짜",
    "const": "고정값",
}

#: 열에서 값을 받는 행이 고를 수 있는 유형 축(문서순 = 그룹 표시순).
DISPLAY_TYPE_GROUPS = ("text", "date", "amount")

#: 표시형 프리셋은 유형별 고정이라 한 번 계산한다(코어 라벨 그대로). 행 투영이 소비하므로
#: 투영과 같은 자리에 산다 — 종전 자리는 링2(`screen_editor._FMT_OPTIONS`)였고 투영이 링1 로
#: 올라오면서 그 상수도 따라왔다(투영이 자기 재료를 링2 에서 import 하면 링이 뒤집힌다).
_FMT_OPTIONS = {
    t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES
}

#: 「첫 행」 미리보기의 **읽기 상태** 3태(U6-F #980). 편집기는 데이터를 이미 들고 있어
#: ``ready`` 만 내지만, 「문서 작업」 상세는 선택 직후 아직 파일을 안 읽었고(``pending``)
#: 읽다 실패할 수도 있다(``error``). ``record={}`` 로 미읽음을 흉내 내지 않는 것이 이 축의
#: 존재 이유다 — 빈 레코드는 :data:`~hwpxfiller.domain.job.MISSING_MARKER` 를 찍어 「산출물이
#: 담을 것」과 「아직 모름」을 한 표식으로 접는다(조용한 거짓말).
FIRST_ROW_STATES = ("ready", "pending", "error")

#: 아직 읽지 않은 첫 행 칸의 표식. 홑 문자 하나짜리 **빈 칸 마커**라
#: ``docs/COPY_STYLE_GUIDE.md`` §3-1(문장 안 em dash 금지)의 예외다 — 문장이 아니다.
PENDING_PREVIEW_MARK = "—"


def pairing_preview(
    template_fields: "list[str]", source_fields: "list[str]"
) -> "tuple[int, int]":
    """고르기 단계 연결 카드의 **읽기 전용** 수치 ``(자동 연결, 확인 필요)`` — 순수 함수.

    U6-B(#976). 1단계는 매핑 모델을 만들지 **않는다**: 모델 생성은 2단계 진입의
    ``_ensure_model`` 하나가 지고(전원 미확정 재생성·값 이월 재진술이 그 자리에 걸려
    있다), 카드가 미리 만들면 고르기를 바꿔 보는 것만으로 그 전이가 돌아 확정이 조용히
    무너진다. 그래서 여기서는 :func:`~hwpxfiller.domain.mapping.suggest_mappings` 를
    **그대로** 한 번 돌려 세어 보기만 한다 — 같은 함수라 카드의 「자동 연결 n」과 2단계가
    실제로 세우는 제안 행 수가 정의상 같다(수치를 따로 지으면 두 곳이 갈린다).

    ``확인 필요`` 는 제안을 못 받은 나머지다. 확정/미확정 축은 여기 없다 — 그 축은 모델이
    있을 때만 존재하고, 있으면 표면은 이 함수 대신 모델의 실제 수치를 읽는다(``basis``).
    """
    suggested = {
        m.template_field for m in suggest_mappings(template_fields, source_fields)
    }
    auto = sum(1 for name in template_fields if name in suggested)
    return auto, len(template_fields) - auto


def default_transform_for(inferred_type: str) -> str:
    """스키마의 의미 타입에서 기본 값 유형을 유도한다(date→date, amount→amount, 그 외 text)."""
    return _DEFAULT_TYPE.get(inferred_type, "text")


def profile_source_vocabulary(profile) -> "list[str]":
    """프로파일이 참조하는 소스 키 합집합 — 선언순·중복 제거(단일 출처).

    malformed blank+source(구/훼손 프로파일이 blank 선언에 source 를 남긴 경우)는
    어휘에 흘리지 않는다 — 유령 키가 소스 피커 후보로 오표시되는 것을 막는다.
    :meth:`MappingModel.from_profile` 과 에디터 편집 모드 복원(``load_job``)이 같은
    합집합을 써야 드롭다운 오표시가 표류하지 않아 여기 한 곳에 모은다.
    """
    seen: "dict[str, None]" = {}
    for m in profile.mappings:
        if not m.is_blank and m.source:
            seen.setdefault(m.source, None)
    return list(seen)


# ── 행 투영(U6-F #980) — 편집기 2단계 표와 「문서 작업」 상세 표가 **같은 함수**를 부른다 ──
# 종전에는 링2 컨트롤러(`screen_editor._row_snapshot`)가 이 성형을 소유했고, 두 번째 호스트가
# 생기는 순간 그 사본이 하나 더 생길 자리였다. #966 이 라이브러리 상세의 「필드 연결」 표를
# 걷은 이유가 바로 그 사본(별도 라벨 사전을 든 payload 사슬)이었으므로, 되살리는 길은 하나다:
# 투영과 라벨을 링1 로 올려 **두 표면이 같은 값을 소비**하게 한다.


def source_kind_of(row: "RowState") -> str:
    """이 행의 데이터 열 칸이 지금 무엇을 들고 있는가 — ``column``/``const``/``today``/
    ``blank``/``""``.

    「비워 둠」이 먼저다: 유형은 남아 있어도 사람이 「채우지 않는다」고 선언한 행은 그
    선언으로 보여야 한다.
    """
    if row.is_empty_confirmed():
        return "blank"
    if row.type == "const":
        return "const"
    if row.type == "today":
        return "today"
    return "column" if row.source else ""


def source_option_value(row: "RowState", source_kind: str) -> str:
    """데이터 열 select 가 지금 고르고 있는 **항목 값**.

    실 열은 ``col:``, 특수 항목은 ``sp:`` 접두다 — 두 이름 공간이 구조적으로 갈리므로
    「고정값…」이라는 이름의 실제 열이 있어도 충돌하지 않는다(센티넬을 소스 값에 얹지
    않는다는 규칙의 집행). 웹은 이 값을 파싱하지 않고 항목의 ``kind`` 로 발행 액션을 가른다.
    """
    if source_kind == "column":
        return f"col:{row.source}"
    if source_kind in ("const", "today", "blank"):
        return f"sp:{source_kind}"
    return ""


def display_options(row: "RowState", source_kind: str) -> "list[dict]":
    """이 행의 표시형 select 항목 — **유형 그룹**으로 묶인다(U6-C 리뷰 1).

    값은 ``"<유형>:<표시형 코드>"`` 한 쌍이고 항목이 ``type``·``fmt`` 를 따로 들어 웹이 그
    문자열을 파싱하지 않는다(데이터 열 항목과 같은 규율).

    그룹 집합은 **값의 출처**가 가른다: 열에서 받는 행은 텍스트·날짜·금액 셋을 고를 수
    있고(이 select 가 곧 유형 축이다), 「오늘 날짜」 행은 날짜 어휘 하나뿐이며(값은 실행
    시각이지만 표시형 표는 같다 — U4 §2.14 판정 1), 「고정값」 행은 프리셋이 없어 빈
    목록이다(표면은 비활성 「—」로 접는다).
    """
    if source_kind == "const":
        return []
    kinds = ("today",) if source_kind == "today" else DISPLAY_TYPE_GROUPS
    groups: "list[dict]" = []
    for kind in kinds:
        options = [
            {"value": f"{kind}:{o['code']}", "label": o["label"], "type": kind, "fmt": o["code"]}
            for o in _FMT_OPTIONS.get(kind, [])
        ]
        if options:
            groups.append({"label": TYPE_GROUP_LABEL[kind], "options": options})
    return groups


def row_projection(
    row: "RowState",
    record: "dict",
    *,
    index: int,
    source_fields: "list[str]",
    has_records: bool,
    now: "datetime | None" = None,
    first_row_state: str = "ready",
) -> dict:
    """행 1개의 표 투영 — 편집기 2단계와 「문서 작업」 상세가 공유하는 **순수 함수**.

    ``now`` 는 ``today``(오늘 날짜) 미리보기의 기준 시각이다 — 호출자가 **스냅샷당 1회**
    잡아 전 행이 공유한다(RC-02 확장, `screen_job` 의 `_names_now` 규율). 행마다 clock 을
    다시 부르면 한 표 안에서 서로 다른 시각이 서고, 하위-일 서식에서 그 차이가 눈에 보인다.

    **행 상태와 그 라벨은 링1 이 낸다**(U6-C #977): ``row_state`` 는 닫힌 집합 4태이고
    ``state_label`` 은 그 문안이다.

    **미리보기는 산출물이 담을 것을 그대로 말한다.** 결속됐는데 이 행에서 값이 비면 빈칸이
    아니라 :data:`~hwpxfiller.domain.job.MISSING_MARKER` 다 — 생성이 그 자리에 실제로 넣는
    문자열이라 UI 문안이 아니라 데이터다.

    ``first_row_state`` 는 **레코드를 실제로 읽었는가**를 명시로 받는다(U6-F #980):
    ``pending``·``error`` 면 ``record`` 를 보지 않고 미리보기 칸만 그 상태로 낸다. 이 인자가
    없으면 호출자가 빈 레코드로 미읽음을 흉내 내게 되고, 그 순간 표는 「아직 모름」을
    「미입력 표식이 박힐 자리」로 말한다.
    """
    if first_row_state not in FIRST_ROW_STATES:
        raise ValueError(f"알 수 없는 첫 행 상태: {first_row_state!r}")
    preview_error = False
    empty = False
    if first_row_state == "pending":
        preview_kind, preview = "pending", PENDING_PREVIEW_MARK
    elif first_row_state == "error":
        # 사유는 호출자가 존 수준에서 싣는다 — 행마다 같은 문장을 복제하지 않는다.
        preview_kind, preview, preview_error = "error", "", True
    else:
        try:
            preview = row.to_mapping().value_for(record, now=now)
        except ValueError:
            preview, preview_error = "", True
        empty = bool(row.has_content()) and preview == ""
        if preview_error:
            preview_kind, preview = "error", ""
        elif row.has_content():
            preview_kind = "missing" if empty else "value"
            if empty:
                preview = MISSING_MARKER.format(field=row.template_field)
        elif row.is_empty_confirmed():
            preview_kind, preview = "blank", ""
        else:
            preview_kind, preview = "none", ""
    source_kind = source_kind_of(row)
    state = row.status()
    inferred = getattr(row.spec, "inferred_type", "") if row.spec else ""
    return {
        "index": index,
        "template_field": row.template_field,
        "inferred_type": inferred,
        "context": getattr(row.spec, "context", "") if row.spec else "",
        "source": row.source,
        "type": row.type,
        "const": row.const,
        "fmt": row.fmt,
        # 이 행의 표시형 후보 — **유형 축을 흡수한 그룹 목록**이다(U6-C 리뷰 1). 유형별 표를
        # 웹이 되짚지 않는다(유형이 행 축이므로 후보도 행 축이다).
        "display_options": display_options(row, source_kind),
        "display_value": f"{row.type}:{row.fmt}",
        "confirmed": row.confirmed,
        "touched": row.touched,
        "has_content": row.has_content(),
        # 배지 버튼이 눌리는가 — 채울 것이 없고 **확인도 안 된** 행만 잠긴다(U6-C 리뷰 4).
        # 비움 확정 행은 채울 것이 없어도 확인을 **풀 수 있어야** 한다: 잠그면 「확인」 배지가
        # 비활성으로 서서 「열을 고르세요」라고 말하는, 자기 상태와 어긋난 손잡이가 된다.
        "confirmable": row.has_content() or row.confirmed,
        # ↻(자동 제안 되돌리기)가 서는가 — `_do_revert_source` 가 확정 행을 거절하는 것과
        # **같은 술어**다(U6-C 리뷰 9). 웹이 다시 조립하면 거절과 어포던스가 갈린다.
        "revertable": row.touched and not row.confirmed and has_records,
        "suggestion_score": round(row.suggestion_score, 3),
        "preview": preview,
        "preview_kind": preview_kind,
        "preview_empty": empty,
        "preview_error": preview_error,
        "row_state": state,
        "state_label": ROW_STATUS_LABEL[state],
        "source_kind": source_kind,
        "source_value": source_option_value(row, source_kind),
        # 결속 열이 지금 데이터에 없다 — 「(비움)」으로 오표시하지 않고 명시 항목으로
        # 드러낸다(문안은 여기, 렌더는 웹).
        "source_missing_label": (
            f"{row.source} (데이터에 없음)"
            if source_kind == "column" and row.source not in source_fields else ""
        ),
    }


def source_cell_label(projection: "dict") -> str:
    """읽기 전용 표의 「데이터 열」 칸 문안 — :func:`row_projection` 결과 하나를 읽는다.

    편집하는 표는 select 라 항목이 자기 라벨을 들고 오지만, 읽기 전용 표는 **해소된 라벨**이
    필요하다. 그것을 웹에서 지으면 특수 항목 문안 표(:data:`SPECIAL_SOURCE_LABEL`)가 링1 밖에
    한 벌 더 생긴다 — #966 이 걷은 그 사슬이 이름만 바꿔 돌아오는 자리다.
    """
    if projection["source_missing_label"]:
        return projection["source_missing_label"]
    kind = projection["source_kind"]
    if kind == "column":
        return projection["source"]
    if kind == "const":
        # 고정값은 「무엇으로 고정했는가」가 곧 그 칸의 내용이다.
        return f"{SPECIAL_SOURCE_LABEL['const']} {projection['const']}".rstrip()
    if kind in SPECIAL_SOURCE_LABEL:
        return SPECIAL_SOURCE_LABEL[kind]
    return NO_SOURCE_LABEL


def display_cell_label(projection: "dict") -> str:
    """읽기 전용 표의 「표시형」 칸 문안 — 고른 표시형의 라벨(없으면 빈 칸 마커).

    프리셋 표를 **직접** 본다(투영이 든 그룹 목록을 훑지 않는다): 후보 목록은 select 를
    그리려고 있는 것이고, 여기 필요한 것은 (유형, 표시형) 한 쌍의 이름 하나다. 고정값 행은
    프리셋이 없어 고를 것도 없다(편집기에서 비활성 「—」로 접히는 그 자리).
    """
    kind, _, code = str(projection["display_value"]).partition(":")
    for option in _FMT_OPTIONS.get(kind, ()):
        if option["code"] == code:
            return option["label"]
    return PENDING_PREVIEW_MARK


@dataclass
class RowState:
    """템플릿 필드 1개의 매핑 편집 상태 — 단일 ``source`` 를 ``type`` 으로 서식.

    ``confirmed=True`` 인데 채울 내용이 없으면(소스도 상수도 없음) **의도적 비움
    확정** — "이 필드는 채우지 않는다"를 사람이 명시한 상태다(``to_profile`` 이
    명시적 ``blank`` 선언으로 영속화 — L1).
    ``suggestion_score`` 는 자동 제안의 유사도(0=제안 없음) — 뷰가 신뢰도 툴팁에 쓴다.

    **소유권(칩-라이브 계약, R-flow 슬라이스 5 블록 2 결정 12)**: ``touched`` 는 사람이 소스/
    내용을 직접 골랐거나 편집했는가다. **미확정·미접촉**(``not confirmed and not touched``)
    = 시스템 소유 → 활성 헤더가 바뀌면 최선으로 **라이브 재제안**된다(조용). **수동(touched)·
    확정** = 사람 소유 → 칩 토글이 못 덮고, 매핑된 헤더가 꺼지면 **시끄러운 강등**(R4)한다.
    ``from_suggestions`` 초안은 ``touched=False``(제안일 뿐), 사람 편집·프로파일 복원은 True.
    """

    template_field: str
    spec: "FieldSpec | None" = None
    source: str = ""
    type: str = "text"
    const: str = ""
    fmt: str = ""  # 표시형 프리셋 키(유형 내). "" = 기본.
    confirmed: bool = False
    suggestion_score: float = 0.0
    touched: bool = False  # 사람이 소스/내용을 직접 정함(수동=사람 소유). 미접촉=시스템 소유.

    def is_system_owned(self) -> bool:
        """시스템 소유 행 — 미확정·미접촉이라 활성 헤더 따라 라이브 재제안 대상(결정 12)."""
        return not self.confirmed and not self.touched

    def is_human_owned(self) -> bool:
        """사람 소유 행(확정 또는 touched) — 소유권 술어의 단일 정의(리뷰: 3중 재진술이
        강등·재제안·이월을 어긋나게 하는 조용한 드리프트류). 강등 조건·이월 대상이 이걸 쓴다."""
        return not self.is_system_owned()

    def default_type(self) -> str:
        """이 행의 **추정 기본 유형** — 리셋·특수 유형 해제가 되돌아갈 자리의 단일 정의.

        두 자리(:meth:`reset_to_system` · :meth:`MappingModel.set_source`)가 각자 적으면
        「되돌리기」와 「열 다시 고르기」가 서로 다른 유형에 착지한다.
        """
        return default_transform_for(self.spec.inferred_type if self.spec else "")

    def status(self) -> str:
        """행 상태 **4태**(U6-C #977) — ``suggested``·``edited``·``confirmed``·``needs_source``.

        종전에는 링2 가 `confirmed`/`has_content`/`schema_only` 로 4태를 짓고 링2 위의 웹이
        `!confirmed && !touched && source` 로 「제안」을 **다시** 유추했다 — 같은 상태를 세
        층이 판정했고, 그중 하나만 고치면 표가 자기 배지와 다른 말을 한다. 판정은 여기 하나다.

        축은 둘이다: **확인했는가**(confirmed)와 **채울 것이 있는가**(has_content). 내용이
        있는데 미확정이면 그것을 누가 정했는지가 갈린다 — 시스템이면 「제안」, 사람이면
        「확인 필요」다(사람이 손댄 값을 「제안」이라 부르면 자동 결과와 구별되지 않는다).
        데이터 미연결(구 ``schemaonly``)은 별도 상태가 아니라 ``needs_source`` 다: 행이
        요구하는 것은 같고, **왜 고를 열이 없는지**는 표 머리가 말한다.
        """
        if self.confirmed:
            return "confirmed"
        if not self.has_content():
            return "needs_source"
        return "suggested" if self.is_system_owned() else "edited"

    def reset_to_system(self) -> None:
        """행을 갓 제안 전의 **시스템 소유 초기 상태**로 완전 리셋 — 강등·되돌리기의 단일 정의.

        소유권 해제(touched/confirmed)만으로는 부족하다(리뷰 R1 동류): 유형·상수·표시형이
        남으면 이후 재제안이 소스만 얹어 '제안 표시 ≠ 실제 출력(옛 상수 방출)' 하이브리드가
        된다. 두 강등 경로(``revert_to_auto``·``apply_active_sources`` R4)가 전부 이 정의로
        착지해 관문 간 상태 불일치를 막는다(구판 ``ignore_source`` 는 관문 단일화로 소멸).
        소스 재제안은 호출측 소관(단일 행=``resuggest_row``, 집합=다음 활성 변화)."""
        self.touched = False
        self.confirmed = False
        self.source = ""
        self.const = ""
        self.fmt = ""
        self.type = self.default_type()
        self.suggestion_score = 0.0

    def has_content(self) -> bool:
        """매핑 내용이 있는가 — **값을 방출하는가**.

        ``const``(man)는 리터럴만 방출하므로(``value_for`` 는 ``source`` 를 무시하고 ``const``
        를 낸다) 기억된 소스는 내용이 아니다 — 결속 값을 비운 자리는 되돌리기 위해 소스를
        기억할 뿐, 출력은 빈 문자열이다(Codex F2). 그걸 내용으로 세면 값을 비우고 확정해도
        :meth:`is_empty_confirmed` 가 거짓이라 확정-비움으로 인식되지 않아 게이트가 계속
        묻는다. 그 외 유형은 결속 소스가 곧 내용이다.

        ``today``(오늘 날짜)는 소스도 상수도 없이 **언제나** 실행 시각의 날짜를 방출한다
        — 소스 유무로 재면 내용 없음이 되어 확정 시 ``to_profile`` 이 ``blank`` 로 강등해
        값이 통째 소실된다(조용한 값 소실). 그래서 무조건 참이다."""
        if self.type == "today":
            return True
        if self.type == "const":
            return self.const != ""
        return bool(self.source)

    def is_empty_confirmed(self) -> bool:
        """의도적 비움 확정 — 확정됐지만 채울 내용이 없음."""
        return self.confirmed and not self.has_content()

    def to_mapping(self, *, blank: bool = False) -> FieldMapping:
        return FieldMapping(
            template_field=self.template_field,
            source="" if blank else self.source,
            type="blank" if blank else self.type,
            const=self.const,
            fmt=self.fmt,
        )


class MappingModel:
    """위저드 매핑 스텝의 전체 행 모델 — 뷰(mapping_table)는 이 API 만 호출한다."""

    def __init__(
        self,
        rows: "list[RowState] | None" = None,
        source_fields: "list[str] | None" = None,
        aliases: "dict[str, str] | None" = None,
    ):
        self.rows: "list[RowState]" = list(rows or [])
        self.source_fields: "list[str]" = list(source_fields or [])
        self.aliases: "dict[str, str]" = dict(aliases or {})

    # ------------------------------------------------------------- 초안 생성
    @classmethod
    def from_suggestions(
        cls,
        schema: TemplateSchema,
        source_fields: "list[str]",
        aliases: "dict[str, str] | None" = None,
    ) -> "MappingModel":
        """스키마 전 필드(문서순)에 행을 만들고 ``suggest_mappings`` 초안을 얹는다.

        미매칭 필드도 빈 행으로 포함한다(사람이 채우거나 비움 확정). 기본 유형은
        inferred_type 에서 유도(date→date, amount→amount, 그 외 text). 모든 행은
        confirmed=False 로 시작한다 — 초안은 초안이다(명시성 원칙).
        """
        aliases = dict(aliases or {})
        drafts = {
            m.template_field: m
            for m in suggest_mappings(schema.field_names(), source_fields, aliases)
        }
        rows: "list[RowState]" = []
        for spec in schema.fields:
            row = RowState(
                template_field=spec.name,
                spec=spec,
                type=default_transform_for(spec.inferred_type),
            )
            draft = drafts.get(spec.name)
            if draft is not None and draft.source:
                row.source = draft.source
                # 제안 점수는 suggest 와 동일 방식(alias 라벨 대상 유사도)으로 복원.
                row.suggestion_score = similarity(
                    spec.name, aliases.get(draft.source, draft.source)
                )
            rows.append(row)
        return cls(rows=rows, source_fields=source_fields, aliases=aliases)

    @classmethod
    def from_field_names(
        cls,
        field_names: "list[str]",
        source_fields: "list[str] | None" = None,
        aliases: "dict[str, str] | None" = None,
        col_kinds: "dict[str, str] | None" = None,
    ) -> "MappingModel":
        """스키마 없이 **토큰 이름 목록**으로 행 모델을 세운다(#148 슬라이스 3b — 「기안」 맞추기).

        txt 트랙엔 hwpx 의 :class:`TemplateSchema` 가 없다({{토큰}} 평문). 매핑 층이 실제로
        쓰는 것은 '순서 있는 이름 + 이름별 유형'뿐이라(모델은 이미 schema-불가지, 설계
        착수전 실측 1) 이름 목록에서 바로 세운다 — ``from_suggestions`` 는 이 위의 스키마
        래퍼가 된다. ``spec=None`` 이며 소비 3곳이 이미 None-관용이다.

        **결속 정책 = 결정 30**: 열 이름이 토큰과 **정확히 같은** 자리만 자동 결속(auto)한다.
        근사는 붙이지 않고 :meth:`suggestions` 의 원클릭 제안으로 넘긴다 — 「근사 제안 자동
        적용」은 저장 세션의 지속성 스위치(슬라이스 5)라 휘발 기본은 꺼져 있다.

        **유형 = 결정 5 우선순위**: 자동 결속 열은 값 스니핑(``col_kinds``)이 이름 추론을
        이긴다. 무결속·스니핑 부재는 이름 휴리스틱(:func:`~hwpxfiller.domain.schema.infer_type`),
        그마저 없으면 text. 전 행 미확정(``confirmed=False``)·미접촉으로 시작한다(초안은 초안).
        """
        source_fields = list(source_fields or [])
        aliases = dict(aliases or {})
        col_kinds = col_kinds or {}
        cols = set(source_fields)
        rows: "list[RowState]" = []
        for name in field_names:
            row = RowState(
                template_field=name,
                spec=None,
                type=default_transform_for(infer_type(name)),
            )
            if name in cols:  # 정확 일치 = 자동 결속(결정 30) — 근사는 suggestions 로
                row.source = name
                row.suggestion_score = 1.0
                kind = col_kinds.get(name, "")
                if kind:  # 값 스니핑이 이름 추론을 이긴다(결정 5) — 없으면 이름 추론 유지
                    row.type = default_transform_for(kind)
            rows.append(row)
        return cls(rows=rows, source_fields=source_fields, aliases=aliases)

    @classmethod
    def from_profile(cls, profile) -> "MappingModel":
        """저장된 프로파일(공유 베이스)에서 직접 행 모델을 구성한다 — 템플릿 없이.

        각 ``FieldMapping`` → **확정** ``RowState``(과거 사람 확정의 복원, ``apply_profile`` 선례).
        워크벤치가 베이스를 표시·재편집할 때 쓴다. ``source_fields`` 는 프로파일이 참조하는
        소스 키 합집합(테이블 소스 피커의 후보, :func:`profile_source_vocabulary` 공유 —
        유령 키 필터 문서화도 그쪽) — 별도 소스 주입 없이도 기존 매핑을 손본다.
        """
        rows: "list[RowState]" = []
        for m in profile.mappings:
            is_blank = m.is_blank
            rows.append(RowState(
                template_field=m.template_field,
                source="" if is_blank else m.source,
                type="text" if is_blank else m.type,
                const="" if is_blank else m.const,
                fmt="" if is_blank else m.fmt,
                confirmed=True,  # 베이스는 확정본
                touched=True,  # 사람 소유(과거 확정 산출물) — 라이브 재제안 비대상(결정 12)
            ))
        return cls(
            rows=rows, source_fields=profile_source_vocabulary(profile), aliases={}
        )

    # ------------------------------------------------------------ 행 편집 API
    # 사람의 편집은 모두 ``touched=True`` — 그 행은 사람 소유가 되어 활성 헤더 변화의 라이브
    # 재제안이 덮지 못한다(칩-라이브 결정 12). 자동 제안으로 되돌리려면 ``revert_to_auto``.
    def set_source(self, index: int, source: str) -> None:
        """열 결속 — **값을 내는 유형과 함께** 세운다(U6-C #977).

        ``const``/``today`` 는 소스를 보지 않고 값을 낸다(``value_for``). 그 유형을 남긴 채
        소스만 얹으면 표는 「이 열에서 온다」고 보이는데 산출물에는 옛 상수·오늘 날짜가
        박힌다 — 표시와 출력이 갈리는 조용한 거짓말이다. 데이터 열을 고르는 것은 곧
        「열에서 값을 얻겠다」는 선언이므로 특수 유형을 추정 기본형으로 되돌리고 그 유형이
        데리고 있던 상수·표시형을 함께 걷는다.
        """
        row = self.rows[index]
        if row.type in ("const", "today"):
            row.type = row.default_type()
            row.const = ""
            row.fmt = ""
        row.source = source
        row.confirmed = False
        row.touched = True

    def set_type(self, index: int, type_: str) -> None:
        if type_ not in TYPES:
            raise ValueError(f"지원하지 않는 유형: {type_!r} (지원: {TYPES})")
        row = self.rows[index]
        row.type = type_
        row.fmt = ""  # 유형이 바뀌면 이전 표시형 키는 무효 → 기본으로.
        if type_ in ("const", "today"):
            # 값의 출처가 열이 아니게 됐다 — 남긴 소스는 표에 「이 열」로 보이지만 값은
            # 상수·오늘 날짜다(``set_source`` 의 짝 규칙). 되돌리기용 소스 기억이 필요한
            # 자리는 ``set_manual`` 이고 그쪽은 이 관문을 지나지 않는다.
            row.source = ""
        row.confirmed = False
        row.touched = True

    def set_blank(self, index: int) -> None:
        """이 필드는 **채우지 않는다**고 사람이 선언한다(U6-C #977) — 행별 비움 확정.

        구 「모두 확정 → 이름 재진술 모달 → ``confirm_fields``」(ADR-E)가 하던 일을 행에서
        직접 한다. 승격 대상을 모아 이름을 되읽어 주던 이유는 **일괄**이 반사적 dismiss 로
        여러 필드를 한 번에 비우기 때문이었고, 행별 선언에는 그 위험이 없다(고른 행이 곧
        확인한 행이다). 결과 상태는 그때와 같다 — ``to_profile`` 은 ``blank`` 선언으로,
        ``declared_blank_fields`` 는 이 필드를 담는다.

        **특수 유형은 추정 기본형으로 되돌린다**(리뷰 5). ``today`` 는 소스도 상수도 없이
        언제나 값을 내므로(``has_content`` 무조건 참) 남기면 「비워 둠」으로 확정된 행이
        오늘 날짜를 찍는다. ``const`` 는 값이야 안 내지만(상수를 비웠다) 유형이 남으면 머리
        pill 「고정값 n」이 채우지 않는 행까지 세고, 확인을 풀면 데이터 열 칸이 「고정값…」
        으로 되살아나 사람이 고른 적 없는 상태를 보여 준다.

        **사람의 편집이므로 ``touched=True`` 다**(리뷰 3 · :class:`RowState` 소유권 규율).
        빼면 확인을 푼 순간 그 행이 시스템 소유로 돌아가 라이브 재제안·일괄 승격이 조용히
        덮는다 — 「채우지 않는다」는 선언이 사람 모르게 뒤집히는 자리다.
        """
        row = self.rows[index]
        row.source = ""
        row.const = ""
        if row.type in ("const", "today"):
            row.type = row.default_type()
            row.fmt = ""
        row.confirmed = True
        row.touched = True

    def set_fmt(self, index: int, fmt: str) -> None:
        """표시형(유형 내 프리셋) 변경 — 편집이므로 확정 해제."""
        row = self.rows[index]
        row.fmt = fmt
        row.confirmed = False
        row.touched = True

    def set_const(self, index: int, const: str) -> None:
        row = self.rows[index]
        row.const = const
        row.confirmed = False
        row.touched = True

    def set_display(self, index: int, type_: str, fmt: str) -> None:
        """**(유형, 표시형) 한 쌍을 원자적으로** 세운다(U6-C 리뷰 1) — 표시형 select 의 단일 관문.

        두 발(``set_type`` → ``set_fmt``)로 나누면 그 사이에 유형만 바뀐 상태가 실재한다:
        ``set_type`` 이 표시형을 기본으로 리셋하므로 왕복 하나가 늦거나 실패하면 사람이 고른
        표시형이 조용히 사라진다. 한 번의 선택은 한 번의 전이여야 한다.

        ``const``/``today`` 는 열에서 값을 받지 않으므로 소스를 함께 비운다
        (:meth:`set_type` 의 짝 규칙과 같은 근거 — 표시와 출력이 갈리지 않게).
        """
        if type_ not in TYPES:
            raise ValueError(f"지원하지 않는 유형: {type_!r} (지원: {TYPES})")
        row = self.rows[index]
        row.type = type_
        row.fmt = fmt
        if type_ in ("const", "today"):
            row.source = ""
        if type_ != "const":
            row.const = ""
        row.confirmed = False
        row.touched = True

    def revert_to_auto(self, index: int) -> None:
        """사람 소유(touched) 행을 시스템 소유로 **완전** 되돌린다 — 자동 제안에 다시 맡김(칩-라이브).

        소스뿐 아니라 사람이 손댄 유형·상수·표시형도 초기화한다(리뷰 R1): 소스만 풀면 재제안이
        새 소스를 얹어 '제안'으로 보이는데 type=const 가 남아 ``to_mapping`` 이 옛 상수를 그대로
        방출하는 하이브리드(제안 표시 ≠ 실제 출력)가 된다 — 되돌리기는 갓 제안된 행과 동형이어야
        한다. 소스는 여기서 세우지 않는다 — 호출측이 활성 집합으로 ``resuggest_row`` 를 돌려 그
        행만 라이브 재제안한다(무관 행 불건드림, 리뷰 R4). 리셋 정의는
        :meth:`RowState.reset_to_system` 단일 출처(강등 경로들과 동일 착지).
        """
        self.rows[index].reset_to_system()

    def set_confirmed(self, index: int, confirmed: bool = True) -> None:
        """사람의 행별 확정/해제 — 빈 행 확정은 '의도적 비움'을 뜻한다."""
        self.rows[index].confirmed = confirmed

    def unconfirm_all(self) -> None:
        for row in self.rows:
            row.confirmed = False

    def _score_row(self, row: "RowState", m) -> None:
        """제안 결과(FieldMapping | None)를 행에 얹는다 — 소스·제안 점수(후보 없으면 비움).

        점수는 ``from_suggestions`` 와 같은 방식(alias 라벨 대상 유사도)으로 복원한다 —
        ``suggest_mappings`` 가 점수를 돌려주지 않아 재계산한다(리뷰 R8: from_suggestions 와
        동일 패턴, 필드·소스 수가 작아 무시 수준). 단일 출처화로 재제안 경로가 어긋나지 않는다.
        """
        if m is not None and m.source:
            row.source = m.source
            row.suggestion_score = similarity(row.template_field, self.aliases.get(m.source, m.source))
        else:
            row.source = ""
            row.suggestion_score = 0.0

    def _resuggest_system_rows(self, active_sources: "list[str]") -> None:
        """시스템 소유 행(미확정·미접촉)의 소스를 활성 헤더 중 최선으로 다시 세운다(라이브 재제안).

        칩-라이브 결정 12의 '미접촉 = 시스템 소유, 활성 헤더 따라 라이브 재제안'. ``suggest_mappings``
        를 활성 소스만으로 다시 돌려(from_suggestions 와 같은 산출) 시스템 행의 소스·제안 점수를
        갱신한다. 활성 중 맞는 후보가 없으면 ``source=""``(후보 없음). 사람 소유 행은 건드리지 않는다.
        """
        system_fields = [r.template_field for r in self.rows if r.is_system_owned()]
        if not system_fields:
            return
        drafts = {
            m.template_field: m
            for m in suggest_mappings(system_fields, active_sources, self.aliases)
        }
        for row in self.rows:
            if row.is_system_owned():
                self._score_row(row, drafts.get(row.template_field))

    def resuggest_row(self, index: int, active_sources: "list[str]") -> None:
        """**단일** 행만 활성 헤더 중 최선으로 재제안한다(``revert_to_auto`` 직후 — 리뷰 R4).

        전집합 ``apply_active_sources`` 를 쓰면 무관한 stale 사람 소유 행까지 강등돼 조용히
        파괴된다(되돌리기는 그 행 하나의 의사표시일 뿐) — 그 행만 다시 세운다. 사람 소유 행에는
        무영향(시스템 소유일 때만 동작)."""
        row = self.rows[index]
        if not row.is_system_owned():
            return
        drafts = {
            m.template_field: m
            for m in suggest_mappings([row.template_field], active_sources, self.aliases)
        }
        self._score_row(row, drafts.get(row.template_field))

    def apply_active_sources(
        self, active_sources: "list[str]", *, vocabulary: "list[str] | None" = None
    ) -> "list[str]":
        """활성 소스 집합 변경을 반영한다(칩-라이브 결정 12·13 — 헤더 사용/미사용의 단일 관문).

        - **시스템 소유 행**(미확정·미접촉): 활성 헤더 중 최선으로 **라이브 재제안**(조용).
        - **사람 소유 행**(확정·touched)의 소스가 **비활성이 되면 시끄러운 강등**(R4):
          ``source=""`` · ``confirmed=False`` · ``touched=False`` 로 되돌리고 이름을 반환한다.

        ``vocabulary``(현재 데이터의 전체 헤더)를 주면 강등은 **어휘 안 소스**로 한정된다
        (PR-3 리뷰 F1): 어휘 밖 소스를 겨눈 사람 소유 행(이월된 stale — 뷰가 「데이터에 없음」
        으로 이미 시끄럽게 표시)은 헤더 칩 조작과 무관하므로 건드리지 않는다 — 전집합 강등이면
        무관한 칩 토글 한 번에 이월 값이 소실되고 통지는 끈 적 없는 헤더를 지목한다(오귀속).
        None(기본)이면 종전 거동(활성 밖 전부 강등) — 어휘 개념이 없는 호출측 호환.

        **순서가 계약이다**(리뷰 R3): 재제안을 **먼저** 하고 강등을 **나중**에 한다. 그러면
        강등된 사람 소유 행은 ``source=""`` 로 **비어 남는다** — 재제안이 다른 그럴싸한 소스를
        얹어 사용자가 재확정 시 원래와 다른 열로 조용히 치환되는 것을 막고, 의식적 재선택을
        강제한다(구 ``ignore_source`` 의 안전 거동 복원). '항상 시스템이었던' 행만 재제안되고,
        이번에 강등된 행은 다음 활성 변화에서야 시스템 소유로 재제안된다.

        구 ``ignore_source``(헤더별 무차별 해제)의 대체 — 헤더/모델 정합을 한 번에 재계산해
        같은 파일 재겨눔 시 헤더 UI 와 모델이 어긋나던 창을 닫는다(리뷰 F3). 반환 = R4 강등 이름.

        강등은 **완전 리셋**(:meth:`RowState.reset_to_system`)이다: 소스·확정만 풀고 유형·
        상수를 남기면 강등 행이 시스템 소유가 된 뒤 다음 재제안이 소스를 얹어 '제안 표시 ≠
        옛 상수 방출' 하이브리드가 된다(``revert_to_auto`` 리뷰 R1 과 같은 근거 — 강등 경로만
        부분 리셋일 이유가 없다).
        """
        active_set = set(active_sources)
        vocab = set(vocabulary) if vocabulary is not None else None
        self._resuggest_system_rows(active_sources)  # 1) 항상 시스템이던 행만 재제안(강등 전)
        demoted: "list[str]" = []
        for row in self.rows:  # 2) 사람 소유 행 R4 강등 — 비운 채 남긴다(재제안 안 함)
            if (
                row.is_human_owned()
                and row.source
                and row.source not in active_set
                and (vocab is None or row.source in vocab)  # 어휘 밖 stale 은 불건드림(F1)
            ):
                row.reset_to_system()
                demoted.append(row.template_field)
        return demoted

    # 구판 ignore_source(헤더별 무차별 해제)는 칩-라이브 재배선으로 소비자가 소멸해 제거됐다
    # — 헤더 사용/미사용의 유일 관문은 apply_active_sources(결정 12·13).

    # ------------------------------------------------- 일괄 승격 게이트(U6-C #977)
    # 구 '모두 확정'(내용 있는 전 행 즉시 확정 + 비움 승격 이름게이트)의 후계다. 승격
    # 대상을 **시스템 소유**로 좁힌 것이 유일한 의미 변화이고 그것이 이 동사가 한 질문에
    # 답하게 만든다: 「자동 제안을 그대로 받겠다」. 사람이 손댄 행(edited)과 채울 것이 없는
    # 행(needs_source)은 각자 다른 답을 요구하므로 이 버튼이 대신 답하지 않는다.
    def confirm_suggested(self) -> int:
        """**자동 제안 행만** 확정한다 — 사람이 손댄 행·열 필요 행은 건드리지 않는다.

        반환값은 이번에 확정된 행 수. 승격 뒤에도 남은 행이 있으면 저장 게이트
        (:meth:`is_complete`)가 그대로 막는다 — 이 동사는 게이트의 우회로가 아니라
        게이트를 통과시키는 정상 경로의 한 걸음이다(명시성 원칙 불변).
        """
        targets = [r for r in self.rows if r.is_system_owned() and r.has_content()]
        for row in targets:
            row.confirmed = True
        return len(targets)

    def suggested_count(self) -> int:
        """상태가 ``suggested`` 인 행 수 — 일괄 승격 버튼의 수치·머리 pill 이 같이 읽는다."""
        return sum(1 for r in self.rows if r.status() == "suggested")

    def needs_confirm_count(self) -> int:
        """사람이 답해야 하는 행 수 = ``edited`` + ``needs_source``(일괄 승격 비대상 전부)."""
        return sum(1 for r in self.rows if r.status() in ("edited", "needs_source"))

    def const_count(self) -> int:
        """고정값 행 수 — 데이터가 아니라 사람이 적어 넣은 값이 몇 자리인가."""
        return sum(1 for r in self.rows if r.type == "const")

    def unused_source_fields(self) -> "list[str]":
        """어느 행도 겨누지 않는 데이터 열 — 표 바닥 한 줄이 잇는 정보(U6 §2.5).

        「사용할 데이터 열」 선별이 퇴역하며 남은 질문은 이것 하나다: 안 쓰는 열이 몇인가.
        매핑되지 않은 열은 자연히 쓰이지 않으므로 끄는 동사가 필요 없다.
        """
        used = {r.source for r in self.rows if r.source}
        return [f for f in self.source_fields if f not in used]

    def confirmed_count(self) -> int:
        """확정된 행 수 — '모두 해제' 파괴 확인 게이트가 파기 규모를 진술하는 근거."""
        return sum(1 for r in self.rows if r.confirmed)

    # ------------------------------------------------------------- 상태 질의
    def is_schema_only(self) -> bool:
        """데이터 미연결(스키마온리) 세션인가 — 연결된 데이터 소스의 필드가 0개(UD-28).

        데이터 스텝을 건너뛰면(ADR-J 선택 플로우) ``source_fields`` 가 비어 애초에
        매칭할 데이터가 없다. 이때 내용 없는 행은 '미매칭'(데이터가 있는데 못 맞춘 것)이
        아니라 '데이터 미연결'이다 — 뷰가 빨강 경보를 중립으로 강등하고(오경보 방지),
        스키마온리 안내 배너를 띄우는 근거다. Qt 비의존이라 헤드리스로 검증한다.
        """
        return not self.source_fields

    def is_complete(self) -> bool:
        """전 행이 사람 확정을 받았는가 — 명시성 게이트. 행이 없으면 False."""
        return bool(self.rows) and all(r.confirmed for r in self.rows)

    def emits_any_value(self) -> bool:
        """확정된 행 중 실제 값을 방출하는 행이 하나라도 있는가 — '전부 비움' 저장 가드.

        전 행을 비움 확정하면 ``is_complete`` 는 통과하지만 ``to_profile`` 은 blank
        선언만 담아 어떤 누름틀에도 값을 주입하지 않는다(RC-08). blank 도 mappings 에
        영속화되므로(L1) 뷰는 자료구조 내부(``profile.mappings``)가 아니라 이 질의로
        무의미 작업 저장을 판단한다.
        """
        return any(r.confirmed and r.has_content() for r in self.rows)

    def preview(
        self, record: "dict[str, object]", *, now: "datetime | None" = None
    ) -> "dict[str, str]":
        """행별 현재 매핑을 레코드 1건에 적용한 미리보기 값(확정 여부 무관).

        ``now`` 는 ``today``(오늘 날짜) 행의 기준 시각 — 표면이 **스냅샷당 1회** 잡아
        넘긴다(RC-02 확장). 미지정이면 적용 시점으로 폴백한다.
        """
        return {
            r.template_field: r.to_mapping().value_for(record, now=now)
            for r in self.rows
        }

    def preview_empties(
        self, record: "dict[str, object]", *, now: "datetime | None" = None
    ) -> "list[str]":
        """내용은 매핑됐으나 이 레코드에선 값이 빈 필드 — validate.py 의 empty_valued 를
        단건화한 것. 의도적 비움(내용 없음) 행은 제외한다."""
        return [
            r.template_field
            for r in self.rows
            if r.has_content() and r.to_mapping().value_for(record, now=now) == ""
        ]

    def preview_counts(
        self, record: "dict[str, object]", *, now: "datetime | None" = None
    ) -> "tuple[int, int, int]":
        """미리보기 3상태 집계 ``(채움, 빈 값, 미매핑)`` — 합은 언제나 전체 행 수(UD-27).

        기존 요약은 '채움/빈 값' 2상태만 세어 미매핑(내용 없는) 행이 무집계로 빠져
        합계가 필드 수와 어긋났다(공란 규모 과소 진술). 세 항의 합 = ``len(rows)`` 로
        묶어 어떤 필드도 집계에서 사라지지 않게 한다(ADR-B '빈 공간으로 보이면 안 됨').
        """
        empties = self.preview_empties(record, now=now)
        content_rows = sum(1 for r in self.rows if r.has_content())
        filled = content_rows - len(empties)
        unmapped = len(self.rows) - content_rows
        return filled, len(empties), unmapped

    def name_token_values(
        self, record: "dict[str, object]", *, now: "datetime | None" = None
    ) -> "dict[str, object]":
        """파일 이름 토큰이 읽을 ``{템플릿필드: 값}`` — 내용 있는 행만(U6-F #980).

        파일 이름 예시를 내는 두 표면(편집기 3단계의 라이브 예시 · 「문서 작업」 상세의
        계획 한 줄)이 **같은 재료**로 같은 이름을 말하게 하는 자리다. 이름 자체는 실제
        생성기와 같은 함수(:func:`~hwpxfiller.naming.make_output_filename`)가 만들고, 여기서
        갈릴 수 있는 것은 그 함수에 무엇을 먹이느냐 하나뿐이라 그것을 여기 모은다.

        값 계산이 실패한 행은 빈 문자열이다 — 표시 전용 경로이고, 토큰이 통째로 빠지면
        미치환 토큰이 그대로 노출돼 예시가 실제 산출물과 다른 모양이 된다.
        """
        data: "dict[str, object]" = {}
        for row in self.rows:
            if not row.has_content():
                continue
            try:
                data[row.template_field] = row.to_mapping().value_for(record, now=now)
            except ValueError:
                data[row.template_field] = ""
        return data

    # ------------------------------------------------------- 프로파일 입출력
    def to_profile(self, name: str = "") -> MappingProfile:
        """확정된 전 행을 프로파일로. 빈 행은 명시적 ``blank`` 선언으로 영속화한다."""
        return MappingProfile(
            name=name,
            mappings=[
                r.to_mapping(blank=r.is_empty_confirmed())
                for r in self.rows if r.confirmed
            ],
        )

    # -------------------------------------------------- 휘발 렌더·결속(#148 슬라이스 3b·4)
    def live_profile(self, name: str = "") -> MappingProfile:
        """휘발 미리보기·복사가 소비하는 **지금** 매핑 — 확정 게이트 무관, 내용 있는 전 행.

        :meth:`to_profile` 은 ``confirmed`` 행만 담는 저장 산출물용이다. 「기안」 휘발 세션은
        확정을 저장 게이트로 쓰지 않으므로(그건 슬라이스 5 승격) 결속·상수가 든 모든 행을
        그대로 적용한다 — :meth:`MappingProfile.apply` 가 큐 레코드마다 값 사전을 낸다
        (이음매 = 레코드→매핑→값 사전→render_segments). 무결속·무상수·**미확정** 행은 빠져
        토큰이 ``missing``({{토큰}} 빨강)으로 남고, 결속 열 값이 비면 키는 있고 값이 빈
        ``blank``(〈빈 값〉)이 된다.

        **확정-비움(#148 슬라이스 4, 결정 12)**: 확정됐는데 채울 내용이 없는 행(사람이
        「이 필드는 비운다」를 명시)은 **빈 값 방출**로 담는다 — 렌더는 데이터-빈값 ``blank`` 와
        **같게**(〈빈 값〉·클립보드 빈 문자열) 보이되, 게이트 제외는 소비자(작업대 `gate_empty_fields`)가
        :meth:`declared_blank_fields` 로 가른다. ``type="blank"`` 이 아니라 **빈 text 매핑**으로
        방출하는 이유: :meth:`MappingProfile.apply` 는 ``is_blank`` 를 값 사전에서 **드롭**하므로
        (hwpx 누름틀은 손대지 말라는 계약) blank 로 담으면 키가 사라져 ``missing`` 으로 렌더된다 —
        txt 는 누름틀이 없고 선언된 비움은 빈 문자열이라, 키를 남겨 ``blank`` 로 표지돼야 한다."""
        mappings: "list[FieldMapping]" = []
        for r in self.rows:
            if r.has_content():
                mappings.append(r.to_mapping())
            elif r.is_empty_confirmed():
                # 확정-비움 → 빈 값 방출(키 유지 → render_segments 가 blank 로 표지).
                mappings.append(FieldMapping(template_field=r.template_field, type="text"))
        return MappingProfile(name=name, mappings=mappings)

    def declared_blank_fields(self) -> "list[str]":
        """확정-비움(확정·무내용) 필드 이름 — 렌더는 ``blank`` 지만 빈칸 게이트에서 빠진다(결정 12).

        「확인한 것은 다시 묻지 않는다」(ADR-E ack 동형)의 큐 판: 사람이 「비운다」고 선언한
        토큰은 복사 전 빈칸 게이트·완료 노트·빈칸 지도에서 제외된다. 데이터가 비어 생긴
        ``blank`` 는 사람의 선언이 아니라 그 행의 사실이므로 여기 들지 않고 게이트에 **남는다** —
        두 무결속 상태의 구분이 여기서 값을 한다."""
        return [r.template_field for r in self.rows if r.is_empty_confirmed()]

    def index_of(self, template_field: str) -> int:
        """토큰 이름 → 행 인덱스(없으면 ValueError) — 디스패치가 이름으로 겨눈다."""
        for i, r in enumerate(self.rows):
            if r.template_field == template_field:
                return i
        raise ValueError(f"매핑에 없는 토큰: {template_field!r}")

    def suggestions(self) -> "dict[str, str]":
        """무결속 행별 **근사 열 제안 1개**(결정 30) — 자동 적용 안 함(원클릭 대상).

        정확 일치는 :meth:`from_field_names` 가 이미 자동 결속했으므로, 여기 남는 건 이름이
        비슷하기만 한 자리다. 이미 다른 토큰이 쓰는 열은 후보에서 뺀다(1:1 계약) — 같은 열을
        여러 자리에 미는 제안은 소음이다. 임계 미만은 후보 없음(빈 dict 항목 없음).

        임계는 :data:`~hwpxfiller.domain.mapping.SUGGEST_THRESHOLD` 를 **빌려 쓴다**. 예전엔
        0.6 리터럴을 여기 다시 적었는데, 그러면 같은 판정을 두 곳이 소유해 도메인 임계를
        올려도 TXT 트랙(``from_field_names`` + 이 메서드)만 옛 값에 남는다 — #908 의 위험
        근접쌍이 실제로 그 경로로 살아 있었다."""
        used = {r.source for r in self.rows if r.source}
        out: "dict[str, str]" = {}
        for row in self.rows:
            if row.source:
                continue
            best, score = None, 0.0
            for col in self.source_fields:
                if col in used:
                    continue
                s = similarity(row.template_field, self.aliases.get(col, col))
                if s > score:
                    best, score = col, s
            if best is not None and score >= SUGGEST_THRESHOLD:
                out[row.template_field] = best
        return out

    def bind_column(self, index: int, source: str, kind: str = "") -> None:
        """열 결속(auto) — 소스·유형 세팅 + 상수/서식 청소(결정 5·30). 사람 소유(touched).

        빈/부재 ``kind`` 는 이름 추론으로 낙착(값 스니핑 우선, 결정 5). ``source`` 는 활성
        열이어야 한다(호출측 검증) — 여긴 모델 갱신만. man→auto 재결속도 이 경로(상수를 지워
        결속 값이 다시 산다)."""
        row = self.rows[index]
        row.source = source
        row.type = default_transform_for(kind) if kind else default_transform_for(
            infer_type(row.template_field)
        )
        row.const = ""
        row.fmt = ""
        row.confirmed = False
        row.touched = True

    def set_manual(self, index: int, value: str) -> None:
        """직접 입력(man) — 상수 강등. **결속 소스는 기억**한다(되돌리기로 복귀, 사용자 결정).

        결속 값(auto)을 손으로 고치면 그 값은 필연적으로 전 행 공통이라 상수가 옳다 — hand 는
        큐에서 '어느 행의 값'인지 모호해 존치하지 않고, ``type=const`` 로 강등하되 ``source``
        를 남겨 :meth:`revert_binding` 이 열 결속을 되살린다."""
        row = self.rows[index]
        row.type = "const"
        row.const = value
        row.confirmed = False
        row.touched = True

    def freeze_to_const(self, index: int, value: str) -> None:
        """데이터 해제 시 결속 값 **평문 동결**(R-flow 결정 30) — 소스도 뗀다(``set_manual`` 과 차이).

        데이터를 통째 떼면 결속 열이 사라져 되돌릴 대상이 없으므로, 값을 상수로 굳히되 소스
        기억은 남기지 않는다(:meth:`set_manual` 은 revert 용으로 소스를 남긴다 — 여기선 되살릴
        데이터가 없어 「자동으로 되돌리기」가 죽은 손잡이가 된다). 표지는 「직접 입력」."""
        row = self.rows[index]
        row.type = "const"
        row.const = value
        row.source = ""
        row.fmt = ""
        row.confirmed = False
        row.touched = True

    def revert_binding(self, index: int, kind: str = "") -> bool:
        """man→auto 되돌리기 — 기억한 결속 소스 복귀(상수 청소·유형 재유도). 소스 없으면 무동작.

        반환 = 되돌렸는가(소스 기억이 있었나) — 표면이 「자동으로 되돌리기」를 띄울지 판정."""
        row = self.rows[index]
        if not row.source:
            return False
        row.type = default_transform_for(kind) if kind else default_transform_for(
            infer_type(row.template_field)
        )
        row.const = ""
        row.fmt = ""
        return True

    def unbind(self, index: int) -> None:
        """열 해제 — 결속만 떼고 시스템 소유로 낙착(자동 제안에 다시 맡김). 값 동결은 없다.

        휘발 큐에선 결속 값이 레코드마다 다르므로 '평문 동결'(quickdraft 단건 문법)이 성립하지
        않는다 — 해제 = 이 자리를 비워 근사 제안·재결속을 기다리는 상태."""
        self.rows[index].reset_to_system()

    def set_fmt_for(self, template_field: str, code: str) -> None:
        """이름으로 표시형 정정 — 디스패치 편의(:meth:`set_fmt` 의 이름 판)."""
        self.set_fmt(self.index_of(template_field), code)

    def human_owned_rows(self) -> "list[RowState]":
        """사람 소유 행 — 확정됐거나 손댐(touched). 미접촉 제안(시스템 소유)은 제외."""
        return [r for r in self.rows if r.is_human_owned()]

    def carry_profile(self, name: str = "") -> MappingProfile:
        """데이터 교체 재초안 시 **이월용** 프로파일 — 사람 소유 행의 값(소스/유형/상수/서식).

        확정 전용 :meth:`to_profile` 과 달리 **touched 미확정 행도 담는다**(리뷰 F2: 미확정
        수동 편집도 '사람 소유'라 데이터를 바꿔도 조용히 소실시키지 않는다). 미접촉 제안(시스템
        소유)은 담지 않는다 — 새 데이터 기준으로 재제안돼야 하므로. ``apply_profile(confirm=False)``
        로 적용해 값만 이월하고 전 행 미확정으로 착지시킨다(사람 재검토 강제).

        단 **내용 없는 touched 미확정 행은 담지 않는다**(리뷰 반영): 비움 확정(blank 선언)도
        아니고 이월할 값도 없는데 담으면, ``apply_profile`` 이 touched 를 재날인해 그 필드가
        새 데이터에서 **영구히 라이브 재제안에서 제외**된다(조용한 동결). 그런 행은 시스템
        소유로 낙착시켜 새 데이터 기준 자동 제안을 다시 받게 한다.
        """
        return MappingProfile(
            name=name,
            mappings=[
                r.to_mapping(blank=r.is_empty_confirmed())
                for r in self.human_owned_rows()
                if r.confirmed or r.has_content()
            ],
        )

    def apply_profile(
        self,
        profile: MappingProfile,
        *,
        require_source: bool = False,
        confirm: bool = True,
    ) -> int:
        """저장 프로파일을 행에 반영 — 일치 필드는 값 복원 + ``confirmed=True`` 도착.

        프로파일에 없는 필드는 건드리지 않는다(미확정 유지 — 사람이 마저 확정).
        반영된 행 수(값이 복원되고 확정 자격이 있는 행)를 반환한다.

        ``require_source=True``: 복원한 행이 참조하는 소스 컬럼이 현재 소스 어휘
        (``source_fields``)에 **없으면 확정 도착시키지 않는다**(값은 복원하되 미확정 유지).
        데이터를 바꿔 이전 확정을 되살릴 때, 사라진 컬럼을 겨눈 행이 조용히 확정 상태로
        남아 저장 게이트(``is_complete``)를 통과하고 빈 값 문서를 찍는 함정을 막는다 —
        그런 행은 미확정으로 남아 사람 재검토를 강제한다(빈/const 행은 소스 의존이 없어
        영향 없음). 기본(False)은 종전 거동(전 일치 행 확정)이라 다른 호출측은 불변이다.

        ``confirm=False``: 값(소스/유형/상수/서식)만 이월하고 **어느 행도 확정 도착시키지
        않는다** — 전 행 미확정 초안. 템플릿/데이터 키가 바뀐 재초안 경로가 쓴다: 같은
        이름 컬럼이라도 새 데이터에선 의미가 다를 수 있어, 이전 확정을 확정 상태로 되살리면
        사람 검토 없이 ``is_complete`` 를 통과해 저장·실행까지 흐른다(조용한 게이트 우회).
        기본(True)은 종전 거동(프로파일 로드=사람 확정 산출물 복원)이라 다른 호출측은 불변.
        """
        available = set(self.source_fields)
        by_field = {m.template_field: m for m in profile.mappings}
        applied = 0
        for row in self.rows:
            m = by_field.get(row.template_field)
            if m is None:
                continue
            row.source = "" if m.is_blank else m.source
            row.type = "text" if m.is_blank else m.type
            row.const = "" if m.is_blank else m.const
            row.fmt = "" if m.is_blank else m.fmt
            # 프로파일 복원/이월된 행은 **사람 소유**(과거 확정 산출물 또는 touched 이월) —
            # touched=True 로 라이브 재제안이 덮지 못하게 한다(칩-라이브 결정 12). 확정 여부는
            # confirm 인자·missing_source 가 따로 결정한다(값 복원 ≠ 확정 도착).
            row.touched = True
            missing_source = (
                require_source
                and not m.is_blank
                and bool(m.source)
                and m.source not in available
            )
            row.confirmed = confirm and not missing_source
            if not missing_source:
                applied += 1
        return applied


# ============================================================= PARTIAL 확정 게이트
# 위저드 1단계(TemplatePage)의 위험 상태 게이트를 Qt 비의존 순수 파이썬으로 뽑아
# 헤드리스 단위 테스트가 가능하게 한다(위젯은 이 결정을 그대로 그린다).
def _leftover_token_names(
    sites: "list", strays: "list[str]"
) -> "list[str]":
    """PARTIAL 게이트가 재진술할 **미해결 토큰 이름** — 문서순·중복 제거.

    ``scan_tokens`` 사이트(컴파일 가능/파편 skip)의 이름 + 스키마의 본문 평문 잔존
    (``stray_tokens``)을 합친다. 이 이름들이 "값이 주입되지 않는다"를 사람에게 구체적으로
    재진술하는 대상이다(범용 메시지 금지 — ADR-E 반사적 dismiss 봉쇄의 전제).

    이름이 빈 사이트(예: ``{{   }}`` 공백뿐인 토큰 — ``compile_status`` 는 compilable 로
    세어 PARTIAL 로 트리거하지만 정제 이름은 "")도 대표 라벨로 반드시 열거한다. 그러지
    않으면 ``unmet_tokens`` 가 비어 ack 가 "0개 토큰" dead-end 가 되고, 열거가 PARTIAL
    트리거와 어긋난다(fail-closed 지만 진행 불가한 함정).
    """
    names: "list[str]" = []
    seen: "set[str]" = set()
    for s in sites:
        label = s.name or "(이름 없는 토큰)"  # 무명 토큰도 대표 라벨로 열거(트리거와 일치)
        if label not in seen:
            seen.add(label)
            names.append(label)
    for t in strays:
        if t and t not in seen:
            seen.add(t)
            names.append(t)
    return names


@dataclass
class PartialGate:
    """PARTIAL "다 된 것 같지만 아닌" 상태의 확정 게이트(Qt 비의존, 헤드리스 테스트 대상).

    ``compile_status`` 상태 + 미해결 토큰 이름에서 '진행 가부'를 파생한다:
    - ``RAW``(필드 0개): 차단(채울 대상 없음 — 상위 페이지가 이미 필드 없는 템플릿을 거부).
    - ``PARTIAL``(필드 有 + skip/파편/평문 잔존): **명시 ack 또는 인라인 컴파일 전까지 차단**
      — 값이 조용히 누락되는 위험을 소리 나게 세운다(confirm-or-alarm).
    - ``COMPILED``/``FILLED``: 통과.

    **반사적 dismiss 봉쇄(ADR-E).** ack 는 *정확히 재진술된 미해결 이름 전체*를 확인해야
    성립한다(``acknowledge`` 가 받은 이름 집합이 ``unmet_tokens`` 와 일치할 때만). 다른/부분/
    오래된 확인으로는 게이트가 열리지 않아, 이름을 안 보고 누르는 한 번-클릭 해제를 막는다.
    """

    status: TemplateStatus
    unmet_tokens: "list[str]" = field(default_factory=list)
    _acked: "set[str]" = field(default_factory=set)

    @property
    def state(self) -> CompileState:
        return self.status.state

    @property
    def structure_blocked(self) -> bool:
        """잔존 구간 표기가 있는가 — **ack 로 열리지 않는** 차단(S8-04 #835).

        빈 값 ack 는 「이 토큰은 비우고 진행한다」는 사용자 확정이다. 미변환 구간 표기는
        비우고 진행할 수 있는 값이 아니라 **구조가 아직 안 선 상태**라, 확정할 대상이
        없다(확정하면 모든 선택지가 든 문서가 나온다). 그래서 여기는 확인 왕복이 아니라
        수선 동선을 재진술하는 차단이다.
        """
        return self.status.structure_marker_n > 0

    def needs_gate(self) -> bool:
        """PARTIAL 만 확정 게이트가 닫힌다(RAW 는 상위에서 차단, COMPILED/FILLED 는 통과)."""
        return self.status.state is CompileState.PARTIAL

    def acknowledge(self, confirmed: "Iterable[str]") -> None:
        """사용자가 재진술된 미해결 토큰을 직접 확인 — 확인한 **이름 집합**을 기록한다.

        위젯은 정확히 ``unmet_tokens`` 를 넘겨 확인시킨다. 부분/엉뚱한 이름을 넘기면
        ``is_acked`` 가 불성립이라 게이트가 열리지 않는다(반사적 확인 무력화).
        """
        self._acked = set(confirmed)

    def is_acked(self) -> bool:
        """미해결 토큰 **전체**를 정확히 확인했는가(부분·오래된·빈 확인은 불성립)."""
        return bool(self.unmet_tokens) and self._acked == set(self.unmet_tokens)

    def can_proceed(self) -> bool:
        """이 상태에서 다음 단계로 넘어가도 되는가 — 게이트의 최종 판정."""
        st = self.status.state
        if st is CompileState.RAW:
            return False
        if self.structure_blocked:
            return False  # ack 와 무관한 차단(구조 미완 — 수선 동선은 변환)
        if st is CompileState.PARTIAL:
            return self.is_acked()
        return True  # COMPILED / FILLED

    def message(self) -> str:
        """사람이 볼 게이트 메시지 — PARTIAL 은 구체 토큰 이름을 재진술한다."""
        st = self.status.state
        if st is CompileState.RAW:
            return RAW_BLOCK_MESSAGE
        if self.structure_blocked:
            # 토큰 이름 열거로 답할 수 없는 차단이라 먼저 선다 — 그러지 않으면 잔존
            # 토큰이 0 인 문서에서 「토큰 0개가 남아 있습니다()」라는 속 빈 문장이 나온다.
            return STRUCTURE_NOTATION_BLOCK_MESSAGE
        if st is not CompileState.PARTIAL:
            return ""
        names = ", ".join(self.unmet_tokens)
        if self.is_acked():
            return (
                f"확인함: 아래 {len(self.unmet_tokens)}개 토큰은 비우고 진행합니다({names})"
            )
        return (
            f"진행 차단: 값이 채워지지 않는 토큰 {len(self.unmet_tokens)}개가 남아 있습니다"
            f"({names}). [여기서 누름틀 변환]으로 누름틀로 바꾸거나, 비움을 확정하세요."
        )


def gate_for_template(pkg: object) -> PartialGate:
    """열린 package 에서 컴파일 상태 + 미해결 토큰 이름을 읽어 게이트를 만든다.

    **package-only**(P2-19R) — 경로를 든 호출자(ring 2)가 External adapter로 한 번 열어
    넘긴다(세 판정이 같은 스냅샷 공유).
    전부 읽기 전용(``compile_status``/``extract_schema``/``scan_tokens`` 는 무변형). 위저드와
    테스트가 공유하는 진입점 — PARTIAL 게이트가 겨누는 실제 파생을 한자리에 모은다.
    """
    status = compile_status(pkg)
    schema = extract_schema(pkg)
    unmet = _leftover_token_names(scan_tokens(pkg), schema.stray_tokens)
    return PartialGate(status=status, unmet_tokens=unmet)
