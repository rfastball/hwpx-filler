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

from ..core.dataset_pool import (
    STATUS_ACTIVE,
    DatasetPoolItem,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import RenderReport
from ..gui.dataset_pool_state import DatasetPoolRow
from ..gui.txt_state import TxtDraftViewModel

# 푸시 sink: (화면 id, 스냅샷 dict) → None. 앱=evaluate_js, 테스트=수집.
PushSink = Callable[[str, dict], None]

# ------------------------------------------------- 등록 데이터(풀) 겨눔 공유 관문(#26/#6)
# 나라장터 소스 동결 결정(2026-07-16): 내부망 API 미확인으로 매몰비용이 가장 큰 영역이라
# 웹 표면에 노출하지 않는다(#10 frozen·#24 계류와 정합). 도메인 seam(data/nara.py·
# source_from_pool_item 의 nara 분기·register_nara)은 보존 — 동결 해제 시 재배선 지점.
# 풀에 이미 있는 nara 항목은 숨기지 않고 목록에 표시하되, 겨눔은 아래 관문이 시끄럽게
# 거절한다(confirm-or-alarm: 조용한 실패·조용한 숨김 둘 다 금지).
NARA_FROZEN_TEXT = (
    "나라장터 소스는 현재 웹에서 지원되지 않습니다(동결) — "
    "파일 또는 엑셀 참조 등록 데이터를 사용하세요."
)


def default_pool_registry() -> DatasetPoolRegistry:
    """웹 컨트롤러 기본 풀 레지스트리 — 홈 레지스트리(ADR J). 테스트는 생성자 주입."""
    return DatasetPoolRegistry(default_dataset_pool_dir())


def pool_source_rows(pool_registry: DatasetPoolRegistry) -> "list[dict]":
    """**활성** 풀 항목의 웹 직렬화(이름·종류·참조 요약) — 실행 후보는 active 만(ADR J).

    행 성형은 링1 :class:`~hwpxfiller.gui.dataset_pool_state.DatasetPoolRow` 재사용
    (참조 요약·종류 라벨 재구현 금지). nara 항목도 그대로 실린다 — 존재를 숨기지 않고
    겨눔 시점에 :func:`load_pool_item_checked` 가 거절한다.
    """
    return [
        {
            "name": row.name,
            "kind": row.kind,
            "kind_label": row.kind_label,
            "reference": row.reference,
        }
        for row in (
            DatasetPoolRow.from_item(it)
            for it in pool_registry.list_items(status=STATUS_ACTIVE)
        )
    ]


def load_pool_item_checked(
    pool_registry: DatasetPoolRegistry, name: str
) -> DatasetPoolItem:
    """이름으로 풀 항목을 로드하되 나라(동결)는 시끄럽게 거절 — 웹 2소스 경계의 단일 관문."""
    try:
        item = pool_registry.load(name)
    except FileNotFoundError:
        raise ValueError(f"등록 데이터를 찾을 수 없습니다: {name}") from None
    if item.kind == "nara":
        raise ValueError(NARA_FROZEN_TEXT)
    return item


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

    def __init__(
        self,
        registry: TextTemplateRegistry,
        push: PushSink,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
    ) -> None:
        self.vm = TxtDraftViewModel(registry)
        self._push_sink = push
        self.data_label = ""  # 겨눈 데이터 파일 표시명(서버 소유 — run/matrix 와 정렬, P4)
        self.data_source_label = ""  # 소스 종류 병기 라벨("파일: x" / "등록 데이터: 이름", #26)
        # 등록 데이터(풀) 겨눔(#26/#6) — 기본은 홈 레지스트리, 테스트는 주입.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
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
            "data_source_label": self.data_source_label,  # 소스 종류 병기(#26)
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

    # ---------------------------------------------- 등록 데이터(풀) 겨눔(#26/#6)
    def _do_pool_sources(self, p: dict) -> dict:
        """활성 등록 데이터 목록 — 웹 선택 모달이 소비(이름·종류·참조 요약)."""
        return {"items": pool_source_rows(self.pool_registry)}

    def _do_load_pool(self, p: dict) -> dict:
        """등록 데이터 항목을 이름으로 겨눔 — 나라(동결)·죽은 참조는 시끄럽게 거절.

        실패는 raise 대신 오류 dict 재진술(웹이 모달 안에서 그대로 표시) — generate 계열과
        같은 문법. 성공 시 라벨은 스냅샷(data_label)이 서버 소유로 반영한다(P4).
        """
        name = p["name"]
        try:
            item = load_pool_item_checked(self.pool_registry, name)
            records = self.vm.load_pool_item(item)
        except ValueError as exc:  # 동결 거절·항목 부재 — 문구 그대로 재진술
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — 죽은 참조(파일 이동 등) 사용자 문구로
            return {"ok": False, "error": f"등록 데이터를 불러올 수 없습니다: {exc}"}
        if not records:
            return {"ok": False, "error": "레코드 0건 — 상태를 바꾸지 않았습니다."}
        self.data_label = name
        self.data_source_label = f"등록 데이터: {name}"
        return {"ok": True, "label": self.data_source_label}

    # ------------------------------------------------ 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 파일 경로를 링1 VM 으로 로드(레코드 0건이면 시끄럽게 실패·상태 불변).

        ``sheet`` = 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트)."""
        records = self.vm.load_data(path, sheet=sheet)
        if not records:
            raise ValueError("레코드 0건 — 상태를 바꾸지 않았습니다.")
        self.data_label = Path(path).name  # 서버 소유(P4)
        self.data_source_label = f"파일: {self.data_label}"  # 소스 종류 병기(#26)
        self._push()

    def render(self) -> "tuple[str, RenderReport]":
        """현재 렌더 텍스트+리포트 — 복사/저장 완료 동작이 소비한다."""
        return self.vm.render()
