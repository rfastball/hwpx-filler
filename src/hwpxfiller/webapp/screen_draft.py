"""「기안」 화면 컨트롤러 — TXT 작업-앵커 master-detail(골격). R-info 3부(#148).

「작업」(HWPX)의 대칭 화면: 저장 기계는 하나(JobRegistry)·화면은 둘이고, 매체는 선언하지
않고 ``template_path`` 접미사에서 유도한다(결정 4). 이 화면은 **TXT 작업만 조회**한다
(조회 경계 = 결정 13 · 1층). 좌 목록 그룹 구획·평면·drift 고지는 「작업」과 같은 공용 빌더
(:mod:`~hwpxfiller.webapp.job_list`)를 쓰고, 그룹 CRUD 는 같은 :class:`~hwpxfiller.core.job.
JobRegistry` 메서드에 위임한다 — 매핑 로직·판정은 재구현하지 않는다.

**스코프 경계 — 미구현 명시(confirm-or-alarm: 없는 걸 있는 척하지 않는다)**. 이 골격(슬라이스
2b)이 세우는 것은 좌 목록(TXT 작업 조회·그룹 관리)과 상세 패널 **껍데기**뿐이다. 아직 없는 것:
- **세션 패널**(데이터·맞추기·미리보기·완료 4존 합병) — 슬라이스 3(빠른 기안 × 기안문 채우기
  합병). 그전까지 상세는 정직한 빈 상태이고 목록 선택은 강조만 한다(``RunViewModel`` 미사용 —
  그건 hwpx 전용, 결정 13).
- **휘발 세션 진입**(목록 미선택 + 템플릿 붙여넣기, 결정 5)·**매핑 그릇**(슬라이스 4)·
  **「기안으로 저장」 승격**(슬라이스 5, #135). TXT 작업은 슬라이스 5 저장 배선 전까지 실제로
  생성되지 않으므로 이 골격에서 목록은 늘 비어 있다(빈 상태가 참이다).
- **매체 교차 그룹 의미론(#148 리뷰 #3)**: 그룹은 **레지스트리-전역**이다 — ``Job.group`` 은
  매체-불가지 단일 필드라 같은 이름 그룹이 두 매체에 걸쳐 하나로 산다(화면은 뷰만 매체로
  가른다). 따라서 ``rename_group``/``disband_group`` 은 두 매체를 함께 옮기고, **확인 건수도
  전역 관측**(``registry.list_jobs``)으로 센다 — TXT 집합만 세면 숨은 HWPX 소속을 조용히
  움직이며 수치가 과소 진술된다(confirm-or-alarm 위반). 전역이 실제 영향 집합과 일치하는
  정직한 수다. (매체별 격리 그룹이 필요하다는 실증이 나오면 그때 매체-스코프 연산을 별도 설계.)
"""
from __future__ import annotations

from ..core.job import JobRegistry
from .job_list import build_flat_rows, build_group_sections, drift_note
from .screens import PushSink
from .settings import load_draft_collapsed_groups, save_draft_collapsed_groups


class DraftController:
    """「기안」 화면 — 좌 TXT 작업 목록 + 우 상세 패널 껍데기(세션은 슬라이스 3에서)."""

    name = "draft"

    def __init__(self, registry: JobRegistry, push: PushSink) -> None:
        self.registry = registry
        self._push_sink = push
        self.job_name = ""  # 좌 목록에서 겨눈 기안 작업(골격은 강조만 — 세션 미구현)
        # 좌 목록 접힌 그룹 — 「작업」과 별도 키(매체별 격리, 결정 1). Python 설정 영속(#74).
        self._collapsed: "set[str]" = set(load_draft_collapsed_groups())

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _jobs(self):
        """조회 경계(결정 13 · 1층) — TXT 매체 작업만. 매체는 template_path 에서 유도(결정 4)."""
        return [j for j in self.registry.list_jobs() if j.media == "txt"]

    # ------------------------------------------------------------- 스냅샷
    def snapshot(self) -> dict:
        """좌 목록(그룹 구획) + 상세 패널 껍데기 상태. 세션 4존은 슬라이스 3에서 온다."""
        jobs = self._jobs()
        sections, flat = build_group_sections(jobs, self.job_name, self._collapsed)
        return {
            "job_rows": build_flat_rows(jobs, self.job_name),
            "job_sections": sections,
            "job_flat": flat,
            "job_group_names": [s["group"] for s in sections if s["group"]],
            "job_name": self.job_name,
            "has_job": bool(self.job_name),
            # 세션 패널 미구현(골격) — 상세는 정직한 빈 상태. 슬라이스 3에서 True 로 승격.
            "session_ready": False,
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------------- 디스패치
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 기안 화면 액션: {action!r}")
        result = handler(payload)
        blocked = isinstance(result, dict) and result.get("needs_confirm")
        if not blocked:
            self._push()
        return result

    def _do_refresh(self, p: dict) -> None:
        """레지스트리 재스캔 반영 + stale 선택 무효화(다른 화면에서 삭제·개명됐을 수 있다)."""
        if self.job_name and self.job_name not in self.registry.names():
            self.job_name = ""

    def _do_select_job(self, p: dict) -> None:
        """좌 목록 클릭 = 강조(골격). 세션 재구성은 슬라이스 3 — 여기선 job_name 만 겨눈다.

        RunViewModel(hwpx 전용, 결정 13)을 만들지 않는다 — 기안 세션은 별도 표면이다.
        """
        self.job_name = p.get("name", "")

    def _do_toggle_group(self, p: dict) -> None:
        """그룹 접힘/펼침 토글 — 마지막 상태를 Python 설정에 영속(「작업」과 별도 키)."""
        g = p["group"]
        if g in self._collapsed:
            self._collapsed.discard(g)
        else:
            self._collapsed.add(g)
        save_draft_collapsed_groups(sorted(self._collapsed))

    def _do_rename_job(self, p: dict) -> dict:
        """작업 이름 변경(인라인 커밋) — 검증 실패는 ``{"ok": False, error}`` 재진술."""
        name, new = p["name"], p.get("new", "")
        try:
            self.registry.rename(name, new)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if self.job_name == name:
            self.job_name = new.strip()
        return {"ok": True}

    def _do_clone_job(self, p: dict) -> dict:
        """작업 복제 — 레지스트리 clone(유일 이름 합성·이력 미계승) 위임. 그룹 계승 = 인접."""
        return {"ok": True, "name": self.registry.clone(p["name"])}

    def _do_delete_job(self, p: dict) -> "dict | None":
        """작업 삭제 — 무확인 호출은 재진술 자료를 돌려주고 멈춘다(RC-02 왕복 동형).

        세션 껍데기라 열린 세션 파괴 수치는 없다 — durable 삭제 사실만 재진술한다.
        """
        name = p["name"]
        if not p.get("confirm"):
            return {"needs_confirm": True, "name": name, "open_session": False}
        self.registry.delete(name)
        if name == self.job_name:
            self.job_name = ""

    def _do_set_group(self, p: dict) -> None:
        """그룹 지정/해제(이동 다이얼로그 확정) — ``group=""`` 는 「그룹 없음」으로 이동."""
        self.registry.set_group(p["name"], p.get("group", ""))

    def _do_rename_group(self, p: dict) -> dict:
        """그룹 이름 변경 — 새 이름이 **기존 그룹**이면 병합이므로 확인 승격(무확인 반환).

        건수는 **레지스트리 전역**(``list_jobs``) 관측이다 — 그룹은 매체-전역이고 rename_group 도
        전역이라, 실제 영향 집합(두 매체 모두)과 확인 수치를 일치시킨다(리뷰 #3, 과소 진술 봉합).
        순수 개명이면 접힘을 새 이름으로 승계, 병합이면 대상 접힘 존중하고 옛 이름만 걷는다.
        """
        old, new = p["name"], p.get("new", "").strip()
        if not new:
            return {"ok": False, "error": "그룹 이름이 비어 있습니다."}
        if new == old:
            return {"ok": True, "count": 0, "drift_note": ""}
        target_members = sum(1 for j in self.registry.list_jobs() if j.group == new)
        if target_members and not p.get("confirm"):
            count = sum(1 for j in self.registry.list_jobs() if j.group == old)
            return {"needs_confirm": True, "kind": "merge_group", "name": old,
                    "new": new, "count": count, "target_count": target_members}
        count = self.registry.rename_group(old, new)
        if old in self._collapsed:
            self._collapsed.discard(old)
            if not target_members:
                self._collapsed.add(new)
            save_draft_collapsed_groups(sorted(self._collapsed))
        return {"ok": True, "count": count, "drift_note": drift_note(p.get("seen"), count)}

    def _do_disband_group(self, p: dict) -> dict:
        """그룹 해산 — 무확인 호출은 소속 수(**레지스트리 전역** 관측) 재진술로 멈춘다. 소속은
        「그룹 없음」. 전역 수가 실제 영향 집합과 일치한다(리뷰 #3 — 매체 교차 과소 진술 봉합)."""
        name = p["name"]
        if not p.get("confirm"):
            count = sum(1 for j in self.registry.list_jobs() if j.group == name)
            return {"needs_confirm": True, "name": name, "count": count}
        count = self.registry.disband_group(name)
        if name in self._collapsed:
            self._collapsed.discard(name)
            save_draft_collapsed_groups(sorted(self._collapsed))
        return {"ok": True, "count": count, "drift_note": drift_note(p.get("seen"), count)}
