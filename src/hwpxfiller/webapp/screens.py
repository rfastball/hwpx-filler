"""화면별 컨트롤러 — 링1 VM 을 소유·위임하는 얇은 어댑터(webview 비의존).

브리지(:mod:`~hwpxfiller.webapp.app`)가 화면 id → 컨트롤러로 라우팅한다. 컨트롤러는 pywebview
를 임포트하지 않으므로 **헤드리스로 구동·테스트**된다(스파이크 Q1: 링1 이 Qt-free 라 뷰 계층만
교체하면 된다는 배당금의 연장). VM 로직은 재구현하지 않는다 — ``dispatch`` 는 VM 메서드로 위임만.

Python→웹은 관측 푸시(``push(screen, snapshot)``)로 밀어 넣는다. 푸시 sink 는 생성자에 주입되어
앱에선 ``window.evaluate_js`` 로, 테스트에선 리스트 수집으로 연결된다 — 컨트롤러는 채널을 모른다.

네이티브 자원이 필요한 동작(파일 다이얼로그·클립보드·원자 저장)은 창을 쥔 브리지가 수행하고,
데이터 로드·렌더는 컨트롤러 메서드(``load_data_path``·``render``)로 위임한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import RenderReport
from ..gui.txt_state import TxtDraftViewModel

# 푸시 sink: (화면 id, 스냅샷 dict) → None. 앱=evaluate_js, 테스트=수집.
PushSink = Callable[[str, dict], None]


class ScreenController(Protocol):
    """브리지가 라우팅하는 화면 컨트롤러 표면. 새 화면 = 이 표면 구현 + 등록."""

    name: str

    def initial(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def dispatch(self, action: str, payload: dict) -> object: ...  # 값 반환 가능(예: 확인 게이트)


class TxtController:
    """즉시 기안(txt) 화면 — :class:`TxtDraftViewModel` 소유·위임.

    스파이크가 끝까지 검증한 첫 실화면(SPIKE_FINDINGS.md). 표현 재진술(빨강 미입력 ``{{토큰}}`` ·
    〈빈 값〉)은 링2 대체라 웹(js/screens/txt.js)에서 만든다 — VM 로직 재구현이 아니다.
    """

    name = "txt"

    def __init__(self, registry: TextTemplateRegistry, push: PushSink) -> None:
        self.vm = TxtDraftViewModel(registry)
        self._push_sink = push
        self.data_label = ""  # 겨눈 데이터 파일 표시명(서버 소유 — run/matrix 와 정렬, P4)
        names = self.vm.template_names()
        if names:
            self.vm.select_template(names[0])

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def snapshot(self) -> dict:
        vm = self.vm
        text, report = vm.render()
        n = vm.record_count()
        return {
            "template_name": vm.template_name or "(붙여넣은 텍스트)",
            "template_text": vm.template_text,
            "record": {k: ("" if v is None else str(v)) for k, v in vm.current_record().items()},
            "tokens": [{"name": t.name, "state": t.state} for t in vm.token_states()],
            "record_index": (vm.record_index % n) + 1 if n else 0,
            "record_count": n,
            "render_text": text,
            "missing_fields": report.missing_fields,
            "empty_fields": report.empty_fields,
            "data_label": self.data_label,  # 서버 소유(P4) — 붙여넣기/템플릿 전환에도 실상태 반영
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태(템플릿 목록 포함)."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅 후 푸시. 미지 액션은 시끄럽게 거부(P5: 타 화면 규약과 정렬)."""
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 txt 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_select_template(self, p: dict) -> None:
        self.vm.select_template(p["name"])

    def _do_set_template_text(self, p: dict) -> None:
        self.vm.set_template_text(p["text"])

    def _do_step(self, p: dict) -> None:
        self.vm.step(int(p["delta"]))

    # ------------------------------------------------ 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str) -> None:
        """선택된 파일 경로를 링1 VM 으로 로드(레코드 0건이면 시끄럽게 실패·상태 불변)."""
        records = self.vm.load_data(path)
        if not records:
            raise ValueError("레코드 0건 — 상태를 바꾸지 않았습니다.")
        self.data_label = Path(path).name  # 서버 소유(P4)
        self._push()

    def render(self) -> "tuple[str, RenderReport]":
        """현재 렌더 텍스트+리포트 — 복사/저장 완료 동작이 소비한다."""
        return self.vm.render()
