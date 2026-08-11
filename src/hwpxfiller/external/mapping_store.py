"""매핑 프로파일의 영속 어댑터 — 프로파일 JSON 원자 저장(P2-18, #566).

프로파일의 의미·검증(:class:`~hwpxfiller.domain.mapping.MappingProfile`)은 Domain 이 소유하고,
durable write 개시는 여기로 승계한다. JSON 관례(UTF-8·``ensure_ascii=False``·``indent=2``)와
원자 쓰기 의미(RC-01)는 구 ``MappingProfile.save`` 와 바이트 동일하다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .atomic import write_text_atomic

from hwpxfiller.domain.mapping import MappingProfile


def load_mapping_profile(path: "str | Path") -> MappingProfile:
    """UTF-8 JSON 프로파일을 Domain 모델로 복원한다."""
    return MappingProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_mapping_profile(profile: MappingProfile, path: "str | Path") -> None:
    """원자 쓰기(RC-01) — 저장 중 실패가 기존 프로파일 JSON 을 파괴하지 않는다."""
    write_text_atomic(path, json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
