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

import hashlib
from dataclasses import replace
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

from ..core.job import Job, JobRegistry
from ..core.text_registry import TextTemplateRegistry
from ..gui.job_editor_state import overwrite_confirm_text
from .draft_session import DraftSessionMixin, TargetFontSetting
from .job_list import build_flat_rows, build_group_sections, drift_note
from .screens import DatasetPoolRegistry, PushSink
from .settings import load_draft_collapsed_groups, save_draft_collapsed_groups
from .template_groups import TemplateGroupModel, rel_key, validate_template_name


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
        txt_groups: "TemplateGroupModel | None" = None,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self._deleted_job_slot = None
        # txt 템플릿 그룹 모델(#108) — 「템플릿으로 저장」(#135)이 그룹을 지정하므로 필요하다.
        # 관리 화면·구 「빠른 기안」과 **같은 인스턴스**여야 한다(app.py 가 주입): 별도면 지정·접힘
        # 인메모리 캐시가 갈라져 여기서 넣은 그룹이 관리 화면 목록에 안 보인다(에디터 1단계 피커에
        # hwpx 모델을 공유한 것과 같은 이유). 「기안으로 저장」의 Job.group(레지스트리 전역)과는
        # 별개 축이다 — 이건 TXT **라이브러리** 그룹(TemplateGroupModel), 저건 작업 그룹.
        self._groups = txt_groups if txt_groups is not None else TemplateGroupModel("txt")
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

    def _do_refresh(self, p: dict) -> "dict | None":
        """레지스트리 재스캔 반영 + stale 결속 무효화(다른 화면에서 삭제·개명됐을 수 있다).

        결속했던 저장 기안이 사라졌으면 휘발 세션으로 복귀한다 — 유래만 소거하면 사라진 기안의
        원문·매핑이 저장 모드로 계속 떠 있어 정의와 실제가 갈라진다(confirm-or-alarm).

        **결속 세션 소실 시 시끄러운 사후 고지(리뷰 5a 3R P1 / 121)**: 다른 화면(홈 등)에서
        결속 기안을 삭제하면 그 확인창은 정의 삭제만 알렸을 뿐, 이 화면의 진행 중 세션(데이터·
        선택·큐·미저장 편집)은 언급하지 못한다 — 삭제 화면은 draft 세션을 모른다. 삭제는 이미
        일어나 사전 확인이 불가하므로, 무장(:meth:`_leave_guard`) 세션을 조용히 버리지 않고
        소실 사실을 실어 표면이 alert 로 사후 고지한다(confirm-or-alarm 의 "시끄럽게 알려라"
        갈래 — 묻지 못하면 알린다). 무장 아니면 잃을 게 없어 조용히 복귀한다."""
        if self._bound_job and self._bound_job not in self.registry.names():
            name = self._bound_job
            g = self._leave_guard()
            self._restore_volatile()
            if g["armed"]:
                bits = []
                if g["sel_count"]:
                    bits.append(f"선택 {g['sel_count']}행")
                if g["copied_count"]:
                    bits.append(f"복사 {g['copied_count']}건")
                if g["map_dirty"]:
                    bits.append("미저장 매핑 편집")
                detail = f"(진행: {' · '.join(bits)}) " if bits else ""
                return {"notice": (
                    f"연결했던 기안 '{name}' 이(가) 다른 화면에서 삭제되어 세션이 닫혔습니다. "
                    f"{detail}이 진행은 복구할 수 없습니다."
                )}
        return None

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
        # 저장 세션을 떠나면 그 데이터·큐·미저장 편집이 사라진다 — 무장이면 확인 왕복(위 docstring).
        # _leave_guard = 선택·큐(T3) ∨ 미저장 레시피 편집(147) — 데이터 미로드라도 상수·확정
        # 편집만으로 무장한다(데이터 교체 T3와 달리 세션 교체는 매핑도 폐기하므로).
        if self._bound_job and not p.get("confirm"):
            g = self._leave_guard()
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
                "붙여넣거나 고친 원문은 기안으로 저장할 수 없습니다. "
                "원문을 '템플릿으로 저장'한 뒤 저장하세요.")}
        # 캐시된 template_path 재검증(리뷰 5c P2) — 이 세션이 경로를 캐시한 뒤 템플릿 관리에서
        # 삭제·이동됐을 수 있다. 빈 문자열만 보던 위 게이트는 통과하지만, 그러면 다시 못 여는
        # 템플릿을 가리키는 Job 이 생긴다. 지금 실 파일인지 읽어 확인한다(confirm-or-alarm).
        try:
            disk_text = Path(self._template_path).read_text(encoding="utf-8")
        except OSError:
            return {"ok": False, "error": (
                "이 기안의 템플릿 파일이 사라졌거나 이동했습니다. 템플릿을 다시 고른 뒤 저장하세요.")}
        # 템플릿 파일 **내용** 드리프트(리뷰 5c 3R P1 / 216) — 세션이 배접 원문을 읽은 뒤 템플릿
        # 관리에서 그 파일이 편집되면, 맞춰 둔 매핑은 옛 원문 기준인데 Job 은 새 원문을 가리켜
        # 토큰이 어긋난다(옛 매핑 조용한 소실·새 토큰 미해소). 파일 내용이 세션 baseline(vm.
        # template_text — 같은 read_text 로 실린 값)과 다르면 막고 재선택을 요구한다(재선택이 새
        # 원문으로 매핑을 다시 세운다). 존재만 보던 위 게이트는 이 불일치를 통과시켰다.
        if disk_text != self.vm.template_text:
            return {"ok": False, "error": (
                "이 기안의 템플릿이 템플릿 관리에서 바뀌었습니다. 맞춰 둔 정의가 옛 원문 기준이라,"
                " 템플릿을 다시 고른 뒤 저장하세요.")}
        # 빈 레시피 가드(리뷰 5c 2R P1 / 196) — **실제 영속될 프로파일**을 기준으로 판정한다.
        # 휘발 승격은 내용 행을 강제 확정하니 has_content 로 충분하지만, 저장 모드(재저장)는
        # 사람의 확정을 존중하므로(force-confirm 안 함) 확정을 전부 해제하면 to_profile 이 빈
        # 프로파일이 된다. has_content(확정 무시)만 보면 그 게이트를 통과해 저장분을 조용히
        # 빈 레시피로 덮어쓴다 — 저장 모드는 emits_any_value(확정+내용)로 본다.
        if self._bound_job:  # 저장 모드 = 사람 확정 존중 → 실제 영속될 프로파일(확정+내용)로 판정
            would_emit = self.mapping.emits_any_value()
            empty_msg = ("저장할 확정된 값이 없습니다. 토큰에 데이터 열을 연결하거나 값을 직접"
                         " 입력해 확정한 뒤 저장하세요.")
        else:  # 휘발 승격 = 내용 행을 강제 확정하므로 has_content 로 충분
            would_emit = any(r.has_content() for r in self.mapping.rows)
            empty_msg = "맞춰진 토큰이 없습니다. 데이터 열을 연결하거나 값을 직접 입력한 뒤 저장하세요."
        if not would_emit:
            return {"ok": False, "error": empty_msg}
        name = p.get("name", "").strip()
        if not name:
            return {"ok": False, "error": "기안 이름을 입력하세요."}
        # 덮어쓰기 판정·메타 보존·저장을 **한 임계구역**에서(리뷰 5c P1, 에디터 _save_locked 동형).
        # 잠금 밖에서 exists/load 로 결정하면, 확인~저장 사이(모달이 열린 동안 포함) 다른 pywebview
        # writer 가 이 이름을 새로 만들거나 바꿔치기할 때 **확인한 것과 다른 작업을 덮거나 새
        # 작업을 무확인 덮어쓴다**(TOCTOU). 잠금 안에서 지금 상태로 판정·저장한다.
        with self.registry.write_lock():
            exists = self.registry.exists(name)
            # 이 slug 자리의 현재 Job 을 잠금 안에서 **한 번** 읽어 게이트(덮어쓰기/드리프트)와
            # 메타 보존에 함께 쓴다(두 번 읽으면 그 사이 또 갈릴 수 있다).
            existing = None
            if exists:
                try:
                    existing = self.registry.load(name)
                except (FileNotFoundError, ValueError):
                    existing = None  # 손상 — 추측 금지(victim 이름 불명·메타 승계 포기)
            # 확인 문안을 **잠금 안에서 지금** 성형하고 사용자가 확인한 문안과 대조한다(에디터
            # _overwrite_gate 동형). 두 갈래를 한 판정으로 모은다:
            #   ① 자기 재저장(name==bound): 로드 이후 디스크가 바뀌었으면(내용 지문 불일치) '열어
            #      둔 사이 외부 변경'을 확인한다(리뷰 5c 2R P1 / 212 — 무확인 stale 덮어쓰기 금지).
            #   ② 다른 이름 덮어쓰기(name!=bound): victim 재진술.
            # 모달이 열린 사이 대상이 바뀌면 문안이 달라져 confirm:true 라도 **새 문안으로 다시
            # 묻는다**(확인한 것과 다른 것을 무확인 덮어쓰지 않는다).
            gate_text = ""
            if name == self._bound_job:
                if existing is not None and self._baseline_fingerprint(existing) != self._editing_fingerprint:
                    # 관측한 **버전**을 확인 문안에 못박는다(리뷰 5c 6R P1 / 273). 이름만 든 문안은
                    # 버전 불가지라, 모달이 열린 사이 또 다른 외부 버전으로 바뀌어도 confirmed_text
                    # 가 그대로 맞아 새 버전을 무확인 덮는다(victim 게이트가 victim 이름으로 버전을
                    # 못박는 것과 동형 — 자기 재저장은 이름 불변이라 내용 다이제스트로 못박는다).
                    digest = hashlib.sha256(
                        self._baseline_fingerprint(existing).encode("utf-8")).hexdigest()[:8]
                    gate_text = (
                        f"열어 둔 사이 기안 작업 '{name}' 이(가) 다른 곳에서 바뀌었습니다"
                        f" (현재 내용 #{digest}).\n지금 저장하면 그 변경을 이 세션의 상태로 덮어씁니다.")
                elif exists and existing is None:  # 손상 — 내용 불명, 조용히 덮지 않는다
                    gate_text = (
                        f"기안 작업 '{name}' 파일이 손상돼 현재 내용을 확인할 수 없습니다.\n"
                        "지금 저장하면 그 자리를 이 세션의 상태로 덮어씁니다.")
            elif exists:
                victim = existing.name if existing is not None else ""  # 손상 = 이름 불명
                gate_text = overwrite_confirm_text(name, victim)
            if gate_text and (not p.get("confirm") or p.get("confirmed_text", "") != gate_text):
                return {"ok": False, "needs_confirm": True, "name": name, "confirm_text": gate_text}
            if not self._bound_job:  # 휘발 승격 — 확정 열이 숨어 있었으니 저장이 확정(내용 있는 행)
                for i, r in enumerate(self.mapping.rows):
                    if r.has_content():
                        self.mapping.set_confirmed(i, True)
            profile = self.mapping.to_profile(name)
            if existing is not None:
                # 기존 메타 보존(리뷰 5c P1) — 이 화면이 편집하지 않는 필드(tags·last_run_at·
                # default_dataset_ref·version·filename_pattern·group)를 전부 승계하고 template_path·
                # mapping·**name** 만 갈아 끼운다. name 명시(리뷰 5c 2R P2 / 235): slug 만 같고
                # 표기가 다른 victim(예 '예산/2026' vs '예산_2026')을 덮으면 preserved.name 을
                # 그대로 두어 파일이 victim 이름을 유지하고 결속(_bound_job)과 어긋난다.
                job = replace(existing, name=name, template_path=self._template_path, mapping=profile)
            else:
                # 새 이름(빈 자리) — 결속 원본이 있으면 그 그룹을 승계한다(리뷰 5c 2R P2 / 237):
                # 그룹 있는 저장 기안을 「다른 이름으로 저장」하면 사본이 조용히 「그룹 없음」으로
                # 튀지 않게. 결속 원본이 손상·부재면 무그룹(추측 금지).
                group = ""
                if self._bound_job:
                    try:
                        group = self.registry.load(self._bound_job).group
                    except (FileNotFoundError, ValueError):
                        group = ""
                job = Job(name=name, template_path=self._template_path,
                          mapping=profile, group=group)
            self.registry.save(job, allow_overwrite=True)
            self._editing_fingerprint = self._baseline_fingerprint(job)  # 저장분 = 새 baseline
        # 미결속(휘발) 승격이었나 — 결속 세우기 **전에** 관측한다(아래서 _bound_job 을 덮으므로).
        was_unbound = not self._bound_job
        # 제자리 결속 — 세션 그대로, 저장 모드 전이(원문 읽기 전용). 목록에 새 행이 선다.
        self._bound_job = name
        self._source_readonly = True
        self._source_dirty = False
        self._pasted_unbacked = False
        # 방금 이 매핑을 영속했으니 미저장 편집은 없다 — 표지를 내린다(리뷰 5c 3R P2 / 301).
        # 안 내리면 저장 직후 다른 기안으로 떠날 때 _leave_guard 가 있지도 않은 "미저장 매핑
        # 편집"으로 거짓 파괴 확인을 띄운다(저장 = 새 baseline, restore/fresh 와 동형).
        self._map_dirty = False
        # 미결속 승격이면 스태시를 비운다(리뷰 5c 5R P2 / 310). 승격한 세션이 곧 이 저장 기안
        # 이라 되돌아갈 별도 휘발이 없는데, 스태시가 그 세션의 vm·mapping 객체를 계속 alias
        # 하면 「이번 세션」 클릭이 방금 저장한 초안을 '미저장'인 척 되살리고 저장-모드 편집이
        # 그 alias 로 샌다. 「다른 이름으로 저장」(결속 상태에서 시작)은 붙여넣던 별도 휘발이
        # 스태시에 살아 있어야 하므로 건드리지 않는다.
        if was_unbound:
            self._volatile_stash = None
        return {"ok": True, "name": name}

    def _do_validate_save_name(self, p: dict) -> dict:
        """저장명 prompt의 보존형 인라인 검증. 변이 없이 입력만 판정한다."""
        if not p.get("name", "").strip():
            return {"ok": False, "error": "기안 이름을 입력하세요."}
        return {"ok": True, "error": ""}

    _do_validate_save_name.is_query = True

    # ---------------------------------- 「템플릿으로 저장」 승격(#148 슬라이스 6, #135)
    #
    # 구 「빠른 기안」이 혼자 갖고 있던 두 번째 승격 동사를 흡수한다(삭제는 의무를 상속한다).
    # 「기안으로 저장」(위 `_do_save_job`)은 **바인딩**(Job = template_path+매핑+그룹)을 남기고
    # **라이브러리 배접 원문만** 자격이 있다 — 붙여넣거나 고친 원문은 파일과 어긋나 저장할 수
    # 없어, `_do_save_job` 의 비활성 사유가 "「템플릿으로 저장」한 뒤 저장하세요"로 안내한다.
    # 그 동사가 여기다: 세션 **원문 자체**를 TXT 라이브러리(.txt 파일)로 동결한다(값은 저장 대상
    # 아님). 착지 뒤 세션은 죽지 않고 정체만 라이브러리 배접으로 승격해(원문≠파일 표지 해제) 곧
    # 「기안으로 저장」 자격이 선다. 노출은 **휘발 세션 전용**(스냅샷 `can_save_template`) — 저장
    # 기안 결속(saved) 모드는 원문이 이미 라이브러리에 있어 재저장이 무의미하다(사용자 결정).
    def _do_promote_info(self, p: dict) -> dict:
        """저장 모달 프리필 — 이름 후보·그룹 후보·현재 그룹(무변이 질의).

        정체 원천은 ``_template_path`` 다(``vm.template_name`` 이 아니라): 신 세션에서 원문 라이브
        편집(``set_template_text``)은 ``template_name`` 을 **None 으로** 지우지만 배접 파일 경로는
        유지한다(수정됨 표지 = ``_source_dirty``, 경로 = ``_template_path``). 그래서 편집한
        라이브러리 템플릿도 원 이름으로 프리필해 **되돌려 쓰기**(같은 파일 덮어쓰기)가 정상 경로가
        된다(구 「빠른 기안」은 origin=='lib' 이 편집에도 살아 같은 효과). 붙여넣기(경로 없음)와
        **미등록 배접**(루트 밖 손상 Job·대소문자 구분 FS 의 미스캔 ``.TXT``, 리뷰 F1·G)은 빈칸에서
        사람이 짓는다 — 미등록 경로의 stem 을 라이브러리 이름처럼 프리필하면 그 정체를 되돌려-쓰는
        것처럼 오도한다(실제 저장은 루트 안 새 항목으로 낙착, `_resolve_dest` 참조). 프리필은 실제
        ``list_templates`` 멤버십(`_registered_name_of_path`)으로만 연다. 그룹 후보는 **살아있는
        지정만** 센다(고아 그룹 부활 금지 — #108 결정 8). 판정은 여기 Python 단일 출처다.
        """
        reg_name = self._registered_name_of_path(self._template_path) if self._template_path else None
        keys = self._library_keys()
        group = ""
        if reg_name is not None:
            group = self._groups.group_of(rel_key(Path(self._template_path), self._registry.directory))
        return {
            "name": reg_name or "",
            "groups": self._groups.existing_groups(keys),
            "group": group,
        }

    _do_promote_info.is_query = True  # 무변이 질의 — 재렌더 유발 금지

    def _library_keys(self) -> "list[str]":
        """살아있는 txt 템플릿의 그룹 식별키 — 관리 화면과 같은 규칙(루트 상대경로+확장자).

        키는 **실제 경로**에서 뽑는다(구 화면 리뷰 2R P2): 이름에 소문자 ``.txt`` 를 합성하면
        Windows 에서 정상 등록되는 ``REPORT.TXT`` 의 키가 관리 화면(실경로 기준)과 갈라진다.
        """
        root = self._registry.directory
        return [rel_key(t.path, root) for t in self._registry.list_templates()]

    def _registry_name(self, path: "Path") -> str:
        """실제 경로 → 레지스트리 이름(루트 상대·확장자 제외, POSIX).

        접미사 **대소문자에 의존하지 않는다**(구 화면 리뷰 2R P2): ``removesuffix(".txt")`` 는
        ``REPORT.TXT`` 를 못 벗겨 세션 이름과 레지스트리 이름이 갈라지고, 그러면 콤보 현재 선택·
        그룹 조회·다음 저장의 경로 재발견이 전부 어긋난다.
        """
        try:
            rel = path.relative_to(self._registry.directory)
        except ValueError:  # 루트 밖(방어) — rel_key 폴백과 같은 규율
            rel = Path(path.name)
        return rel.with_suffix("").as_posix()

    def _registered_name_of_path(self, path: "Path | str") -> "str | None":
        """이 경로가 **등록된** 라이브러리 템플릿이면 그 레지스트리 이름, 아니면 None(리뷰 F1·G).

        "루트 안 + 존재"만으론 부족하다(리뷰 G): 대소문자 구분 FS 에서 대문자 ``.TXT`` 는
        ``template_media`` 로는 TXT 로 분류되지만 ``list_templates``(``*.txt`` 스캔)엔 안 잡혀
        **선택 가능한 라이브러리 항목이 아니다**. 그런 경로를 되돌려-쓰기 관용으로 재사용하면 그
        외부/미등록 파일을 덮으며 라이브러리 항목은 안 생긴다(계약 거짓말). 재사용·프리필 관용은
        실제 ``list_templates`` **멤버십**(실경로 일치)으로만 연다 — save_job 의 JobRegistry 멤버십
        판정과 동형. 등록이면 루트 안이 함의되므로 별도 루트 검사는 이 하나로 대체한다.
        """
        try:
            rp = Path(path).resolve()
        except OSError:
            return None
        for t in self._registry.list_templates():
            try:
                if t.path.resolve() == rp:
                    return t.name
            except OSError:
                continue
        return None

    def _resolve_dest(self, raw_name: str) -> "Path":
        """제출된 이름 → 저장 경로. 실패는 :class:`ValueError`(인라인 재진술용).

        **현 세션이 든 라이브러리 정체와 같은 이름이면 그 파일의 실제 경로**를 돌려준다(구 화면
        Codex 리뷰 P2). 정체는 ``_template_path`` 로 판정한다(``vm.template_name`` 은 편집에 지워짐 —
        위 promote_info 참조). 재귀 스캔이 하위폴더 파일을 ``하위폴더/이름`` 으로 노출하므로 프리필도
        그 값인데, 그걸 새 이름처럼 검증하면 ``/`` 때문에 거부돼 **하위폴더 템플릿은 고쳐서 되돌려
        쓰는 정상 경로가 언제나 막힌다**. 반대로 경로 구분자를 허용하면 새 이름으로 루트 밖·임의
        하위 경로를 만들 수 있으므로, 관용은 **현 세션의 배접 파일이 실제 등록된 그 템플릿일 때만**
        연다(리뷰 F1·G — ``_registered_name_of_path``: 루트 밖·미등록 ``.TXT`` 배접은 제외). 그 외엔
        ``<루트>/<검증된 이름>.txt`` 새 항목으로 낙착해 라이브러리 안에 사본이 생긴다(붙여넣기는
        ``_template_path=="" `` 라, 새 이름엔 구분자 계속 금지라 이 관용에 못 든다).
        """
        name = (raw_name or "").strip()
        if name and self._template_path and self._registered_name_of_path(self._template_path) == name:
            return Path(self._template_path)
        return self._registry.directory / (
            validate_template_name(raw_name) + TextTemplateRegistry.SUFFIX
        )

    def _do_save_template(self, p: dict) -> dict:
        """「템플릿으로 저장」(결정 33·34) — 세션 원문을 TXT 라이브러리로 승격. 값은 저장 대상 아님.

        동명은 **확인 게이트**를 거친다(결정 34). 관리 화면의 두 기존 경로와 다른 계약인 것은
        의도다: 「가져오기」는 ``이름 (2).txt`` 접미로 회피하고 「새 TXT」는 loud 거부하는데, 여기선
        **되돌려 쓰기가 본래 목적**(라이브러리 사본을 고쳐 왔으니 같은 이름으로 되돌아가는 게 정상
        경로)이라 회피도 거부도 사용자가 원한 일을 막는다. 대신 파괴를 확인받는다.

        저장 뒤 세션은 죽지 않고 **정체만 승격**한다(구 ``mark_saved_as`` 등가): ``vm.template_name``
        을 새 이름으로, ``_template_path`` 를 실경로로, ``_source_dirty`` 를 내린다 — 채우던 값·데이터
        겨눔·큐 진행은 그대로라 하던 일을 잇고, 곧 「기안으로 저장」 자격(라이브러리 배접·미수정)이
        선다. 매핑·원문은 불변이라 재구성하지 않는다(토큰 집합 그대로).
        """
        if not self.vm.template_text.strip():  # 빈손 승격 = 빈 템플릿 양산(복사 게이트 동형)
            return {"ok": False, "error": "저장할 템플릿 원문이 없습니다."}
        root = self._registry.directory
        try:
            dest = self._resolve_dest(p.get("name", ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}  # 모달 인라인 재진술(창 밖 예외 금지)
        name = self._registry_name(dest)
        # 덮어쓰기 재검증~교체를 **한 임계구역**으로 묶는다(리뷰 F5 — save_job `write_lock` 동형).
        # 종전 F2 지문 게이트는 지문 재-읽기와 write_text_atomic(os.replace) 사이에 락이 없어,
        # 그 미세 창에서 다른 스레드(관리 화면 「새 TXT」·편집)가 대상을 바꾸면 confirmed_text 가
        # 여전히 맞아 **검토한 적 없는 내용을 덮었다**. 락 안에서 지금 디스크 내용의 지문을 다시
        # 읽어 문안을 성형하고, 재시도의 confirmed_text 와 대조한다: 락을 잡은 채 대조→교체하므로
        # 그 사이 다른 writer 가 끼어들 수 없다(모든 템플릿 writer 가 같은 락을 공유). 지문이
        # 어긋나면(락 밖에서 그새 바뀜) confirm:true 라도 새 문안으로 다시 묻는다. (락은 스레드
        # 직렬화다 — 단일 인스턴스 뮤텍스가 다른 프로세스를, 원자 교체가 부분 쓰기를 이미 막는다;
        # 외부 편집기의 락 밖 변경은 재-읽기 지문이 최소화한다.)
        with self._registry.write_lock():
            if dest.exists():
                try:
                    digest = hashlib.sha256(dest.read_bytes()).hexdigest()[:8]
                except OSError:
                    digest = "????????"  # 읽기 실패 — 내용 불명, 조용히 덮지 않게 그래도 게이트
                gate_text = (
                    f"라이브러리에 이미 '{name}' 템플릿이 있습니다 (현재 내용 #{digest}). "
                    "덮어쓰면 기존 내용은 되돌릴 수 없고, 채운 값 없이 원문만 저장됩니다."
                )
                if not p.get("confirm") or p.get("confirmed_text", "") != gate_text:
                    return {"ok": False, "needs_confirm": True, "name": name, "confirm_text": gate_text}
                overwritten = True
            else:
                overwritten = False
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(str(dest), self.vm.template_text)
        # 그룹 지정은 **저장 성공 뒤에만** — 파일 없는 키에 지정을 남기면 고아가 된다. 여기서
        # 실패해도(설정 파일 읽기 전용 등) **저장 자체는 이미 일어났다**(구 화면 Codex 리뷰 P2):
        # 예외로 되던지면 "실패"라 말하면서 라이브러리 내용은 바뀐 상태가 되고 재시도는 난데없이
        # 덮어쓰기 게이트를 만난다. 파일 쓰기를 되돌리면 덮어쓰기에서 원본 복원이 불가해 더 나쁘다
        # — 성공으로 보고하되 못 남긴 것을 정확히 진술한다(일어난 일과 안 일어난 일을 가른다).
        key = rel_key(dest, root)
        group_error = ""
        try:
            self._groups.set_group(key, p.get("group", ""))
        except (OSError, ValueError) as exc:
            group_error = str(exc) or exc.__class__.__name__
        # 정체 승격(구 mark_saved_as 등가) — 세션은 그대로, 원문만 라이브러리 배접이 된다.
        self.vm.template_name = name
        self._template_path = str(dest)
        self._source_dirty = False
        self._pasted_unbacked = False
        return {
            "ok": True,
            "name": name,
            "overwritten": overwritten,
            "group_error": group_error,
            # 실패 뒤 **실제로 남아 있는 그룹**(구 화면 리뷰 2R P2). ``set_group`` 은 저장 성공 뒤에만
            # 인메모리를 교체하므로 실패 시 이전 지정이 그대로 산다 — "「그룹 없음」에 있다"고
            # 단정하면 관리 화면 상태와 어긋난 거짓이 된다(over-warn). 표면은 이 값을 그대로 재진술.
            "group": self._groups.group_of(key),
            # 콤보는 initial() 에서 한 번 받아 캐시하므로, 새 이름이 목록에 서려면 갱신본을 함께
            # 돌려준다(방금 만든 템플릿이 콤보에 없는 어긋남 방지).
            "templates": self.vm.template_names(),
        }

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
            # 로드 시점 지문(212)도 새 이름으로 갱신한다(리뷰 5c 3R P2 / 260) — 드리프트 지문이
            # name 을 포함하므로, 안 갱신하면 다음 자기 재저장이 늘 드리프트 게이트에 걸려 거짓
            # 외부 변경을 주장한다(개명은 내용 불변인데 지문만 옛 이름으로 남아서).
            try:
                self._editing_fingerprint = self._baseline_fingerprint(
                    self.registry.load(self._bound_job))
            except (FileNotFoundError, ValueError):
                pass  # 손상·경합 — 다음 refresh/재선택이 정리(무리한 추측 금지)
        return {"ok": True}

    def _do_clone_job(self, p: dict) -> dict:
        """작업 복제 — 레지스트리 clone(유일 이름 합성·이력 미계승) 위임. 그룹 계승 = 인접."""
        return {"ok": True, "name": self.registry.clone(p["name"])}

    def _do_delete_job(self, p: dict) -> "dict | None":
        """작업 삭제 — 무확인 호출은 재진술 자료를 돌려주고 멈춘다(RC-02 왕복 동형).

        결속 중인 기안을 삭제하면 휘발 세션으로 복귀한다 — 사라진 정의가 저장 모드로 계속
        떠 있지 않게(스태시해 둔 휘발이 있으면 그대로, 없으면 새 휘발).

        **결속 세션 소실 재진술(리뷰 5a 2R P1, `screen_job._do_delete_job` 동형)**: 지금 결속한
        저장 기안을 삭제하면 그 세션의 데이터·선택·큐 진행이 함께 사라진다(Job 계약 = 데이터/행
        미저장 → 복원 불가). ``open_session`` 과 무장 수치(:meth:`_guard_state`)를 동봉해 표면이
        세션 진행 소실만 한 모달로 말하게 한다(confirm-or-alarm). 결속 아닌 기안과 클린
        결속은 복원 가능한 휴지통 이동이므로 사전 확인 없이 실행한다."""
        name = p["name"]
        if not p.get("confirm"):
            if name == self._bound_job:
                guard = self._leave_guard()
                if guard["armed"]:
                    return {"needs_confirm": True, "name": name,
                            "open_session": True, **guard}
        self._deleted_job_slot = self.registry.soft_delete(name)
        if name == self._bound_job:
            self._restore_volatile()
        return {"ok": True, "undo": True, "name": name}

    def _do_undo_delete_job(self, p: dict) -> dict:
        if self._deleted_job_slot is None:
            return {"ok": False, "error": "복원할 최근 기안 작업이 없습니다."}
        name = self.registry.restore_soft_deleted(self._deleted_job_slot)
        self._deleted_job_slot = None
        return {"ok": True, "name": name}

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
