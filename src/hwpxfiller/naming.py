"""레코드 dict 로 출력 파일 이름을 계획하는 얇은 어댑터 — 규칙은 이름 kernel 한 곳(#798).

해석·조립·안전 판정·대소문자 무관 충돌은 :mod:`hwpxfiller.domain.output_name` 이 소유하고, managed
배달(:mod:`hwpxfiller.application.generation_delivery`)도 같은 함수를 부른다. 여기는 그 kernel 을
**매핑된 레코드 목록**(``{템플릿필드: 값}``)에 적용하는 자리만 남는다 — 실행 화면의 「문서」 열·
사전검증 감사·편집기 예시·legacy 일괄 생성이 소비한다. 그래서 미리 보인 이름과 배달이 쓰는 이름이
같은 판정에서 나온다.

종전 이 모듈이 따로 갖던 규칙(대소문자 구분 충돌, 닫히지 않은 ``{{`` 를 리터럴로 파일 이름에
흘림, 리터럴의 경로 구분자 통과)은 사라졌다. 이름을 만들 수 없는 입력은
:class:`~hwpxfiller.domain.output_name.OutputNameError`(``ValueError``) 로 시끄럽게 닫힌다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hwpxfiller.domain.output_name import (
    OutputNameError,
    dedupe_output_names,
    guard_output_name,
    parse_filename_pattern,
    render_output_name,
)

# 표시·편집 표면이 이 모듈에서 찾던 판독기는 kernel 의 것을 그대로 쓴다(``X as X`` re-export).
from hwpxfiller.domain.output_name import (
    pattern_field_tokens as pattern_field_tokens,
    pattern_uses_seq as pattern_uses_seq,
    seq_token_pads as seq_token_pads,
)


def make_output_filename(
    pattern: str,
    data: "Mapping[str, object]",
    *,
    seq: "int | None" = None,
    now: "datetime | None" = None,
) -> str:
    """한 레코드의 파일 이름 — kernel 조립 + 안전 판정. 확장자 ``.hwpx`` 를 보장한다.

    데이터에 없는 필드 토큰은 ``{{키}}`` 그대로 남긴다(미해소 토큰 경고가 따로 선다). 패턴이
    유효하지 않거나 최종 이름이 안전하지 않으면 :class:`OutputNameError` 다.
    """
    name, _parts = render_output_name(
        parse_filename_pattern(pattern), data,
        seq=seq if seq is not None else 1, now=now, keep_unresolved=True,
    )
    guard_output_name(name)
    return name


def _base_names(
    pattern: str, records: "Sequence[Mapping[str, object]]", now: "datetime | None"
) -> list[str]:
    tokens = parse_filename_pattern(pattern)
    names: list[str] = []
    for index, record in enumerate(records):
        name, _parts = render_output_name(
            tokens, record, seq=index + 1, now=now, keep_unresolved=True
        )
        guard_output_name(name)
        names.append(name)
    return names


def plan_output_names(
    pattern: str, records: "Sequence[Mapping[str, object]]", *, now: "datetime | None" = None
) -> "list[str]":
    """배치가 발급할 파일 이름 전체(배치 순서) — 배치 안 충돌은 대소문자 무관 접미사.

    디스크의 기존 파일과의 충돌은 여기서 피하지 않는다(확인-또는-경보: 덮어쓰기 확인이 가른다).
    """
    return dedupe_output_names(_base_names(pattern, records, now))


#: Windows 기본 경로 길이 한계(끝 NUL 포함). 확장 경로(``\\?\``)·`longPathsEnabled` 에서는
#: 더 길어도 성공하므로 **경고이지 차단이 아니다**(단정하면 문안이 거짓이 된다).
MAX_PATH_CHARS = 260


def default_max_path() -> int:
    """이 런타임에서 적용할 경로 길이 한계(``0`` = 세지 않음). Windows 밖에서는 한계가 없다."""
    return MAX_PATH_CHARS if os.name == "nt" else 0


@dataclass(frozen=True)
class OutputNameAudit:
    """배치가 발급할 이름의 **집합 단위** 감사(C-01).

    - ``converged`` — 서로 다른 레코드가 같은 이름(대소문자 무관)으로 수렴해 꼬리표가 붙은 자리.
    - ``too_long`` — 저장 경로가 한계를 넘을 **가능성**이 있는 자리(경고, 차단 아님).
    - ``refusal_code`` — 이름을 만들 수 없는 입력(패턴 문법·안전하지 않은 최종 이름)의 진단
      코드. 비어 있지 않으면 ``names`` 는 비어 있다 — 배달이 계획을 세우지 않는 것과 같다.
    """

    names: "tuple[str, ...]" = ()
    converged: "tuple[int, ...]" = ()   # 이름 목록 안의 자리(0-based)
    too_long: "tuple[int, ...]" = ()
    refusal_code: str = ""

    @property
    def has_warning(self) -> bool:
        return bool(self.too_long)


def audit_output_names(
    pattern: str, records: "Sequence[Mapping[str, object]]", out_dir: "str | Path" = "",
    *, now: "datetime | None" = None, max_path: "int | None" = None,
) -> OutputNameAudit:
    """:func:`plan_output_names` 와 **같은 규칙·순서**로 계산하며 집합 성질을 함께 센다.

    이름을 만들 수 없으면 예외 대신 ``refusal_code`` 를 싣는다 — 이 감사는 화면 스냅샷 경로라
    거절 사실을 게이트가 말해야 하고, 스냅샷을 죽이면 안 된다.
    """
    try:
        base = _base_names(pattern, records, now)
    except OutputNameError as exc:
        return OutputNameAudit(refusal_code=exc.code)
    names = dedupe_output_names(base)
    limit = default_max_path() if max_path is None else max_path
    root = Path(out_dir) if (out_dir and limit) else None
    converged = tuple(i for i, (a, b) in enumerate(zip(base, names, strict=True)) if a != b)
    too_long = tuple(
        i for i, name in enumerate(names)
        if root is not None and len(str(root / name)) >= limit
    )
    return OutputNameAudit(tuple(names), converged, too_long)
