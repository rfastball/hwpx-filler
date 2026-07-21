"""「기안문 채우기」 화면 컨트롤러(구 표면) — 세션 본체는 공용 믹스인이 소유.

스파이크가 끝까지 검증한 첫 실화면(SPIKE_FINDINGS.md)이라 오래 :mod:`.screens` 안에 살았다.
#148 슬라이스 3a 에서 세션 본체를 :class:`~hwpxfiller.webapp.draft_session.DraftSessionMixin`
으로 끌어올리며(「기안」 화면과 단일 출처) 이 모듈로 분가했다 — 화면 하나에 모듈 하나라는
저장소 관례에도 맞고, ``draft_session → screens`` 단방향 의존을 지켜 순환을 만들지 않는다.

**수명**: 이 화면은 슬라이스 6(구 화면 사망)에서 「기안」에 흡수되어 사라진다. 그때까지
잠시 공존하며(레일 7), 두 표면은 **같은 세션 기계**를 본다 — 드리프트가 생길 자리가 없다.
"""
from __future__ import annotations

from ..core.text_registry import TextTemplateRegistry
from .draft_session import DraftSessionMixin, TargetFontSetting
from .screens import DatasetPoolRegistry, PushSink


class TxtController(DraftSessionMixin):
    """즉시 기안(txt) 화면 — 세션이 화면의 전부라 공용 세션 스냅샷이 곧 스냅샷이다.

    세션 본체(데이터 존·큐·작업점 카드·대상 글꼴·정렬 린트·T3 가드·클립보드 렌더)의 계약과
    수명 주석은 :class:`~hwpxfiller.webapp.draft_session.DraftSessionMixin` 이 소유한다.
    """

    name = "txt"
    _action_label = "txt"

    def __init__(
        self,
        registry: TextTemplateRegistry,
        push: PushSink,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
        target_font: "TargetFontSetting | None" = None,
    ) -> None:
        self._push_sink = push
        self._init_session(registry, pool_registry=pool_registry, target_font=target_font)

    def snapshot(self) -> dict:
        return self._session_snapshot()

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태(템플릿 목록 포함)."""
        return {"templates": self.vm.template_names(), **self.snapshot()}
