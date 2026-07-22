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
from ..gui.dataset_pool_state import DatasetPoolRow

# 푸시 sink: (화면 id, 스냅샷 dict) → None. 앱=evaluate_js, 테스트=수집.
PushSink = Callable[[str, dict], None]

# ------------------------------------------------- 등록 데이터(풀) 겨눔 공유 관문(#26/#6)
# 나라장터 소스 동결 결정(2026-07-16): 내부망 API 미확인으로 매몰비용이 가장 큰 영역이라
# 웹 표면에 노출하지 않는다(#10 frozen·#24 계류와 정합). 도메인 seam(data/nara.py·
# source_from_pool_item 의 nara 분기·register_nara)은 보존 — 동결 해제 시 재배선 지점.
# 풀에 이미 있는 nara 항목은 숨기지 않고 목록에 표시하되, 겨눔은 아래 관문이 시끄럽게
# 거절한다(confirm-or-alarm: 조용한 실패·조용한 숨김 둘 다 금지).
NARA_FROZEN_TEXT = (
    "나라장터 소스는 현재 웹에서 지원되지 않습니다. "
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
        raise ValueError("이 경로는 앱이 추적하는 참조가 아니라 열 수 없습니다.")
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
        f"손상 {len(corrupted)}건(데이터 관리에서 확인)" if corrupted else ""
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
            prefix=f"등록 데이터 '{name}' 에 시트가 지정되지 않았습니다. ",
        )
        if err:
            raise ValueError(err)
    return item


# 빈 데이터 재진술 단일 출처(R-copy) — run/editor/pool 공유. "레코드"는 개발 어휘라
# 사용자 문구에선 "행"(엑셀 어휘)으로 통일한다(101 순회 F15 계열).
NO_ROWS_TEXT = "데이터에 행이 없습니다."


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
            "error": f"새 템플릿을 읽을 수 없습니다: {drift.read_error}",
        }
    if not confirm:
        drift_clause = (
            (
                "\n\n⚠ 새 파일의 구조가 이 작업의 확정 매핑과 다릅니다:\n"
                f"{drift.describe()}\n"
                "매핑을 다시 확정하기 전에는 생성이 차단됩니다."
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
    # 확정 커밋 — 단일 필드 뮤테이션(매핑·태그·기본 데이터 참조 보존)을 레지스트리의 **잠긴
    # 경로**로 낸다(#129 리뷰 3R P1). 위에서 읽은 사본으로 통째 저장하면, 확인 왕복 사이에
    # 다른 writer(생성 스탬프·에디터 저장·태그 편집)가 남긴 변경을 낡은 값으로 되돌린다 —
    # 확인 게이트가 있어 그 창이 사람 시간만큼 길다는 점이 이 경로를 특히 위험하게 만든다.
    def _relink(j) -> None:
        j.template_path = path

    job_registry.mutate(name, _relink)
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

