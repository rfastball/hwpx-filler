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

import os
from pathlib import Path
from typing import Callable, Iterable, Protocol

from ..core.dataset_pool import (
    STATUS_ACTIVE,
    DatasetPoolItem,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from ..data.excel import ambiguous_sheet_error  # 다중 시트 확정 게이트 판정+문구(#33)
from ..core.fill_ledger import template_path_drift  # 재연결 드리프트 재진술(#67)
from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import (
    RenderReport,
    align_segments,
    render_segments,
    segments_have_space_run,
    template_fields,
)
from ..gui.dataset_pool_state import DatasetPoolRow
from ..gui.selection_state import SelectionModel
from ..gui.txt_queue import TxtQueueModel
from ..gui.txt_state import TxtDraftViewModel
from .data_zone import DataZoneMixin
from .settings import (
    is_proportional_font,
    load_draft_target_font,
    save_draft_target_font,
)

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


# -------------------------------------------- 추적성 로케이트 화이트리스트(#53-B)
def norm_path(p: "str | Path") -> str:
    """경로 비교 정규화 — 대소문자·구분자·상대경로 차이를 흡수(Windows 대소문자 무시)."""
    return os.path.normcase(os.path.abspath(str(p)))


def collect_owned_paths(
    job_registry, pool_registry, session_paths: "Iterable[str]" = ()
) -> "set[str]":
    """열기/보기/복사 대상 화이트리스트 — 웹 페이로드로 임의 경로를 실행하는 통로를 봉쇄
    (``reveal_corrupt_job`` 화이트리스트 선례). 사용자 소유 참조만 통과: 작업 템플릿·등록
    데이터 파일(durable 레지스트리) + 현재 세션 경로(에디터/실행). 손상 항목은 흡수 목록으로
    받아 raise 시키지 않는다(로케이트가 손상 하나로 죽지 않게). 순수 함수라 헤드리스 테스트."""
    paths: "set[str]" = set()
    for j in job_registry.list_jobs():                    # 손상 제외가 기본
        if getattr(j, "template_path", ""):
            paths.add(norm_path(j.template_path))
    for it in pool_registry.list_items(corrupted=[]):     # 손상 흡수(raise 방지)
        p = it.opts.get("path") if isinstance(it.opts, dict) else None
        if isinstance(p, str) and p:
            paths.add(norm_path(p))
    for p in session_paths:
        if p:
            paths.add(norm_path(p))
    return paths


def validate_owned_path(path: str, owned: "set[str]") -> str:
    """``path`` 가 소유 화이트리스트에 있으면 그대로 반환, 아니면 시끄럽게 거부."""
    if not path:
        raise ValueError("경로가 비어 있습니다.")
    if norm_path(path) not in owned:
        raise ValueError(
            "이 경로는 앱이 추적하는 참조(작업 템플릿·등록 데이터·현재 세션)가 "
            "아니라 열 수 없습니다."
        )
    return path


def default_pool_registry() -> DatasetPoolRegistry:
    """웹 컨트롤러 기본 풀 레지스트리 — 홈 레지스트리(ADR J). 테스트는 생성자 주입."""
    return DatasetPoolRegistry(default_dataset_pool_dir())


def pool_sources_payload(pool_registry: DatasetPoolRegistry) -> dict:
    """피커 페이로드 ``{"items": 활성 풀 항목 행, "corrupted_note": 손상 병기 문구}``.

    **활성** 풀 항목의 웹 직렬화(이름·종류·참조 요약) — 실행 후보는 active 만(ADR J).
    행 성형은 링1 :class:`~hwpxfiller.gui.dataset_pool_state.DatasetPoolRow` 재사용
    (참조 요약·종류 라벨 재구현 금지). nara 항목도 그대로 실린다 — 존재를 숨기지 않고
    겨눔 시점에 :func:`load_pool_item_checked` 가 거절한다.

    **손상 병기(C5)**: 손상 ``.dataset.json`` 은 격리 수집해 ``corrupted_note`` 로
    함께 싣는다(없으면 ``""``) — 예전엔 미수집 격리로 손상 데이터셋이 피커에서
    무표시 증발했다(조용한 드롭 금지). 상세 조치는 데이터 관리 화면 몫.
    """
    corrupted: "list[tuple[Path, str]]" = []
    rows = [
        {
            "name": row.name,
            "kind": row.kind,
            "kind_label": row.kind_label,
            "reference": row.reference,
        }
        for row in (
            DatasetPoolRow.from_item(it)
            for it in pool_registry.list_items(status=STATUS_ACTIVE, corrupted=corrupted)
        )
    ]
    note = (
        f"손상 {len(corrupted)}건 — 데이터 관리에서 확인" if corrupted else ""
    )
    return {"items": rows, "corrupted_note": note}


def load_pool_item_checked(
    pool_registry: DatasetPoolRegistry, name: str
) -> DatasetPoolItem:
    """이름으로 풀 항목을 로드하되 나라(동결)·모호 시트는 시끄럽게 거절 — 웹 2소스 경계의 단일 관문.

    **다중 시트 확정 게이트(#33) 재확립:** 시트를 지정하지 않은 엑셀 참조는 실행 복원 때
    ``ExcelDataSource(sheet=None)`` 이 **조용히 첫 시트**를 읽는다 — 파일 선택 경로가 #33 에서
    봉인한 바로 그 함정이 풀 경로로 재개방된 것. 워크북에 시트가 여럿이면 여기서 loud 거절해
    사용자가 데이터 관리에서 시트를 지정해 다시 등록하게 한다(등록 시점 게이트가 있어도, 그
    이전에 만들어진 모호 항목까지 여기 단일 관문이 잡는다). 판정+문구·읽기 실패(죽은 참조)
    통과 정책은 :func:`~hwpxfiller.data.excel.ambiguous_sheet_error` 단일 출처(등록 게이트와
    공유 — 두 사이트의 문구 표류 봉인), 죽은 참조는 이어지는 실제 로드가 재진술.
    """
    try:
        item = pool_registry.load(name)
    except FileNotFoundError:
        raise ValueError(f"등록 데이터를 찾을 수 없습니다: {name}") from None
    if item.kind == "nara":
        raise ValueError(NARA_FROZEN_TEXT)
    if item.kind == "excel" and not item.opts.get("sheet"):
        err = ambiguous_sheet_error(
            str(item.opts.get("path", "")),
            prefix=f"등록 데이터 '{name}' 에 시트가 지정되지 않았습니다 — ",
        )
        if err:
            raise ValueError(err)
    return item


# 빈 데이터 재진술 단일 출처(R-copy) — run/editor/pool 공유. "레코드"는 개발 어휘라
# 사용자 문구에선 "행"(엑셀 어휘)으로 통일한다(101 순회 F15 계열).
NO_ROWS_TEXT = "데이터에 행이 없습니다 — 데이터를 바꾸지 않았습니다."


def load_pool_into(
    pool_registry: DatasetPoolRegistry, name: str, loader: "Callable[[DatasetPoolItem], list]"
) -> dict:
    """등록 데이터 겨눔의 공유 실행부 — 나라 동결·모호 시트·죽은 참조·레코드 0건을 단일
    문구 체계로 재진술한다(run/txt 화면 동형).

    ``loader(item)`` 는 각 화면 VM 의 ``load_pool_item`` (실행 시점 재읽기="싱크"). 성공 시
    ``{"ok": True, "records": [...]}`` 를, 실패 시 ``{"ok": False, "error": ...}`` 를 돌려준다
    — 라벨·선택 초기화 등 화면별 후처리는 호출측이 결과 레코드로 수행한다. 예전엔 이 20줄
    try/except 사다리가 컨트롤러마다 복붙돼 문구가 이미 표류했다(txt '상태' vs run
    '데이터') — 여기로 수렴해 락스텝 편집 부담과 재표류를 없앤다.
    """
    try:
        item = load_pool_item_checked(pool_registry, name)
        records = loader(item)
    except ValueError as exc:  # 동결 거절·항목 부재·모호 시트 — 문구 그대로 재진술
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — 죽은 참조(파일 이동 등) 사용자 문구로
        return {"ok": False, "error": f"등록 데이터를 불러올 수 없습니다: {exc}"}
    if not records:
        return {"ok": False, "error": NO_ROWS_TEXT}
    # item 동봉(#67) — 호출측이 로케이트 경로(opts["path"]) 등 참조 메타를 재사용한다.
    return {"ok": True, "records": records, "item": item}


def source_label(source: str, data_label: str) -> str:
    """소스 종류 플래그(``'file'``|``'pool'``)+표시명 → 병기 라벨 합성(K8).

    예전엔 ``data_source_label`` 이 ``data_label`` 과 쌍으로 컨트롤러 여러 지점에서
    저장·리셋되는 전(全)파생 중복 상태였다 — 저장하지 않고 스냅샷이 매번 여기서 합성한다
    (단일 출처 = 문구 표류·리셋 누락 봉인). 미지 플래그는 시끄럽게 실패한다
    (confirm-or-alarm: 조용한 빈 라벨 금지)."""
    if not source:
        return ""
    if source == "file":
        return f"파일: {data_label}"
    if source == "pool":
        return f"등록 데이터: {data_label}"
    raise ValueError(f"알 수 없는 데이터 소스 종류: {source!r}")


# ------------------------------------------------- 템플릿 다시 연결(#67)
def relink_job_template(job_registry, name: str, path: str, *, confirm: bool = False) -> dict:
    """작업 템플릿 참조 재지정 — run/home 공유 확정 게이트(교차-단위 계약 단일 출처).

    파일 이동/삭제로 끊긴 ``Job.template_path`` 를 새 파일로 갱신하는 유일한 durable
    뮤테이션 경로다. 에디터는 죽은 템플릿 작업을 loud 차단해 열지 못하므로(#67 결정)
    여기가 막다른길을 푸는 입구이며, 드리프트 정책은 그 순서를 따른다:

    - **read_error = 하드 차단**: 읽을 수 없는 파일은 확인으로도 템플릿이 될 수 없다(알람).
    - **구조 드리프트 = 재진술 확인 후 허용**: 커밋해도 생성은 기존 드리프트 게이트
      (:meth:`~hwpxfiller.gui.run_state.RunViewModel` fail-closed)가 매핑 재확정 전까지
      차단하므로 안전하다. 여기서 막으면 '이동+구조 변경' 작업은 영구 복구 불능이 된다.
    - 드리프트가 없어도 durable JSON 뮤테이션이므로 기존→새 경로 재진술 확인 1회.

    실패는 raise 대신 오류 dict 재진술(``_do_register_excel`` 문법) — 웹이 그대로 표시.
    """
    if not path:
        return {"ok": False, "error": "새 템플릿 경로가 비어 있습니다."}
    try:
        job = job_registry.load(name)
    except FileNotFoundError:
        return {"ok": False, "error": f"작업을 찾을 수 없습니다(이미 삭제된 작업): {name}"}
    except ValueError as exc:  # 손상 JSON — 격리 대상, 재연결로 고칠 수 없다.
        return {"ok": False, "error": f"작업을 읽을 수 없습니다: {exc}"}
    drift = template_path_drift(path, job.mapping)
    if drift.read_error:  # has_drift 는 read_error 를 포함하므로 반드시 선판정
        return {
            "ok": False,
            "error": f"새 템플릿을 읽을 수 없습니다: {drift.read_error} — 연결을 바꾸지 않았습니다.",
        }
    if not confirm:
        drift_clause = (
            (
                "\n\n⚠ 새 파일의 구조가 이 작업의 확정 매핑과 다릅니다:\n"
                f"{drift.describe()}\n"
                "저장해도 에디터에서 매핑을 재확정하기 전에는 생성이 차단됩니다."
            )
            if drift.has_drift else ""
        )
        return {
            "ok": True, "needs_confirm": True, "name": name,
            "confirm_text": (
                f"작업 '{name}' 의 템플릿 연결을 바꿉니다.\n"
                f"기존: {job.template_path or '(비어 있음)'}\n"
                f"새 파일: {path}{drift_clause}"
            ),
        }
    old = job.template_path
    job.template_path = path  # 단일 필드 뮤테이션 — 매핑·태그·기본 데이터 참조 보존
    job_registry.save(job, allow_overwrite=True)
    return {"ok": True, "relinked": True, "name": name, "old": old, "path": path}


class PoolTargetingMixin:
    """등록 데이터(풀) 겨눔 래퍼 공용화(K4) — ``_do_pool_sources``/``_do_load_pool`` 화면 동형.

    예전엔 이 두 래퍼가 실행 표면 컨트롤러들에 독스트링('(#26/#6)')까지 복붙돼
    있었다 — 게이트 실행부(:func:`load_pool_into`)만 공용이고 래퍼는 여러 벌. 여기로 수렴하고
    화면별 차이는 두 훅으로만 남긴다:

    - :meth:`_pool_guard` — 겨눔 전제 미충족 시 사용자 문구 반환(기본 없음, run=작업 선택).
    - :meth:`_after_pool_load` — 성공 후처리(기본 no-op, run=행 선택 초기화).

    요구 표면: ``pool_registry``·``vm.load_pool_item``·``data_label``·``data_source``.
    """

    pool_registry: DatasetPoolRegistry
    data_label: str
    data_source: str  # ''(미겨눔) | 'file' | 'pool' — 라벨은 source_label 이 합성(K8)
    # 로케이트 대상 파일 경로(#67) — 겨눔 시점에 캐시(렌더당 I/O 0). 겨눔 후 풀 항목이
    # 재연결되면 구식화되지만, 이는 로드된 레코드와 동일한 sync-at-aim 신선도 의미다.
    data_track_path: str = ""

    def _pool_guard(self) -> "str | None":
        """겨눔 전제조건 검사 — 미충족이면 사용자 문구, 충족이면 None."""
        return None

    def _after_pool_load(self, records: list) -> None:
        """겨눔 성공 후 화면별 후처리(행 선택 초기화 등). 기본 no-op."""

    def _do_pool_sources(self, p: dict) -> dict:
        """활성 등록 데이터 목록 — 웹 선택 모달이 소비(이름·종류·참조 요약 + 손상 병기)."""
        return pool_sources_payload(self.pool_registry)

    def _do_load_pool(self, p: dict) -> dict:
        """등록 데이터 항목을 이름으로 겨눔 — 공유 관문(:func:`load_pool_into`)에 위임.

        실패는 raise 대신 오류 dict 재진술(웹이 모달 안에서 그대로 표시) — generate 계열과
        같은 문법. 성공 시 라벨은 스냅샷이 소스 플래그로 합성해 반영한다(K8).
        """
        blocked = self._pool_guard()
        if blocked:
            return {"ok": False, "error": blocked}
        name = p["name"]
        res = load_pool_into(self.pool_registry, name, self.vm.load_pool_item)
        if not res["ok"]:
            return res
        self.data_label = name
        self.data_source = "pool"
        # 로케이트 경로 캐시(#67) — kind 판정을 DatasetPoolRow.locate_path 와 동형으로
        # (excel 만 파일 경로; opts["path"]만 보면 두 사이트의 판정이 표류한다 — PR #70 리뷰).
        item = res["item"]
        raw = item.opts.get("path") if isinstance(item.opts, dict) else None
        self.data_track_path = raw if (item.kind == "excel" and isinstance(raw, str)) else ""
        self._after_pool_load(res["records"])
        return {"ok": True, "label": source_label("pool", name)}


class ScreenController(Protocol):
    """브리지가 라우팅하는 화면 컨트롤러 표면. 새 화면 = 이 표면 구현 + 등록."""

    name: str

    def initial(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def dispatch(self, action: str, payload: dict) -> object: ...  # 값 반환 가능(예: 확인 게이트)


class TxtController(DataZoneMixin, PoolTargetingMixin):
    """즉시 기안(txt) 화면 — :class:`TxtDraftViewModel` 소유·위임.

    스파이크가 끝까지 검증한 첫 실화면(SPIKE_FINDINGS.md). 표현 재진술(빨강 미입력 ``{{토큰}}`` ·
    〈빈 값〉)은 링2 대체라 웹(js/screens/txt.js)에서 만든다 — VM 로직 재구현이 아니다.

    **데이터 존(블록 3·4, 슬라이스 6 PR-2b)**: 행 선택 = 복사용 렌더링 큐의 **전-선언**
    (결정 16 — hwpx 와 문법 대칭, 차이는 선언 입도뿐). 필터·선택 디스패치와 스냅샷 합성은
    :class:`~hwpxfiller.webapp.data_zone.DataZoneMixin` 공유(작업 화면과 단일 출처), 큐
    상태는 링1 :class:`~hwpxfiller.gui.txt_queue.TxtQueueModel` 이 소유한다(재구현 금지) —
    선택 변경마다 :meth:`TxtQueueModel.reconcile` 로 재봉합(``copied ⊆ selected`` 자가복구).

    **작업점 카드(블록 3, 슬라이스 6 PR-3)**: 큐가 지나가는 한 장(결정 16). :meth:`snapshot`
    의 ``card`` 섹션이 작업점 레코드를 링1 :func:`~hwpxfiller.core.text_render.render_segments`
    (채움 표지 삼분, 결정 22)로 사영하고 상태 색인(위치·처리·빈칸 지도)을 싣는다. :meth:`render`
    는 자유 레코드 커서가 아니라 큐 작업점을 렌더하며(복사=완료의 대상), :meth:`note_copied` 가
    복사 후 큐를 전진시킨다(전진 opt-in=``_advance_after``, 기본 꺼짐). 건별 파일 저장은 사망
    (결정 18) — 새 큐 표면에 재구현하지 않는다.

    **대상 글꼴 선언·정렬 린트·T3 가드(블록 3, 슬라이스 6 PR-4)**: 클립보드 평문은 글꼴을
    운반하지 않으므로(글꼴 = 목적지 소유) 붙여넣을 곳의 표준 글꼴을 선언받고 카드 렌더가 그
    선언을 따른다(결정 17 — 넘기려는 모습으로 미리 봄). 선언이 비례폭일 때만 연속 공백 정렬을
    경보하고 전각 치환을 제안하며, 치환은 **세션 렌더 옵션**(``_fullwidth``)이라 템플릿 원본은
    불변이고 카드와 클립보드가 같은 함수를 통과한다(보이는 것이 복사되는 것). T3 가드는
    데이터 교체가 큐의 부분 진행을 조용히 버리지 못하게 막는다(결정 26·27).
    """

    name = "txt"

    def __init__(
        self,
        registry: TextTemplateRegistry,
        push: PushSink,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
    ) -> None:
        self._registry = registry
        self._push_sink = push
        # 등록 데이터(풀) 겨눔(#26/#6) — 기본은 홈 레지스트리, 테스트는 주입.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
        # 직전 필터 슬롯·소스 키(결정 28)는 **컨트롤러 수명** — 세션(「새 기안」)이 죽어도
        # 직전 "정의"의 연속성은 남는다. filter 는 _fresh_session 의 스태시 판정이 첫
        # 호출에서도 안전하게 미리 눕힌다.
        self._last_filter = None
        self._data_key = ""
        self.filter = None
        # 복사 후 전진 옵션(결정 16, 기본 꺼짐) — 컨트롤러 수명(세션 「새 기안」을 넘어 유지,
        # 워드프로세서 토글 멘탈 모델). 넘어가기 = 사용자의 사실상 붙여넣기 서명이라 opt-in.
        self._advance_after = False
        # 대상 글꼴 선언(결정 17) — **전역 영속**(설정 파일)이라 컨트롤러보다 오래 산다.
        # 배치는 큐 상단 드롭다운이지만 스코프는 앱 전역(워드프로세서 툴바 멘탈 모델).
        self._target_font = load_draft_target_font()
        # 전각 정렬 치환(결정 17 린트 처방) — **세션 렌더 옵션**. 템플릿 원본은 건드리지 않고
        # (이름 있는 템플릿이 조용히 「이름 없는 세션 템플릿」으로 강등되지 않게) 렌더 단계에서만
        # 적용한다. 카드와 클립보드가 같은 변환을 통과하므로 되읽기가 곧 검증이다.
        self._fullwidth = False
        # 직전 복사 확정(스냅샷 구동 완료 노트) — 복사가 세팅, 어떤 동작이든 무효화(결정 16).
        self._last_copy: "dict | None" = None
        # 빈칸 지도 캐시(리뷰 F6) — (records 정체, 템플릿) 키. 데이터/템플릿 불변이면 재계산 안 함.
        self._gap_cache: "dict[int, bool]" = {}
        self._gap_cache_key: "tuple | None" = None
        self._fresh_session()

    def _fresh_session(self) -> None:
        """기안 세션 초기 상태 — VM 재구성 + 첫 템플릿 자동 선택 + 데이터 라벨 소거.

        생성자와 「새 기안」(F11)이 같은 경로를 탄다 — 두 초기 상태가 갈라지지 않게.
        죽는 세션의 활성 필터 정의는 직전 슬롯으로 넘긴다(결정 28 — 슬롯은 세션보다
        오래 산다). 선택·큐·필터 자체는 세션 휘발(결정 8·24)이라 세션과 함께 죽는다.
        """
        self._stash_filter()  # 옛 소스 키 기준 — 키 소거 전에
        self.vm = TxtDraftViewModel(self._registry)
        self.data_label = ""  # 겨눈 데이터 파일 표시명(서버 소유 — run 과 정렬, P4)
        self.data_source = ""  # 소스 종류 플래그('file'|'pool') — 병기 라벨은 스냅샷이 합성(K8)
        self._data_key = ""
        # 데이터 존(슬라이스 6) — 레코드 정체 = 세션 내 인덱스(SelectionModel 키를 큐가 재사용).
        self.selection = SelectionModel(0)
        self.queue = TxtQueueModel(self.selection)
        self.filter = None
        # 전각 치환은 그 원문에 대한 판단이라 세션과 함께 죽는다(대상 글꼴 선언은 전역 영속이라
        # 살아남는 것과 대비 — 선언은 사용자의 환경 사실, 치환은 이번 원문의 조치).
        self._fullwidth = False
        names = self.vm.template_names()
        if names:
            self.vm.select_template(names[0])

    def _records(self) -> list:
        return self.vm.records

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def snapshot(self) -> dict:
        vm = self.vm
        n = vm.record_count()
        records = self._records()
        fields = template_fields(vm.template_text)
        # 데이터 존(블록 3·4) — 선두 「큐」 열 소재 = 큐 표지(대기·복사됨·작업점).
        # 큐 조회는 **1회 O(n) 선계산** 후 O(1) 로 본다(PR-2b 리뷰: position_of·is_copied 는
        # 각각 리스트 스캔이라 행마다 부르면 매 push 가 O(n²) — 대형 코퍼스에서 타건마다 지연).
        indices = self.selection.selected_indices()
        qpos_of = {idx: k + 1 for k, idx in enumerate(self.queue.uncopied())}
        copied_set = set(self.queue.copied_tail())
        current = self.queue.current

        def lead_for(i: int) -> dict:
            return {
                "index": i,
                "selected": self.selection.is_selected(i),
                # 미처리 큐 순번 — 표면은 이 수를 **행 표에 렌더하지 않는다**(큐-꼬리 순서라
                # 레코드 순서 표에서 비단조로 읽힌다, PR-2b 리뷰). 큐 순서로 그리는 상태
                # 색인·작업점 카드(PR-3)가 소비할 링1 진실이라 스냅샷엔 싣는다.
                "qpos": qpos_of.get(i),
                "copied": i in copied_set,
                "current": current == i,
            }

        filter_snap, table_snap, _view, _visible = self._zone_sections(indices, lead_for)

        # 작업점 카드(결정 16) — 큐가 지나가는 한 장. 렌더는 링1 render_segments(채움 표지
        # 삼분, 결정 22)를 소비한다: 웹은 토큰 정규식을 재구현하지 않는다(파생경계 번역오류
        # 상류 차단, PR-1 예고).
        # 프리뷰 레코드(리뷰 F1): 작업점이 있으면 그 행, 없어도 **데이터가 있으면 행 0 을
        # 미리 보여준다**(자유 커서 시절 거동 복원). 선택 0(전체 해제)에서 빈 레코드로 그리면
        # `_field_state` 가 실재하는 열까지 전부 '항목 없음'(missing)으로 칠해 **거짓 경보**를
        # 낸다(confirm-or-alarm 정면 위반). 복사 게이트는 프리뷰가 아니라 `has_current` 가 진다.
        preview_idx = current if (current is not None and 0 <= current < n) else (0 if n else None)
        card_rec = records[preview_idx] if preview_idx is not None else {}
        segments, card_report = render_segments(vm.template_text, card_rec)
        # 정렬 린트 술어는 **치환 전 원문** 기준(결정 17) — 치환하면 런이 사라지므로 원문
        # 기준으로 보아야 "적용됨 · 되돌리기" 상태에서도 무엇을 고쳤는지 정직하게 말한다.
        space_run = segments_have_space_run(segments)
        proportional = is_proportional_font(self._target_font)
        segments = self._aligned(segments)

        # 빈칸 지도(has_gap)는 레코드 값+템플릿에만 의존(선택·작업점 무관) — 네비게이션·필터
        # 타건마다 O(행×필드)로 재계산하지 않게 (records 정체, 템플릿) 키로 캐시한다(리뷰 F6:
        # 매 push 재구축이 PR-2b 가 세운 O(1) 을 무너뜨림). 데이터 교체·템플릿 변경 시 무효화.
        gap_key = (id(records), vm.template_text)
        if self._gap_cache_key != gap_key:
            self._gap_cache = {}
            self._gap_cache_key = gap_key
        gap_cache = self._gap_cache

        def _has_gap(i: int) -> bool:  # 미충족(항목 없음·빈 값) 카드 판정, 인덱스별 1회 상각
            if i not in gap_cache:
                rec = records[i]
                gap_cache[i] = any(
                    name not in rec or ("" if rec[name] is None else str(rec[name])).strip() == ""
                    for name in fields
                )
            return gap_cache[i]

        index_map = [
            {
                "index": i,
                "state": "current" if i == current else ("copied" if i in copied_set else "uncopied"),
                "has_gap": _has_gap(i) if 0 <= i < n else False,
            }
            for i in self.queue.display_order()
        ]
        # 토큰 상태 = **링1 render_segments 리포트에서 파생**(리뷰 F4) — 같은 카드를 두 번 걷지
        # 않는다(_field_state 재유도 폐기). 카드 렌더(음영/〈빈 값〉/빨강)와 토큰 배지가 한 출처.
        missing_set, empty_set = set(card_report.missing_fields), set(card_report.empty_fields)
        tokens = [
            {
                "name": name,
                "state": "missing" if name in missing_set else ("blank" if name in empty_set else "fill"),
            }
            for name in fields
        ]
        card = {
            "index": current,
            "has_current": current is not None,
            "is_copied": current in copied_set if current is not None else False,
            "position": self.queue.position_of(current) if current is not None else None,
            "uncopied_count": len(self.queue.uncopied()),
            "copied_count": self.queue.copied_count(),
            "selected_count": self.selection.selected_count(),
            "is_complete": self.queue.is_complete(),
            "advance_after": self._advance_after,
            "segments": [{"text": s.text, "kind": s.kind, "name": s.name} for s in segments],
            "missing_fields": card_report.missing_fields,
            "empty_fields": card_report.empty_fields,
            "index_map": index_map,
            # 선언-조건부 정렬 린트(결정 17) — 표면은 **판정하지 않는다**(글꼴 이름으로
            # 비례폭을 재판별하거나 정규식을 다시 걷지 않는다, 파생경계 번역오류 차단).
            # active = 경보/확인 줄을 세울지. **치환이 걸려 있으면 선언 글꼴과 무관하게 선다**
            # (리뷰 F1): 고정폭으로 되돌린 뒤 줄이 사라지면 전각이 계속 클립보드로 나가는데
            # 사용자는 통보도 되돌릴 손잡이도 잃는다 — 조용한 변환 금지. 경보(치환 전)만
            # 선언-조건부다(고정폭에서 연속 공백은 정당한 저작이라 경보하면 소음).
            "lint": {
                "proportional": proportional,
                "space_run": space_run,
                "applied": self._fullwidth,
                "active": self._fullwidth or (proportional and space_run),
            },
            # 직전 복사 확정(결정 16 복사=완료) — **스냅샷 구동**이라 announce 순서 경합이 없다:
            # 노트가 카드와 같은 push 로 오고(어긋남 불가), 복사한 행을 명시(전진 시 카드는 다음
            # 행이라 행 번호로 어느 카드가 복사됐는지 못박는다). 어떤 동작이든(dispatch·데이터
            # 교체) 무효화 → 걷힌다(리뷰: 매 push 무조건 sticky 면 완료 노트가 다른 카드와 모순).
            "last_copy": self._last_copy,
        }
        return {
            "template_name": vm.template_name or "(붙여넣은 텍스트)",
            "template_text": vm.template_text,
            "tokens": tokens,
            "record_count": n,
            # 미충족 리포트는 **card 단일 출처**(리뷰 F9: 최상위 트윈은 조용한 desync 위험) —
            # 상태 배지(setStatus)·카드 판독·완료 노트 모두 card.missing_fields/empty_fields 소비.
            # render_text 이중 방출도 폐기(리뷰 F8): 카드 평문은 card.segments 로 재구성한다.
            "data_label": self.data_label,  # 서버 소유(P4) — 붙여넣기/템플릿 전환에도 실상태 반영
            # 소스 종류 병기 라벨(#26) — 저장 상태가 아니라 플래그에서 매번 합성(K8).
            "data_source_label": source_label(self.data_source, self.data_label),
            # 데이터 존 계약(datazone.js 소비 키) — 작업 화면과 같은 모양.
            # ``data_key`` = 소스 **정체**(경로 정규화·시트/참조 병기) — 표시 라벨은
            # basename 이라 `folder1/명단.xlsx`↔`folder2/명단.xlsx` 가 같은 문자열이 된다.
            # 표면의 세션 리셋(Shift 앵커·디바운스·고지)은 이 키에 겨눠야 동명 전환에서
            # stale 앵커로 엉뚱한 범위가 조용히 선택되지 않는다(PR-2b 리뷰).
            "data_key": self._data_key,
            "has_data": vm.datasource is not None,
            "selected_count": self.selection.selected_count(),
            # 대상 글꼴 선언(결정 17) — 카드가 아니라 최상위: 값의 스코프가 전역 영속이라
            # 카드/세션과 수명이 다르다(카드에 실으면 세션 값처럼 읽힌다).
            "target_font": self._target_font,
            "filter": filter_snap,
            "table": table_snap,
            "card": card,
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태(템플릿 목록 포함)."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅 후 푸시. 미지 액션은 시끄럽게 거부(P5: 타 화면 규약과 정렬).

        액션 후 큐 재봉합(:meth:`TxtQueueModel.reconcile`) — 선택·필터 변이가 큐 지형을
        바꾼다(``copied ⊆ selected`` 자가복구, 블록 3). reconcile 은 멱등이라 액션별 분기
        없이 공통 후처리로 둔다. 무변이 질의(``is_query`` — filter_panel)는 push 를
        생략한다(작업 화면 규약 승계 — 패널 여는 중 동일 스냅샷 재렌더 낭비 제거).
        """
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 txt 액션: {action!r}")
        result = handler(payload)
        self.queue.reconcile()
        if not getattr(handler, "is_query", False):
            # 변이 동작(네비게이션·템플릿·선택)은 직전 복사 확정을 무효화한다 — 카드가 바뀌므로
            # 완료 노트가 다른 카드와 모순되지 않게(리뷰 F1). 무변이 질의는 재렌더가 없어 불건드림.
            self._last_copy = None
            self._push()
        return result

    def _do_select_template(self, p: dict) -> None:
        self.vm.select_template(p["name"])
        self._fullwidth = False  # 치환은 그 원문에 대한 판단 — 원문이 바뀌면 함께 죽는다(리뷰 F2)

    def _do_new_draft(self, p: dict) -> None:
        """홈 「＋ 새 기안」 — 세션 원자 초기화(F11, F10 「새 작업」과 대칭 문법).

        종전 bare nav 는 직전 기안의 템플릿 선택·붙여넣은 텍스트·데이터·레코드 위치를
        그대로 남겨 라벨 '새'와 어긋났다.

        **면제 철회(#126)**: 원장 F11 의 무확인 근거는 "txt 출력은 일회성이라 버릴 durable
        상태가 없다"였는데, 블록 3 전-선언 큐가 신설되면서 거짓이 됐다. 큐의 복사 진행은
        durable 은 아니어도 **복구 불가**다 — 어디까지 붙여넣었는지는 앱 밖 기억이다. 이제
        이 전이도 T3 술어(:meth:`_guard_state`)를 지나며, 확인은 제스처를 소유한 표면
        (``TxtScreen.confirmNewDraftIfArmed``)이 큐 진행을 재진술해 받는다. 결정 32 가 빠른
        기안에서 같은 F11 전제를 이미 부분 개정했다(수기 폼 신설로 버릴 상태가 생김).
        """
        self._fresh_session()

    def _do_copy_precheck(self, p: dict) -> dict:
        """복사 전 빈칸 게이트 질의(결정 16 · 부록 A-3-28) — 클립보드로 나갈 카드의 결손 보고.

        게이트를 **복사 앞**에 세우기 위한 질의다: 종전에는 :meth:`can_copy`(작업점 실재)만
        보고 곧바로 클립보드에 쓴 뒤 결손을 사후 노트로 알렸다. 그러면 미해소 ``{{토큰}}`` 이
        확인 없이 나가고, 사용자는 온나라 기안작성기에 붙여넣은 **다음에야** 안다.

        판정은 여기서 지금 한다(JS 는 문안만) — 복사와 같은 :meth:`render` 통로를 타므로
        게이트가 본 집합과 실제 나가는 텍스트가 갈라지지 않는다. 완화 조항(결정 31)은
        "틀리면 보이는 추측(표현형)"에만 적용되고 미해소 토큰은 **그럴싸한 오류** 쪽이라
        엄격 유지가 같은 결정의 명문이다.
        """
        if not self.can_copy():
            return {"can_copy": False, "row": None, "missing_fields": [], "empty_fields": []}
        _text, report = self.render()
        return {
            "can_copy": True,
            "row": self.queue.current,
            "missing_fields": list(report.missing_fields),
            "empty_fields": list(report.empty_fields),
        }

    _do_copy_precheck.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def _do_set_template_text(self, p: dict) -> None:
        self.vm.set_template_text(p["text"])
        self._fullwidth = False  # 붙여넣은 새 원문에 옛 치환 결정이 승계되지 않는다(리뷰 F2)

    def _do_step(self, p: dict) -> None:
        """작업점을 큐 표시 순서로 이동(↓/↑, 경계 멈춤) — 자유 레코드 커서가 아니라 큐 판(결정 16)."""
        self.queue.step(int(p["delta"]))

    def _do_set_current(self, p: dict) -> None:
        """상태 색인 점 클릭 = 작업점 직접 지정(큐 밖 인덱스는 큐 모델이 정규화로 되돌린다)."""
        idx = p.get("index")
        self.queue.set_current(int(idx) if idx is not None else None)

    def _do_defer(self, p: dict) -> None:
        """미루기(결정 19) — 막힌 미처리 카드를 큐 뒤로. index 없으면 작업점(막힌 카드 탈출구)."""
        idx = p.get("index")
        self.queue.defer(int(idx) if idx is not None else None)

    def _do_toggle_advance(self, p: dict) -> None:
        """복사 후 전진 옵션(결정 16, 기본 꺼짐) — 컨트롤러 수명(세션 넘어 유지)."""
        self._advance_after = bool(p["value"])

    def _do_set_target_font(self, p: dict) -> None:
        """대상 글꼴 선언(결정 17) — 열거형 밖 값은 조용히 무시하지 않고 시끄럽게 거부한다.

        검증은 :func:`~hwpxfiller.webapp.settings.save_draft_target_font` 단일 출처가 진다
        (리뷰 F4: 여기 사본을 두면 열거형·문안이 갈라진다). **저장이 먼저**인 이유는 영속에
        실패했는데 화면 값만 바뀌면 "다음 부팅에 조용히 되돌아가는" 어긋남이 생기기 때문이다 —
        던지면 상태 불변 + 브리지 경보.
        """
        font = p["font"]
        save_draft_target_font(font)
        self._target_font = font

    def _do_set_fullwidth(self, p: dict) -> None:
        """전각 정렬 치환 적용/해제(결정 17 린트 처방) — 세션 렌더 옵션, 템플릿 원본 불변."""
        self._fullwidth = bool(p["value"])

    # ------------------------------------------------- 세션 가드(T3, 블록 4 결정 26·27)
    def _guard_state(self) -> dict:
        """무장 판정 = 선택 성분(공유 술어) ∨ **큐 부분 진행**(T3) — 데이터 교체가 소비한다.

        T3 성분: ``0 < 복사 < 선택``. 큐를 절반 걷다 데이터를 갈아치우면 처리 표지가 통째로
        증발하는데(새 데이터 = 새 큐), 어디까지 붙여넣었는지는 앱 밖 기억이라 복구 불가다.
        완주(``복사 == 선택``)는 완료 이벤트라 무장 해제 — 선택 성분에도 완주 집합을
        ``settled`` 로 넘겨 "다 복사한 선택"이 수작업으로 재고발되지 않게 한다.

        소비처는 **둘**이다: 데이터 재겨눔(원 T3)과 「＋ 새 기안」(#126 — 면제 철회, 근거
        상세는 :meth:`_do_new_draft`). 템플릿 교체는 여전히 가드 대상이 아니다 — 큐를 죽이지
        않으므로 잃을 진행이 없다.
        """
        copied, selected = self.queue.copied_count(), self.selection.selected_count()
        complete = self.queue.is_complete() and selected > 0
        settled = set(self.selection.selected_indices()) if complete else set()
        g = self._selection_guard(settled=settled)
        queue_partial = 0 < copied < selected
        g["copied_count"] = copied
        g["queue_partial"] = queue_partial
        g["armed"] = g["armed"] or queue_partial
        return g

    def _do_guard_state(self, p: dict) -> dict:
        """무장 상태 실시간 질의 — 표면의 데이터 재겨눔 사전 확인이 소비(작업 화면과 동형).

        스냅샷 캐시가 아니라 지금 Python 이 판정한다(왕복 지연·무푸시 경로의 stale 오판 차단).
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    # 등록 데이터(풀) 겨눔(#26/#6)은 PoolTargetingMixin 공용 래퍼(K4) — txt 화면별 후처리는
    # _after_pool_load(데이터 존 리셋)가 진다.
    def _after_pool_load(self, records: list) -> None:
        """풀 겨눔도 파일과 동일 리셋 — 전체 선택·새 큐·필터 재생성(작업 화면과 동형)."""
        self._stash_filter()  # 죽는 세션의 정의 → 슬롯(옛 소스 키 기준 — 키 갱신 전에)
        self._data_key = self._pool_key()  # 라벨은 공용 래퍼가 이미 세팅
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self.queue = TxtQueueModel(self.selection)     # 큐 = 세션 휘발 — 새 데이터 = 새 큐
        self._install_filter(records, {})  # txt 는 매핑 힌트 없음 — 값 스니핑만(결정 24)

    # ------------------------------------------------ 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 파일 경로를 링1 VM 으로 로드(레코드 0건이면 시끄럽게 실패·상태 불변).

        ``sheet`` = 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트)."""
        records = self.vm.load_data(path, sheet=sheet)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 표류 변형('상태를…')도 단일 출처로 수렴(R-copy)
        self._stash_filter()  # 죽는 세션의 정의 → 직전 필터 슬롯(결정 28, 옛 소스 키 기준)
        self.data_label = Path(path).name  # 서버 소유(P4)
        self.data_source = "file"  # 병기 라벨은 스냅샷이 합성(#26·K8)
        self._data_key = self._file_key(path, sheet)  # 소스 일치 게이트(결정 28)
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self.queue = TxtQueueModel(self.selection)     # 큐 = 세션 휘발 — 새 데이터 = 새 큐
        self._last_copy = None  # 새 데이터 = 직전 복사 확정 무효(네이티브 경로라 dispatch 미경유)
        self._install_filter(records, {})  # txt 는 매핑 힌트 없음 — 값 스니핑만(결정 24)
        self._push()

    def render(self) -> "tuple[str, RenderReport]":
        """작업점 카드(``queue.current``)의 렌더 텍스트+리포트 — 복사 완료가 소비한다(결정 16).

        자유 레코드 커서가 아니라 큐 작업점을 렌더한다(``vm.record_index`` 비의존 — 카드가
        진실). 작업점이 없으면 빈 레코드(전 토큰 미충족)라 표면이 복사를 게이트하지만,
        방어적으로 시끄러운 리포트를 낸다(confirm-or-alarm: 크래시 아닌 경보).
        """
        cur = self.queue.current
        records = self._records()
        rec = records[cur] if (cur is not None and 0 <= cur < len(records)) else {}
        # 클립보드 텍스트 = **카드와 같은 변환의 결과**(결정 17 치환의 계약): 세그먼트를
        # 이어붙여 만든다. render_record 를 그냥 부르면 치환이 카드에만 걸려 "보이는 것과
        # 복사되는 것"이 갈라진다 — 세그먼트 경로 하나로 묶어 그 어긋남을 구조적으로 없앤다.
        segments, report = render_segments(self.vm.template_text, rec)
        return "".join(s.text for s in self._aligned(segments)), report

    def _aligned(self, segments: list) -> list:
        """전각 치환 적용(세션 옵션이 켜졌을 때만) — 카드 렌더·클립보드 공용 통로."""
        return align_segments(segments) if self._fullwidth else segments

    def can_copy(self) -> bool:
        """복사 가능 = 작업점 실재(리뷰 F3) — 브리지가 이걸로 게이트해 작업점 없을 때 빈 템플릿
        (생 ``{{토큰}}``)이 클립보드로 조용히 나가는 것을 막는다(버튼 비활성과의 레이스·직접 호출)."""
        return self.queue.current is not None

    def note_copied(self, report: "RenderReport") -> None:
        """복사 완료 후 큐 갱신 — 작업점을 처리 후미로(멱등), 전진 opt-in, 재봉합·푸시(결정 16).

        복사=완료(결정 28)의 큐 판: 클립보드 쓰기(app.py 브리지)에 이어 상태를 전진시킨다.
        작업점을 복사해도 작업점은 그 카드에 머문다(조용한 이동 금지) — 전진은 ``_advance_after``
        가 켜졌을 때만 다음 미처리로. 작업점이 없으면(게이트가 막았어야) 무동작.

        ``report`` = 브리지가 클립보드용으로 이미 렌더한 그 카드의 리포트(재렌더 없이 재사용) —
        복사한 **행 번호**와 함께 ``_last_copy`` 에 담아 스냅샷 구동 완료 노트로 낸다(announce
        순서 경합·전진 시 카드 desync 차단, 리뷰 F1·F2)."""
        cur = self.queue.current
        if cur is None:
            return
        # 복사한 카드(전진 전 작업점)를 못박아 완료 노트에 실린다 — 전진해도 어느 행인지 명시.
        self._last_copy = {
            "row": cur,
            "missing_fields": list(report.missing_fields),
            "empty_fields": list(report.empty_fields),
        }
        self.queue.copy(cur)
        if self._advance_after:
            self.queue.advance_to_next_uncopied()
        self.queue.reconcile()  # copied ⊆ selected 불변식 유지(멱등)
        self._push()
