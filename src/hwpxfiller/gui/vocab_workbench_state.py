"""매핑 프로파일 관리 ViewModel — Qt 비의존(링1). 공유 매핑 프로파일(베이스)의 관리면.

위젯(:class:`~hwpxfiller.gui.vocab_workbench.VocabWorkbenchPanel`)은 이 뷰모델을 들고
목록 렌더·삭제·이름변경만 오케스트레이션한다. 베이스 **저작**은 위저드가 담당한다
(베이스 = 위저드에서 확정한 매핑을 명명 저장한 것) — 워크벤치는 목록·참조수·수명 관리다.

**참조 경고**(ADR J 전파): 베이스를 삭제/이름변경하면 그 베이스를 계보로 참조하는 작업
(Job.base_mapping_name)이 영향받는다 → 참조 작업 수/이름을 시끄럽게 노출한다. 이름변경은
참조 작업의 **계보만** 새 이름으로 갱신한다(매핑 자체는 불변 — run-path 무관).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VocabBaseRow:
    """공유 베이스 1건이 렌더할 성형 데이터 — 위젯은 이 필드만 읽는다."""

    name: str
    field_count: int
    ref_count: int  # 이 베이스를 계보로 참조하는 작업 수

    def ref_badge(self) -> str:
        return f"작업 {self.ref_count}개 참조" if self.ref_count else "참조 작업 없음"


class VocabWorkbenchViewModel:
    """공유 베이스 목록 + 수명 관리. 위젯은 구독해 렌더한다(Qt 비의존).

    ``base_registry`` 는 :class:`~hwpxfiller.core.mapping_base.MappingBaseRegistry`,
    ``job_registry`` 는 참조수 계산용(없으면 참조수 0으로 성형). 둘 다 주입 가능(테스트).
    """

    def __init__(self, base_registry, job_registry=None):
        self.registry = base_registry
        self.job_registry = job_registry
        self._rows: "list[VocabBaseRow]" = []
        self._subs: list = []
        self.refresh()

    # ---------------------------------------------------------- 변경 통지
    def subscribe(self, cb) -> None:
        self._subs.append(cb)

    def _notify(self) -> None:
        for cb in self._subs:
            cb()

    # ---------------------------------------------------------- 참조 조회
    def ref_names(self, base_name: str) -> "list[str]":
        """이 베이스를 계보로 참조하는 작업 이름들(전파 경고의 근거)."""
        if self.job_registry is None:
            return []
        return [
            j.name for j in self.job_registry.list_jobs()
            if getattr(j, "base_mapping_name", "") == base_name
        ]

    # ---------------------------------------------------------- 데이터
    def refresh(self) -> None:
        self._rows = [
            VocabBaseRow(b.name, len(b.mappings), len(self.ref_names(b.name)))
            for b in self.registry.list_bases()
        ]
        self._notify()

    def rows(self) -> "list[VocabBaseRow]":
        return list(self._rows)

    def is_empty(self) -> bool:
        return not self._rows

    def count_label(self) -> str:
        return f"{len(self._rows)}개" if self._rows else ""

    # ---------------------------------------------------------- 수명
    def delete(self, name: str) -> None:
        """베이스 삭제. 참조 작업의 계보(base_mapping_name)는 그대로 두어 '없어진 베이스를
        가리키는' 상태를 숨기지 않는다(순수 메타라 무해, 재저장 시 자연 해소)."""
        self.registry.delete(name)
        self.refresh()

    def rename(self, old: str, new: str) -> None:
        """베이스 이름변경 — 프로파일 복사·구 삭제 + 참조 작업 **계보만** 새 이름으로 갱신.

        매핑 내용은 불변(run-path 무관). 새 이름이 이미 있으면 시끄럽게 거절.
        """
        new = (new or "").strip()
        if not new:
            raise ValueError("새 이름이 비어 있습니다.")
        if new == old:
            return
        if self.registry.exists(new):
            raise ValueError(f"'{new}' 베이스가 이미 있습니다.")
        profile = self.registry.load(old)
        profile.name = new
        self.registry.save(profile)
        self.registry.delete(old)
        if self.job_registry is not None:
            for j in self.job_registry.list_jobs():
                if getattr(j, "base_mapping_name", "") == old:
                    j.base_mapping_name = new
                    self.job_registry.save(j)
        self.refresh()
