"""같은 창의 작업 공간 전환 — 사용자 환경과 튜토리얼 연습 환경(#1126).

작업 공간은 **컨트롤러 그래프 하나**다: 템플릿 루트·작업 저장소·데이터 풀·템플릿 권위·저작
기록·작업별 설정이 모두 한 홈에 결속된 채로 조립된다. 연습 환경은 같은 조립을 그 과정의 홈에서
한 번 더 한 것이고, 전환은 이 모듈의 :class:`WorkspaceSwitch` 한 곳에서만 일어난다.

- **사용자 그래프는 연습 동안 그대로 메모리에 산다.** 데이터·행 선택·필터·작업 선택·저작
  세션을 다시 조립하지 않으므로, 이탈은 그 객체를 다시 활성으로 세우는 것뿐이다.
- **비활성 그래프의 관측 푸시는 화면에 닿지 않는다.** 활성화 순간 활성 그래프의 모든 채널을
  새 스냅샷으로 다시 민다(웹 저장소는 도착 순서대로 덮어쓴다).
- **기본 위치 전환은 메모리 값이다**(:func:`hwpxfiller.host.locations.activate_workspace`).
  비정상 종료 뒤 다음 기동은 언제나 사용자 환경이다. 단일 인스턴스 잠금·WebView2 프로필·
  앱 전역 설정은 이 전환과 무관하게 실제 앱 홈을 쓴다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..host.locations import activate_workspace
from .screens import PushSink

__all__ = ["WorkspaceGraph", "WorkspaceSwitch"]


@dataclass
class WorkspaceGraph:
    """한 홈에 결속된 제품 컨트롤러 묶음. ``home is None`` 이면 사용자 환경이다."""

    home: "Path | None"
    controllers: "dict[str, Any]"
    template_root: Any
    job_registry: Any
    pool_registry: Any
    token: object = field(default_factory=object)


#: (홈, 이 그래프 전용 푸시, 그래프 토큰) → 조립된 그래프.
GraphBuilder = Callable[["Path | None", PushSink, object], WorkspaceGraph]


class WorkspaceSwitch:
    """활성 작업 공간의 단일 소유자 — 진입·이탈·재전송만 한다(판정은 튜토리얼 컨트롤러)."""

    def __init__(self, push: PushSink, build: GraphBuilder,
                 adopt: "Callable[[WorkspaceGraph], None]") -> None:
        self._push = push
        self._build = build
        self._adopt = adopt
        self._lock = threading.RLock()
        self._token: object = object()
        activate_workspace(None)
        self.user = build(None, self._gate(self._token), self._token)
        self.practice: "WorkspaceGraph | None" = None
        self.active = self.user
        adopt(self.user)

    def _gate(self, token: object) -> PushSink:
        def push(screen: str, snapshot: dict):
            if token is not self._token:
                return None  # 비활성 그래프 — 활성화 때 새 스냅샷으로 다시 민다.
            return self._push(screen, snapshot)

        return push

    @property
    def practice_home(self) -> "Path | None":
        """지금 활성인 연습 홈 — 사용자 환경이면 ``None``."""
        return self.active.home

    def enter(self, home: Path) -> None:
        """그 과정의 홈으로 전환한다. 같은 홈의 그래프가 이미 있으면 그대로 다시 세운다."""
        with self._lock:
            practice = self.practice
            if practice is not None and practice.home == home:
                self._activate(practice)
                return
            # 조립 중 푸시는 화면에 닿지 않는다(토큰은 활성화가 끝난 뒤에 선다). 조립이 실패하면
            # 기본 위치를 지금 활성 그래프의 홈으로 되돌린다 — 활성 그래프도 그대로다.
            token = object()
            activate_workspace(home)
            try:
                graph = self._build(home, self._gate(token), token)
            except BaseException:
                activate_workspace(self.active.home)
                raise
            self.practice = graph
            self._activate(graph)

    def leave(self) -> None:
        """사용자 환경으로 돌아간다 — 연습 그래프는 다음 재개를 위해 메모리에 남는다."""
        with self._lock:
            self._activate(self.user)

    def _activate(self, graph: WorkspaceGraph) -> None:
        activate_workspace(graph.home)
        self.active = graph
        self._adopt(graph)
        self._token = graph.token  # 브리지 참조가 이 그래프로 바뀐 뒤에야 그 푸시가 닿는다.
        self.refresh()

    def refresh(self) -> None:
        """활성 그래프의 모든 채널을 지금 스냅샷으로 다시 민다(공유 튜토리얼 채널 제외)."""
        tutorial = self.active.controllers.get("tutorial")
        for name, controller in self.active.controllers.items():
            if controller is not tutorial:
                self._push(name, controller.snapshot())

    def all_controllers(self) -> "list[Any]":
        """메모리에 있는 모든 그래프의 컨트롤러 — 창 종료 가드가 비활성 쪽 손실도 묻는다."""
        seen: "dict[int, Any]" = {}
        for graph in (self.active, self.user, self.practice):
            for controller in (graph.controllers.values() if graph else ()):
                seen.setdefault(id(controller), controller)
        return list(seen.values())
