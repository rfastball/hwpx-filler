"""Job durable mutation 의 Application 경계 — semantic port + use case(P2-21 #569 2단계).

:class:`JobStorePort` 는 작업 저장의 **의미 계약**이다: 표면에 물리(파일 ``Path``·suffix·
JSON text·raw lock·``write_lock``·OS 타입)도, 콜백 ``mutate`` 도 올리지 않는다 — 잠긴
읽기-수정-쓰기가 필요한 업무 전이는 전부 **semantic atomic op** 하나로 완결된다
(:mod:`~hwpxfiller.application.dataset_pool` 이 #570 에서 세운 규율을 P2-99(#542) D-1 에서
이 포트에도 적용했다: 콜백은 「무엇을 바꿀 수 있는가」를 열어 둬 호출자가 잠금 안에서
업무 규칙을 재판정하는 뒷문이 된다).

아래 use case 함수들이 **durable mutation transaction 의 진입점**이다. ring 2 컨트롤러는
concrete 레지스트리 메서드를 직접 부르지 않고 여기를 지나며, concrete 결속
(:class:`hwpxfiller.external.job_store.JobRegistry`)은 호출자가 첫 인자로 **주입**한다 —
Application 은 External 을 import 하지 않고, 기본 구현·service locator 도 없다.

이 모듈은 Domain(:mod:`hwpxfiller.domain.job`)만 안다. 잠금·재시도·slug·휴지통 보존 같은
물리 의미는 전부 포트 뒤(External)에 산다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..domain.job import Job

#: 손상 파일 조치의 화이트리스트 거절 문구 — 컨트롤러 선판정(:mod:`~hwpxfiller.webapp.
#: screen_library`)과 저장소의 잠금 안 재판정이 **같은 말**을 하도록 포트 계약이 소유한다
#: (두 곳이 다른 문구면 같은 거절이 두 얼굴로 보인다).
CORRUPT_PATH_REJECT = "손상 작업 목록에 없는 경로입니다. 새로고침 후 다시 시도하세요."

#: 소프트 삭제가 돌려주는 **불투명 복원 슬롯** — 구조는 External 이 소유하고 Application 은
#: 받은 값을 그대로 :func:`restore_job` 에 되돌려줄 뿐이다(물리 좌표를 계약으로 만들지 않는다).
DeletedJobSlot = Any


class CrossMediaRelinkError(Exception):
    """잠금 안 재판정이 잡은 매체 교차(§10.16 판정 C) — **사실만** 나르고 문안은 안 짓는다.

    작업 방식은 생성 시점에 정해져 바뀌지 않는다(링0 불변식 1). 확인 왕복은 사람 시간이라
    그 사이 다른 재연결이 매체를 정했으면 이 커밋이 사전 게이트를 우회하므로, 어댑터가
    쓰기 잠금 안에서 한 번 더 판정해 fail-closed 한다
    (:class:`~hwpxfiller.application.dataset_pool.StaleConfirmError` 동형).

    문안은 표면이 :func:`~hwpxfiller.webapp.screens._cross_media_refusal` 로 재진술한다 —
    거절 사유의 어휘(작업 방식 라벨)는 링2 소유라 여기서 조립하지 않는다.

    ``old_path`` 는 **잠금 안에서 본** 그때의 템플릿 경로다 — 사전 게이트가 읽은 사본이
    아니라 이 값으로 문안을 지어야 경합에서 진 쪽이 실제로 무엇과 부딪혔는지 말한다.
    """

    def __init__(self, old_path: str, new_media: str) -> None:
        super().__init__(f"매체 교차 재연결 거절: {old_path!r} → {new_media!r}")
        self.old_path = old_path
        self.new_media = new_media


@dataclass(frozen=True)
class CorruptJobEntry:
    """파싱 실패한 작업 파일 1건의 사실 — 저장소가 주는 값 객체(RC-05 표면화의 원료).

    ``token`` 은 손상 항목을 지목하는 **불투명 식별자**다(현재 구현은 ``str(path)`` 지만
    소비자는 그 사실에 기대지 않는다 — 표시·:func:`remove_corrupt_entry` 왕복에만 쓴다).
    """

    file_name: str
    token: str
    error: str


class JobStorePort(Protocol):
    """작업 durable 저장의 semantic port — 물리 lock/storage 누수 0(#569).

    구조적(덕타이핑) 계약이다: concrete 는
    :class:`hwpxfiller.external.job_store.JobRegistry`, 테스트는 in-memory 구현이 선다.
    모든 메서드는 저장 매체 안에서 **원자적으로** 완결된다 — 호출자가 잠금을 알 필요도,
    잡을 방법도 없다. 각 메서드의 의미 계약은 아래 같은 이름의 use case 문서가 진다.
    """

    # ---- 읽기 표면(P2-24) — 잠금 없는 스냅샷 조회. read-modify-write 에 쓰지 않는다
    # (그건 mutate 소관). Presentation 은 concrete 레지스트리 대신 아래 query use case 를
    # 지난다 — 물리(디렉터리 스캔·파일 존재)는 계약 밖이다.
    def list_jobs(self) -> "list[Job]": ...
    def names(self) -> "list[str]": ...
    def load(self, name: str) -> Job: ...
    def exists(self, name: str) -> bool: ...
    # 저장이 덮어쓰는 작업 **내용**의 지문 — 외부 변경 감지의 단일 술어. 직렬화 codec 과
    # 같은 소유자(저장소)가 낸다: 지문의 정의역이 곧 「저장이 덮어쓰는 것」이기 때문이다.
    def content_fingerprint(self, job: Job) -> str: ...
    # 분류 태그 통째 교체 — 검증된 값을 받아 원자 왕복으로 저장한다.
    def set_tags(self, name: str, tags: "dict[str, str]") -> Job: ...
    # 템플릿 참조 재지정 — 잠금 안에서 매체 교차를 재판정하고 커밋까지 원자적.
    # 교차면 CrossMediaRelinkError(변경 0건), 구 매체 미상이면 사용 이력 미승계.
    def relink_template(self, name: str, path: str) -> Job: ...
    # 완주 스탬프 — 시각·검토 기준선을 같은 원자 왕복으로. rules=None 은 기준선 불변.
    def stamp_last_run(
        self, name: str, when: str, *, rules: "dict[str, str] | None" = None
    ) -> Job: ...
    # 즐겨찾기 지정/해제 — 시각은 저장소가 쓰기 순서와 정합하게 찍는다.
    def set_favorite(self, name: str, favorited: bool, when: "str | None" = None) -> Job: ...
    # S3 권위 Work identity 최초 1회 결속(S3-09) — 기존 값이 있으면 쓰지 않는다(멱등).
    def assign_authority_id(self, name: str, authority_id: str) -> Job: ...
    def rename(self, name: str, new_name: str) -> None: ...
    def clone(self, name: str) -> str: ...
    def delete(self, name: str) -> None: ...
    def soft_delete(self, name: str) -> DeletedJobSlot: ...
    def restore_soft_deleted(self, slot: DeletedJobSlot) -> str: ...
    def set_group(self, name: str, group: str) -> None: ...
    def rename_group(self, name: str, new_name: str) -> int: ...
    def disband_group(self, name: str) -> int: ...
    # 손상 항목 삭제 — 잠금 안 재판정 뒤 제거. 목록 밖 token 은 CORRUPT_PATH_REJECT 로 loud.
    def remove_corrupt_entry(self, token: str) -> None: ...


# ------------------------------------------------------------------ use case
# 각 함수는 포트를 첫 인자로 받는 **얇은 트랜잭션 진입점**이다: 판정·문안은 호출자
# (링1·컨트롤러)가, 원자성·물리는 포트 구현이 소유하고, 여기는 「어떤 durable 변이가
# 제품의 동사인가」를 한 곳에 열거한다(#569 완료 조건 2).
#
# 아래 query 군(P2-24)은 같은 규율의 읽기판이다: Presentation 이 concrete 레지스트리를
# 직접 부르지 않고 지나는 자리이며, 얇음이 곧 계약이다(판정을 여기 들이지 않는다).


def list_jobs(store: JobStorePort) -> "list[Job]":
    """저장된 전 작업 스냅샷(이름순) — 후보·탐색·그룹 집계가 소비하는 읽기 표면."""
    return list(store.list_jobs())


def job_names(store: JobStorePort) -> "list[str]":
    """저장된 작업 이름 목록 — 존재 대조(stale 세션 무효화)용 가벼운 조회."""
    return list(store.names())


def load_job(store: JobStorePort, name: str) -> Job:
    """작업 1건 적재 — 부재·손상은 포트가 loud raise 한다(조용한 폴백 없음)."""
    return store.load(name)


def job_exists(store: JobStorePort, name: str) -> bool:
    """작업 존재 여부 — 유령 지목 방지용 선판정(잠금 없는 스냅샷)."""
    return store.exists(name)


def job_content_fingerprint(store: JobStorePort, job: Job) -> str:
    """작업 내용 지문 — 외부 변경 감지(재적재·자기-갱신 게이트)의 단일 술어."""
    return store.content_fingerprint(job)


def group_member_count(store: JobStorePort, group: str) -> int:
    """그룹 소속 수 — 병합·해산 확인 문안의 관측치(약속이 아니라 그 시점의 관측, #149).

    잠금 밖 집계다: 실제 이동 건수는 잠금 안 일괄 갱신이 세어 돌려주고, 어긋나면
    ``drift_note`` 가 함께 말한다 — 그 계약이 이 조회의 TOCTOU 창을 이미 진다.
    """
    return sum(1 for j in store.list_jobs() if j.group == group)


def stamp_run_completion(
    store: JobStorePort, name: str, when: str, *, rules: "dict[str, str] | None"
) -> Job:
    """완주 런의 시각·검토 기준선 영속 — ``rules`` 는 **그 런이 실제 쓴 규칙**의 지문.

    기본값을 두지 않는 이유: ``None``(기준선 불변)이 조용한 기본이 되면 그 폴백이 곧
    조용한 승인 통로다 — 호출자가 매번 명시한다.
    """
    return store.stamp_last_run(name, when, rules=rules)


def set_favorite(
    store: JobStorePort, name: str, favorited: bool, when: "str | None" = None
) -> Job:
    """즐겨찾기 지정/해제 — 정렬 메타만 바꾼다(§18.5). ``when`` 은 결정적 테스트용."""
    return store.set_favorite(name, favorited, when)


def rename_job(store: JobStorePort, name: str, new_name: str) -> None:
    """작업 이름 변경 — 자리 선점·빈 이름은 포트가 loud ``ValueError`` 로 거절한다."""
    store.rename(name, new_name)


def assign_job_authority_id(store: JobStorePort, name: str, authority_id: str) -> Job:
    """S3 권위 Work identity 최초 1회 결속(S3-09) — 반환 Job 의 값이 정본이다(경합 화해)."""
    return store.assign_authority_id(name, authority_id)


def clone_job(store: JobStorePort, name: str) -> str:
    """작업 복제(F22) — 새 이름을 돌려준다(이력·즐겨찾기·판본 미계승은 포트 의미)."""
    return store.clone(name)


def delete_job(store: JobStorePort, name: str) -> None:
    """작업 즉시 삭제 — 확인 UI 는 호출 표면 몫이고 여기는 확정된 삭제만 나른다."""
    store.delete(name)


def soft_delete_job(store: JobStorePort, name: str) -> DeletedJobSlot:
    """보존 삭제 — 되돌리기용 불투명 슬롯을 돌려준다(:func:`restore_job` 짝)."""
    return store.soft_delete(name)


def restore_job(store: JobStorePort, slot: DeletedJobSlot) -> str:
    """보존 삭제 복원 — :func:`soft_delete_job` 이 준 슬롯을 그대로 되돌려준다."""
    return store.restore_soft_deleted(slot)


def assign_group(store: JobStorePort, name: str, group: str) -> None:
    """그룹 지정/해제 — ``""`` 는 「그룹 없음」으로 이동(소속=생성, 빈 그룹 불가)."""
    store.set_group(name, group)


def rename_group(store: JobStorePort, name: str, new_name: str) -> int:
    """그룹 이름 일괄 변경 — 실제 이동 건수를 반환한다(병합 확인은 화면 게이트 소관)."""
    return store.rename_group(name, new_name)


def disband_group(store: JobStorePort, name: str) -> int:
    """그룹 해산 — 소속 작업을 「그룹 없음」으로 되돌리고 소속 수를 반환한다."""
    return store.disband_group(name)


def update_tags(store: JobStorePort, name: str, tags: "dict[str, str]") -> Job:
    """분류 태그(축→값) 통째 교체 — 검증된 값을 받아 원자 왕복으로 저장한다.

    축·값 검증(비어 있지 않은 문자열·중복 축 loud)은 호출 seam
    (:meth:`~hwpxfiller.gui.home_state.HomeViewModel.set_tags`)이 계속 소유한다.
    """
    return store.set_tags(name, tags)


def relink_template(store: JobStorePort, name: str, path: str) -> Job:
    """작업 템플릿 참조 재지정의 **durable 커밋** — 매체 교차 재판정까지 한 왕복(#542 F-1).

    사전 게이트(경로 유효성·읽기 가능·구조 드리프트 재진술·확인 왕복)는 호출 표면이
    소유하고, 여기는 그 확정을 **잠긴 원자 전이 하나**로 낸다. 사전 게이트는 잠금 밖
    사본을 봤고 확인 왕복은 사람 시간이라, 같은 금지를 잠금 안에서 다시 묻는 것은
    포트 구현 몫이다 — 교차면 :class:`CrossMediaRelinkError` 로 **변경 0건**.
    """
    return store.relink_template(name, path)


def remove_corrupt_entry(store: JobStorePort, token: str) -> None:
    """손상 작업 항목 제거 — 잠금 안 재판정·삭제는 포트 구현이 소유한다(#137 F10 시간 축)."""
    store.remove_corrupt_entry(token)
