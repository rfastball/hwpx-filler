"""「기안」 화면 컨트롤러 — TXT 작업-앵커 master-detail + 휘발 세션. R-info 3부(#148).

「작업」(HWPX)의 대칭 화면: 저장 기계는 하나(JobRegistry)·화면은 둘이고, 매체는 선언하지
않고 ``template_path`` 접미사에서 유도한다(결정 4). 이 화면은 **TXT 작업만 조회**한다
(조회 경계 = 결정 13 · 1층). 좌 목록 그룹 구획·평면·drift 고지는 「작업」과 같은 공용 빌더
(:mod:`~hwpxfiller.webapp.job_list`)를 쓰고, 그룹 CRUD 는 같은 :class:`~hwpxfiller.core.job.
JobRegistry` 메서드에 위임한다 — 매핑 로직·판정은 재구현하지 않는다.

**휘발 세션(슬라이스 3a)**. 상세 패널의 4존(데이터·필드 상태·미리보기·완료)은 **목록
미선택** 상태에서 열리는 **휘발 세션**이다(결정 5 — 휘발 진입은 별도 레일 항목이 아니라
"목록 미선택 + 템플릿 붙여넣기"로 표현된다). 세션 본체는 「기안문 채우기」와 **같은 기계**
(:class:`~hwpxfiller.webapp.draft_session.DraftSessionMixin`)라 두 표면이 갈라질 자리가
없다 — 400줄 사본을 새로 짓지 않는다.

**착지분**. 맞추기 표·원문 뷰 전환(슬라이스 3b)에 이어, **큐 퇴화 규칙**(단건·데이터 없음 =
가상 길이 1, 결정 8·14)·**미루기 사망**(결정 10, 구 화면 포함 전수)·자유 이동 어포던스
(◀▶·점 클릭)가 슬라이스 3c 에서 착지했다.

**착지분(슬라이스 4)**. 맞추기 표 **그릇**이 섰다 — 유형 열(값 스니핑 오판 정정)·확정 열·
**확정-비움**(확정+무내용 = blank 렌더·빈칸 게이트 제외, 결정 12). 그릇은 두 표면 모두 늘
켜져 있고, 저장 세션 유래로 켜고 끄는 지속성 스위치(결정 7)는 슬라이스 5 가 얹는다.

**스코프 경계 — 미구현 명시(confirm-or-alarm: 없는 걸 있는 척하지 않는다)**. 아직 없는 것:
- **「기안으로 저장」 승격**(슬라이스 5, #135)·**저장 세션 복원**. TXT 작업은 슬라이스 5
  저장 배선 전까지 실제로 생성되지 않으므로 좌 목록은 아직 늘 비어 있다(빈 상태가 참이다).
  따라서 **작업을 고른 상태의 상세는 여전히 껍데기**이고(``RunViewModel`` 미사용 — 그건 hwpx
  전용, 결정 13), 지속성 스위치 5종·읽기 전용 원문도 그때 함께 온다.
- **매체 교차 그룹 의미론(#148 리뷰 #3)**: 그룹은 **레지스트리-전역**이다 — ``Job.group`` 은
  매체-불가지 단일 필드라 같은 이름 그룹이 두 매체에 걸쳐 하나로 산다(화면은 뷰만 매체로
  가른다). 따라서 ``rename_group``/``disband_group`` 은 두 매체를 함께 옮기고, **확인 건수도
  전역 관측**(``registry.list_jobs``)으로 센다 — TXT 집합만 세면 숨은 HWPX 소속을 조용히
  움직이며 수치가 과소 진술된다(confirm-or-alarm 위반). 전역이 실제 영향 집합과 일치하는
  정직한 수다. (매체별 격리 그룹이 필요하다는 실증이 나오면 그때 매체-스코프 연산을 별도 설계.)
"""
from __future__ import annotations

from ..core.job import JobRegistry
from ..core.text_registry import TextTemplateRegistry
from .draft_session import DraftSessionMixin, TargetFontSetting
from .job_list import build_flat_rows, build_group_sections, drift_note
from .screens import DatasetPoolRegistry, PushSink
from .settings import load_draft_collapsed_groups, save_draft_collapsed_groups


class DraftController(DraftSessionMixin):
    """「기안」 화면 — 좌 TXT 작업 목록(master) + 우 휘발 세션 4존(detail).

    두 계열의 ``_do_*`` 가 **한 라우터**를 공유한다(MRO): 목록 액션은 여기, 세션 액션은
    :class:`~hwpxfiller.webapp.draft_session.DraftSessionMixin`. 디스패치 규약(큐 재봉합 ·
    무변이 질의 · 확인 왕복 push 생략)도 믹스인 단일 출처다.
    """

    name = "draft"
    _action_label = "기안 화면"

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        text_registry: TextTemplateRegistry,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
        target_font: "TargetFontSetting | None" = None,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self.job_name = ""  # 좌 목록에서 겨눈 기안 작업(저장 세션 복원은 슬라이스 5)
        # 좌 목록 접힌 그룹 — 「작업」과 별도 키(매체별 격리, 결정 1). Python 설정 영속(#74).
        self._collapsed: "set[str]" = set(load_draft_collapsed_groups())
        self._init_session(text_registry, pool_registry=pool_registry, target_font=target_font)

    def _jobs(self):
        """조회 경계(결정 13 · 1층) — TXT 매체 작업만. 매체는 template_path 에서 유도(결정 4)."""
        return [j for j in self.registry.list_jobs() if j.media == "txt"]

    # ------------------------------------------------------------- 스냅샷
    def snapshot(self) -> dict:
        """좌 목록(그룹 구획) + 우 휘발 세션 4존.

        세션 키는 「기안문 채우기」와 **문자 그대로 같은 조각**이라 draft.js 가 datazone.js·
        segview.js 를 그대로 소비한다(키 이름이 갈라지면 팩토리 재사용이 깨진다).
        """
        jobs = self._jobs()
        sections, flat = build_group_sections(jobs, self.job_name, self._collapsed)
        return {
            "job_rows": build_flat_rows(jobs, self.job_name),
            "job_sections": sections,
            "job_flat": flat,
            "job_group_names": [s["group"] for s in sections if s["group"]],
            "job_name": self.job_name,
            # 저장 작업을 고른 상태의 상세는 아직 껍데기(저장 세션 복원 = 슬라이스 5)이고,
            # 휘발 세션(아래 키)은 **목록 미선택**일 때 열린다(결정 5) — 표면 분기는 이
            # has_job 하나가 진다. 별도 session_ready 플래그는 두지 않는다(같은 사실을 두 번
            # 선언하면 갈라질 자리가 생긴다 — 이 저장소 지배 결함류).
            "has_job": bool(self.job_name),
            **self._session_snapshot(),
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태(휘발 세션 템플릿 목록 포함)."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    # ------------------------------------------------------------- 목록 디스패치
    # 라우터는 DraftSessionMixin.dispatch 단일 출처(큐 재봉합·확인 왕복 규약 공유).

    def _do_refresh(self, p: dict) -> None:
        """레지스트리 재스캔 반영 + stale 선택 무효화(다른 화면에서 삭제·개명됐을 수 있다)."""
        if self.job_name and self.job_name not in self.registry.names():
            self.job_name = ""

    def _do_select_job(self, p: dict) -> None:
        """좌 목록 클릭 = 겨눔. 저장 세션 **복원**은 슬라이스 5 — 여기선 job_name 만 바꾼다.

        RunViewModel(hwpx 전용, 결정 13)을 만들지 않는다. 휘발 세션 상태는 **건드리지 않는다**:
        목록을 눌렀다 미선택으로 돌아오면 붙여넣던 원문·데이터·큐 진행이 그대로 있어야 한다
        (선택은 화면 전환이지 세션 파괴가 아니다 — 조용한 소실 금지).
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
