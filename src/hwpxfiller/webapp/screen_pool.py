"""등록 데이터(데이터셋 풀) 컨트롤러 — **화면 없는** 상태 소유자(webview 비의존).

웹 패리티 회수(#26 단위 A, #4). 링1 VM 을 **그대로 임포트**해 구동한다: 풀 항목 목록·상태
배지·상태별 게이트 액션(보관/활성화/삭제)·참조 등록은
:class:`~hwpxfiller.gui.dataset_pool_state.DatasetPoolViewModel`(Qt-free)가 소유한다.
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

**스코프 경계(조용히 빠뜨리지 않고 명시)**: 나라장터 참조 **등록**은 웹에 노출하지 않는다
(동결 결정 2026-07-16 — 내부망 API 미확인, ServiceKey 웹 표면 부재). 단 풀에 이미 있는
nara 항목은 숨기지 않고 그대로 표시한다(도메인 seam ``register_nara`` 는 보존, 배선만 유보).
"""
from __future__ import annotations

from pathlib import Path

from ..core.dataset_pool import DatasetPoolRegistry
from ..data.excel import ambiguous_sheet_error  # 다중 시트 확정 게이트 판정+문구(#33)
from ..gui.dataset_pool_state import (
    DatasetPoolViewModel,
    kind_transition_clause,
    reference_summary,
)
from .screens import PushSink, default_pool_registry


class PoolController:
    """등록 데이터 수명 — 데이터셋 풀 VM 위임(webview 비의존).

    **소비 표면은 데이터 선택 다이얼로그**(`web/js/data_picker.js`)다 — 「데이터 관리」
    화면은 F1 에서 죽었고 이 컨트롤러만 살아남아 그 다이얼로그가 스냅샷·액션을 소비한다.
    """

    name = "pool"

    def __init__(
        self,
        registry: "DatasetPoolRegistry | None",
        push: PushSink,
    ) -> None:
        self._push_sink = push
        # 레지스트리 주입 가능(테스트는 tmp_path); 기본은 홈 레지스트리(~/.hwpxfiller/datasets).
        self.vm = DatasetPoolViewModel(
            registry if registry is not None else default_pool_registry()
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
                # exists() 는 풀 액션 시에만 push 되는 이 화면에서만 지불(렌더당 I/O 아님).
                "missing": bool(r.locate_path) and not Path(r.locate_path).exists(),
                "note": r.note,
                "actions": [{"key": a.key, "label": a.label} for a in r.actions()],
            }
            for r in self.vm.rows()
        ]

    def _corrupted_rows(self) -> "list[dict]":
        """격리된 손상 파일을 웹이 시끄럽게 표면화할 행으로(RC-05 — 조용한 은닉 금지)."""
        return [
            {"file": path.name, "error": err}
            for path, err in self.vm.corrupted()
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

    def snapshot(self) -> dict:
        return {
            "rows": self._rows(),
            "count": self.vm.count_label(),
            "empty": self.vm.is_empty(),
            "corrupted": self._corrupted_rows(),
            "duplicates": self._duplicate_groups(),
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
    def _stale_item_result(self, label: str) -> dict:
        """stale 카드 공통 처리(C7) — 다른 표면(CLI·에디터 등)에서 삭제된 항목의 카드를
        누르면 FileNotFoundError 가 웹으로 새어 버튼이 무반응이 된다. 조용한 무반응 대신
        loud 재진술 + 재스캔으로 화면을 실상에 맞춘다(confirm-or-alarm)."""
        self.vm.refresh()
        msg = f"등록 데이터를 찾을 수 없습니다(이미 삭제된 항목): {label}. 목록을 새로 읽었습니다."
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
        key = p["key"]
        if not p.get("confirm"):
            try:
                item = self.vm.registry.load(key)
            except FileNotFoundError:
                return self._stale_item_result(self._row_name(key))
            return {
                "ok": True, "needs_confirm": True, "key": key,
                "confirm_text": (
                    f"등록 데이터 참조를 삭제합니다(원본 파일은 지우지 않습니다):\n"
                    f"{item.name} ({reference_summary(item)})"
                ),
            }
        name = self._row_name(key)
        self.vm.delete(key)
        self.vm.refresh()
        self._set_result(f"데이터셋 참조를 삭제했습니다: {name}")
        return {"ok": True}

    # ---- 등록(참조만 — 경로 포인터, 스냅샷·데이터 없음)
    def _do_register_excel(self, p: dict) -> dict:
        """엑셀/CSV 참조 등록 — 중복 판정은 **정체성**(경로+시트, §5.3 C)이다.

        - 같은 데이터 미등록 → 새 항목 추가.
        - 같은 데이터가 이미 있고 **바뀌는 게 없으면**(같은 이름·빈 메모) → 「이미
          고정돼 있습니다」 성사(확인 소음 금지 — 결정이 없다).
        - 같은 데이터가 이미 있고 이름·메모가 바뀌면 → 기존 이름을 재진술하고 확인 후
          **라벨 갱신**(참조·수명 불변 — 종전 「참조 재지정」 위험은 정체성 재편으로 소멸).

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
                    # 결정이 남지 않은 재등록 — 사실만 재진술하고 성사로 접는다.
                    self._set_result(
                        f"이미 고정돼 있습니다: {existing.name} "
                        f"({reference_summary(existing)})"
                    )
                    return {"ok": True, "key": key, "name": existing.name}
                if not p.get("confirm"):
                    return {
                        "ok": True, "needs_confirm": True, "key": key, "name": name,
                        "confirm_text": (
                            f"이 데이터는 이미 '{existing.name}' 으로 고정돼 있습니다"
                            f"({reference_summary(existing)}).\n"
                            f"같은 등록을 유지하고 이름·메모를 갱신합니다: '{name}'."
                        ),
                    }
                item = self.vm.relabel(key, name, note=note)
            else:
                if p.get("confirm"):
                    # 확인 모달은 "기존 등록 갱신"에 대한 승인이다. 모달을 읽는 사이 다른
                    # 화면이 항목을 삭제했다면 이를 신규 등록 승인으로 바꾸지 않는다.
                    return self._stale_item_result(name)
                item = self.vm.register_excel(name, path, sheet=sheet, note=note)
        except FileNotFoundError:
            # 분류 직후~mutate 잠금 획득 사이 삭제된 경우도 신규 등록으로 부활시키지 않는다.
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
        self._set_result(f"등록 데이터를 {verb}했습니다: {item.name} ({reference_summary(item)})")
        return {"ok": True, "name": item.name}

    # ---- 다시 연결(#67 → §5.3 키 재편) — 같은 슬롯의 참조 교체(수명 보존)
    def _do_relink(self, p: dict) -> dict:
        """끊긴(또는 갈아탈) 참조를 새 파일로 — **슬롯을 유지**한 채 kind+opts 만 바꾼다.

        내용물 교체가 이 개체의 정상 수명 사건이라(§5.3 — 월별 파일 갈아끼우기) 정체성이
        바뀌어도 슬롯·상태·생성시각은 산다. 종전엔 동명 재등록 confirm 경로가 이 일을
        겸했지만, 중복 판정이 정체성 기준이 되며 갈라졌다: 재등록은 「같은 데이터인가」를,
        여기는 「이 슬롯이 무엇을 가리키게 할 것인가」를 판정한다. 확정 전 1차 호출은
        기존→새 참조(+이름 변경·kind 전이)를 재진술한다(durable 뮤테이션 확인 1회).
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
        try:
            item = self.vm.registry.load(key)
        except (FileNotFoundError, ValueError):
            return self._stale_item_result(name or key)
        if not p.get("confirm"):
            rename_clause = (
                f"\n이름도 '{item.name}' → '{name}' 으로 바뀝니다."
                if name and name != item.name else ""
            )
            return {
                "ok": True, "needs_confirm": True, "key": key,
                "confirm_text": (
                    f"'{item.name}' 의 참조를 새 파일로 바꿉니다.\n"
                    f"기존: {reference_summary(item)}\n새 파일: {path}"
                    f"{kind_transition_clause(item)}{rename_clause}"
                ),
            }
        try:
            updated = self.vm.update_excel_reference(
                key, path, sheet=sheet, note=note, name=name
            )
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
    def _do_resolve_duplicate(self, p: dict) -> dict:
        """같은 데이터 등록 그룹에서 남길 1건 확정 → 나머지 삭제(확인 라운드트립).

        1차 호출은 **무엇이 남고 무엇이 지워지는지**를 재진술만 하고, 그 재진술이 겨눈
        멤버 키 집합(``group_keys``)을 함께 돌려준다 — 이름·메모가 다른 등록들을 지우는
        파괴라 조용한 자동 병합은 금지다(confirm-or-alarm).

        확정(2차)은 **사용자가 읽고 승인한 그 집합**과 지금 디스크의 그룹을 대조한다
        (코덱스 1R P1 — TOCTOU): 확인 모달을 읽는 사이 다른 writer 가 같은 정체성의
        등록을 더했으면, 재조회 결과를 그대로 채택할 때 **고지된 적 없는 등록이 drop 에
        조용히 포함**된다. 집합이 다르면(추가든 소멸이든) 아무것도 지우지 않고 차이를
        loud 재진술한다 — 승인한 문안과 실제로 일어나는 일이 갈리는 것이 이 저장소의
        지배 결함류다(에디터 덮어쓰기 게이트의 confirmed_overwrite_text 대조와 동형).
        """
        keep = p["keep"]
        # 판정·대조·삭제를 **레지스트리 공유 쓰기 잠금 한 경계 안**에서 밟는다 — 대조와
        # 삭제 사이에 다른 writer 가 끼면 대조가 다시 낡는다(잠금은 재진입 RLock 이라
        # 안의 vm.delete 가 그대로 통과한다). 판정은 지금 디스크로 다시 내린다.
        with self.vm.registry.write_lock():
            self.vm.refresh()
            group = next(
                (g for g in self.vm.duplicates() if any(r.key == keep for r in g)), None
            )
            if group is None:
                msg = "병합할 중복 등록이 더는 없습니다. 목록을 새로 읽었습니다."
                self._set_result(msg, "danger")
                return {"ok": False, "error": msg}
            keep_row = next(r for r in group if r.key == keep)
            drop = [r for r in group if r.key != keep]
            current_keys = sorted(r.key for r in group)
            if not p.get("confirm"):
                dropped = ", ".join(f"'{r.name}'" for r in drop)
                return {
                    "ok": True, "needs_confirm": True, "keep": keep,
                    # 확정이 되돌려 보낼 판정 근거 — 이 집합에 대한 승인이지 그룹 일반에
                    # 대한 승인이 아니다.
                    "group_keys": current_keys,
                    "confirm_text": (
                        f"같은 데이터({keep_row.reference})를 가리키는 등록 {len(group)}건을 "
                        f"'{keep_row.name}' 하나로 합칩니다.\n"
                        f"삭제되는 등록: {dropped} — 그 이름·메모는 사라집니다"
                        "(원본 파일은 지우지 않습니다)."
                    ),
                }
            confirmed = p.get("group_keys")
            if not isinstance(confirmed, list) or sorted(map(str, confirmed)) != current_keys:
                # 근거 미동봉(구식 호출)도 같은 거절이다 — 무엇을 승인했는지 모르는 확정으로
                # 지울 수는 없다(fail-closed).
                msg = (
                    "확인하는 사이 이 데이터의 등록 구성이 바뀌어 정리를 실행하지 않았습니다. "
                    "목록을 새로 읽었으니 다시 확인해 주세요."
                )
                self._set_result(msg, "danger")
                return {"ok": False, "error": msg}
            for r in drop:
                self.vm.delete(r.key)
        self._set_result(
            f"중복 등록 {len(drop)}건을 정리하고 '{keep_row.name}' 을(를) 남겼습니다."
        )
        return {"ok": True, "kept": keep_row.name, "removed": len(drop)}
