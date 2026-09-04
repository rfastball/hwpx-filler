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

from ..domain.mapping import MappingProfile
from .run_state import unresolved_name_tokens_in

# ── 연결 확정 대기(#911) ────────────────────────────────────────────────────────────────
# 「변경 저장」과 **다른 동사**다. 관리 검토가 연결 확정을 요구하는데 매핑이 이미 옳으면
# 더럽힐 것이 없어 변경 기반 무장이 영영 안 열린다(#895 3차 관측: 푸터 두 동사 모두 비활성,
# blocker 는 REVIEW_BINDING 상주). 그래서 문안이 **무변경 확정**임을 먼저 말한다 — 변경을
# 전제한 라벨로는 누를 이유가 화면 어디에도 없다.
#
# 어휘는 정본표를 따른다(COPY_STYLE_GUIDE §4-A): 사용자 대면에서 Binding 은 '연결'이다.
# 같은 말을 쓰는 자리가 이미 있다 — 편집기의 '필드 연결·표시' 탭과 실행 결과 증거의 판본
# 줄(`연결 r5`). 편집기 머리의 판본 표기는 #945 F5 로 걷혔지만(내부 어휘) 어휘 정본은
# 그 표기가 아니라 정본표라 이 상수의 근거는 그대로 선다.
BINDING_CONFIRM_LABEL = "연결 확정"
BINDING_CONFIRM_HINT = "바꿀 것이 없어도 지금 연결을 확정해야 문서를 만들 수 있습니다."

# ── 작업 이름 기본값(U6-D #978) ─────────────────────────────────────────────────────────
#: 두 이름을 잇는 **이름 구분자**. em dash 가 아니라 가운뎃점이다(U6 §5 미결 항목의 확정):
#: `docs/COPY_STYLE_GUIDE.md` §3-1 이 문장 안 em dash 를 전면 금지하는데, 라벨 문형과
#: 이름 문형이 같은 글자를 두 뜻으로 쓰면 그 규칙이 자리마다 예외를 갖는다. 「·」는 이미
#: 제품 전반의 병기 구분자다(개수 병기·손실 목록·구간 요약).
JOB_NAME_SEPARATOR = " · "

#: 도출된 이름 옆에 서는 힌트 — **표지가 참일 때만** 선다(사람이 고치면 사라진다).
NAME_DERIVED_HINT = "템플릿과 데이터 이름에서 미리 채웠습니다. 고쳐도 됩니다."


def derive_job_name(template_display: str, data_display: str) -> str:
    """작업 이름 기본값 — 「{템플릿} · {데이터}」(순수).

    이름을 **비어 있는 필수 입력**으로 두면 저장 게이트의 「작업 이름을 입력하세요」가
    거의 모든 초안에서 서고, 사람은 방금 고른 두 이름을 손으로 다시 적는다. 도출값은
    추측이 아니라 재진술이다 — 화면이 이미 머리에서 말하고 있는 두 이름 그대로다.

    한쪽만 있으면 그것 하나이고 둘 다 없으면 ``""`` 다: 없는 절반을 자리표시자로 채우면
    이름이 「공고서 · (데이터 없음)」 같은 문장이 되어 저장본에 그대로 굳는다.
    """
    left, right = template_display.strip(), data_display.strip()
    if left and right:
        return f"{left}{JOB_NAME_SEPARATOR}{right}"
    return left or right


@dataclass(frozen=True)
class SaveVerdict:
    """저장 게이트 판정 1회 — 차단이면 ``block_reason``, 통과면 확정 ``profile``.

    술어 순서는 고정 계약이다:
    매핑 미확정 → 템플릿 스키마 불일치 → 데이터 미연결(#932 U4-C) → 이름 없음 →
    파일명 패턴 없음(RC-20) → 전부 비움(RC-08) → 미해소 파일명 토큰.

    ``blocked_field="data"`` 가 가리키는 자리는 U6-B(#976)에서 **1단계 「고르기」의 데이터
    풀**로 옮겨 갔다 — 종전의 2단계 머리 관문(`DataGateway`)이 그 자리에서 걷혔다. 판정
    순서·술어는 그대로이고 바뀐 것은 처방이 지목하는 표면 이름 하나다.

    ``blocked_field`` 는 **고칠 입력이 어디인가**다(U2 §2.4). 차단 문구만 띄우고 커서를
    안 옮기면 "입력하세요"라고 말한 뒤 어디에 입력할지는 안 알려 주는 꼴이다. 판정이 낸
    이름을 표면이 그대로 겨눈다 — 링2 가 차단 **문구를 파싱해** 어느 칸인지 알아내면 문안을
    고칠 때마다 조준이 조용히 깨진다.

    ``"name"`` 과 ``"pattern"`` 이 사는 자리는 U6-D(#978)에서 **3단계 「이름·저장」 폼**으로
    모였다 — 이름은 종전 편집기 머리의 인라인 입력이었다(라벨 없이 제목 자리에 살아 특히 못
    찾던 자리). 그 자리를 **문안이 지목한다**: 다른 단계에서 막혔을 때 표면이 대신 그 단계로
    옮겨 가면 지나온 단계의 patch 가 자동 버리기에 걸려, 거절된 저장이 사람이 방금 한 편집을
    없앤다(연결 확인의 비움 선언이 그렇게 사라진다). 거절은 아무것도 파괴하지 않는다 —
    그래서 이동은 사람이 하고, 차단 문구가 어느 단계인지를 말한다.
    """

    block_reason: str = ""
    profile: "MappingProfile | None" = None
    blocked_field: str = ""

    @property
    def ok(self) -> bool:
        return not self.block_reason


def validate_save(
    model, name: str, pattern: str, *, data_path: str,
    schema=None, media: str = "hwpx",
) -> SaveVerdict:
    """저장 전 게이트 술어(순수) — 위젯은 ``block_reason`` 을 경고로 띄우기만 한다.

    ``model`` 은 :class:`~hwpxfiller.gui.mapping_state.MappingModel`(또는 ``None``).
    '전부 비움'은 링1 질의(:meth:`~hwpxfiller.gui.mapping_state.MappingModel.emits_any_value`)
    로 판단한다 — 자료구조 내부 표현을 재구현하지 않는다(RC-08). 「비워 둠」 표시형 퇴역
    뒤 **빈 고정값은 값 선언**이라 전 필드를 그렇게 확정한 작업도 통과한다(누름틀에 빈
    문자열을 실제로 써 넣는다). 남은 차단은 아무것도 선언하지 않은 확정 행이라, 지금
    표면이 만들 수 없는 상태의 **방어층**이다. 통과 시 ``profile`` 에 확정 매핑 프로파일을
    담아 재계산 없이 저장에 쓴다.

    ``schema`` 가 주어지면(현재 로드된 템플릿 스키마) 매핑 행 필드가 그 스키마 필드와
    정확히 일치하는지 재대조한다 — 세션 혼합(#25)으로 구 템플릿 스키마 기반 모델이
    새 템플릿으로 저장되는 조용한 오저장을 시끄럽게 차단한다(confirm-or-alarm, 방어층).

    ``media`` — 파일명 패턴 게이트는 **매체 인지**다(F6 PR-B): TXT 작업은 파일을 만들지
    않아 파일 이름 축 자체가 없다(§3.2). 없는 규칙을 요구하면 고칠 표면이 없는 차단
    문구가 된다. U6-D(#978) 뒤로 TXT 도 3단계를 갖지만 그 단계의 **문서 파일 이름 행**은
    서지 않으므로 이 술어의 근거는 그대로다(단계가 아니라 행이 매체 파생이다).

    ``data_path`` 는 이 세션이 선 **데이터 결속**의 경로다(U4 §2.4, #932 U4-C). 기본값이
    없는 키워드인 이유는 그것이 곧 이 게이트의 실체이기 때문이다: 기본을 두면 결속을
    안 실은 호출부가 조용히 통과하거나 조용히 차단당하고, 어느 쪽이든 판정이 호출부의
    부주의로 정해진다. 술어 자체는 :func:`~hwpxfiller.domain.job.has_data_binding` 과
    같은 축(경로 하나)이다.
    """
    if model is None or not model.is_complete():
        return SaveVerdict("모든 매핑 행을 확정해야 작업을 저장할 수 있습니다.")
    if schema is not None and {r.template_field for r in model.rows} != {
        f.name for f in schema.fields
    }:
        return SaveVerdict(
            "매핑이 현재 템플릿 스키마와 일치하지 않습니다. 템플릿을 다시 로드한 뒤 저장하세요."
        )
    # 데이터 결속은 **템플릿 다음**이다(U4 §2.4, #932 U4-C): 템플릿이 필드를 정하고 그
    # 다음에 그 필드를 채울 데이터가 온다. 이름·파일명보다 앞에 서는 이유도 같다 — 데이터가
    # 없으면 이름을 붙일 대상이 아직 규칙으로 완결되지 않았고, 사람이 이름부터 고치게 하면
    # 정작 막힌 자리는 두 번째 저장에서야 드러난다. 「데이터 없이 진행」은 이 술어와 함께
    # 사라졌다(#932 U4-C S2-4).
    if not data_path:
        return SaveVerdict(
            "데이터를 연결해야 작업을 저장할 수 있습니다. '고르기' 단계에서 데이터를 고르세요.",
            blocked_field="data",
        )
    if not name:
        return SaveVerdict(
            "'이름·저장' 단계에서 작업 이름을 입력하세요.", blocked_field="name"
        )
    # 파일명 패턴은 문서 식별자를 결정한다 — 빈 입력을 화면에 없던 값으로
    # 조용히 폴백하지 않는다(확인-또는-경보, RC-20). TXT 는 이 축이 없다(위 docstring).
    if media != "txt" and not pattern:
        return SaveVerdict(
            "'이름·저장' 단계에서 문서 파일 이름을 입력하세요.", blocked_field="pattern"
        )
    if not model.emits_any_value():
        return SaveVerdict(
            "확정된 매핑이 전부 비움이라 채울 값이 없습니다. 소스를 지정한 뒤 저장하세요."
        )
    profile = model.to_profile(name)
    # 미해소 파일명 토큰은 **저장 시점**에 막는다(U4 계열4-4). 이 검사는 데이터가 필요 없는
    # 작업 정의 수준 계약이라 여기서 답할 수 있고, 실행 화면까지 미루면 「고칠 자리는 편집기인데
    # 지적은 문서 만들기에서」가 돼 수정 동선이 갈린다. 판정 몸통은 실행 게이트와 공유한다.
    if media != "txt":
        unresolved = unresolved_name_tokens_in(profile, pattern)
        if unresolved:
            listed = ", ".join(f"{{{{{token}}}}}" for token in unresolved)
            return SaveVerdict(
                f"파일명 패턴의 {listed} 에 채울 값이 없습니다. "
                "매핑에서 그 항목을 연결하거나 패턴에서 지운 뒤 저장하세요.",
                blocked_field="pattern",
            )
    return SaveVerdict(profile=profile)


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
