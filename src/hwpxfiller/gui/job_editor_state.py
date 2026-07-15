"""작업 저장 게이트 판단 — Qt 비의존(링1). 에디터 ``accept()`` 의 술어를 헤드리스로 뽑았다.

``JobEditorWizard.accept`` 는 Qt 오버라이드라 헤드리스 테스트 사각이었고, RC-08(전부 비움
dead guard)이 그 사각에서 시그널 없이 썩은 실증이다(RC-28). 저장 가부·차단 사유·덮어쓰기
확인 필요 여부·확인 문구는 전부 여기서 판정/성형하고, 위젯은 결과를 그대로 그린다
(다이얼로그 표시만).

**확인-또는-경보**: 차단 사유는 구체 문구로 재진술하고(조용한 무저장 금지), 다른 작업을
덮게 되는 저장만 확인을 요구한다(자기 자신 갱신은 자명 — 프롬프트 없음).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.mapping import MappingProfile


@dataclass(frozen=True)
class SaveVerdict:
    """저장 게이트 판정 1회 — 차단이면 ``block_reason``, 통과면 확정 ``profile``.

    술어 순서는 종전 ``accept()`` 와 동일하게 고정한다:
    매핑 미확정 → 이름 없음 → 파일명 패턴 없음(RC-20) → 전부 비움(RC-08).
    """

    block_reason: str = ""
    profile: "MappingProfile | None" = None

    @property
    def ok(self) -> bool:
        return not self.block_reason


def validate_save(model, name: str, pattern: str, *, schema=None) -> SaveVerdict:
    """저장 전 게이트 술어(순수) — 위젯은 ``block_reason`` 을 경고로 띄우기만 한다.

    ``model`` 은 :class:`~hwpxfiller.gui.mapping_state.MappingModel`(또는 ``None``).
    '전부 비움'은 링1 질의(:meth:`~hwpxfiller.gui.mapping_state.MappingModel.emits_any_value`)
    로 판단한다 — blank 선언도 mappings 에 영속화되므로(L1) 자료구조 내부 표현을
    재구현하지 않는다(RC-08). 통과 시 ``profile`` 에 확정 매핑 프로파일을 담아
    재계산 없이 저장에 쓴다.

    ``schema`` 가 주어지면(현재 로드된 템플릿 스키마) 매핑 행 필드가 그 스키마 필드와
    정확히 일치하는지 재대조한다 — 세션 혼합(#25)으로 구 템플릿 스키마 기반 모델이
    새 템플릿으로 저장되는 조용한 오저장을 시끄럽게 차단한다(confirm-or-alarm, 방어층).
    """
    if model is None or not model.is_complete():
        return SaveVerdict("모든 매핑 행을 확정해야 작업을 저장할 수 있습니다.")
    if schema is not None and {r.template_field for r in model.rows} != {
        f.name for f in schema.fields
    }:
        return SaveVerdict(
            "매핑이 현재 템플릿 스키마와 일치하지 않습니다 — 템플릿을 다시 로드한 뒤 저장하세요."
        )
    if not name:
        return SaveVerdict("작업 이름을 입력하세요.")
    # 파일명 패턴은 문서 식별자를 결정한다 — 빈 입력을 화면에 없던 값으로
    # 조용히 폴백하지 않는다(확인-또는-경보, RC-20).
    if not pattern:
        return SaveVerdict("파일명 패턴을 입력하세요.")
    if not model.emits_any_value():
        return SaveVerdict(
            "확정된 매핑이 전부 비움이라 채울 값이 없습니다. 소스를 지정한 뒤 저장하세요."
        )
    return SaveVerdict(profile=model.to_profile(name))


def needs_overwrite_confirm(
    name: str, initial_name: "str | None", exists: bool
) -> bool:
    """이 이름 저장에 덮어쓰기 확인이 필요한가(순수).

    자기 자신 갱신(편집 모드, 이름 그대로)은 자명이라 묻지 않는다 — 이름을 바꿔
    **다른 기존 작업**을 덮게 될 때만 True.
    """
    editing_self = initial_name is not None and name == initial_name
    return not editing_self and exists


def overwrite_confirm_text(name: str, victim: str) -> str:
    """덮어쓰기 확인 문구 — 실제 파괴 대상을 재진술한다(RC-15 P6).

    레지스트리는 slug 로 저장하므로 입력 이름(``name``)과 파괴되는 기존 작업 이름
    (``victim``)이 다를 수 있다 — 입력 이름만 재진술하면 확인 내용이 거짓이 된다.
    ``victim=""`` 은 기존 파일이 손상되어 이름 불명인 경우(추측 금지, 그대로 고지).
    """
    if not victim:
        return (
            f"작업 '{name}' 의 저장 위치에 기존 작업 파일이 있습니다"
            "(손상되어 어떤 작업인지 확인할 수 없습니다).\n"
            "계속하면 그 파일을 덮어씁니다."
        )
    if victim != name:
        return (
            f"작업 이름 '{name}' 은(는) 기존 작업 '{victim}' 과(와) 같은 파일로 "
            f"저장됩니다.\n계속하면 작업 '{victim}' 을(를) 덮어씁니다."
        )
    return f"작업 '{name}' 이(가) 이미 있습니다.\n계속하면 기존 작업을 덮어씁니다."
