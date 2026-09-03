"""「문서 작업」(전역 라이브러리) 화면 컨트롤러 — browser + detail(webview 비의존).

계약 §19.6(전역 문서 작업 라이브러리)·§19.7(전역 작업 건강)의 표면. **홈 화면을 대체한다**
(재작성 F2, 지도 §10.8): 카드 나열 + group-by 렌즈였던 홈은 죽고, 저장된 작업을 찾는 자리가
이 화면 하나로 모였다. 링1 VM(:class:`~hwpxfiller.gui.home_state.HomeViewModel`)의 라이브러리
투영·건강 번역을 **그대로** 소비한다 — 백엔드 판정 재구현 0.

(링1 모듈은 ``home_state``·``HomeViewModel`` 이름을 유지한다 — 지도 §10.3 이 "재작성 무영향"
자산으로 배정했다. 링2 만 어휘를 정산했다: 이 파일·푸시 채널·액션 키가 ``library`` 다.)

**허브 내비게이션**: 이 컨트롤러는 다른 화면 컨트롤러를 모른다. 「문서 만들기에서 사용」·
「작업 편집」 같은 이동은 링2(웹)가 대상 화면의 자체 dispatch 로 미리 겨눈 뒤 셸 라우터
(앱 셸이 내는 `Nav` — 전역이 아니라 주입으로 닿는다)로 전환한다.

**좌 목록 관리 동사의 소유(지도 §10.8 판정 F)**: 이름 변경은 「문서 만들기」 컨트롤러가
계속 소유하고 링2가 교차 화면 dispatch 로 부른다 — 열린 세션의 정체(``job_name``)와 결속돼
있어 여기서 재구현하면 판정이 둘로 갈린다. 이 화면이 직접 소유하는 것은 라이브러리 자신의
축(보기·방식·검색·선택)과, 세션 정체와 무관한 관리 동사(즐겨찾기·복제·삭제·다시 연결·손상
조치)뿐이다.

**그룹·태그는 표면에 없다(U4 §2-30)**: 그룹 지정/이름 변경/해산·접힘, 태그 편집, 그리고 태그로
좁히던 facet 칩이 함께 걷혔다 — 태그를 만들 자리가 없는데 태그로 좁히는 칩만 남기면 신규
사용자에게 영영 빈 줄이다. 링0·링1 의 group/tag 판정과 영속(``Job.group``·``Job.tags``·
``job_collapsed_groups``·``template_groups``)은 **동결**이다: 지우지 않고 두되 제품 표면이
읽지도 쓰지도 않는다(나라장터 소스와 같은 처분). 되살릴 때 이 화면이 다시 소비하면 된다.

**남은 스코프 경계(조용히 빠뜨리지 않고 명시)**:
- Template/Binding **판본**은 §19.6 상세가 요구하지만 F7 신설분이라 오늘 존재하지 않는다.
  빈 자리·「준비 중」 표기도 두지 않는다(없는 기능을 있는 척하지 않는다, 지도 §10.8 판정 D).
- 상세는 매핑 목록을 보이지 않는다. 저장된 항목 키를 읽기 전용으로 한 벌 더 그리던 표는
  철거됐다 — 매핑의 정본은 편집기 탭이고, 상세가 그 사본을 들면 같은 상태를 두 자리가 말한다.
  상세가 지는 것은 **정체와 조치**(템플릿·데이터·건강 원인·재선택 동선)다.
- 기안 **템플릿** 목록(구 홈 txt 트랙)의 승계처는 편집기 「템플릿」 탭 TXT 밴드(F6 PR-B)다.
  TXT **작업**은 이 화면에 합류했고 방식 필터(「온나라 기안」)가 구 좌 목록의 최종 승계처다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.jobs import (
    CORRUPT_PATH_REJECT,
    clone_job,
    load_job,
    restore_job,
    set_favorite,
    soft_delete_job,
)
from ..data.factory import source_for_binding
from ..domain.engine import HwpxEngine
from ..domain.job import Job, data_binding_of, has_data_binding, template_media
from ..domain.template_status import library_display_name
from ..external import example_pack
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.template_root import TemplateRoot
from ..external.text_registry import TextTemplateRegistry
from ..external.template_inspection import template_compile_status
from ..gui.compile_badge import badge_level
from ..gui.home_state import (
    NO_GROUP_LABEL,
    HomeViewModel,
    JobRow,
    library_health,
    library_health_causes,
    library_mode_of,
)
from ..gui.mapping_state import (
    MappingModel,
    display_cell_label,
    profile_source_vocabulary,
    row_projection,
    source_cell_label,
)
from ..gui.work_mode import work_mode_label, work_mode_of_filter_value
from ..naming import make_output_filename
from .output_folder_zone import output_folder_zone
from .screens import NO_ROWS_TEXT, PushSink, dataset_display_name, relink_job_template

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


def run_in_worker_thread(work: "Callable[[], None]") -> None:
    """첫 행 읽기의 **제품 실행 자리** — 데몬 워커 하나(U6-F #980).

    읽기는 파일 IO 라 창을 붙들면 목록이 그동안 얼어붙는다. 이 함수가 하는 일은 실행 위치를
    바꾸는 것뿐이고 판정·상관 키 대조는 호출자가 그대로 진다.
    """
    threading.Thread(target=work, name="library-first-row", daemon=True).start()


#: 상세 표가 프레임 안에 두는 행 수(동결 시안 장면 4). 나머지는 스크롤로 조용히 감추지
#: 않고 **이름으로 명시**한다 — 「그 밖에 n행」이 이름을 들지 않으면 표가 자기 일부를
#: 숨기고도 그 사실을 말하지 않는다.
DETAIL_ROW_LIMIT = 8

#: 결속이 없는 작업의 「첫 행」 사유. 실패가 아니라 저작 중 상태이지만, 빈 칸으로 두면
#: 「아직 못 읽었다」와 구별되지 않아 사유를 그 자리에 적는다.
UNBOUND_FIRST_ROW_REASON = "데이터를 연결해야 첫 행을 채울 수 있습니다."


@dataclass(frozen=True)
class FirstRowRead:
    """데이터 참조 1벌을 실제로 읽은 결과 — 「문서 작업」 상세의 첫 행 재료(U6-F #980).

    ``state`` 는 ``ready``/``error`` 둘뿐이다(``pending`` 은 **결과가 없다**는 뜻이라 캐시에
    들어오지 않는다). 실패는 삼키지 않고 ``reason`` 으로 재진술한다 — 이 값이 곧 표의 첫
    행 칸에 서는 문장이다.
    """

    state: str
    reason: str = ""
    record: "dict" = field(default_factory=dict)
    headers: "tuple[str, ...]" = ()
    record_count: int = 0


def _binding_key(name: str, job: "Job") -> "tuple | None":
    """이 작업의 데이터 결속 상관 키 — 미결속이면 ``None``.

    작업 이름까지 무는 이유는 캐시가 상세 패널의 것이기 때문이다: 같은 파일을 두 작업이
    가리켜도 시트·헤더 행이 같으면 값은 같지만, 늦게 도착한 결과를 **어느 선택에 대한
    답인지** 대조하려면 선택 정체가 키에 들어야 한다(`_push_progress` 의 ``run_token``
    규율과 같은 자리).
    """
    if not has_data_binding(job):
        return None
    return (name, *data_binding_of(job))


def _read_first_row(job: "Job") -> FirstRowRead:
    """결속 참조로 데이터를 **읽어** 첫 레코드·헤더·건수를 낸다(워커 스레드에서 돈다).

    읽기는 전량이다 — 어댑터에 ``limit`` API 가 없고 이 슬라이스가 만들지도 않는다.
    라이브러리 선택은 사용자 행위 1회이고, 검색 타이핑의 재렌더가 파일을 다시 읽지 않게
    막는 것은 호출자의 캐시다.

    실패는 사유와 함께 ``error`` 로 돌아온다(예외를 밖으로 던지지 않는다 — 이 결과가 향하는
    곳은 표의 한 칸이고, 거기서 조용한 빈칸이 되는 것만 금지된다).
    """
    path, sheet, header_row, kind = data_binding_of(job)
    if not Path(path).exists():
        return FirstRowRead(state="error", reason=f"경로를 찾을 수 없음: {path}")
    try:
        source = source_for_binding(
            {"path": path, "sheet": sheet, "header_row": header_row, "kind": kind}
        )
        records = source.records()
        headers = tuple(source.fields())
    except Exception as exc:  # noqa: BLE001 — 시트 부재·손상·권한: 사유를 그대로 나른다
        return FirstRowRead(state="error", reason=str(exc))
    if not records:
        return FirstRowRead(state="error", reason=NO_ROWS_TEXT, headers=headers)
    return FirstRowRead(
        state="ready", record=records[0], headers=headers, record_count=len(records),
    )


def _job_row_dict(r: JobRow) -> dict:
    """행 1건 성형 — 링1 JobRow 표면만 읽는다(VM 로직 재구현 없음).

    §19.6 "행은 이름, 작업 방식 텍스트, 작업 건강, 즐겨찾기를 보여준다"(사용자 group 은
    U4 §2-30 에서, **최근 사용 문구**는 이번 정리에서 표면이 걷혀 행에도 싣지 않는다 —
    `last_run_at` 은 「최근 사용」 보기의 **정렬 재료**로만 산다). 컴파일 배지의 심각도(pill
    색 레벨)는 :func:`badge_level`(RC-29 단일 어휘)로 파생해 템플릿 관리 화면과 같은 상태에
    같은 신호를 낸다.
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
        "template_missing": r.template_missing,
        # 데이터 결속 유무(U4 §2.4 · #932 U4-C) — 행에는 **유무만** 싣는다. 라벨은 상세가
        # 지고 행은 「조치가 필요한가」만 말한다(템플릿 축의 `template_missing` 과 같은 결).
        "data_bound": r.data_bound,
        "runnable": r.is_runnable(),
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
                 generation_lock: "threading.Lock",
                 template_root: TemplateRoot,
                 remembered_output_directory: "Callable[[], str]",
                 clock: "Callable[[], datetime]" = datetime.now,
                 first_row_runner: "Callable[[Callable[[], None]], None]"
                 = run_in_worker_thread) -> None:
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
        # 데이터 풀 — 연결 카드의 **등록명** 조회(같은 인스턴스라 등록·개명이 즉시 보인다).
        self._pool_registry = pool_registry
        self._engine = engine
        # 「문서 만들기」와 **같은** 생성 자물쇠(9R P1) — 이 화면의 재연결도 durable 규칙을
        # 쓰므로 진행 중 런과 겹치면 안 된다. **필수 주입**이다(P2-24 폴백 제거): 화면이
        # 자기 것을 세우면 run transaction 상태의 제2 정본이 된다(#570 pool_registry 동형).
        self._generation_lock = generation_lock
        self._push_sink = push
        self._deleted_job_slot = None
        # 상세 패널이 겨눈 작업(§19.6 ``selectedWorkId``) — **활성 작업과 무관**하다.
        # 여기서 행을 골라도 「문서 만들기」의 선택·데이터·승인은 불변이다(§19.6 서문).
        self.selected_work: str = ""
        # 서식 폴더 권위(U6-A #975 · U6-D #978) — 템플릿 표시명을 목록·편집기와 **같은
        # 홀더**로 짓는다. 두 홀더를 두면 재지정 직후 같은 파일이 두 이름으로 불린다.
        self._template_root = template_root
        # 전역 저장 폴더의 소유자는 「문서 만들기」 컨트롤러 하나다(U6-D #978 리뷰 3) —
        # 여기서는 그 값을 **읽기만** 한다(설정 파일 재판독 금지).
        self._remembered_output_directory = remembered_output_directory
        self._clock = clock
        # 「첫 행」 지연 읽기의 **사적 캐시**(U6-F #980). 키는 결속 상관 키이고 값은 실제
        # 읽기 결과다. 이 캐시가 없으면 검색 타이핑의 재렌더마다 엑셀을 다시 연다.
        # 캐시는 `refresh` 로 비우지 않는다 — 참조가 같으면 값도 같고, 참조가 바뀌면
        # (다시 연결·데이터 재선택 뒤 저장) 키가 달라져 자연히 미스가 난다.
        self._first_row_cache: "dict[tuple, FirstRowRead]" = {}
        # 지금 겨눈 결속의 상관 키 — 늦게 끝난 읽기가 자기 답을 밀어도 되는지의 판정 재료.
        self._selected_binding_key: "tuple | None" = None
        # 읽기를 **어디서 돌리는가**. 제품은 워커 스레드(창을 막지 않는다), 헤드리스
        # 테스트는 완료 시점을 손에 쥐려고 즉시·지연 실행을 주입한다(푸시 sink 주입과 같은
        # 규율 — 판정은 여기 그대로 두고 실행 자리만 갈아끼운다).
        self._first_row_runner = first_row_runner
        # 타 화면 무장 세션 가드 조회 함수들(#268 리뷰) — app.py 가 작업·기안 컨트롤러의
        # ``session_guard_for`` 를 배선한다(생성 순서상 이 화면이 먼저라 사후 배선).
        self.session_guards: "list" = []

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    def _sections(self) -> "list[dict]":
        """현재 보기의 구획 — U4 §2-30 이후 **언제나 헤더 없는 평면 하나**다.

        구획을 만들던 축은 사용자 group 하나였고 그 표면이 걷혔다. 링1 의 group 판정은
        동결이라 살아 있지만(`library_sections(grouped=True)`) 제품은 묻지 않는다 —
        저장된 group 값으로 구획을 그리면 이름을 바꾸거나 해산할 동사가 없는 헤더가 선다.
        모양(`headed`·`is_untagged`·`collapsed`)은 링1 퇴화 갈래가 내는 값 그대로 싣는다.
        """
        out: "list[dict]" = []
        for sec in self.vm.library_sections(grouped=False):
            headed = bool(sec.value) or sec.is_untagged
            out.append({
                "value": sec.value,
                "label": NO_GROUP_LABEL if sec.is_untagged else sec.value,
                "count": sec.count,
                "is_untagged": sec.is_untagged,
                "headed": headed,
                "collapsed": False,
                "rows": [_job_row_dict(r) for r in sec.rows],
            })
        return out

    # ------------------------------------------------- 상세 연결 존(U6-F #980)
    def _pairing_detail(self, row: JobRow, job: "Job") -> dict:
        """상세 하단의 **연결 카드 + 읽기 전용 4열 표 + 계획 한 줄**.

        §19.6 이 오래 「상세는 매핑 사본을 싣지 않는다」고 못 박아 온 자리다. 그 금지가
        겨눈 것은 **별도 라벨 사전을 든 payload 사슬**(#966 이 걷은 `detail.bindings`)이었지
        정보 자체가 아니었다 — 여기서 그리는 행은 편집기 2단계와 **같은 링1 투영**
        (:func:`~hwpxfiller.gui.mapping_state.row_projection`)이고 라벨도 그 한 자리에서
        온다. 판정이 하나이므로 두 표면이 서로 다른 말을 할 자리가 없다.

        **카드와 표는 답하는 질문이 다르다.** 카드는 정체(무엇과 무엇이 붙었나)이고 그것은
        템플릿을 못 읽어도 답할 수 있다 — 게다가 그 정체를 **바꾸러 가는 동사**(재선택)가
        거기 있어서, 템플릿이 사라진 갈래에서 카드를 접으면 고치러 갈 길이 함께 접힌다.
        표는 구조(어느 필드가 어느 열에서 오나)이고 현재 템플릿과의 대칭차 없이는 「확인
        필요 k」를 말할 수 없으므로, 못 읽는 갈래에서는 **빈 행 목록**으로 서지 않는다
        (수치가 상태를 참칭하지 않게 `counted` 도 거짓이다).
        """
        card = {
            # 표시명은 목록·편집기와 **같은 규칙**이다(U6-A·U6-D) — 같은 파일을 화면마다
            # 다른 문법으로 부르지 않는다.
            "template_name": library_display_name(
                self._template_root.path(), job.template_path
            ) if job.template_path else "",
            "template_bound": row.template_linked,
            "template_missing": row.template_missing,
            "data_name": dataset_display_name(
                self._pool_registry,
                path=job.data_path, sheet=job.data_sheet, kind=job.data_kind,
            ),
            # 수치는 **현재 템플릿과의 대칭차**에서 온다(링1 `JobRow`) — 저장된 프로파일은
            # 확정 행만 담아 「확인 필요」를 셀 수 없다. 세지 못한 갈래는 세지 않았다는
            # 사실을 `counted` 로 말한다(0 을 사실처럼 말하지 않는다).
            "counted": row.template_field_count > 0,
            "template_field_count": row.template_field_count,
            "mapped_count": row.template_field_count - row.unbound_field_count,
            "unbound_count": row.unbound_field_count,
            "stale_count": row.stale_mapping_count,
        }
        if not row.template_linked or row.template_missing:
            # 표·첫 행·계획은 전부 **읽을 수 있는 템플릿**을 전제한다. 그 갈래의 답은
            # 건강 원인과 카드의 재선택 동사다.
            return {"card": card, "rows": [], "more_fields": [],
                    "first_row": None, "plan": None, "output_folder": None}
        is_txt = template_media(job.template_path) == "txt"
        binding_key = _binding_key(row.name, job)
        read = self._first_row_cache.get(binding_key) if binding_key else None
        if binding_key is None:
            state, reason, record_count = "error", UNBOUND_FIRST_ROW_REASON, 0
        elif read is None:
            state, reason, record_count = "pending", "", 0
        else:
            state, reason, record_count = read.state, read.reason, read.record_count
        record = read.record if (read is not None and read.state == "ready") else {}
        # 실 헤더는 **읽었을 때만** 선다 — 못 읽었는데 프로파일 어휘를 헤더인 척 쓰면
        # 「데이터에 없음」 판정이 언제나 거짓이 되어 사라진 열을 조용히 넘긴다.
        source_fields = (
            list(read.headers) if (read is not None and read.headers)
            else profile_source_vocabulary(job.mapping)
        )
        model = MappingModel.from_profile(job.mapping)
        # 「오늘 날짜」 미리보기와 파일 이름 계획이 **한 시각**을 말하게 1회만 찍는다(#957).
        now = self._clock()
        rows = [
            row_projection(
                r, record, index=i, source_fields=source_fields,
                has_records=bool(record_count), now=now, first_row_state=state,
            )
            for i, r in enumerate(model.rows)
        ]
        for projection in rows:
            # 읽기 전용 칸이 필요한 것은 **해소된 라벨**이다(select 는 항목이 자기 라벨을
            # 들고 오지만 이 표에는 select 가 없다). 지어내지 않고 링1 조회로 받는다.
            projection["source_label"] = source_cell_label(projection)
            projection["display_label"] = display_cell_label(projection)
        shown, rest = rows[:DETAIL_ROW_LIMIT], rows[DETAIL_ROW_LIMIT:]
        return {
            "card": card,
            "rows": shown,
            "more_fields": [r["template_field"] for r in rest],
            "first_row": {"state": state, "reason": reason, "record_count": record_count},
            # TXT 는 계획이 없다 — 파일을 만들지 않는 작업이라 이름 규칙이 저장돼 있어도
            # (durable 기본값) 그것으로 만들 파일이 없다.
            "plan": None if is_txt else self._plan_line(
                job, model, record, state, record_count, now=now
            ),
            # TXT 는 파일을 만들지 않아 폴더가 축이 아니다(§ 「저장 폴더 — 전역 단일 값」의
            # 표와 같은 판정) — 빈 재진술을 세우면 만들지 않을 파일의 저장 위치를 말한다.
            "output_folder": None if is_txt else output_folder_zone(
                template_path=job.template_path,
                remembered_directory=self._remembered_output_directory(),
            ),
        }

    def _plan_line(
        self, job: "Job", model: MappingModel, record: "dict", state: str,
        record_count: int, *, now: datetime,
    ) -> "dict | None":
        """「이 작업이 만들 파일」 한 줄 — 이름은 **실제 생성기와 같은 함수**가 만든다.

        패턴이 비면 ``None`` 이다 — 만들지 않을 파일의 이름을 계획으로 말하지 않는다.
        ``pattern`` 을 함께 싣는 이유는 첫 행을 아직 못 읽은 동안에도 **규칙은 참**이기
        때문이다(상세의 옛 「파일 이름 규칙」 행이 여기로 내려왔다 — 규칙과 실제 이름을
        두 자리에서 말하면 한쪽이 늙는다).
        (매체 판정은 호출자가 진다: TXT 는 durable 기본 패턴을 들고 있어도 파일을 만들지
        않으므로 패턴 유무로 갈리지 않는다.) 첫 행을 아직 못 읽었으면 이름도 아직 없다 —
        같은 수명이다: 데이터 토큰이 빈 이름을 지어 보이면 그 예시가 산출물과 다르다.
        """
        if not job.filename_pattern:
            return None
        if state != "ready":
            # 규칙은 지금도 참이다 — 이름을 아직 못 지었을 뿐이라 규칙으로 답한다.
            return {"state": state, "pattern": job.filename_pattern,
                    "first_name": "", "count": 0}
        try:
            first = make_output_filename(
                job.filename_pattern, model.name_token_values(record, now=now),
                seq=1, now=now,
            )
        except Exception:  # noqa: BLE001 — 표시 전용(패턴 검증은 저장 게이트 소관)
            first = ""
        return {"state": state, "pattern": job.filename_pattern,
                "first_name": first, "count": record_count}

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
            "primary": primary_action(row),
            # (`template_name`(확장자 붙은 basename)은 U6-F(#980)에서 걷혔다 — 상세가
            #  템플릿을 부르는 이름은 연결 카드의 표시명 하나이고, 목록·편집기와 같은
            #  규칙(`library_display_name`)이다. 두 어휘를 한 패널에 두면 같은 파일이
            #  두 이름으로 불린다.)
            # 템플릿 전체 경로(U2 §2.20, #342) — 상세의 「열기」·「폴더에서 보기」가 겨눈다.
            # 경보(템플릿 미연결 N건)는 이 화면이 내는데 파일을 열거나 폴더로 갈 길이 이
            # 화면에 없었다(계기판의 짝). 경로 검증은 백엔드 화이트리스트(app.py
            # ``_validate_owned``)가 이미 소유한다 — 신설은 이 한 칸뿐이다.
            "template_path": job.template_path,
            # 데이터 결속의 정체(U4 §2.4) — 템플릿 정체 바로 옆이 제자리다: 「무엇으로
            # 만드는가」의 두 축이고, 한쪽만 보이면 목록이 절반만 말한다. 라벨 성형은
            # 링0 단일 출처(`data_binding_label`)라 표면이 basename·시트 표기를 안 짓는다.
            "data_label": row.data_label,
            "data_path": job.data_path,
            # (`filename_pattern` 은 U6-F(#980)에서 계획 존으로 내려갔다 — 「이 작업이
            #  만들 파일」을 말하는 자리가 하나여야 규칙과 실제 이름이 갈리지 않는다.
            #  TXT 의 「실행 방식」 문구는 그보다 앞서 걷혔다: 방식은 부제가 이미 말한다.)
            "health_causes": [
                {"severity": s, "text": t} for s, t in library_health_causes(row)
            ],
            # 상세 하단의 연결 그림(U6-F #980 · §2.6). 건강 원인과 **섞지 않는다**: 저쪽은
            # 「이 작업이 지금 돌 수 있는가」이고 이쪽은 「무엇을 무엇으로 채워 어떤 파일을
            # 만드는가」다. 첫 행 읽기 실패도 그래서 여기 안에서 말한다(§19.7 분리).
            "pairing_detail": self._pairing_detail(row, job),
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
            # 저장된 작업이 없는 갈래의 두 번째 출구(#891 · §4.1) — 「예제로 시작하기」의
            # 라벨·설치 여부는 tpl 스냅샷과 **같은 단일 출처**를 읽는다(프런트 발명 금지).
            # 실행 자체는 tpl 채널의 `install_examples` 를 교차 화면 dispatch 로 부른다:
            # 설치는 템플릿 라이브러리의 사건이지 작업 레지스트리의 사건이 아니다.
            "examples": example_pack.entry_point_state(),
            # 라이브러리 browser(§19.6) — 보기 4종 × 작업 방식 × 검색.
            "view": self.vm.library_view,
            "mode": self.vm.library_mode,
            "query": self.vm.library_query,
            "counts": self.vm.library_counts(),
            "sections": self._sections(),
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
        """보기 교체(§19.6) — 검색어·방식 필터는 유지한다(축이 다르므로 서로 지우지 않는다)."""
        self.vm.set_library_view(p.get("view") or "")

    def _do_set_mode(self, p: dict) -> None:
        self.vm.set_library_mode(p.get("mode") or "")

    def _do_set_query(self, p: dict) -> None:
        self.vm.set_library_query(str(p.get("text", "")))

    def _do_clear_filters(self, p: dict) -> None:
        """필터를 전부 지우고 「모든 작업」으로 — 0건 화면의 상주 출구(§8.4 도달성 면).

        보기·방식·검색 셋이 이 화면의 절단자다(태그 facet 은 U4 §2-30 에서 걷혔다). 0건이
        됐을 때 어느 축이 범인인지 일일이 되짚게 두면 필터 밖 작업에 도달할 길이 사실상
        사라진다.
        """
        self.vm.set_library_mode("")
        self.vm.set_library_query("")
        self.vm.set_library_view("")

    def _do_select_work(self, p: dict) -> None:
        """상세 패널이 겨눌 행(§19.6 ``selectedWorkId``) — **활성 작업은 바뀌지 않는다**.

        빈 이름은 선택 해제다. 여기서 다른 작업을 열어도 「문서 만들기」의 선택·데이터·
        승인 상태는 유지된다(§19.6 서문 · 화면 머리 문안이 그 사실을 사용자에게 말한다).

        선택은 **읽기를 시작**한다(U6-F #980): 상세의 「첫 행」 열은 데이터 파일을 열어야
        채워지므로 여기서 워커를 띄우고, 이 디스패치의 푸시는 ``pending`` 인 채로 먼저
        나간다. 그 읽기가 「문서 만들기」의 마운트·선택·필터를 건드리지 않는 것이
        「선택 ≠ 착석」 불변의 이 슬라이스 판이다 — 편집기·작업 화면의 ``load_data_path``
        계열은 여기서 **절대** 재사용하지 않는다.
        """
        self.selected_work = str(p.get("name", ""))
        self._begin_first_row_read()

    def _begin_first_row_read(self) -> None:
        """선택한 작업의 첫 행을 **워커 스레드**에서 읽어 두 번째 푸시로 채운다.

        캐시 히트·미결속·읽을 수 없는 작업은 아무것도 시작하지 않는다(스냅샷이 이미 그
        사실을 말한다). 늦게 끝난 읽기는 **상관 키**를 다시 대조한 뒤에만 푸시한다
        (`_push_progress` 의 ``run_token`` 규율 선례): 그사이 다른 행을 골랐으면 결과는
        캐시에만 들어가고, 그 행을 다시 고르는 순간 히트로 즉시 선다.

        푸시는 **전체 스냅샷**이다 — 부분 dict 델타는 job 채널만 허용한다(런타임 reduce).
        """
        # 겨눔이 바뀌는 **모든** 갈래에서 먼저 지운다 — 캐시 히트·미결속으로 일찍 돌아가는
        # 자리에 옛 키가 남으면 앞 선택의 늦은 워커가 지금 화면에 자기 답을 민다.
        self._selected_binding_key = None
        name = self.selected_work
        if not name:
            return
        row = next((r for r in self.vm.rows() if r.name == name), None)
        if row is None or not row.template_linked or row.template_missing:
            return
        try:
            job = load_job(self._job_registry, name)
        except Exception:  # noqa: BLE001 — 상세 자체가 None 으로 정직하게 그려진다
            return
        key = _binding_key(name, job)
        self._selected_binding_key = key
        if key is None or key in self._first_row_cache:
            return

        def work() -> None:
            result = _read_first_row(job)
            self._first_row_cache[key] = result
            # 이 답이 **지금 화면의 질문**에 대한 것일 때만 푸시한다: 이름과 참조 4벌이
            # 그대로여야 한다(이름만 보면 그사이 데이터를 바꿔 저장한 같은 이름의 작업에
            # 옛 데이터의 첫 행을 그린다). 아니면 캐시에만 남고, 그 행을 다시 고르는
            # 순간 히트로 즉시 선다.
            if self._selected_binding_key == key:
                self._push()

        self._selected_binding_key = key
        self._first_row_runner(work)

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
        sel = str(p.get("select", "") or "")
        if sel and any(r.name == sel for r in self.vm.rows()):
            self.selected_work = sel

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
