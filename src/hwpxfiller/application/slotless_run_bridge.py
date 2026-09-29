"""managed 생성이 재사용하는 slotless 시절 admission 어휘 — 코드·오류만 남는다(#1081 PR2).

slot 없는 HWPX 를 legacy generator 로 보내던 admission(exact applied Candidate bytes staging +
실행 구성 provenance 판정)은 문서 생성 경로가 managed 하나가 되며 사라졌다. slot 유무와 무관하게
봉인·물질화·배달을 타고, 실행 bytes 의 무결성·구간 표기 검문은 managed 파이프라인
(:mod:`hwpxfiller.external.managed_generation`)이 같은 코드로 진다.
"""

from __future__ import annotations

#: 적용된 템플릿 bytes 를 읽거나 대조할 수 없다(fail-closed).
APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR = "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"
#: 실행할 bytes 에 미변환 구간 표기가 남았다(S8-04 #835). 이것을 통과시키면 산출물은
#: 모든 선택지를 품은 채 마커 텍스트까지 그대로 실린 **구조적으로 틀린 문서**가 된다.
STRUCTURE_NOTATION_UNCOMPILED = "STRUCTURE_NOTATION_UNCOMPILED"

__all__ = [
    "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR",
    "STRUCTURE_NOTATION_UNCOMPILED",
]
