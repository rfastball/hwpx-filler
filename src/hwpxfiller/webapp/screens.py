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

from ..application.jobs import CrossMediaRelinkError, relink_template
from ..data.excel import ambiguous_sheet_error  # 다중 시트 확정 게이트 판정+문구(#33)
from ..domain.dataset_reference import DatasetReference
from ..domain.engine import HwpxEngine
from ..external.dataset_store import DatasetPoolRegistry
from ..external.text_registry import read_text_utf8
from ..domain.fill_ledger import template_path_drift  # 재연결 드리프트 재진술(#67)
from ..domain.job import template_media, work_mode  # 재연결 매체 게이트(§10.16 판정 C)
from ..domain.text_render import template_fields  # TXT 토큰 판정(에디터와 같은 술어)
from ..gui.work_mode import work_mode_label  # 거절 문안의 방식 라벨 단일 출처(§19.1)

# 푸시 sink: (화면 id, 스냅샷 dict) → None. 앱=evaluate_js, 테스트=수집.
PushSink = Callable[[str, dict], None]

# 템플릿 bytes 변이 통지 sink: (kind, path) → None. 통지하는 쪽(tpl 채널)과 받는 쪽(편집
# 세션 재정산)이 **같은 어휘**를 써야 해서 여기 공용에 둔다(#320).
MutationSink = Callable[[str, str], None]

#: 그 kind 의 전수 — 파일이 제자리에서 **바뀜**(누름틀 변환·TXT 내용 저장) · **사라짐**
#: (휴지통 이동) · **돌아옴**(복원) 셋뿐이다. 새 durable 변이 동사를 더하면 여기 이름을 먼저
#: 정하고 그 성공 직후에 통지한다 — 이름 없는 kind 는 양쪽 다 시끄럽게 거절한다.
MUTATION_KINDS: "tuple[str, ...]" = ("mutated", "deleted", "restored")

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


def _pipeline_has_nara_source(opts: object) -> bool:
    """조립 참조 그래프 안의 나라 소스를 찾는다(손상 shape는 기존 loader에 맡김).

    ``inline`` 레코드 같은 일반 데이터 안의 ``{"kind": "nara"}``는 소스 참조가 아니다.
    따라서 각 ``sources`` 슬롯의 ``kind``만 보고, ``pipeline`` 슬롯의
    ``opts.sources``만 반복해서 내려간다. 타입이 다른 손상 조각은 변환하거나 여기서 새로
    실패시키지 않아 기존 복원 경로가 원래 오류를 그대로 재진술하게 한다.
    """
    if not isinstance(opts, dict):
        return False
    sources = dict.get(opts, "sources")
    if not isinstance(sources, list):
        return False

    pending: "list[object]" = list(sources)
    seen: "set[int]" = set()
    while pending:
        reference = pending.pop()
        if not isinstance(reference, dict):
            continue
        identity = id(reference)
        if identity in seen:
            continue
        seen.add(identity)

        kind = dict.get(reference, "kind")
        if not isinstance(kind, str):
            continue
        if kind == "nara":
            return True
        if kind != "pipeline":
            continue

        nested_opts = dict.get(reference, "opts")
        if not isinstance(nested_opts, dict):
            continue
        nested_sources = dict.get(nested_opts, "sources")
        if isinstance(nested_sources, list):
            pending.extend(nested_sources)
    return False

# TXT 판 RAW 차단(F6 PR-B) — hwpx 의 RAW_BLOCK_MESSAGE 는 누름틀·변환(fieldize)을 말하므로
# 그대로 쓰면 조치 안내가 거짓이 된다. TXT 의 채울 대상은 {{토큰}}이고 처방은 원문 편집이다
# (거처는 편집기 「템플릿」 탭 행 ⋮ — tpl 화면 사망(F8)으로 문안 재지정, 없는 곳 지시 금지).
# 여기(링2 공용)에 두는 이유: 같은 파일을 편집기 픽과 재연결 게이트가 각자 판정하므로
# 술어(`template_fields` 빈 결과)와 문안이 한 자리여야 두 표면이 같은 말을 한다(리뷰 2R P1
# — 편집기만 차단하고 재연결이 통과시키면 작업대가 모든 레코드에 같은 원문을 복사한다).
TXT_RAW_BLOCK = (
    "채울 {{토큰}}이 없는 TXT 템플릿입니다.\n"
    "목록의 행 ⋮ → '내용 편집'에서 원문에 {{필드이름}} 토큰을 넣은 뒤 다시 고르세요."
)


# -------------------------------------------- 추적성 로케이트 화이트리스트(#53-B)
def norm_path(p: "str | Path", base_dir: "str | Path") -> str:
    """경로 비교 정규화 — 대소문자·구분자·상대경로 차이를 흡수(Windows 대소문자 무시)."""
    path = Path(p)
    if not path.is_absolute():
        path = Path(base_dir) / path
    return os.path.normcase(os.path.abspath(str(path)))


def collect_owned_paths(
    job_registry, pool_registry, session_paths: "Iterable[str]" = (), *, base_dir: "str | Path"
) -> "set[str]":
    """열기/보기/복사 대상 화이트리스트 — 웹 페이로드로 임의 경로를 실행하는 통로를 봉쇄
    (``reveal_corrupt_job`` 화이트리스트 선례). 사용자 소유 참조만 통과: 작업 템플릿·등록
    데이터 파일(durable 레지스트리) + 현재 세션 경로(에디터/실행). 손상 항목은 흡수 목록으로
    받아 raise 시키지 않는다(로케이트가 손상 하나로 죽지 않게). 순수 함수라 헤드리스 테스트."""
    paths: "set[str]" = set()
    for j in job_registry.list_jobs():                    # 손상 제외가 기본
        if getattr(j, "template_path", ""):
            paths.add(norm_path(j.template_path, base_dir))
    for it in pool_registry.list_items(corrupted=[]):     # 손상 흡수(raise 방지)
        p = it.opts.get("path") if isinstance(it.opts, dict) else None
        if isinstance(p, str) and p:
            paths.add(norm_path(p, base_dir))
    for p in session_paths:
        if p:
            paths.add(norm_path(p, base_dir))
    return paths


def validate_owned_path(path: str, owned: "set[str]", *, base_dir: "str | Path") -> str:
    """``path`` 가 소유 화이트리스트에 있으면 그대로 반환, 아니면 시끄럽게 거부."""
    if not path:
        raise ValueError("경로가 비어 있습니다.")
    if norm_path(path, base_dir) not in owned:
        raise ValueError("이 경로는 앱이 추적하는 참조가 아니라 열 수 없습니다.")
    return path


def load_pool_item_checked(
    pool_registry: DatasetPoolRegistry, key: str
) -> DatasetReference:
    """슬롯 키로 풀 항목을 로드하되 나라(동결)·모호 시트는 시끄럽게 거절 — 웹 2소스 경계의 단일 관문.

    겨눔의 정체는 슬롯 ``key`` 다(U2 §5.3 — 이름은 중복 허용 라벨). 거절 문구는 사람이
    아는 어휘(항목 이름)로 재진술한다.

    **다중 시트 확정 게이트(#33) 재확립:** 시트를 지정하지 않은 엑셀 참조는 실행 복원 때
    ``ExcelDataSource(sheet=None)`` 이 **조용히 첫 시트**를 읽는다 — 파일 선택 경로가 #33 에서
    봉인한 바로 그 함정이 풀 경로로 재개방된 것. 워크북에 시트가 여럿이면 여기서 loud 거절해
    사용자가 데이터 선택 다이얼로그에서 시트를 지정해 다시 등록하게 한다(등록 시점 게이트가 있어도, 그
    이전에 만들어진 모호 항목까지 여기 단일 관문이 잡는다). 판정+문구·읽기 실패(죽은 참조)
    통과 정책은 :func:`~hwpxfiller.data.excel.ambiguous_sheet_error` 단일 출처(등록 게이트와
    공유 — 두 사이트의 문구 표류 봉인), 죽은 참조는 이어지는 실제 로드가 재진술.
    """
    try:
        item = pool_registry.load(key)
    except (FileNotFoundError, ValueError):
        raise ValueError("등록 데이터를 찾을 수 없습니다(이미 삭제된 항목).") from None
    if item.kind == "nara" or (
        item.kind == "pipeline" and _pipeline_has_nara_source(item.opts)
    ):
        raise ValueError(NARA_FROZEN_TEXT)
    if item.kind == "excel" and not item.opts.get("sheet"):
        err = ambiguous_sheet_error(
            str(item.opts.get("path", "")),
            prefix=f"등록 데이터 '{item.name}' 에 시트가 지정되지 않았습니다. ",
        )
        if err:
            raise ValueError(err)
    return item


# 빈 데이터 재진술 단일 출처(R-copy) — run/editor/pool 공유. "레코드"는 개발 어휘라
# 사용자 문구에선 "행"(엑셀 어휘)으로 통일한다(101 순회 F15 계열).
NO_ROWS_TEXT = "데이터에 행이 없습니다."


def load_pool_into(
    pool_registry: DatasetPoolRegistry, key: str, loader: "Callable[[DatasetReference], list]"
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
        item = load_pool_item_checked(pool_registry, key)
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
def _cross_media_refusal(name: str, old_path: str, new_media: str) -> str:
    """매체 교차 거절 문안(§10.16 판정 C) — 사전 게이트와 잠금 안 재판정이 같은 말을 한다."""
    old_label = work_mode_label(work_mode(old_path))
    new_noun = "온나라 기안 TXT" if new_media == "txt" else "HWPX"
    return (
        f"작업 '{name}' 은(는) '{old_label}' 작업이라 {new_noun} 템플릿을 "
        "연결할 수 없습니다. 작업 방식을 바꾸려면 이 작업을 삭제하고 새로 만드세요."
    )


def relink_job_template(
    job_registry, name: str, path: str, *, engine: HwpxEngine, confirm: bool = False
) -> dict:
    """작업 템플릿 참조 재지정 — run/home 공유 확정 게이트(교차-단위 계약 단일 출처).

    파일 이동/삭제로 끊긴 ``Job.template_path`` 를 새 파일로 갱신하는 유일한 durable
    뮤테이션 경로다. 에디터는 죽은 템플릿 작업을 loud 차단해 열지 못하므로(#67 결정)
    여기가 막다른길을 푸는 입구다. relink 는 **같은 매체 안의 복구 동사**다(§10.16 판정 C
    3분기): 미연결·미상 구작업의 연결은 허용(아직/이미 길이 없다 — 복구 유일 경로), 같은
    매체 재연결은 허용(#67 그대로), **매체 교차는 거절**한다 — 작업 방식은 생성 시점에
    정해져 바뀌지 않고(링0 불변식 1), `last_run_at` 의 뜻이 매체마다 달라(§19.4) 원천을
    갈아치우면 이력·순위가 거짓이 된다. 게이트 통과 뒤 검사·확인 정책:

    - **read_error = 하드 차단**: 읽을 수 없는 파일은 확인으로도 템플릿이 될 수 없다(알람).
      hwpx 는 드리프트 프로브가, txt 는 여는 계약과 같은 UTF-8 읽기가 판정한다
      (:meth:`~hwpxfiller.gui.home_state.JobRow.from_job` 의 txt_readable 과 같은 규율).
    - **구조 드리프트(hwpx) = 재진술 확인 후 허용**: 커밋해도 생성은 기존 드리프트 게이트
      (:meth:`~hwpxfiller.gui.run_state.RunViewModel` fail-closed)가 매핑 재확정 전까지
      차단하므로 안전하다. 여기서 막으면 '이동+구조 변경' 작업은 영구 복구 불능이 된다.
      txt 는 hwpx 스키마 개념인 드리프트가 없다 — 프로브에 넣으면 zip 파싱 오류로 합법
      복구가 죽는다(§10.16 후속에서 수리).
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
    # 매체 게이트 3분기(§10.16 판정 C) — 검사·확인보다 먼저, confirm 으로도 못 뚫는다.
    # 새 매체 미상은 fail-closed 거절(relink 가 unsupported 작업을 제조하지 못하게),
    # 구 매체 미상(빈 경로·.docx)은 통과 — 첫 연결(require_hwpx 「빈 경로 = 통과」 규율)과
    # 손상 복구의 유일 경로라 막으면 영구 복구 불능이 된다.
    old_media = template_media(job.template_path)
    new_media = template_media(path)
    if new_media not in ("hwpx", "txt"):
        return {
            "ok": False,
            "error": (
                "새 템플릿이 HWPX 도 온나라 기안 TXT 도 아닙니다. "
                "HWPX 또는 TXT 파일을 선택하세요."
            ),
        }
    if old_media in ("hwpx", "txt") and new_media != old_media:
        return {"ok": False, "error": _cross_media_refusal(name, job.template_path, new_media)}
    drift_clause = ""
    if new_media == "hwpx":
        drift = template_path_drift(path, job.mapping, engine=engine)
        if drift.read_error:  # has_drift 는 read_error 를 포함하므로 반드시 선판정
            return {
                "ok": False,
                "error": f"새 템플릿을 읽을 수 없습니다: {drift.read_error}",
            }
        if drift.has_drift:
            drift_clause = (
                "\n\n⚠ 새 파일의 구조가 이 작업의 확정 매핑과 다릅니다:\n"
                f"{drift.describe()}\n"
                "매핑을 다시 확정하기 전에는 생성이 차단됩니다."
            )
    else:  # txt — 여는 계약과 같은 방식(UTF-8)으로 읽고, 토큰 0 이면 에디터 픽과 같은 차단.
        try:
            text = read_text_utf8(path)
        except Exception as exc:  # noqa: BLE001 — 못 읽으면 이유 불문 하드 차단(알람)
            return {"ok": False, "error": f"새 템플릿을 읽을 수 없습니다: {exc}"}
        if not template_fields(text):  # 채울 대상 0 = hwpx RAW 동형(리뷰 2R P1) — 하드 차단
            return {"ok": False, "error": TXT_RAW_BLOCK}
    # 미상 구작업의 사용 이력은 승계하지 않는다(리뷰 5R P2): `last_run_at` 의 뜻은 매체가
    # 정하는데(§19.4) 미상 작업의 스탬프는 어느 술어로도 읽을 수 없다 — 새 매체의 사건으로
    # 재해석되면 편집기 덮어쓰기 게이트(4R)가 막는 것과 같은 위조다. 즐겨찾기는 방식 무관
    # 사용자 선호라 남기고, 검토 기준선은 규칙 지문에 결속돼 스스로 무효화된다.
    history_clause = (
        "\n\n형식을 확인할 수 없던 작업이라 최근 사용 기록은 함께 지워집니다."
        if old_media not in ("hwpx", "txt") and job.last_run_at else ""
    )
    if not confirm:
        return {
            "ok": True, "needs_confirm": True, "name": name,
            "confirm_text": (
                f"작업 '{name}' 의 템플릿 연결을 바꿉니다.\n"
                f"기존: {job.template_path or '(비어 있음)'}\n"
                f"새 파일: {path}{drift_clause}{history_clause}"
            ),
        }
    old = job.template_path
    # 확정 커밋 — durable 트랜잭션은 Application use case 가 소유한다(P2-99 #542 F-1). 위에서
    # 읽은 사본으로 통째 저장하면, 확인 왕복 사이에 다른 writer(생성 스탬프·에디터 저장·태그
    # 편집)가 남긴 변경을 낡은 값으로 되돌린다 — 확인 게이트가 있어 그 창이 사람 시간만큼
    # 길다는 점이 이 경로를 특히 위험하게 만든다. 잠금 안 매체 재판정(그 사이 다른 relink 가
    # 매체를 정했으면 이 커밋이 교차 금지를 우회한다)과 미상 이력 미승계도 그 원자 전이
    # 안이다 — 여기 남는 것은 **거절 문안 재진술**뿐이다.
    try:
        relink_template(job_registry, name, path)
    except CrossMediaRelinkError as exc:
        # 문안은 **잠금 안에서 본** 경로로 짓는다(exc.old_path) — 위 `old` 는 확인 왕복 전
        # 사본이라 경합에 진 경우 실제로 부딪힌 상대와 다르다.
        return {"ok": False, "error": _cross_media_refusal(name, exc.old_path, exc.new_media)}
    return {"ok": True, "relinked": True, "name": name, "old": old, "path": path}


class PoolTargetingMixin:
    """등록 데이터(풀) 겨눔 래퍼 공용화(K4) — ``_do_load_pool`` 화면 동형.

    예전엔 이 래퍼가 실행 표면 컨트롤러들에 독스트링('(#26/#6)')까지 복붙돼
    있었다 — 게이트 실행부(:func:`load_pool_into`)만 공용이고 래퍼는 여러 벌. 여기로 수렴하고
    화면별 차이는 두 훅으로만 남긴다:

    - :meth:`_pool_guard` — 겨눔 전제 미충족 시 사용자 문구 반환(기본 없음, run=작업 선택).
    - :meth:`_after_pool_load` — 성공 후처리(기본 no-op, run=행 선택 초기화).

    요구 표면: ``pool_registry``·``vm.load_pool_item``·``data_label``·``data_source``·
    ``data_path``/``data_sheet``(:class:`~hwpxfiller.webapp.data_zone.DataZoneMixin` 소유).
    """

    pool_registry: DatasetPoolRegistry
    data_label: str
    data_source: str  # ''(미겨눔) | 'file' | 'pool' — 라벨은 source_label 이 합성(K8)
    # 겨눈 풀 슬롯 키(U2 §5.3) — 라벨은 개명 자유라 세션이 참조 정체를 따로 든다.
    data_pool_key: str = ""

    def _pool_guard(self) -> "str | None":
        """겨눔 전제조건 검사 — 미충족이면 사용자 문구, 충족이면 None."""
        return None

    def _after_pool_load(self, records: list) -> None:
        """겨눔 성공 후 화면별 후처리(행 선택 초기화 등). 기본 no-op."""

    def _pool_loader(self):
        """겨눔 로더 — 기본은 링1 VM(작업-앵커 화면). 세션 소유 화면(데이터-우선 「작업」)은
        vm 없이도 겨눌 수 있게 재정의한다."""
        return self.vm.load_pool_item

    def _do_load_pool(self, p: dict) -> dict:
        """등록 데이터 항목을 슬롯 키로 겨눔 — 공유 관문(:func:`load_pool_into`)에 위임.

        겨눔의 정체는 ``key`` 다(U2 §5.3 — 이름은 중복 허용 라벨이라 같은 이름 2건을
        구별하지 못한다). 실패는 raise 대신 오류 dict 재진술(웹이 모달 안에서 그대로
        표시) — generate 계열과 같은 문법. 성공 시 라벨은 스냅샷이 소스 플래그로 합성해
        반영한다(K8).
        """
        blocked = self._pool_guard()
        if blocked:
            return {"ok": False, "error": blocked}
        key = p["key"]
        res = load_pool_into(self.pool_registry, key, self._pool_loader())
        if not res["ok"]:
            return res
        item = res["item"]
        self.data_label = item.name
        self.data_source = "pool"
        self.data_pool_key = key
        # 마운트 대상 재진술(F1, 구 data_track_path 승계) — 출처가 pool 이면 「이 데이터 고정」은 뜨지 않지만(이미 고정된
        # 참조), 「현재 데이터」 구획이 경로·확정 시트를 말할 수 있어야 한다. kind 판정은
        # DatasetPoolRow.locate_path 와 동형(excel 만 파일 경로 — opts["path"]만 보면 두 사이트의
        # 판정이 표류한다, PR #70 리뷰).
        raw = item.opts.get("path") if isinstance(item.opts, dict) else None
        self.data_path = raw if (item.kind == "excel" and isinstance(raw, str)) else ""
        raw_sheet = item.opts.get("sheet") if isinstance(item.opts, dict) else None
        self.data_sheet = raw_sheet if isinstance(raw_sheet, str) else ""
        # 헤더 행도 **같은 시점에** 포획한다(#349 리뷰 2R) — 참조 성분을 나중에 슬롯에서
        # 다시 읽으면, 그사이 「다시 연결」된 슬롯이 지금 화면에 없는 데이터를 답한다.
        # 형이 깨진 값은 추측해 고치지 않고 어댑터 기본(0)으로 둔다.
        raw_hdr = item.opts.get("header_row") if isinstance(item.opts, dict) else None
        self.data_header_row = (
            raw_hdr if self.data_path and isinstance(raw_hdr, int)
            and not isinstance(raw_hdr, bool) and raw_hdr > 0 else 0
        )
        self._after_pool_load(res["records"])
        return {"ok": True, "label": source_label("pool", item.name)}


class ScreenController(Protocol):
    """브리지가 라우팅하는 화면 컨트롤러 표면. 새 화면 = 이 표면 구현 + 등록."""

    name: str

    def initial(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def dispatch(self, action: str, payload: dict) -> object: ...  # 값 반환 가능(예: 확인 게이트)
