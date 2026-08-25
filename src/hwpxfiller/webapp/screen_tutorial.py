"""온보딩 튜토리얼 체크리스트의 링2 컨트롤러 — 슬라이스 E(#894).

정본은 :doc:`docs/ONBOARDING_TUTORIAL.md` §4.3(판정·렌더·통신)·§4.4(영속)다. 이 컨트롤러가
지는 것은 **소유·영속·전달** 셋이고, 판정과 문안은 하나도 여기 없다:

1. **세션 소유** — 앱에 :class:`~hwpxfiller.gui.tutorial_state.TutorialViewModel` 하나뿐이고
   그 하나를 이 컨트롤러가 든다. 다른 화면 컨트롤러는 VM 도 ``settings`` 도 들지 않고
   :data:`~hwpxfiller.webapp.screens.TutorialSink`
   (= :meth:`TutorialController.notify`) **콜러블 하나만** 주입받는다 —
   푸시 sink 주입과 같은 규율이다(컨트롤러는 채널도 저장소도 모른다).
2. **영속 왕복** — 부팅 때 ``load_tutorial_progress()`` 로 복원하고, 달성·종료·재개가
   성립할 때마다 ``save_tutorial_progress()`` 로 저장한다. 값만 드나들므로 링1 은 계속
   IO 0 이다(:mod:`~hwpxfiller.gui.tutorial_state` 머리말).
3. **스냅샷 전달** — 기존 관측 푸시(`window.__hwpx` 의 ``snapshot`` 사건) 위에 얹은
   ``tutorial`` 채널 하나다. 새 통신 경로를 만들지 않는다.

## 화면이 아니라 채널이다

``tutorial`` 은 제품 화면이 아니다 — DOM 루트도 탭도 없고, 표면은 셸 레벨 React 패널이다.
그래도 action registry 의 화면 키를 갖는 이유는 그것이 이 저장소에서 **스냅샷 채널과 디스패치
어휘를 얻는 유일한 방법**이기 때문이다(채널 목록은 ``SCREEN_ACTIONS`` 에서 유도된다 — 손
목록이 없다). 같은 형태의 선례가 ``pool`` 이다: 화면은 죽고 컨트롤러와 채널만 살아 데이터
선택 다이얼로그가 그것을 소비한다.

## 큐 소비는 왜 왕복인가

동시 1장·억제·자동 소멸은 표면의 몫이라 링1 은 미소비 카드 목록만 낸다. 표면이 한 장을
띄운 뒤 ``consume_moment`` 로 소비를 되알리지 않으면 같은 카드가 다음 스냅샷에서 다시 뜬다 —
그래서 소비는 **디스패치 액션**이고, 프런트가 자기 안에서 조용히 지우는 경로는 없다.
소비는 진행이 아니라 표시 이력이라 영속하지 않는다(세션 값이다).
"""
from __future__ import annotations

from typing import Callable

from ..gui.tutorial_state import Milestone, TutorialViewModel
from .screens import PushSink

__all__ = ["TutorialController"]

class TutorialController:
    """튜토리얼 진행 감지 체크리스트 — VM 소유 + 영속 + 스냅샷 채널(webview 비의존)."""

    name = "tutorial"

    def __init__(
        self,
        push: PushSink,
        *,
        load_progress: "Callable[[], dict]",
        save_progress: "Callable[..., None]",
    ) -> None:
        # 영속 어댑터는 composition root 가 주입한다 — 컨트롤러가 ``settings`` 를 직접 import
        # 하면 헤드리스 테스트가 홈 격리 말고는 이 왕복을 잡을 축을 잃는다(locator 뒷문 금지).
        self._push_sink = push
        self._save_progress = save_progress
        self.vm = TutorialViewModel.from_progress(load_progress())

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _persist(self) -> None:
        self._save_progress(**self.vm.progress())

    # ------------------------------------------------------- 마일스톤 통지(컨트롤러 간)
    def notify(self, milestone: "Milestone | str") -> bool:
        """이미 성립한 전이 사실을 기록한다 — 새로 기록됐으면 ``True``.

        디스패치 액션이 **아니다**: 웹이 부르는 표면이 아니라 원인 동사(작업 저장·마운트·
        승인·생성 완료·복사·compile)의 성공과 같은 줄에서 파이썬이 스스로 부르는 컨트롤러 간
        seam 이다(``tpl`` → 편집기 재정산 seam 과 같은 부류). 중복 통지는 무해하고, 모르는
        단계 식별자는 링1 이 시끄럽게 거절한다.

        새로 기록됐을 때만 저장·푸시한다 — 같은 사실의 재통지가 디스크 쓰기와 렌더를 부르면
        생성 한 번이 통지 여러 번인 경로에서 그 비용이 조용히 곱해진다.
        """
        if not self.vm.notify(milestone):
            return False
        self._persist()
        self._push()
        return True

    # ------------------------------------------------------------- 스냅샷
    def snapshot(self) -> dict:
        return self.vm.snapshot()

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 tutorial 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_dismiss(self, p: dict) -> None:
        """명시 종료 — 표면을 내리고 대기 카드를 버린다. 달성 기록은 남는다(재개가 잇는다)."""
        self.vm.dismiss()
        self._persist()

    def _do_resume(self, p: dict) -> None:
        """재개 — 닫는 동안에도 기록은 이어졌으므로 진행이 그대로 선다."""
        self.vm.resume()
        self._persist()

    def _do_consume_moment(self, p: dict) -> dict:
        """순간 카드 한 장의 소비를 되알린다(표시 이력이라 영속하지 않는다).

        모르는 식별자는 링1 ``_coerce`` 가 ``ValueError`` 로 거절한다 — 표면의 오타가 큐를
        조용히 그대로 두어 같은 카드가 영원히 다시 뜨는 경로를 만들지 않는다.
        """
        return {"consumed": self.vm.consume_moment(p["milestone"])}
