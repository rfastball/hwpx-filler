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
**확정-비움**(확정+무내용 = blank 렌더·빈칸 게이트 제외, 결정 12).

**착지분(슬라이스 5a)**. 저장 기안 **복원** + **유래별 열 게이팅**. 좌 목록에서 저장 기안을
고르면 세션이 그 Job 에서 되살아난다(원문 읽기 전용·유형/확정 열 표시·``apply_profile(
confirm=True)`` 사람 소유 복원, 결정 12) — ``RunViewModel``(hwpx 전용, 결정 13)은 쓰지 않고
:meth:`DraftSessionMixin._restore_from_job` 이 진다. **두 세션 병존**: 붙여넣던 휘발 세션은
스태시돼 살아 있고 「이번 세션」으로 돌아오면 그대로다(소실 0). 맞추기 그릇의 유형·확정 열은
이제 ``mode``(_bound_job 유도)로 켜고 끈다 — 휘발이면 숨고 저장이면 뜬다(결정 7 그릇 스위치).

**스코프 경계 — 미구현 명시(confirm-or-alarm: 없는 걸 있는 척하지 않는다)**. 아직 없는 것:
- **「사본으로 편집」 포크**(슬라이스 5b) — 저장 원문은 지금 읽기 전용이되, 손보기 위해 휘발
  사본으로 가르는 동사(값·데이터 승계)는 아직 없다.
- **「기안으로 저장」 승격**(슬라이스 5c, #135) — 휘발 세션을 TXT ``Job`` 으로 저장하는 배선.
  이게 서기 전까지 좌 목록에 저장 기안이 실제로 생기려면 다른 경로(직접 Job 저장)가 필요하다.
- **매체 교차 그룹 의미론(#148 리뷰 #3)**: 그룹은 **레지스트리-전역**이다 — ``Job.group`` 은
  매체-불가지 단일 필드라 같은 이름 그룹이 두 매체에 걸쳐 하나로 산다(화면은 뷰만 매체로
  가른다). 따라서 ``rename_group``/``disband_group`` 은 두 매체를 함께 옮기고, **확인 건수도
  전역 관측**(``registry.list_jobs``)으로 센다 — TXT 집합만 세면 숨은 HWPX 소속을 조용히
  움직이며 수치가 과소 진술된다(confirm-or-alarm 위반). 전역이 실제 영향 집합과 일치하는
  정직한 수다. (매체별 격리 그룹이 필요하다는 실증이 나오면 그때 매체-스코프 연산을 별도 설계.)
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..core.job import Job, JobRegistry
from ..core.text_registry import TextTemplateRegistry
from ..gui.job_editor_state import overwrite_confirm_text
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
        # 좌 목록 접힌 그룹 — 「작업」과 별도 키(매체별 격리, 결정 1). Python 설정 영속(#74).
        self._collapsed: "set[str]" = set(load_draft_collapsed_groups())
        # 좌 목록에서 겨눈 저장 기안 = 세션 유래 결속(``_bound_job``, draft_session 소유·단일
        # 실체). _init_session 이 세운다(생성자 아래) — 목록 선택도 세션 모드도 이 한 필드에서.
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
        sections, flat = build_group_sections(jobs, self._bound_job, self._collapsed)
        return {
            "job_rows": build_flat_rows(jobs, self._bound_job),
            "job_sections": sections,
            "job_flat": flat,
            "job_group_names": [s["group"] for s in sections if s["group"]],
            "job_name": self._bound_job,
            # 저장 기안 결속 여부 = 저장 모드(#148 슬라이스 5a). 세션 모드(mode·source_readonly)와
            # 목록 선택(has_job·job_name)이 **모두 _bound_job 한 필드에서 유도**된다 — 별도
            # session_ready 플래그는 두지 않는다(같은 사실을 두 번 선언하면 갈라질 자리가 생긴다,
            # 이 저장소 지배 결함류). 두 세션은 병존한다: 저장 기안을 고르면 붙여넣던 휘발 세션은
            # 스태시돼 살아 있고, 「이번 세션」 행으로 돌아오면 그대로다(선택은 화면 전환이지 세션
            # 파괴가 아니다 — 조용한 소실 금지).
            "has_job": bool(self._bound_job),
            **self._session_snapshot(),
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태(휘발 세션 템플릿 목록 포함)."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    # ------------------------------------------------------------- 목록 디스패치
    # 라우터는 DraftSessionMixin.dispatch 단일 출처(큐 재봉합·확인 왕복 규약 공유).

    def _do_refresh(self, p: dict) -> None:
        """레지스트리 재스캔 반영 + stale 결속 무효화(다른 화면에서 삭제·개명됐을 수 있다).

        결속했던 저장 기안이 사라졌으면 휘발 세션으로 복귀한다 — 유래만 소거하면 사라진 기안의
        원문·매핑이 저장 모드로 계속 떠 있어 정의와 실제가 갈라진다(confirm-or-alarm)."""
        if self._bound_job and self._bound_job not in self.registry.names():
            self._restore_volatile()

    def _do_select_job(self, p: dict) -> "dict | None":
        """좌 목록 클릭 = 저장 기안 결속(복원) · 「이번 세션」 클릭(빈 이름) = 휘발 귀환(#148 슬라이스 5a).

        **두 세션 병존**: 휘발 세션에서 저장 기안을 고르면 붙여넣던 세션을 스태시하고(소실 0)
        저장-세션을 Job 에서 세운다(:meth:`_restore_from_job` — 원문 읽기 전용·유형/확정 열·
        ``apply_profile(confirm=True)``, 결정 12). 이미 저장 기안에 결속된 상태에서 다른 기안을
        고르면 스태시하지 않는다(저장-세션은 Job 에서 결정적으로 재구성되니 잃을 게 없다) —
        스태시된 휘발은 그대로 살아 있다. RunViewModel(hwpx 전용, 결정 13)은 쓰지 않는다.

        **저장 세션 진행 보존 가드(리뷰 5a P1, T3 동형)**: 저장 세션의 데이터·큐 진행은 Job 에
        저장되지 않아(Job 계약 = 데이터/행 미저장) 다른 기안 전환·「이번 세션」 귀환 시 재구성으로
        사라진다 — 휘발은 스태시로 보존되지만 저장은 잃는다. 무장(진행)이면 파괴를 먼저 재진술한다
        (``needs_confirm`` 왕복, RC-02). 휘발에서의 전환은 스태시로 보존되니 가드 대상이 아니다
        (``_bound_job`` 일 때만 잃는다). 확인(confirm)은 내부 경로로 승계한다.

        stale 선택(레지스트리에서 사라진 이름·템플릿 파일 부재)은 상태를 바꾸지 않고 시끄럽게
        재진술한다(``{"ok": False, error}``) — 스태시한 휘발 세션이 반쪽으로 오염되지 않는다."""
        name = p.get("name", "")
        if name and name == self._bound_job:
            return None  # 재선택 무동작(진행 불변)
        # 저장 세션을 떠나면 그 데이터·큐 진행이 사라진다 — 무장이면 확인 왕복(위 docstring).
        if self._bound_job and not p.get("confirm"):
            g = self._guard_state()
            if g["armed"]:
                return {"needs_confirm": True, "kind": "leave_saved", "target": name, **g}
        if not name:  # 「이번 세션」 = 겨눔 해제 → 휘발 귀환
            if self._bound_job:
                self._restore_volatile()
            return None
        try:
            job = self.registry.load(name)
        except (FileNotFoundError, ValueError) as exc:  # 삭제 경합·손상 — refresh 가 정리
            return {"ok": False, "error": f"저장된 기안을 열 수 없습니다: {exc}"}
        if not self._bound_job:  # 휘발 → 저장: 붙여넣던 세션을 스태시(두 세션 병존)
            self._stash_volatile()
        try:
            self._restore_from_job(job)
        except OSError as exc:  # 템플릿 파일 부재 — 복원은 실패 원자적이라 상태 불변
            return {"ok": False, "error": f"기안 템플릿을 열 수 없습니다: {exc}"}
        return None

    def _do_save_job(self, p: dict) -> "dict | None":
        """「기안으로 저장」(#148 슬라이스 5c, #135) — 라이브러리 배접 세션을 TXT ``Job`` 으로 승격.

        저장 대상은 **바인딩**({template, mapping, group})이지 데이터가 아니다(Job 계약). 자격은
        **라이브러리 배접 원문**(파일 경로 있음)이고 **수정되지 않음** — 붙여넣기·사본 편집은 파일과
        어긋나 저장할 수 없다(먼저 「템플릿으로 저장」, 라이브러리 배접만 결정). 표면이 이미 비활성+
        사유로 막지만 백엔드도 방어한다(조용한 빈-경로 Job 양산 금지).

        **저장 = 확정**: 휘발 세션은 확정 열이 숨어 있어 행이 미확정이므로, 승격이 내용 있는 행을
        확정본으로 굳힌다(``to_profile`` 은 확정 행만 담는다 — 미결속 missing 은 빠져 {{토큰}}으로
        남는다, 정확). 저장 모드(재저장)에선 사람의 확정 토글을 존중한다(force-confirm 안 함).
        미결속뿐(내용 0)이면 빈 레시피라 시끄럽게 막는다(복사 게이트 동형).

        동명 덮어쓰기는 **다른 기존 기안을 덮을 때만** 확인 왕복(자기 재저장은 자명, RC-15).
        저장 뒤 **제자리 결속**(시안 "휘발 행이 그대로 위 목록으로") — 세션을 그대로 두고 저장 모드
        전이(원문 읽기 전용). 스태시(붙여넣던 이전 휘발)는 건드리지 않는다."""
        if self._source_dirty or not self._template_path:
            return {"ok": False, "error": (
                "붙여넣거나 고친 원문은 아직 기안으로 저장할 수 없습니다 — 라이브러리 템플릿을 "
                "골라 채우거나, 원문을 「템플릿으로 저장」한 뒤 저장하세요.")}
        # 캐시된 template_path 재검증(리뷰 5c P2) — 이 세션이 경로를 캐시한 뒤 템플릿 관리에서
        # 삭제·이동됐을 수 있다. 빈 문자열만 보던 위 게이트는 통과하지만, 그러면 다시 못 여는
        # 템플릿을 가리키는 Job 이 생긴다. 지금 실 파일인지 확인한다(confirm-or-alarm).
        if not Path(self._template_path).is_file():
            return {"ok": False, "error": (
                "이 기안의 템플릿 파일이 사라졌거나 이동했습니다 — 템플릿을 다시 고른 뒤 저장하세요.")}
        if not any(r.has_content() for r in self.mapping.rows):
            return {"ok": False, "error": (
                "맞춰진 토큰이 없습니다 — 데이터 열을 결속하거나 값을 직접 입력한 뒤 저장하세요.")}
        name = p.get("name", "").strip()
        if not name:
            return {"ok": False, "error": "기안 이름을 입력하세요."}
        # 덮어쓰기 판정·메타 보존·저장을 **한 임계구역**에서(리뷰 5c P1, 에디터 _save_locked 동형).
        # 잠금 밖에서 exists/load 로 결정하면, 확인~저장 사이(모달이 열린 동안 포함) 다른 pywebview
        # writer 가 이 이름을 새로 만들거나 바꿔치기할 때 **확인한 것과 다른 작업을 덮거나 새
        # 작업을 무확인 덮어쓴다**(TOCTOU). 잠금 안에서 지금 상태로 판정·저장한다.
        with self.registry.write_lock():
            exists = self.registry.exists(name)
            # 덮어쓰기 문안을 **잠금 안에서 지금** 성형하고 사용자가 확인한 문안과 대조한다(리뷰
            # 5c P1 후속, 에디터 _save_locked 동형). 모달이 열린 사이 이 slug 자리가 다른 Job 으로
            # 교체되면 victim 이 바뀌어 문안이 달라진다 — 그러면 confirm:true 라도 **새 문안으로
            # 다시 묻는다**. 확인한 것과 다른 작업을 무확인 덮어쓰지 않는다(덮어쓰기는 되돌릴 수
            # 없어 결과 재진술로 갈음 못 한다). 문안이 같으면 통과(같은 사실을 확인한 것).
            gate_text = ""
            if name != self._bound_job and exists:
                try:
                    victim = self.registry.load(name).name
                except (FileNotFoundError, ValueError):
                    victim = ""  # 손상 — 추측 금지(그대로 고지)
                gate_text = overwrite_confirm_text(name, victim)
            if gate_text and (not p.get("confirm") or p.get("confirmed_text", "") != gate_text):
                return {"ok": False, "needs_confirm": True, "name": name, "confirm_text": gate_text}
            # 기존 메타 보존(리뷰 5c P1) — 재저장/덮어쓰기가 그룹만 남기고 tags·last_run_at·
            # default_dataset_ref·version·filename_pattern 을 조용히 기본값으로 지우지 않게. 이
            # 화면이 편집하지 않는 필드는 전부 승계하고 template_path·mapping 만 갈아 끼운다.
            preserved = None
            if exists:
                try:
                    preserved = self.registry.load(name)
                except (FileNotFoundError, ValueError):
                    preserved = None  # 손상 — 새로 쓴다(덮어쓰기 확인은 이미 통과)
            if not self._bound_job:  # 휘발 승격 — 확정 열이 숨어 있었으니 저장이 확정(내용 있는 행)
                for i, r in enumerate(self.mapping.rows):
                    if r.has_content():
                        self.mapping.set_confirmed(i, True)
            profile = self.mapping.to_profile(name)
            if preserved is not None:  # 승계 초집합(name·group·tags·last_run_at·default_dataset_ref·version·pattern)
                job = replace(preserved, template_path=self._template_path, mapping=profile)
            else:
                job = Job(name=name, template_path=self._template_path, mapping=profile)
            self.registry.save(job, allow_overwrite=True)
        # 제자리 결속 — 세션 그대로, 저장 모드 전이(원문 읽기 전용). 목록에 새 행이 선다.
        self._bound_job = name
        self._source_readonly = True
        self._source_dirty = False
        return {"ok": True, "name": name}

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
        if self._bound_job == name:  # 결속 중인 기안을 개명 — 결속만 새 이름으로(세션 원문·매핑 불변)
            self._bound_job = new.strip()
        return {"ok": True}

    def _do_clone_job(self, p: dict) -> dict:
        """작업 복제 — 레지스트리 clone(유일 이름 합성·이력 미계승) 위임. 그룹 계승 = 인접."""
        return {"ok": True, "name": self.registry.clone(p["name"])}

    def _do_delete_job(self, p: dict) -> "dict | None":
        """작업 삭제 — 무확인 호출은 재진술 자료를 돌려주고 멈춘다(RC-02 왕복 동형).

        결속 중인 기안을 삭제하면 휘발 세션으로 복귀한다 — 사라진 정의가 저장 모드로 계속
        떠 있지 않게(스태시해 둔 휘발이 있으면 그대로, 없으면 새 휘발)."""
        name = p["name"]
        if not p.get("confirm"):
            return {"needs_confirm": True, "name": name, "open_session": False}
        self.registry.delete(name)
        if name == self._bound_job:
            self._restore_volatile()

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
