"""「문서 작업」(전역 라이브러리) 화면 컨트롤러 — browser + detail(webview 비의존).

계약 §19.6(전역 문서 작업 라이브러리)·§19.7(전역 작업 건강)의 표면. **홈 화면을 대체한다**
(재작성 F2, 지도 §10.8): 카드 나열 + group-by 렌즈였던 홈은 죽고, 저장된 작업을 찾는 자리가
이 화면 하나로 모였다. 링1 VM(:class:`~hwpxfiller.gui.home_state.HomeViewModel`)의 라이브러리
투영·건강 번역·facet 판정을 **그대로** 소비한다 — 백엔드 판정 재구현 0.

(링1 모듈은 ``home_state``·``HomeViewModel`` 이름을 유지한다 — 지도 §10.3 이 "재작성 무영향"
자산으로 배정했다. 링2 만 어휘를 정산했다: 이 파일·푸시 채널·액션 키가 ``library`` 다.)

**허브 내비게이션**: 이 컨트롤러는 다른 화면 컨트롤러를 모른다. 「문서 만들기에서 사용」·
「작업 편집」 같은 이동은 링2(웹)가 대상 화면의 자체 dispatch 로 미리 겨눈 뒤 셸 라우터
(앱 셸이 내는 `Nav` — 전역이 아니라 주입으로 닿는다)로 전환한다.

**좌 목록 관리 동사의 소유(지도 §10.8 판정 F)**: 이름 변경·그룹 지정·그룹 이름 변경·해산은
「문서 만들기」 컨트롤러가 계속 소유하고 링2가 교차 화면 dispatch 로 부른다 — 그 동사들은
열린 세션의 정체(``job_name``)와 결속돼 있어 여기서 재구현하면 판정이 둘로 갈린다. 이 화면이
직접 소유하는 것은 라이브러리 자신의 축(보기·방식·검색·facet·접힘·선택)과, 세션 정체와 무관한
관리 동사(즐겨찾기·복제·태그·삭제·다시 연결·손상 조치)뿐이다.

**그룹 접힘의 소유**: 이 화면이 쓰고(``toggle_group``) 「작업」 좌 목록이 함께 읽는다. 영속
키는 기존 ``job_collapsed_groups`` 를 그대로 쓴다 — 키 개명은 마이그레이션 비용만 낳고 얻는
것이 어휘뿐이다(좌 목록은 F2 PR-B 에서 죽고 이 화면이 유일 소유자가 된다).

**남은 스코프 경계(조용히 빠뜨리지 않고 명시)**:
- Template/Binding **판본**은 §19.6 상세가 요구하지만 F7 신설분이라 오늘 존재하지 않는다.
  빈 자리·「준비 중」 표기도 두지 않는다(없는 기능을 있는 척하지 않는다, 지도 §10.8 판정 D).
- 상세 「필드 연결」 표는 **저장된 항목 키**를 보인다(판정 C) — 현재 데이터는 「문서 만들기」
  세션 소유라 여기서 읽으면 화면 간 결합이 생긴다. 되깎기 조건은 지도에 적혀 있다.
- 기안 **템플릿** 목록(구 홈 txt 트랙)의 승계처는 편집기 「템플릿」 탭 TXT 밴드(F6 PR-B)다.
  TXT **작업**은 이 화면에 합류했고 방식 필터(「온나라 기안」)가 구 좌 목록의 최종 승계처다.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..application.jobs import (
    CORRUPT_PATH_REJECT,
    clone_job,
    load_job,
    restore_job,
    set_favorite,
    soft_delete_job,
)
from ..domain.engine import HwpxEngine
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.text_registry import TextTemplateRegistry
from ..external.template_inspection import template_compile_status
from ..gui.compile_badge import badge_level
from ..gui.home_state import (
    NO_GROUP_LABEL,
    HomeViewModel,
    JobRow,
    field_binding_rows,
    library_health,
    library_health_causes,
    library_mode_of,
)
from ..gui.work_mode import work_mode_label, work_mode_of_filter_value
from .screens import PushSink, relink_job_template
from ..external.settings import load_job_collapsed_groups, save_job_collapsed_groups

def mode_label(filter_value: str) -> str:
    """필터 값 → 작업 방식 표시 문구. 링1(:mod:`~hwpxfiller.gui.work_mode`) 위임.

    F6 어휘 통일(지도 §10.15 판정 A) 이전에는 이 표가 여기 링2에 있었다. TXT 가 「문서
    만들기」에 합류하면서 같은 축을 세 표면(후보 카드·문서 탐색·라이브러리)이 그리게 됐고,
    각자 문구를 지으면 같은 상태를 다르게 부르는 자리가 셋이 된다 — 그래서 라벨은 링1이
    소유하고 여기는 **필터 어휘 → 방식 어휘 번역**만 남는다(두 축이 다른 이유는 판정 A).
    """
    return work_mode_label(work_mode_of_filter_value(filter_value))


def primary_action(row: JobRow) -> dict:
    """상세의 **주 행동** — 목적지·라벨을 Python 이 낸다(리뷰 3R 근본 조치).

    되풀이된 결함류: 표면이 **표시용으로 정규화한 매체**(:func:`library_mode_of` 는 미연결을
    `hwpx` 로 센다 — 사용자가 고치러 오는 필터에 남기려고)에서 **행동 경로**를 파생했다.
    그런데 「문서 만들기에서 돌 수 있나」의 판정은 원시 ``Job.media`` 를 쓰는 `rank_available`
    이 낸다. 같은 상태에 두 어휘가 생겨 표시와 행동이 갈렸고, TXT(리뷰 2R)와 미연결
    (리뷰 3R)이 그 한 클래스의 두 표본이었다 — 둘 다 「후보에서 배제 → 확인 필요 탭에서도
    배제 → 빈 화면 착지」로 끝났다.

    그래서 목적지를 **작업 자체의 상태**(데이터 무관 — §19.7 이 이 화면에 준 권한)에서
    한 번에 판정하고 표면은 그것을 그대로 쓴다. 데이터 의존 판정(이 데이터로 돌 수 있나)은
    여전히 「문서 만들기」의 `prefer_work` 몫이다 — 층이 갈리지 섞이지 않는다.

    ``target`` = 그 작업을 실제로 받을 수 있는 표면. ``hint`` 는 왜 그쪽인지(없으면 "").
    """
    if not row.template_linked:
        # 미연결은 "미상 매체"가 아니라 저작 중 작업이다 — 고칠 수 있는 곳으로 보낸다.
        # 「문서 만들기」로 보내면 후보에서 배제돼 빈 「확인 필요」에 착지한다(리뷰 3R).
        return {"target": "editor", "label": "템플릿 연결하기",
                "hint": "템플릿을 연결해야 문서를 만들 수 있습니다."}
    # 여기부터는 연결된 작업이라 표시 정규화와 원시 매체가 일치한다(어휘가 갈리지 않는다).
    # TXT 도 「문서 만들기」가 받는다(F6 PR-B — 실행 버튼 2분기는 job 의 판정 D 가 이미
    # 소유: TXT 작업이면 「검토·복사 시작」으로 서고 작업대로 이어진다). 구 「기안에서
    # 열기」 분기는 승계처가 서면서 걷혔다(§10.15.15 점검표 2행).
    if row.media not in ("hwpx", "txt"):
        return {"target": "editor", "label": "작업 편집에서 확인",
                "hint": "지원하지 않는 작업 방식입니다."}
    return {"target": "job", "label": "문서 만들기에서 사용", "hint": ""}


def _job_row_dict(r: JobRow) -> dict:
    """행 1건 성형 — 링1 JobRow 표면만 읽는다(VM 로직 재구현 없음).

    §19.6 "행은 이름, 작업 방식 텍스트, 사용자 group, 최근 사용, 작업 건강, 즐겨찾기를
    보여준다". 컴파일 배지의 심각도(pill 색 레벨)는 :func:`badge_level`(RC-29 단일 어휘)로
    파생해 템플릿 관리 화면과 같은 상태에 같은 신호를 낸다.
    """
    mode = library_mode_of(r)
    severity, text = library_health(r)
    # 태그는 **행에 싣지 않는다**(리뷰 1R P1 의 근본 조치): 행은 태그를 렌더하지 않는데
    # 페이로드에만 있으면, 표면이 걸러진 목록에서 정체를 조립하는 미끼가 된다 — 실제로
    # 필터 밖 선택의 태그가 `{}` 로 프리필돼 확인 한 번에 전멸했다. 정체는 상세가 소유한다.
    return {
        "name": r.name,
        "meta_line": r.meta_line(),
        "compile_badge": r.compile_badge,
        "badge_level": badge_level(r.compile_state),  # muted/warn/ok/danger
        "last_run_display": r.last_run_display,
        "template_missing": r.template_missing,
        "runnable": r.is_runnable(),
        "group": r.group,
        "favorited": bool(r.favorited_at),
        # 필터가 쓰는 **정규화된** 매체를 그대로 싣는다(리뷰 P2): 미연결을 hwpx 로 걸러 놓고
        # 페이로드엔 빈 값을 주면 소비자가 같은 행을 다른 방식으로 읽는다(표시=판정 정합 붕괴).
        "media": mode,
        "mode_label": mode_label(mode),
        # 심각도 숫자까지 싣는다: 문구만 주면 소비자가 경고(2)와 차단(3)을 구분 못 해
        # §19.7 건강 축을 "사유 있음/없음"으로 뭉갠다.
        "health": {"severity": severity, "text": text},
    }


class LibraryController:
    """「문서 작업」 — 링1 HomeViewModel 소유·위임. 순수 데이터 화면(네이티브 표면 없음)."""

    name = "library"

    def __init__(self, registry: JobRegistry, text_registry: TextTemplateRegistry,
                 push: PushSink, *, engine: HwpxEngine,
                 pool_registry: DatasetPoolRegistry,
                 generation_lock: "threading.Lock") -> None:
        # pool_registry 는 손상 등록 데이터 경보(#45) 용 — composition root(webapp.app)가
        # 주입한다(자기 생성 폴백은 #570 에서 제거 — locator 뒷문 금지).
        # text_registry 는 VM 이 보는 txt 트랙 판정에 쓰인다.
        self.vm = HomeViewModel(
            registry, text_registry,
            pool_registry,
            engine=engine,
            inspect_status=template_compile_status,
        )
        # 템플릿 다시 연결(#67)용 주입 레지스트리 — vm.registry 우회 금지 가드(#44,
        # test_architecture)와 정합: seam 밖 durable 뮤테이션은 공유 게이트
        # (relink_job_template)가 담당하므로 주입분을 직접 보관한다(run.registry 동형).
        self._job_registry = registry
        self._engine = engine
        # 「문서 만들기」와 **같은** 생성 자물쇠(9R P1) — 이 화면의 재연결도 durable 규칙을
        # 쓰므로 진행 중 런과 겹치면 안 된다. **필수 주입**이다(P2-24 폴백 제거): 화면이
        # 자기 것을 세우면 run transaction 상태의 제2 정본이 된다(#570 pool_registry 동형).
        self._generation_lock = generation_lock
        self._push_sink = push
        self._deleted_job_slot = None
        # 「모든 작업」 보기의 그룹 접힘(§19.6 ``collapsedGroups``) — 보기만 바꾸고 행을
        # 집합에서 빼지 않는다. 영속은 「작업」 좌 목록과 **같은 설정 키**(단일 정본).
        self._collapsed: "set[str]" = set(load_job_collapsed_groups())
        # 상세 패널이 겨눈 작업(§19.6 ``selectedWorkId``) — **활성 작업과 무관**하다.
        # 여기서 행을 골라도 「문서 만들기」의 선택·데이터·승인은 불변이다(§19.6 서문).
        self.selected_work: str = ""
        # 타 화면 무장 세션 가드 조회 함수들(#268 리뷰) — app.py 가 작업·기안 컨트롤러의
        # ``session_guard_for`` 를 배선한다(생성 순서상 이 화면이 먼저라 사후 배선).
        self.session_guards: "list" = []

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    def _facets(self) -> "list[dict]":
        return [
            {
                "axis": fa.axis,
                "values": [
                    {"value": v.value, "count": v.count, "active": v.active}
                    for v in fa.values
                ],
            }
            for fa in self.vm.facets()
        ]

    def _sections(self) -> "list[dict]":
        """현재 보기의 구획 — 「모든 작업」만 사용자 group 으로 나뉘고 나머지는 평면.

        ``is_untagged`` 로 「그룹 없음」과 "나눌 group 이 없어 퇴화한 평면"을 가른다(링1
        계약) — 표면이 값으로만 키잉하면 퇴화 평면에 헤더가 붙는다. 접힘은 **행을 지우지
        않고** 표식만 실어 보낸다: 접었다고 건수가 달라지면 목록이 자기 사실을 배신한다.
        """
        out: "list[dict]" = []
        for sec in self.vm.library_sections():
            headed = bool(sec.value) or sec.is_untagged
            out.append({
                "value": sec.value,
                "label": NO_GROUP_LABEL if sec.is_untagged else sec.value,
                "count": sec.count,
                "is_untagged": sec.is_untagged,
                # 헤더가 있는 구획만 접을 수 있다 — 퇴화 평면엔 접을 헤더가 없다.
                "headed": headed,
                "collapsed": headed and sec.value in self._collapsed,
                "rows": [_job_row_dict(r) for r in sec.rows],
            })
        return out

    def _detail(self) -> "dict | None":
        """선택 행의 상세(§19.6) — 없거나 사라졌으면 ``None``(표면이 빈 상태를 그린다).

        「필드 연결」 표는 저장된 Binding 만 읽고(판정 C) 건강은 **전 원인**을 싣는다
        (§19.7 "상세에서 모든 실제 원인"). 판본 열은 F7 까지 만들지 않는다(판정 D).
        """
        if not self.selected_work:
            return None
        row = next((r for r in self.vm.rows() if r.name == self.selected_work), None)
        if row is None:  # 다른 화면에서 삭제·개명됐다 — 유령 상세를 그리지 않는다.
            return None
        try:
            job = load_job(self._job_registry, row.name)
        except Exception:  # noqa: BLE001 — 목록 성형과 상세 적재 사이의 파일 소실·잠김
            return None
        mode = library_mode_of(row)
        return {
            **_job_row_dict(row),
            # 정체 메타는 **상세만** 싣는다(행은 걸러진 투영이라 정체의 원천이 될 수 없다).
            "tags": dict(row.tags),
            "primary": primary_action(row),
            "template_name": row.template_name,
            # 템플릿 전체 경로(U2 §2.20, #342) — 상세의 「열기」·「폴더에서 보기」가 겨눈다.
            # 경보(템플릿 미연결 N건)는 이 화면이 내는데 파일을 열거나 폴더로 갈 길이 이
            # 화면에 없었다(계기판의 짝). 경로 검증은 백엔드 화이트리스트(app.py
            # ``_validate_owned``)가 이미 소유한다 — 신설은 이 한 칸뿐이다.
            "template_path": job.template_path,
            # §19.6: HWPX 는 파일 이름 규칙을, 온나라 기안은 실행 방식을 보여준다.
            "filename_pattern": row.filename_pattern if mode == "hwpx" else "",
            "run_note": (
                "채운 원문을 검토해 복사합니다(문서 파일을 만들지 않습니다)."
                if mode == "txt" else ""
            ),
            "health_causes": [
                {"severity": s, "text": t} for s, t in library_health_causes(row)
            ],
            "bindings": [
                {"template_field": b.template_field, "source_label": b.source_label,
                 "format_label": b.format_label, "blank": b.blank}
                for b in field_binding_rows(job)
            ],
        }

    def snapshot(self) -> dict:
        kpi = self.vm.kpi()
        return {
            # 조치가 필요한 조건만 경보로(#239 결정 8 승계) — 개수 타일은 렌더하지 않는다.
            "alerts": {
                "missing_template_count": kpi.missing_template_count,
                # 데이터 풀 손상 파일 수(#45) — VM 이 세는 값을 웹까지 나른다(0 위장 금지).
                "pool_corrupted": kpi.pool_corrupted,
            },
            "is_empty": self.vm.is_empty(),
            # 라이브러리 browser(§19.6) — 보기 4종 × 작업 방식 × 검색 × 태그 facet.
            "view": self.vm.library_view,
            "mode": self.vm.library_mode,
            "query": self.vm.library_query,
            "counts": self.vm.library_counts(),
            "facets": self._facets(),
            "sections": self._sections(),
            # 그룹 이동 다이얼로그의 도착지 후보 — **레지스트리 전역**이다(리뷰 1R P2).
            # 구획(`sections`)에서 파생하면 평면 보기(최근·즐겨찾기·확인 필요)나 켜진
            # 필터가 목록에서 뺀 그룹이 도착지에서도 사라진다: 있는 그룹으로 못 옮긴다.
            "group_names": self._job_registry.groups(),
            "selected": self.selected_work,
            "detail": self._detail(),
            # 손상 작업 — 숨기지 않고 시끄러운 위험 카드로(RC-05) + 조치 경로(#26 #8).
            "corrupt_rows": [
                {"file_name": c.file_name, "detail_line": c.detail_line(), "path": c.path}
                for c in self.vm.corrupt_rows()
            ],
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 library 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    # ------------------------------------------------------------- 라이브러리 축
    def _do_set_view(self, p: dict) -> None:
        """보기 교체(§19.6) — 검색어·방식 필터·facet 은 유지한다(축이 다르므로 서로 지우지 않는다)."""
        self.vm.set_library_view(p.get("view") or "")

    def _do_set_mode(self, p: dict) -> None:
        self.vm.set_library_mode(p.get("mode") or "")

    def _do_set_query(self, p: dict) -> None:
        self.vm.set_library_query(str(p.get("text", "")))

    def _do_toggle_facet(self, p: dict) -> None:
        self.vm.toggle_facet(p["axis"], p["value"])

    def _do_clear_facets(self, p: dict) -> None:
        self.vm.clear_facets()

    def _do_clear_filters(self, p: dict) -> None:
        """필터를 전부 지우고 「모든 작업」으로 — 0건 화면의 상주 출구(§8.4 도달성 면).

        보기·방식·검색·facet 넷이 이 화면의 절단자다. 0건이 됐을 때 어느 축이 범인인지
        일일이 되짚게 두면 필터 밖 작업에 도달할 길이 사실상 사라진다.
        """
        self.vm.clear_facets()
        self.vm.set_library_mode("")
        self.vm.set_library_query("")
        self.vm.set_library_view("")

    def _do_toggle_group(self, p: dict) -> None:
        """그룹 접힘/펼침 — 마지막 상태를 Python 설정에 영속(#74 전례).

        접힘은 **보기**만 바꾼다: 행은 집합에서 빠지지 않아 건수·검색 판정에 무영향이다.
        ``""`` 는 「그룹 없음」 구획. 「작업」 좌 목록과 같은 키를 쓰므로 그쪽 화면도 다음
        ``refresh`` 에서 같은 접힘을 본다(제2 정본 금지).
        """
        g = p["group"]
        if g in self._collapsed:
            self._collapsed.discard(g)
        else:
            self._collapsed.add(g)
        save_job_collapsed_groups(sorted(self._collapsed))

    def _do_select_work(self, p: dict) -> None:
        """상세 패널이 겨눌 행(§19.6 ``selectedWorkId``) — **활성 작업은 바뀌지 않는다**.

        빈 이름은 선택 해제다. 여기서 다른 작업을 열어도 「문서 만들기」의 선택·데이터·
        승인 상태는 유지된다(§19.6 서문 · 화면 머리 문안이 그 사실을 사용자에게 말한다).
        """
        self.selected_work = str(p.get("name", ""))

    def _do_toggle_favorite(self, p: dict) -> dict:
        """즐겨찾기 지정/해제(§18.5·§19.6 행) — 정렬 메타만 바꾼다.

        값은 표면이 보내는 **의도한 상태**(``value``)다 — 현재 값을 여기서 뒤집으면 빠른
        연속 클릭이 서로의 결과를 되돌린다(#215 동류). 시각은 레지스트리가 쓰기 잠금 안에서
        찍는다(같은 초 동률 방지 — §8.4 시각 정밀도 면, 「작업」 좌 목록과 같은 몸통).
        """
        name = p["name"]
        try:
            set_favorite(self._job_registry, name, bool(p["value"]))
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False,
                    "error": f"'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {exc}"}
        self.vm.refresh()
        return {"ok": True}

    # ------------------------------------------------------------- 관리 동사
    def _do_delete_job(self, p: dict) -> dict:
        """작업을 휴지통으로 옮긴다. 최근 1건은 앱에서 즉시 복원할 수 있다.

        **타 화면 무장 세션 가드(#268 리뷰, `screen_job._do_delete_job` 동형)**: 이 작업이
        작업·기안 화면에 무장 세션(재현 불가능한 수작업 선택·진행)으로 열려 있으면, 여기서의
        즉시 삭제가 그 화면 복귀 시 무확인 세션 소거로 이어진다 — 파일은 복원돼도 세션은 못
        돌아온다. 소유 화면들의 가드(:attr:`session_guards`)를 조회해 무장이면
        ``needs_confirm`` 재진술로 멈춘다(RC-02 왕복 동형). 클린/무관 세션은 30일 휴지통과
        최근 1건 복원에 맡긴다."""
        name = p["name"]
        if not p.get("confirm"):
            for guard_of in self.session_guards:
                g = guard_of(name)
                if g is not None:
                    return {"needs_confirm": True, "name": name, "open_session": True, **g}
        self._deleted_job_slot = soft_delete_job(self._job_registry, name)
        if name == self.selected_work:
            self.selected_work = ""  # 유령 상세 금지 — 사라진 행을 겨눈 채로 두지 않는다.
        self.vm.refresh()
        return {"ok": True, "undo": True, "name": name}

    def _do_undo_delete_job(self, p: dict) -> dict:
        if self._deleted_job_slot is None:
            return {"ok": False, "error": "복원할 최근 작업이 없습니다."}
        name = restore_job(self._job_registry, self._deleted_job_slot)
        self._deleted_job_slot = None
        self.vm.refresh()
        return {"ok": True, "name": name}

    def _do_clone_job(self, p: dict) -> dict:
        """작업 복제(F22) — 매핑 재사용의 단일 동선(공유 베이스 프로파일의 대체).

        새 행이 목록에 나타나는 것이 곧 성공 신호라 성공 배너는 내지 않는다
        (정상은 조용히 — 원장 정련 원칙 1). 원본 부재·손상·저장 실패는 오류 dict 로
        시끄럽게 재진술한다(웹이 alert).
        """
        try:
            new_name = clone_job(self._job_registry, p["name"])
        except Exception as exc:  # noqa: BLE001 — 부재·손상·slug 백스톱: 문구로 loud
            return {"ok": False, "error": f"작업을 복제할 수 없습니다: {exc}"}
        self.vm.refresh()
        return {"ok": True, "cloned": new_name}

    def _do_relink_template(self, p: dict) -> dict:
        """작업 템플릿 다시 연결(#67) — 「문서 만들기」와 공유하는 확정 게이트에 위임(단일 출처).

        커밋되면 행(건강·runnable)을 최신화한다. 「문서 만들기」에 같은 작업이 선택돼 있어도
        여기서 갱신하지 않는다 — 옛 경로는 죽어 있어 실행 게이트가 fail-closed 로 차단하고,
        재선택 시 재적재된다(수용, 그쪽 주석과 쌍).

        **진행 중 런과 겹치면 거절한다**(9R P1 형제 — 「문서 만들기」 쪽 재연결과 쌍): 이
        화면은 런을 돌리지 않지만 durable 규칙을 쓰므로, 저쪽에서 돌고 있는 배치가 고정한
        규칙을 여기서 갈아치울 수 있었다. 그래서 같은 자물쇠를 본다.
        """
        if self._generation_lock.locked():
            raise ValueError("문서 생성이 진행 중입니다. 끝난 뒤에 템플릿을 다시 연결하세요.")
        res = relink_job_template(
            self._job_registry, p["name"], p.get("path", ""),
            engine=self._engine, confirm=bool(p.get("confirm")),
        )
        if res.get("relinked"):
            self.vm.refresh()
            res["restated"] = "템플릿을 다시 연결했습니다."
        return res

    def _do_refresh(self, p: dict) -> None:
        """레지스트리·영속 접힘 재조회 — 다른 화면에서 저장·삭제·접기 후 복귀 시 최신화.

        ``select`` 는 **정체가 바뀌는 관리 동사**(이름 변경)가 새 이름을 실어 보내는 자리다.
        안 실으면 선택이 옛 이름에 남아 상세가 닫히고, 사용자가 보던 문맥과 모달 복귀
        지점이 함께 사라진다(리뷰 2R) — 이름이 바뀌었을 뿐 그 작업은 그대로 있는데.
        존재하지 않는 이름은 조용히 무시한다(경합으로 그사이 사라졌을 수 있다 — 상세는
        어차피 빈 상태로 정직하게 그려진다).
        """
        self.vm.refresh()
        self._collapsed = set(load_job_collapsed_groups())
        sel = str(p.get("select", "") or "")
        if sel and any(r.name == sel for r in self.vm.rows()):
            self.selected_work = sel

    # ------------------------------------------------------- 태그 편집(#26 #2·D14)
    def _do_set_tags(self, p: dict) -> None:
        """작업의 분류 태그(축→값)를 통째로 교체·저장 — VM seam 위임(#44).

        검증(비어 있지 않은 축·값 문자열)·저장·refresh 는 전부
        :meth:`HomeViewModel.set_tags` 가 소유한다 — 다른 액션들과 같은 위임 규약.
        """
        self.vm.set_tags(p["name"], p.get("tags", {}))

    # ------------------------------------------------- 손상 작업 조치(#26 #8·UD-44)
    def validate_corrupt_path(self, raw: str) -> Path:
        """손상 작업 조치 대상 경로 검증 — 레지스트리 밖·비 job 파일은 loud 거절.

        웹 페이로드의 경로를 그대로 신뢰하면 임의 파일 삭제/열기 통로가 된다. 현재
        손상 목록에 실재하는 경로만 허용한다(스냅샷이 곧 화이트리스트).
        """
        candidates = {str(c.path) for c in self.vm.corrupt_rows()}
        if raw not in candidates:
            raise ValueError(CORRUPT_PATH_REJECT)
        return Path(raw)

    def _do_delete_corrupt(self, p: dict) -> dict:
        """손상 작업 파일 삭제 — 파괴이므로 확인 라운드트립(1차=재진술, 2차=삭제)."""
        path = self.validate_corrupt_path(p["path"])
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "path": str(path),
                "confirm_text": (
                    f"손상된 작업 파일을 삭제합니다(복구 불가):\n{path}\n"
                    "내용을 확인하려면 먼저 '폴더 열기'로 살펴보세요."
                ),
            }
        # 실제 삭제는 VM 위임(#44 seam) — 잠금 참여·화이트리스트 재판정·refresh 를 그쪽이
        # 소유한다. 위 선판정은 확인 왕복 **전** 스냅샷이라 사람이 모달을 보는 사이 낡을 수
        # 있어, 파괴 직전 판정은 잠금 안에서 다시 이뤄져야 한다(#129 리뷰 3R P1 유사 범위).
        self.vm.delete_corrupt(str(path))
        return {"ok": True}
