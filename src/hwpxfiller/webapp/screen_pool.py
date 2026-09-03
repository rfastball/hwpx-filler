"""등록 데이터(데이터셋 풀) 컨트롤러 — **화면 없는** 상태 소유자(webview 비의존).

웹 패리티 회수(#26 단위 A, #4). Application VM 을 **그대로 임포트**해 구동한다: 풀 항목
목록·상태 배지·상태별 게이트 액션(보관/활성화/삭제)·참조 등록은
:class:`~hwpxfiller.application.dataset_pool.DatasetPoolViewModel`(Qt-free)가 소유한다.
표현 계층(카드 렌더·확인 라운드트립)만 웹(js/data_picker.js)으로 이식한다 — VM 로직
재구현이 아니다.

**정체성 = 경로+시트, 이름 = 라벨**(U2 §5.3 판정 C, #347): 항목 조작은 슬롯 ``key`` 로,
중복 판정은 정체성으로 한다. 종전의 「동명 재등록 = 참조 재지정」 확인 게이트는 **정체성
재편으로 소멸**했다 — 같은 데이터의 재등록은 참조가 바뀔 수 없고(정체성이 곧 참조) 라벨·
메모 갱신일 뿐이다. 조용한 durable 소실을 막는 confirm-or-alarm 경계는 이렇게 바뀐다:

- 삭제는 파괴이므로 확인 라운드트립(1차=재진술, 2차=삭제) — tpl ``_do_txt_delete`` 미러.
- **같은 데이터 재등록은 라벨 갱신 확정**: 기존 이름을 재진술하고 확인 후 갱신한다.
  아무것도 안 바뀌는 재등록(같은 이름·빈 메모)은 「이미 고정돼 있습니다」로 조용히 성사.
- **구판 마이그레이션의 병합**: 다른 이름·같은 경로 2건(이름=키 시절의 잔재)은 조용히
  하나 버리지 않고 스냅샷 ``duplicates`` 로 표면화, 남길 1건을 사용자가 확정한 뒤에만
  나머지를 삭제한다(``resolve_duplicate`` — 무손실이 아니므로 자동 병합 금지).

**확정 결속(코덱스 2R·3R 근본 조치, P2-22 #570 하강)**: 이 컨트롤러의 **파괴·덮어쓰기
확정 왕복 넷**(``delete`` · ``register_excel`` 의 라벨 갱신 · ``relink`` ·
``resolve_duplicate``)은 전부 **1차가 보여준 상태의 지문**
(:func:`~hwpxfiller.application.dataset_pool.confirm_basis`)에 결속된다. 1차 응답이
``basis`` 를 발행하고 확정이 그대로 되실어 보내면, 저장 어댑터가 쓰기 잠금 안에서 지금
상태의 지문을 다시 지어 대조한다 — 다르거나 미동봉이면 **삭제·덮어쓰기 0건 +
:class:`~hwpxfiller.application.dataset_pool.StaleConfirmError`** 이고, 여기는 그 거절을
loud 재진술한다(판정·수치는 Application·어댑터, 문안·확인 UI 는 이 층).

결속 단위가 키가 아니라 :func:`~hwpxfiller.application.dataset_pool.bound_state` 의
**값 전체**인 이유는 라운드마다 같은 구멍의 다른 조각이 드러났기 때문이다: 멤버가
늘어도(1R), 멤버의 이름·비고가 바뀌어도(2R P1), 다시 연결 대상이 갈려도(2R P2), 경로만
다른 동명 파일로 재연결돼도(3R P2-1), 라벨 갱신 대상의 메타가 바뀌어도(3R P2-2) 사용자가
승인한 것은 **그때 읽은 값**이다. 그래서 ⑴ 재료는 표시 요약이 아니라 정체를 정하는 전체
값이고(요약은 정보를 버리는 함수라 결속에 부적합) ⑵ 네 경로가 기제 하나를 공유한다 —
성분을 개별로 더하거나 경로마다 따로 만들면 다음 라운드에 또 샌다.

**스코프 경계(조용히 빠뜨리지 않고 명시)**: 나라장터 참조 **등록**은 웹에 노출하지 않는다
(동결 결정 2026-07-16 — 내부망 API 미확인, ServiceKey 웹 표면 부재). 단 풀에 이미 있는
nara 항목은 숨기지 않고 그대로 표시한다(도메인 seam ``register_nara`` 는 보존, 배선만 유보).
**계약 목록(pclm) 은 동결이 아니다**(ADR N): 나라 동결의 근거는 실 API·비밀값이었고 pclm 은
네트워크도 비밀도 없는 **로컬 파일 소비자**라 그 근거가 닿지 않는다 — 두 종류를 「외부
소스」로 뭉뚱그려 같은 유보에 넣지 않는다. 이 화면이 지는 것은 **스냅샷**(등록 폼이 물어야
할 기본 DB 자리와 뷰 전수)과 **등록 액션**(:meth:`PoolController._do_register_pclm`)이고,
둘은 폼(``#dataPickerPclm`` → ``#poolRegModal`` pclm 모드)과 **한 계약 변경**으로 함께 섰다
— 프런트 호출자 없는 액션 등록은 단방향 배선이라 저장소가 거절한다
(``tests/repo_contract/test_blocker_affordance_registry.py``). 판정·문안은 링1
(:meth:`~hwpxfiller.application.dataset_pool.DatasetPoolViewModel.register_pclm`)이 소유하고
여기는 그 거절을 재진술만 한다.
"""
from __future__ import annotations

from ..application.dataset_pool import (
    BOUND_FIELDS,
    DatasetPoolPort,
    DatasetPoolViewModel,
    StaleConfirmError,
    available_actions,
    bound_state,
    confirm_basis,
    kind_transition_clause,
    reference_summary,
    resolve_pclm_db,
)
from ..data.excel import ambiguous_sheet_error  # 다중 시트 확정 게이트 판정+문구(#33)
from ..domain.dataset_reference import DatasetReference, pclm_identity
from ..domain.pclm_views import (
    PCLM_DOC_VIEWS,
    PCLM_VIEW_DESCS,
    PCLM_VIEW_TITLES,
    PCLM_VIEWS,
    default_pclm_db,
)
from .pool_column import POOL_ICONS, pool_column_view, pool_row_view
from .screens import PushSink

__all__ = [
    "BOUND_FIELDS",
    "PoolController",
    "bound_state",
    "confirm_basis",
    "display_reference",
]


def display_reference(item: DatasetReference) -> str:
    """재진술 문안에 쓰는 **표시용** 참조 요약 — 결속 재료가 아니다(모듈 독스트링 참조)."""
    return reference_summary(item)


def _row_icon(kind: str) -> str:
    """참조 종류 → 고르기 열 행 표지(:data:`~hwpxfiller.webapp.pool_column.POOL_ICONS`).

    자기 표지가 없는 종류(조립 파이프라인)와 손편집이 남긴 미지 종류는 ``other`` 로 선다 —
    다른 표지로 접으면 화면이 거짓말을 하고, 거절로 존을 죽이면 그 행이 **숨겨진다**.
    고를 수 없다는 사실과 그 사유는 이미 행의 ``reason`` 이 진다.
    """
    return kind if kind in POOL_ICONS else "other"


class PoolController:
    """등록 데이터 수명 — 데이터셋 풀 VM 위임(webview 비의존).

    **소비 표면은 데이터 선택 다이얼로그**(`frontend/js/data_picker.js`)다 — 「데이터 관리」
    화면은 F1 에서 죽었고 이 컨트롤러만 살아남아 그 다이얼로그가 스냅샷·액션을 소비한다.
    """

    name = "pool"

    def __init__(
        self,
        registry: DatasetPoolPort,
        push: PushSink,
    ) -> None:
        self._push_sink = push
        # 레지스트리는 composition root(webapp.app)가 주입한다 — 자기 생성 폴백은 #570 에서
        # 제거됐다(locator 뒷문 금지: 기본값이 있으면 링2 가 구체 저장을 조용히 재선택한다).
        self.vm = DatasetPoolViewModel(registry)
        # 마지막 결과 문구(등록·전이·삭제) — 성과별 심각도 채널(UD-07, tpl 미러).
        self.result_text = ""
        self.result_level = "muted"

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _set_result(self, text: str, level: str = "ok") -> None:
        self.result_text = text
        self.result_level = level

    # ------------------------------------------------------------- 스냅샷
    def _rows(self) -> "list[dict]":
        return [self._row(r) for r in self.vm.rows()]

    def _row(self, r) -> dict:
        reason = r.select_block_reason()
        return {
            "key": r.key,  # 슬롯 키(§5.3) — 행동(사용·보관·활성화·삭제·다시 연결)의 겨눔 대상
            "name": r.name,
            "kind": r.kind,
            "kind_label": r.kind_label,
            "status": r.status,
            "badge_label": r.badge_label,
            "badge_level": r.badge_level,
            "reference": r.reference,
            "locate_path": r.locate_path,  # 추적성 로케이트(#53-B) — 엑셀 파일 경로
            "sheet": r.sheet,  # 다시 연결 프리필(#67)
            # 참조 끊김(#67) — 파일이 이동/삭제된 엑셀 참조를 배지로 표면화한다.
            # 판정은 공유 술어(U3-07 #880) — 부팅 자동 마운트가 같은 것을 본다.
            "missing": r.missing,
            "note": r.note,
            # **과도기 목록**이다: 이 옛 키의 소비자(현 `pool_list.ts`)는 「다시 연결…」을
            # 아직 자기 판정으로 덧붙이므로, 여기에 링1 의 전수 목록을 실으면 그 화면에
            # 같은 버튼이 둘 선다. 그래서 옛 키는 **상태표 그대로**를 유지하고, 전수 목록은
            # 아래 `column` 존이 든다 — 웹이 그 존으로 옮겨 갈 때(슬라이스 ③) 이 키와 함께
            # 웹의 덧붙임도 사라진다.
            "actions": [
                {"key": a.key, "label": a.label} for a in available_actions(r.status)
            ],
            # 「이 데이터를 작업에 쓸 수 있는가」 + 사유 — 판정 자리는 하나다(U6-B #976).
            "selectable": not reason,
            "select_block_reason": reason,
        }

    # ------------------------------------------------- 고르기 열 공용 존(슬라이스 ①)
    def _column_rows(self) -> "list[dict]":
        """우 열 행 — 형은 :mod:`~hwpxfiller.webapp.pool_column` 이 소유한다.

        ``sub`` 는 참조 요약이고 메모가 있으면 병기한다: 메모는 사람이 그 등록을 가르려고
        적은 것이라 목록에서 지우면 같은 파일을 가리키는 두 등록이 한 줄로 보인다.
        """
        rows: "list[dict]" = []
        for r in self.vm.rows():
            sub = f"{r.reference} · {r.note}" if r.note else r.reference
            rows.append(pool_row_view(
                key=r.key,
                name=r.name,
                sub=sub,
                reason=r.select_block_reason(),
                badge_label=r.badge_label,
                badge_level=r.badge_level,
                icon=_row_icon(r.kind),
                path=r.locate_path,
                actions=[{"key": a.key, "label": a.label} for a in r.actions()],
            ))
        return rows

    def _column_notices(self) -> "list[dict]":
        """존 통지 — 손상 격리(danger)와 중복 등록(warn). **문안은 여기가 짓는다**.

        종전에는 두 문장 다 웹 리터럴이었다(``pool_list.ts``). 좌·우 열이 한 컴포넌트가
        되는 이상 통지도 한 층에서 나와야 한다 — 수치(``{n}건``)를 든 문장이 표면에 있으면
        판정과 문안이 갈린 채 늙는다. 중복 통지의 동사는 그 자리에 함께 세운다: 「골라
        정리하세요」라고 말하면서 고를 자리가 없으면 사람이 지시를 실행할 수 없다.
        """
        notices: "list[dict]" = [
            {
                "level": "danger",
                "text": f"⚠ 손상된 등록 데이터: {entry.file_name} — {entry.error}",
                "actions": [],
            }
            for entry in self.vm.corrupted()
        ]
        for group in self.vm.duplicates():
            notices.append({
                "level": "warn",
                "text": (
                    f"같은 데이터({group[0].reference})를 가리키는 등록이 "
                    f"{len(group)}건입니다. 남길 등록을 골라 정리하세요."
                ),
                "actions": [
                    {
                        "key": "resolve_duplicate",
                        "label": f"'{row.name}' 남기기",
                        # payload 키는 `pool/resolve_duplicate` 스키마 그대로(`keep`).
                        "payload": {"keep": row.key},
                    }
                    for row in group
                ],
            })
        return notices

    def _corrupted_rows(self) -> "list[dict]":
        """격리된 손상 파일을 웹이 시끄럽게 표면화할 행으로(RC-05 — 조용한 은닉 금지)."""
        return [
            {"file": entry.file_name, "error": entry.error}
            for entry in self.vm.corrupted()
        ]

    def _duplicate_groups(self) -> "list[dict]":
        """같은 데이터(경로+시트) 등록 2+건 — 구판(이름=키) 마이그레이션의 병합 대상(§5.3).

        조용히 하나 버리지 않는다: 그룹째 표면화하고 남길 1건의 확정(``resolve_duplicate``)
        을 기다린다. 각 항목은 여전히 목록 행으로도 산다(숨김 금지 — 병합 전에도 쓸 수 있다).
        """
        return [
            {
                "reference": group[0].reference,
                "entries": [{"key": r.key, "name": r.name} for r in group],
            }
            for group in self.vm.duplicates()
        ]

    def _pclm_block(self) -> dict:
        """계약 목록 등록 폼이 물어야 할 것 — 기본 DB 자리와 **고르게 할 뷰**, 그리고 제목표.

        웹이 뷰 목록을 리터럴로 들지 않는다: 허용목록도 그 문안도 링0 단일 출처
        (:mod:`hwpxfiller.domain.pclm_views`)이고, 여기 스냅샷은 그 값을 옮기기만 한다 —
        표면이 목록을 복제하면 뷰가 늘거나 문안이 갈릴 때 한쪽만 늙는다.

        두 목록이 **다른 일**을 한다: ``views`` 는 새로 고를 수 있는 것
        (:data:`~hwpxfiller.domain.pclm_views.PCLM_DOC_VIEWS`)이고, ``titles`` 는 이미 선
        마운트를 이름 대신 제목으로 그리기 위한 **뷰 전수** 매핑이다. 후자를 좁히면 CLI 로
        등록한 품목 마운트가 카드에서 내부 이름(``v_품목_v1``)으로 새 나간다.
        """
        return {
            "default_db": str(default_pclm_db()),
            "views": [
                {"name": v, "title": PCLM_VIEW_TITLES[v], "desc": PCLM_VIEW_DESCS[v]}
                for v in PCLM_DOC_VIEWS
            ],
            "titles": {v: PCLM_VIEW_TITLES[v] for v in PCLM_VIEWS},
        }

    def snapshot(self) -> dict:
        return {
            "rows": self._rows(),
            "count": self.vm.count_label(),
            "empty": self.vm.is_empty(),
            "corrupted": self._corrupted_rows(),
            "duplicates": self._duplicate_groups(),
            "pclm": self._pclm_block(),
            "result": {"text": self.result_text, "level": self.result_level},
            # 고르기 우 열(슬라이스 ①) — 좌 열(`tpl` 채널)과 **같은 형**이다. 위의 옛 키들은
            # 웹이 이 존으로 옮겨 갈 때(슬라이스 ③)까지 그대로 산다.
            "column": pool_column_view(
                rows=self._column_rows(),
                notices=self._column_notices(),
                empty_hint=self.vm.empty_hint(),
                count_label=self.vm.count_label(),
                result={"text": self.result_text, "level": self.result_level},
            ),
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 pool 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_refresh(self, p: dict) -> None:
        """풀 재스캔 — 다른 표면(CLI 등록 등)의 변경을 되읽는다."""
        self.vm.refresh()

    # ---- 상태 전이(비파괴 — 확인 없이 즉시, 되돌림 가능)
    def _stale_item_result(self, label: str) -> dict:
        """stale 카드 공통 처리(C7) — 다른 표면(CLI·에디터 등)에서 삭제된 항목의 카드를
        누르면 FileNotFoundError 가 웹으로 새어 버튼이 무반응이 된다. 조용한 무반응 대신
        loud 재진술 + 재스캔으로 화면을 실상에 맞춘다(confirm-or-alarm)."""
        self.vm.refresh()
        msg = f"등록 데이터를 찾을 수 없습니다(이미 삭제된 항목): {label}. 목록을 새로 읽었습니다."
        self._set_result(msg, "danger")
        return {"ok": False, "error": msg}

    def _stale_basis_result(self) -> dict:
        """확정 결속 거절의 재진술 — 어댑터의 :class:`StaleConfirmError` 를 사용자 문구로.

        승인의 대상은 「그때 읽은 값」이다. 근거 미동봉(구식 호출)도 같은 거절이다 —
        무엇을 승인했는지 모르는 확정으로는 지우거나 덮을 수 없다(fail-closed). 호출측은
        이 결과 전에 :meth:`DatasetPoolViewModel.refresh` 를 마친다 — 재확인의 근거는
        새 상태다.
        """
        msg = (
            "확인하는 사이 이 데이터의 등록 상태가 바뀌어 실행하지 않았습니다. "
            "목록을 새로 읽었으니 다시 확인해 주세요."
        )
        self._set_result(msg, "danger")
        return {"ok": False, "error": msg}

    def _row_name(self, key: str) -> str:
        """키 → 표시 라벨(결과 문구용). 못 찾으면 키 자체(추측 금지 — 키도 사실이다)."""
        row = next((r for r in self.vm.rows() if r.key == key), None)
        return row.name if row is not None else key

    def _do_archive(self, p: dict) -> dict:
        name = self._row_name(p["key"])
        try:
            self.vm.archive(p["key"])
        except FileNotFoundError:
            return self._stale_item_result(name)
        self._set_result(f"데이터셋을 보관했습니다: {name}")
        return {"ok": True}

    def _do_activate(self, p: dict) -> dict:
        name = self._row_name(p["key"])
        try:
            self.vm.activate(p["key"])
        except FileNotFoundError:
            return self._stale_item_result(name)
        self._set_result(f"데이터셋을 활성화했습니다: {name}")
        return {"ok": True}

    # ---- 삭제(파괴 — 확인 라운드트립, tpl _do_txt_delete 미러)
    def _do_delete(self, p: dict) -> dict:
        """참조 삭제 — 1차=재진술, 확정=**보여준 상태의 지문 대조 후** 삭제.

        삭제도 다른 셋과 같은 결속을 쓴다(3R 인구조사): 확인 모달이 열린 사이 다른 호출이
        이 슬롯을 재연결·개명하면, 사용자가 승인한 것은 옛 이름·옛 참조의 등록인데 지워지는
        것은 지금 것이다 — 파괴 앞에서 「무엇을 지우는지」가 갈리면 그게 곧 조용한 파괴다.
        """
        key = p["key"]
        try:
            item, basis = self.vm.inspect(key)
        except (FileNotFoundError, ValueError):
            return self._stale_item_result(self._row_name(key))
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "key": key,
                "basis": basis,
                "confirm_text": (
                    f"등록 데이터 참조를 삭제합니다(원본 파일은 지우지 않습니다):\n"
                    f"{item.name} ({display_reference(item)})"
                ),
            }
        try:
            deleted = self.vm.delete_confirmed(key, basis=p.get("basis"))
        except StaleConfirmError:
            self.vm.refresh()
            return self._stale_basis_result()
        except FileNotFoundError:
            return self._stale_item_result(self._row_name(key))
        self._set_result(f"데이터셋 참조를 삭제했습니다: {deleted.name}")
        return {"ok": True}

    # ---- 등록(참조만 — 경로 포인터, 스냅샷·데이터 없음)
    def _do_register_excel(self, p: dict) -> dict:
        """엑셀/CSV 참조 등록 — 중복 판정은 **정체성**(경로+시트, §5.3 C)이다.

        - 같은 데이터 미등록 → 새 항목 추가.
        - 같은 데이터가 이미 있고 **바뀌는 게 없으면**(같은 이름·빈 메모) → 「이미
          고정돼 있습니다」 성사(확인 소음 금지 — 결정이 없다).
        - 같은 데이터가 이미 있고 이름·메모가 바뀌면 → 기존 이름을 재진술하고 확인 후
          **라벨 갱신**(참조·수명 불변 — 종전 「참조 재지정」 위험은 정체성 재편으로 소멸).

        라벨 갱신 확정도 **같은 결속 기제**를 쓴다(코덱스 3R P2-2): 확인 모달이 열린 사이
        다른 호출이 같은 등록의 이름·비고를 바꾸면, 정체성(path+sheet)만 확인하는 확정은
        더 새로운 메타데이터를 무조건 덮는다 — 사용자가 승인한 것은 1차가 보여준 **옛
        라벨**이다. 대조부터 갱신까지는 어댑터의 한 쓰기 잠금 안이다
        (:meth:`~hwpxfiller.application.dataset_pool.DatasetPoolViewModel.relabel_confirmed`).

        검증 실패(빈 이름 등 ValueError)는 날것 예외로 웹에 새지 않게 잡아 사용자 문구로
        재진술한다 — 실패가 조용하지도, 기술적이지도 않게.
        """
        name = (p.get("name") or "").strip()
        path = p.get("path") or ""
        sheet = p.get("sheet") or None
        note = p.get("note") or ""
        # 다중 시트 확정 게이트(#33) — 시트 미지정 참조는 실행 복원 때 첫 시트를 조용히 읽는다.
        # 워크북에 시트가 여럿이면 등록을 막고 시트 지정을 요구한다. 판정+문구·읽기 실패(파일
        # 미개봉 참조 의미) 통과 정책은 ambiguous_sheet_error 단일 출처 — 겨눔 시점 단일 관문과 공유.
        if path and sheet is None:
            msg = ambiguous_sheet_error(path)
            if msg:
                self._set_result(msg, "danger")
                return {"ok": False, "error": msg}
        try:
            same = self.vm.find_same_data(path, sheet) if path else None
            if same is not None:
                key, existing = same
                changes_name = bool(name) and name != existing.name
                changes_note = bool(note) and note != existing.note
                if not changes_name and not changes_note:
                    # 결정이 남지 않은 재등록 — 사실만 재진술하고 성사로 접되, 보고도
                    # 잠금 안 재검증을 지난다(코덱스 #578 P2): find 스냅샷만으로 성사를
                    # 말하면 확인 사이 다른 스레드의 삭제가 거짓 「이미 고정」을 만든다.
                    # 같은 값 재라벨은 무변경 멱등 확정이라 관측 의미가 같고, 동시
                    # 삭제는 FileNotFoundError(아래 stale 접기)로, 동시 메타 변경은
                    # StaleConfirmError 로 정직하게 갈린다.
                    try:
                        item = self.vm.relabel_confirmed(
                            path, sheet, existing.name, note="",
                            basis=confirm_basis([bound_state(key, existing)]),
                        )
                    except StaleConfirmError:
                        self.vm.refresh()
                        return self._stale_basis_result()
                    self._set_result(
                        f"이미 고정돼 있습니다: {item.name} "
                        f"({display_reference(item)})"
                    )
                    return {"ok": True, "key": key, "name": item.name}
                if not p.get("confirm"):
                    return {
                        "ok": True, "needs_confirm": True, "key": key, "name": name,
                        # 승인 대상 = 지금 이 등록의 라벨·비고·참조·수명 전부.
                        "basis": confirm_basis([bound_state(key, existing)]),
                        "confirm_text": (
                            f"이 데이터는 이미 '{existing.name}' 으로 고정돼 있습니다"
                            f"({display_reference(existing)}).\n"
                            f"같은 등록을 유지하고 이름·메모를 갱신합니다: '{name}'."
                        ),
                    }
                try:
                    item = self.vm.relabel_confirmed(
                        path, sheet, name, note=note, basis=p.get("basis")
                    )
                except StaleConfirmError:
                    self.vm.refresh()
                    return self._stale_basis_result()
            else:
                if p.get("confirm"):
                    # 확인 모달은 "기존 등록 갱신"에 대한 승인이다. 모달을 읽는 사이 다른
                    # 화면이 항목을 삭제했다면 이를 신규 등록 승인으로 바꾸지 않는다.
                    return self._stale_item_result(name)
                item = self.vm.register_excel(name, path, sheet=sheet, note=note)
        except FileNotFoundError:
            # 분류 직후~어댑터 잠금 획득 사이 삭제된 경우도 신규 등록으로 부활시키지 않는다.
            return self._stale_item_result(name)
        except ValueError as exc:
            self._set_result(str(exc), "danger")
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            # 저장 자체의 실패(디스크·권한·경로 점유 등) — 날것 예외로 웹에 새면 unhandled
            # rejection 으로 삼켜질 수 있다(C7). 결과줄 문구로 loud 재진술한다.
            msg = f"등록 데이터 저장에 실패했습니다: {exc}"
            self._set_result(msg, "danger")
            return {"ok": False, "error": msg}
        verb = "갱신" if same is not None else "추가"
        self._set_result(f"등록 데이터를 {verb}했습니다: {item.name} ({display_reference(item)})")
        return {"ok": True, "name": item.name}

    def _do_register_pclm(self, p: dict) -> dict:
        """계약 목록(pclm) 참조 등록 — 엑셀 등록의 거울. 중복 판정은 **정체성**(DB+뷰)이다.

        세 분기와 그 근거는 :meth:`_do_register_excel` 과 같다(신규 추가 / 무변경 재등록의
        멱등 확정 / 이름·메모 변경의 라벨 갱신 확정). 갈리는 것은 좌표뿐이다: 엑셀이
        경로+시트로 겨누는 자리를 여기는 DB+뷰로 겨눈다 — 그래서 확정 왕복은 종류를 묻지
        않는 정체성 판(:meth:`~hwpxfiller.application.dataset_pool.DatasetPoolViewModel.
        relabel_confirmed_raw`)을 쓴다(결속 규율 자체는 한 벌이다).

        빈 ``db`` 는 「기본 자리」라는 뜻이라 조회 **전에** 해석한다
        (:func:`~hwpxfiller.application.dataset_pool.resolve_pclm_db`) — 조회와 등록이 다른
        자리를 보면 같은 데이터가 2건이 된다. 뷰 검증은 링1 이 소유하고 여기는 그 거절을
        재진술만 한다(다중 시트 게이트가 엑셀 등록에 서는 자리의 대응물).
        """
        name = (p.get("name") or "").strip()
        db = resolve_pclm_db(str(p.get("db") or ""))
        view = str(p.get("view") or "")
        note = p.get("note") or ""
        try:
            same = self.vm.find_same_pclm(db, view)
            if same is not None:
                key, existing = same
                changes_name = bool(name) and name != existing.name
                changes_note = bool(note) and note != existing.note
                ident = pclm_identity(db, view)
                if not changes_name and not changes_note:
                    # 결정이 남지 않은 재등록 — 사실만 재진술하고 성사로 접되, 보고도 잠금
                    # 안 재검증을 지난다(엑셀 판과 같은 근거, 코덱스 #578 P2).
                    try:
                        item = self.vm.relabel_confirmed_raw(
                            ident, existing.name, note="",
                            basis=confirm_basis([bound_state(key, existing)]),
                        )
                    except StaleConfirmError:
                        self.vm.refresh()
                        return self._stale_basis_result()
                    self._set_result(
                        f"이미 고정돼 있습니다: {item.name} "
                        f"({display_reference(item)})"
                    )
                    return {"ok": True, "key": key, "name": item.name}
                if not p.get("confirm"):
                    return {
                        "ok": True, "needs_confirm": True, "key": key, "name": name,
                        "basis": confirm_basis([bound_state(key, existing)]),
                        "confirm_text": (
                            f"이 데이터는 이미 '{existing.name}' 으로 고정돼 있습니다"
                            f"({display_reference(existing)}).\n"
                            f"같은 등록을 유지하고 이름·메모를 갱신합니다: '{name}'."
                        ),
                    }
                try:
                    item = self.vm.relabel_confirmed_raw(
                        ident, name, note=note, basis=p.get("basis")
                    )
                except StaleConfirmError:
                    self.vm.refresh()
                    return self._stale_basis_result()
            else:
                if p.get("confirm"):
                    # 확인 모달은 「기존 등록 갱신」에 대한 승인이다 — 그 사이 항목이
                    # 사라졌다고 신규 등록 승인으로 바꾸지 않는다.
                    return self._stale_item_result(name)
                item = self.vm.register_pclm(name, db, view=view, note=note)
        except FileNotFoundError:
            return self._stale_item_result(name)
        except ValueError as exc:  # 빈 이름·미지 뷰·정체성 중복 백스톱 — 사용자 문구로
            self._set_result(str(exc), "danger")
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            msg = f"등록 데이터 저장에 실패했습니다: {exc}"
            self._set_result(msg, "danger")
            return {"ok": False, "error": msg}
        verb = "갱신" if same is not None else "추가"
        self._set_result(f"등록 데이터를 {verb}했습니다: {item.name} ({display_reference(item)})")
        return {"ok": True, "name": item.name}

    # ---- 다시 연결(#67 → §5.3 키 재편) — 같은 슬롯의 참조 교체(수명 보존)
    def _do_relink(self, p: dict) -> dict:
        """끊긴(또는 갈아탈) 참조를 새 파일로 — **슬롯을 유지**한 채 kind+opts 만 바꾼다.

        내용물 교체가 이 개체의 정상 수명 사건이라(§5.3 — 월별 파일 갈아끼우기) 정체성이
        바뀌어도 슬롯·상태·생성시각은 산다. 종전엔 동명 재등록 confirm 경로가 이 일을
        겸했지만, 중복 판정이 정체성 기준이 되며 갈라졌다: 재등록은 「같은 데이터인가」를,
        여기는 「이 슬롯이 무엇을 가리키게 할 것인가」를 판정한다. 확정 전 1차 호출은
        기존→새 참조(+이름 변경·kind 전이)를 재진술한다(durable 뮤테이션 확인 1회).

        확정은 **1차가 보여준 슬롯 상태의 지문**(``basis``)에 결속된다(코덱스 2R P2):
        모달이 열린 사이 다른 호출이 같은 슬롯을 재연결·개명하면 정체성 검사는 통과하므로,
        결속이 없으면 사용자가 본 적 없는 더 새로운 참조를 덮어쓴다. 대조부터 변이까지는
        어댑터의 한 쓰기 잠금 안이라 그 사이에 다른 writer 가 끼지 못한다.
        """
        key = p["key"]
        path = p.get("path") or ""
        sheet = p.get("sheet") or None
        note = p.get("note") or ""
        name = (p.get("name") or "").strip()
        if not path:
            msg = "새 파일 경로가 비어 있습니다."
            self._set_result(msg, "danger")
            return {"ok": False, "error": msg}
        if sheet is None:  # 다중 시트 확정 게이트(#33) — 등록 경로와 같은 단일 출처
            msg = ambiguous_sheet_error(path)
            if msg:
                self._set_result(msg, "danger")
                return {"ok": False, "error": msg}
        if not p.get("confirm"):
            try:
                item, basis = self.vm.inspect(key)
            except (FileNotFoundError, ValueError):
                return self._stale_item_result(name or key)
            rename_clause = (
                f"\n이름도 '{item.name}' → '{name}' 으로 바뀝니다."
                if name and name != item.name else ""
            )
            return {
                "ok": True, "needs_confirm": True, "key": key,
                # 승인 대상 = 이 슬롯의 지금 상태(정체성·참조 원본·이름·비고·수명).
                "basis": basis,
                # 문안은 **표시 요약**을 쓴다(사람이 읽는 자리) — 결속은 그보다 정보를
                # 덜 잃는 재료로 따로 짓는다(3R P2-1: 요약은 basename 으로 줄인다).
                "confirm_text": (
                    f"'{item.name}' 의 참조를 새 파일로 바꿉니다.\n"
                    f"기존: {display_reference(item)}\n새 파일: {path}"
                    f"{kind_transition_clause(item)}{rename_clause}"
                ),
            }
        try:
            updated = self.vm.relink_confirmed(
                key, path, sheet=sheet, note=note, name=name, basis=p.get("basis")
            )
        except StaleConfirmError:
            self.vm.refresh()   # 화면을 실상에 — 재확인의 근거는 새 상태다
            return self._stale_basis_result()
        except FileNotFoundError:
            return self._stale_item_result(name or key)
        except ValueError as exc:  # 새 참조가 다른 슬롯의 정체성과 겹침 등 — loud
            self._set_result(str(exc), "danger")
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            msg = f"등록 데이터 저장에 실패했습니다: {exc}"
            self._set_result(msg, "danger")
            return {"ok": False, "error": msg}
        self._set_result(
            f"참조를 다시 연결했습니다: {updated.name} ({reference_summary(updated)})"
        )
        return {"ok": True, "name": updated.name}

    # ---- 구판 병합(§5.3 마이그레이션 — 무손실 아님, 사용자 확정으로만)
    def _gone_group_result(self) -> dict:
        msg = "병합할 중복 등록이 더는 없습니다. 목록을 새로 읽었습니다."
        self._set_result(msg, "danger")
        return {"ok": False, "error": msg}

    def _do_resolve_duplicate(self, p: dict) -> dict:
        """같은 데이터 등록 그룹에서 남길 1건 확정 → 나머지 삭제(확인 라운드트립).

        1차 호출은 **무엇이 남고 무엇이 지워지는지**를 재진술만 하고, 그 재진술이 겨눈
        상태의 지문(``basis``)을 함께 돌려준다 — 이름·메모가 다른 등록들을 지우는 파괴라
        조용한 자동 병합은 금지다(confirm-or-alarm).

        확정(2차)은 **사용자가 읽고 승인한 그 상태**와 지금 디스크를 대조한다. 결속 단위가
        멤버 **키 집합**이면 부족하다는 것이 라운드들의 교훈이다: 멤버가 늘면 고지 없는
        등록이 drop 에 섞이고(1R P1), 키는 그대로인 채 멤버의 **이름·비고**만 바뀌면
        사용자가 본 적 없는 내용의 등록이 지워진다(2R P1). 그래서 지문은
        :func:`~hwpxfiller.application.dataset_pool.bound_state` 의 값 전체를 덮고,
        어긋나면 어댑터가 아무것도 지우지 않은 채 거절한다 — 승인한 문안과 실제로 일어나는
        일이 갈리는 것이 이 저장소의 지배 결함류다(에디터 덮어쓰기 게이트의
        ``confirmed_overwrite_text`` 대조와 동형).
        """
        keep = p["keep"]
        if not p.get("confirm"):
            # 재진술의 소재는 목록과 **같은 스캔**의 디스크 항목이다(3R: VM 행은 표시
            # 성형이라 opts 를 잃는다). 판정은 지금 디스크로 다시 내린다.
            self.vm.refresh()
            group = self.vm.duplicate_group(keep)
            if group is None:
                return self._gone_group_result()
            items = dict(group)
            dropped = ", ".join(
                f"'{it.name}'" for k, it in group if k != keep
            )
            return {
                "ok": True, "needs_confirm": True, "keep": keep,
                # 확정이 되돌려 보낼 판정 근거 — 이 상태에 대한 승인이지 그룹 일반에
                # 대한 승인이 아니다.
                "basis": confirm_basis([bound_state(k, it) for k, it in group]),
                # 문안은 표시 요약(사람이 읽는 자리), 결속은 위 지문(정보 손실 없음).
                "confirm_text": (
                    f"같은 데이터({display_reference(items[keep])})를 가리키는 등록 "
                    f"{len(group)}건을 '{items[keep].name}' 하나로 합칩니다.\n"
                    f"삭제되는 등록: {dropped} — 그 이름·메모는 사라집니다"
                    "(원본 파일은 지우지 않습니다)."
                ),
            }
        try:
            kept_name, removed = self.vm.resolve_duplicates(keep, basis=p.get("basis"))
        except FileNotFoundError:
            self.vm.refresh()
            return self._gone_group_result()
        except StaleConfirmError:
            self.vm.refresh()
            return self._stale_basis_result()
        self._set_result(
            f"중복 등록 {removed}건을 정리하고 '{kept_name}' 을(를) 남겼습니다."
        )
        return {"ok": True, "kept": kept_name, "removed": removed}
