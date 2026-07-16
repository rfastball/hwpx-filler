"""데이터 관리(pool) 화면 컨트롤러 — 등록 데이터(데이터셋 풀) 관리(webview 비의존).

웹 패리티 회수(#26 단위 A, #4). 링1 VM 을 **그대로 임포트**해 구동한다: 풀 항목 목록·상태
배지·상태별 게이트 액션(보관/은퇴/활성화/삭제)·참조 등록은
:class:`~hwpxfiller.gui.dataset_pool_state.DatasetPoolViewModel`(Qt-free)가 소유한다.
표현 계층(카드 렌더·확인 라운드트립)만 웹(js/screens/pool.js)으로 이식한다 — VM 로직
재구현이 아니다.

**confirm-or-alarm 경계 2곳** — 조용한 durable 소실을 막는 이 화면의 존재 이유:
- 삭제는 파괴이므로 확인 라운드트립(1차=재진술, 2차=삭제) — tpl ``_do_txt_delete`` 미러.
- **동명 재등록은 조용한 opts 덮어쓰기 함정**: 같은 이름은 slug 가드를 통과하므로(자기 갱신
  으로 간주) 기존 항목의 포인터가 무경고로 재지정될 수 있다. 여기서 ``exists()`` 로 선판정해
  기존 참조 요약과 함께 확인을 요구한다. 다른 이름·같은 slug 는
  :class:`~hwpxfiller.core.job.SlugCollisionError` 가 막는다 — 날것 전파 대신 문구로 재진술.

**스코프 경계(조용히 빠뜨리지 않고 명시)**: 나라장터 참조 **등록**은 웹에 노출하지 않는다
(동결 결정 2026-07-16 — 내부망 API 미확인, ServiceKey 웹 표면 부재). 단 풀에 이미 있는
nara 항목은 숨기지 않고 그대로 표시한다(도메인 seam ``register_nara`` 는 보존, 배선만 유보).
"""
from __future__ import annotations

from ..core.dataset_pool import DatasetPoolRegistry, default_dataset_pool_dir
from ..core.job import SlugCollisionError
from ..gui.dataset_pool_state import DatasetPoolViewModel, reference_summary
from .screens import PushSink


class PoolController:
    """데이터 관리 화면 — 데이터셋 풀 VM 위임(webview 비의존)."""

    name = "pool"

    def __init__(
        self,
        registry: "DatasetPoolRegistry | None",
        push: PushSink,
    ) -> None:
        self._push_sink = push
        # 레지스트리 주입 가능(테스트는 tmp_path); 기본은 홈 레지스트리(~/.hwpxfiller/datasets).
        self.vm = DatasetPoolViewModel(
            registry if registry is not None
            else DatasetPoolRegistry(default_dataset_pool_dir())
        )
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
        return [
            {
                "name": r.name,
                "kind": r.kind,
                "kind_label": r.kind_label,
                "status": r.status,
                "badge_label": r.badge_label,
                "badge_level": r.badge_level,
                "reference": r.reference,
                "note": r.note,
                "actions": [{"key": a.key, "label": a.label} for a in r.actions()],
            }
            for r in self.vm.rows()
        ]

    def snapshot(self) -> dict:
        return {
            "rows": self._rows(),
            "count": self.vm.count_label(),
            "empty": self.vm.is_empty(),
            "result": {"text": self.result_text, "level": self.result_level},
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
    def _do_archive(self, p: dict) -> dict:
        self.vm.archive(p["name"])
        self._set_result(f"데이터셋을 보관했습니다: {p['name']}")
        return {"ok": True}

    def _do_retire(self, p: dict) -> dict:
        self.vm.retire(p["name"])
        self._set_result(f"데이터셋을 은퇴시켰습니다: {p['name']}")
        return {"ok": True}

    def _do_activate(self, p: dict) -> dict:
        self.vm.activate(p["name"])
        self._set_result(f"데이터셋을 활성화했습니다: {p['name']}")
        return {"ok": True}

    # ---- 삭제(파괴 — 확인 라운드트립, tpl _do_txt_delete 미러)
    def _do_delete(self, p: dict) -> dict:
        name = p["name"]
        if not p.get("confirm"):
            item = self.vm.registry.load(name)
            return {
                "ok": True, "needs_confirm": True, "name": name,
                "confirm_text": (
                    f"등록 데이터 참조를 삭제합니다(원본 파일은 지우지 않습니다):\n"
                    f"{name} — {reference_summary(item)}"
                ),
            }
        self.vm.delete(name)
        self._set_result(f"데이터셋 참조를 삭제했습니다: {name}")
        return {"ok": True}

    # ---- 등록(참조만 — 경로 포인터, 스냅샷·데이터 없음)
    def _do_register_excel(self, p: dict) -> dict:
        """엑셀/CSV 참조 등록 — 동명 덮어쓰기는 확인 승격, slug 충돌은 문구로 loud.

        검증 실패(빈 이름 등 ValueError)와 slug 충돌(SlugCollisionError)은 날것 예외로
        웹에 새지 않게 잡아 사용자 문구로 재진술한다 — 실패가 조용하지도, 기술적이지도 않게.
        """
        name = (p.get("name") or "").strip()
        path = p.get("path") or ""
        sheet = p.get("sheet") or None
        note = p.get("note") or ""
        # 동명 기존 항목 = 같은 slug 라 가드를 통과해 opts 가 조용히 재지정된다(ST-09 의 사각).
        # 1차 호출에선 기존 참조 요약을 재진술하고 확인을 요구한다. 단 exists() 는 slug 기반이라
        # **다른 이름·같은 slug**(충돌)도 잡힌다 — 저장된 실제 이름을 대조해 진짜 동명만 확인
        # 분기로 보내고, 충돌·손상은 아래 slug 가드가 loud 하게 판정하게 통과시킨다.
        if name and self.vm.registry.exists(name) and not p.get("confirm"):
            try:
                existing = self.vm.registry.load(name)
            except Exception:  # noqa: BLE001 — 손상 파일: 가드가 SlugCollisionError 로 재진술
                existing = None
            if existing is not None and existing.name == name:
                return {
                    "ok": True, "needs_confirm": True, "name": name,
                    "confirm_text": (
                        f"같은 이름의 등록 데이터가 이미 있습니다:\n"
                        f"{name} — {reference_summary(existing)}\n\n"
                        f"등록하면 이 참조가 새 파일로 바뀝니다."
                    ),
                }
        try:
            item = self.vm.register_excel(name, path, sheet=sheet, note=note)
        except SlugCollisionError as exc:
            self._set_result(str(exc), "danger")
            return {"ok": False, "error": str(exc)}
        except ValueError as exc:
            self._set_result(str(exc), "danger")
            return {"ok": False, "error": str(exc)}
        self._set_result(f"등록 데이터를 추가했습니다: {item.name} — {reference_summary(item)}")
        return {"ok": True, "name": item.name}
