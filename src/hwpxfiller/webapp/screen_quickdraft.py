"""빠른 기안 화면 컨트롤러 — 작업의 휘발 쌍둥이(R-flow 블록 5, 결정 29). webview 비의존.

R-flow 구현 라운드(에픽 #90) 슬라이스 7. 링1 :class:`~hwpxfiller.gui.quickdraft_state.
QuickDraftViewModel` 을 소유·위임하는 얇은 어댑터다 — 다른 실행 표면과 같은 컨트롤러 계약
(``name``·``initial``·``snapshot``·``dispatch``)을 구현하고 등록 한 줄로 배선된다.

**빠른 기안 = 아무것도 저장하지 않는 작업**(결정 29): 템플릿(라이브러리 사본/붙여넣기)과
선택적 데이터를 세션 안에서만 결합해 복사한다. 세션 전체가 휘발이라(결정 32의 휘발도 사다리)
레일 이탈·복귀는 생존하지만 앱 종료·「새 기안」은 소멸한다. 남기려면 승격 동사(작업/템플릿
저장)로만 동결하는데, 그 승격은 **후속 슬라이스**다(이번엔 표면·복사·휘발도 가드까지).

**슬라이스 착지 순서**(confirm-or-alarm — 없는 기능을 있는 척하지 않는다):
- **PR-1(이 커밋)**: 컨트롤러 골격 + 레일/화면 신설 + 빈 세션 스냅샷. 눈에 보이는 결과는
  도달 가능한 빈손 화면이다(템플릿 소스·토큰 폼·데이터는 아직 없다).
- PR-2: 템플릿 소스(라이브러리·붙여넣기·원문 라이브 편집) + 파이프라인 토큰 폼 + 미리보기
  채움 표지(결정 22·34).
- PR-3: 데이터 소스 이원 + 제스처 결속(정확=자동·근사=제안) + 행 재겨눔 3분류 + 표현형 3층
  (결정 30·31).
- PR-4: 휘발도 가드(결정 32) + 복사(사후 경보 승계) + 표지 토글·소유권 색 + 레일 문구.

**스코프 경계 — 미구현 명시**: 승격 2동사(「작업으로 저장」·「템플릿으로 저장」, 결정 33)는
이 라운드에서 표면만 짓고 승격 자체는 후속으로 분리한다. 승격이 매핑 초안을 미확정 착지시켜
에디터 확정 워크플로가 엄격성을 재부과하는 국경(결정 31)은 그 후속의 계약이다.
"""
from __future__ import annotations

from ..core.text_registry import TextTemplateRegistry
from ..gui.quickdraft_state import QuickDraftViewModel
from .screens import (
    DatasetPoolRegistry,
    PushSink,
    default_pool_registry,
)


class QuickDraftController:
    """빠른 기안 화면 — :class:`QuickDraftViewModel` 소유·위임(링1 로직 재구현 금지)."""

    name = "quickdraft"

    def __init__(
        self,
        registry: TextTemplateRegistry,
        push: PushSink,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
    ) -> None:
        self._registry = registry
        self._push_sink = push
        # 등록 데이터(풀) 겨눔(결정 34의 데이터 판) — 기본은 홈 레지스트리, 테스트는 주입.
        # 다른 실행 표면과 **같은 인스턴스**를 공유해야 데이터 관리 화면의 변경이 즉시 보인다.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
        # 템플릿 라이브러리는 txt·템플릿 관리와 공유 레지스트리(변경이 양쪽에 반영).
        self.vm = QuickDraftViewModel(registry)

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def snapshot(self) -> dict:
        """휘발 세션의 웹 관측 스냅샷. PR-1 은 빈 세션 형상만 방출한다(토큰·데이터는 후속)."""
        vm = self.vm
        return {
            # 템플릿 정체 — 유래(lib/paste)와 (수정됨) 강등 여부는 슬롯 라벨이 소비(결정 34).
            "origin": vm.origin,
            "template_name": vm.template_name,
            "template_text": vm.template_text,
            "modified": vm.modified,
            # 토큰 폼(파이프라인)·데이터 존은 후속 PR — 지금은 빈 계약으로 형상만 고정한다.
            "tokens": [],
            # 겨눔 존재의 단일 진실 = datasource(파생 bool, 별도 저장 없음). data_kind 는
            # 유래(등록/파일)일 뿐 존재 사본이 아니다 — 불변식은 VM 이 원자 세엄으로 성립(PR-3).
            "has_data": vm.datasource is not None,
            "data_label": vm.data_label,
            "data_kind": vm.data_kind,
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태 — 슬롯 드롭다운용 템플릿 목록 포함."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅 후 푸시. 미지 액션은 시끄럽게 거부(P5 규약 정렬).

        PR-1 은 아직 ``_do_*`` 핸들러가 없다 — 템플릿 소스(PR-2)·데이터 결속(PR-3)·휘발도
        가드/복사(PR-4)가 액션을 얹으며 각각 JS 호출자와 함께 배선된다(미배선 액션 금지,
        ``test_dispatch_wiring`` 규약). 그때 이 파일이 ``CONTROLLER_FILES`` 에 합류한다.
        """
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 빠른 기안 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result
