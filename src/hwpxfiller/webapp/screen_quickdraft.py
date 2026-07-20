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
- **PR-3(이 커밋)**: 데이터 소스 이원(등록 데이터·임의 파일) + 제스처 결속(정확=자동·
  근사=제안 원클릭) + 행 재겨눔 3분류 고지 + 표현형 3층(결정 30·31·32·34).
- PR-4: 휘발도 가드(「새 기안」·템플릿 전환) + 복사(사후 경보 승계) + 표지 토글·소유권 색 +
  레일 문구 + 승격 2동사 표면.

**스코프 경계 — 미구현 명시**: 승격 2동사(「작업으로 저장」·「템플릿으로 저장」, 결정 33)는
이 라운드에서 표면만 짓고 승격 자체는 후속으로 분리한다. 승격이 매핑 초안을 미확정 착지시켜
에디터 확정 워크플로가 엄격성을 재부과하는 국경(결정 31)은 그 후속의 계약이다.
"""
from __future__ import annotations

from ..core.format_engine import presets as format_presets
from ..core.mapping import TYPES
from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import render_segments
from ..gui.quickdraft_state import QuickDraftViewModel, QuickToken
from .screens import (
    NO_ROWS_TEXT,
    DatasetPoolRegistry,
    PushSink,
    default_pool_registry,
    load_pool_into,
    pool_sources_payload,
    source_label,
)

# 표시형 프리셋 목록(유형별) — 에디터 스냅샷과 **같은 표(format_engine)**에서 뽑는다.
# 빠른 기안의 fmt 코드가 승격 시 매핑 행의 fmt 로 그대로 이관되려면 두 표면이 같은 어휘를
# 써야 한다(결정 31의 "프리셋 키 = 매핑과 1:1").
_FMT_OPTIONS = {
    t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES
}


def _token_state(t: QuickToken) -> str:
    """토큰 폼 칩 상태(결정 30·31 표현형 3층) — 카드 표지와 한 출처가 되게 이름을 고정한다.

    - ``auto``: 결속·무수정(자동 서식). ``hand``: 결속·직접 수정(사람 소유 강등).
    - ``man``: 무결속 수기 값. ``blank``: 비어 있음.

    결속 토큰은 값이 비어도(데이터 빈칸) ``auto`` 다 — 「비어 있음」은 아직 임자가 없는
    자리를 뜻하는 말이라, 임자가 있는데 값이 빈 자리와 섞으면 표지가 거짓말을 한다.
    """
    if t.col and not t.edited:
        return "auto"
    if t.col and t.edited:
        return "hand"
    if t.text.strip() != "":
        return "man"
    return "blank"


#: 고지 문안에 이름을 그대로 적는 상한 — 넘으면 「외 N개」로 접는다.
_NAMES_SHOWN = 3


def _names(names: "list[str]") -> str:
    """토큰 이름 열거 — 소량은 전부, 대량은 앞 몇 개 + 「외 N개」(결정 5 표본 문안 동형).

    빠른 기안의 토큰 수는 한 화면 분량이라 층화가 필요 없다 — 순서 그대로가 사용자가 폼에서
    보는 순서다.
    """
    if len(names) <= _NAMES_SHOWN:
        return ", ".join(names)
    return f"{', '.join(names[:_NAMES_SHOWN])} 외 {len(names) - _NAMES_SHOWN}개"


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
        """휘발 세션의 웹 관측 스냅샷 — 템플릿 정체·토큰 폼·미리보기 세그먼트.

        미리보기는 링1 :func:`~hwpxfiller.core.text_render.render_segments`(채움 표지 삼분,
        결정 22·33)를 소비한다: 웹은 토큰 정규식을 재구현하지 않는다(파생경계 번역오류 상류
        차단). 토큰 상태 배지도 같은 값 레코드에서 파생해 카드와 한 출처가 되게 한다.
        데이터 존(PR-3)·복사/가드(PR-4)는 아직 없다.
        """
        vm = self.vm
        record = vm.values_record()
        segments, report = render_segments(vm.template_text, record)
        missing, empty = report.missing_fields, report.empty_fields
        tokens = [
            {
                "name": t.name,
                "state": _token_state(t),
                "value": vm.token_value(t),
                # 파이프라인 폼 2열(결정 34): 소스(결속 열, ''=무결속) → 표시형(유형+코드).
                "col": t.col or "",
                "fmt_kind": t.fmt_kind,
                "fmt_code": t.fmt_code,
                # 근사 제안(결정 30) — 자동으로 붙지 않고 버튼 하나로만 붙는다.
                "suggest": vm.suggest_for(t) or "",
            }
            for t in vm.tokens
        ]
        return {
            # 템플릿 정체 — 유래(lib/paste)와 (수정됨) 강등 여부는 슬롯 라벨이 소비(결정 34).
            "origin": vm.origin,
            "template_name": vm.template_name,
            "template_text": vm.template_text,
            "modified": vm.modified,
            # 파이프라인 토큰 폼(결정 34) — 이름·상태(칩)·현재 값. 소스/표시형 드롭다운은 데이터
            # 결속과 함께 PR-3 에서 붙는다(PR-2 는 무결속 수기 값만).
            "tokens": tokens,
            # 미리보기 세그먼트(채움 표지 삼분) — literal/fill/blank/missing. 무결속 빈 토큰은
            # missing 으로 {{토큰}} 원문이 빨강으로 남는다(방향 A 미채움 = 아직 안 채운 자리).
            "segments": [{"text": s.text, "kind": s.kind, "name": s.name} for s in segments],
            "missing_fields": missing,
            "empty_fields": empty,
            # 미채움 = 렌더에서 빠진(missing) + 데이터 빈칸(blank). 알약·상태 배지가 소비.
            "unfilled_count": len(missing) + len(empty),
            # 겨눔 존재의 단일 진실 = datasource(파생 bool, 별도 저장 없음). data_kind 는
            # 유래(등록/파일)일 뿐 존재 사본이 아니다 — 불변식은 VM 의 원자 세엄이 성립시킨다.
            "has_data": vm.has_data(),
            "data_label": vm.data_label,
            "data_kind": vm.data_kind,
            # 병기 라벨은 저장하지 않고 매번 합성한다(K8 단일 출처 — 세 표면 공통 문구).
            "data_source_label": source_label(vm.data_kind, vm.data_label),
            # 경량 데이터 슬롯(단건 표면) — 열 목록·행 스테퍼. 필터·다중 선택 문법은 N 행
            # 표면(txt 큐·작업 존)의 것이라 여기 들이지 않는다(결정 34 형상).
            "columns": vm.columns,
            "record_count": vm.record_count(),
            "row_idx": vm.row_idx,
            "row_label": vm.row_label(),
            "fmt_options": _FMT_OPTIONS,
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태 — 슬롯 드롭다운용 템플릿 목록 포함."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    # 타이핑 구동 액션(값 입력·원문 편집)은 **푸시하지 않고 스냅샷을 반환**한다. 서버 푸시가
    # 포커스된 textarea 의 innerHTML 을 재구성하면 왕복 중 입력한 글자가 지워지고 한글 IME
    # 조합이 끊긴다(슬라이스 4 stale 경합 클래스, 리뷰 확정). JS 가 반환 스냅샷으로 미리보기·
    # 폼만 겨냥 패치하고 포커스 입력은 손대지 않는다(전면 재렌더는 구조 액션에서만).
    _NO_PUSH = {"set_token", "edit_source"}

    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅. 미지 액션은 시끄럽게 거부(P5 규약 정렬).

        구조 액션(템플릿 선택·붙여넣기)은 관측 푸시로 전면 재렌더한다. 타이핑 액션은
        :attr:`_NO_PUSH` 라 푸시 대신 스냅샷을 반환해 JS 가 겨냥 패치하게 한다(위 설명).
        데이터 결속(PR-3)·휘발도 가드/복사(PR-4)가 액션을 더 얹는다(미배선 금지, dispatch_wiring).
        """
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 빠른 기안 액션: {action!r}")
        result = handler(payload)
        if action in self._NO_PUSH:
            return result  # 포커스 입력 보호 — 푸시 대신 반환 스냅샷으로 JS 가 겨냥 패치
        if getattr(handler, "is_query", False):
            return result  # 무변이 질의(고지 판정) — 재렌더 유발 금지(txt·작업 동형)
        self._push()
        return result

    # ---------------------------------------------------- 템플릿 소스(PR-2)
    def _do_select_template(self, p: dict) -> None:
        """슬롯 드롭다운·빈손 카드에서 라이브러리 템플릿 선택 — 세션 사본 적용(결정 34)."""
        self.vm.apply_library(p["name"])

    def _do_paste_template(self, p: dict) -> None:
        """붙여넣기 모달 확정 — 이름 없는 세션 사본(라이브러리 비저장, 결정 34).

        빈 붙여넣기(공백뿐)는 세션을 비운다 — origin='paste' 로 두면 슬롯은 「붙여넣은 텍스트」를
        가리키는데 본문·알약은 빈손을 말해 세 표면이 어긋난다(리뷰 확정, confirm-or-alarm 위반).
        """
        text = p["text"]
        if text.strip() == "":
            self.vm.fresh()
        else:
            self.vm.apply_paste(text)

    def _do_edit_source(self, p: dict) -> dict:
        """원문 편집 탭 라이브 편집 — 타이핑이 토큰 폼을 즉시 재구성((수정됨) 강등, 결정 34).

        _NO_PUSH: 반환 스냅샷으로 JS 가 폼 패인만 재구성하고 포커스된 원문 textarea 는 안 만진다.
        """
        self.vm.edit_source(p["text"])
        return self.snapshot()

    def _do_set_token(self, p: dict) -> dict:
        """토큰 값 직접 입력 — 결속 토큰이면 사람 소유로 강등한다(표현형 3층 최하층).

        _NO_PUSH: 반환 스냅샷으로 JS 가 미리보기만 패치하고 포커스된 값 textarea 는 안 만진다.
        """
        self.vm.set_token_text(p["name"], p.get("text", ""))
        return self.snapshot()

    # ------------------------------------------------- 데이터 겨눔·결속(PR-3)
    #
    # 등록 데이터 겨눔에 :class:`~hwpxfiller.webapp.screens.PoolTargetingMixin` 을 섞지
    # 않는다: 그 래퍼는 **컨트롤러가 라벨·유래를 따로 저장**하는 표면(txt·작업)을 위한
    # 것이라 `data_label = …` → `data_source = …` → `_after_pool_load(…)` 세 대입 사이에
    # 부분 상태 창이 열리는데, 빠른 기안은 겨눔 상태 전부가 휘발 세션 VM 소유이고 불변식
    # (`datasource ⟺ data_kind`)을 **원자 세엄 하나**로만 성립시키기로 했다(PR-1 리뷰).
    # 게이트·문구의 공용 실행부(load_pool_into·pool_sources_payload·source_label·
    # NO_ROWS_TEXT)는 그대로 소비하므로 나라 동결·모호 시트·죽은 참조·0건 재진술은 세
    # 표면 단일 출처다(부록 A-31) — 손복사되는 것은 없다.
    def _do_pool_sources(self, p: dict) -> dict:
        """활성 등록 데이터 목록 — 공용 피커(pool_picker.js)가 그대로 소비한다."""
        return pool_sources_payload(self.pool_registry)

    def _do_load_pool(self, p: dict) -> dict:
        """등록 데이터 겨눔 — 공유 관문에 위임(실패는 raise 대신 오류 dict 재진술)."""
        res = load_pool_into(self.pool_registry, p["name"], self.vm.load_pool_item)
        if not res["ok"]:
            return res
        return {"ok": True, "label": source_label("pool", self.vm.data_label)}

    def _do_clear_data(self, p: dict) -> None:
        """데이터 해제 — 결속 값은 평문 동결(결정 30). 가드 고지는 웹이 먼저 받는다."""
        self.vm.clear_data()

    def _do_set_row(self, p: dict) -> None:
        """행 재겨눔 — 결속·무수정 값만 조용히 재생성된다(결정 32의 3분류)."""
        self.vm.set_row(int(p["index"]))

    def _do_set_source(self, p: dict) -> None:
        """토큰 결속·해제(제안 원클릭·드롭다운 공유 액션) — 해제도 값은 평문 동결."""
        self.vm.bind(p["name"], p.get("col") or None)

    def _do_set_fmt(self, p: dict) -> None:
        """표현형 정정(2층) — 프리셋 코드만 바꾼다(유형은 열이 정한다)."""
        self.vm.set_fmt(p["name"], p.get("code", ""))

    def _do_revert_token(self, p: dict) -> None:
        """직접 수정 → 자동 복귀 — 강등을 되돌리는 출구(막다른 강등 금지, 결정 31)."""
        self.vm.revert_token(p["name"])

    def _do_carry_notice(self, p: dict) -> dict:
        """데이터 교체·해제·행 이동 전 고지 문안 — 지금 Python 이 판정한다(스냅샷 캐시 아님).

        ``armed`` 가 참이면 웹이 확인을 받는다. 결속·무수정 값은 관계에서 재생성되므로
        고지 대상이 아니고, **직접 수정 값(혼합)**·**무결속 수기 값(유지)**만 말한다.
        """
        carry = self.vm.carry_over()
        edited, manual = carry["edited"], carry["manual"]
        parts = []
        if edited:
            parts.append(f"직접 고친 값 {len(edited)}개({_names(edited)})")
        if manual:
            parts.append(f"직접 입력한 값 {len(manual)}개({_names(manual)})")
        message = ""
        if parts:
            message = (
                f"{' 와 '.join(parts)}는 새 데이터에서도 그대로 남습니다. "
                "데이터에서 오는 값과 섞이니 확인하고 계속하세요."
            )
        return {"armed": bool(parts), "message": message, "edited": edited, "manual": manual}

    _do_carry_notice.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 임의 파일을 겨눔(결정 34) — 0건이면 시끄럽게 실패하고 상태는 불변.

        브리지(``pick_data_file``/``load_data_sheet``)가 부르는 공개 표면이라 dispatch 를
        경유하지 않는다 — 그래서 푸시도 여기서 직접 한다.
        """
        records = self.vm.load_data(path, sheet=sheet)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 문구는 세 표면 단일 출처(R-copy)
        self._push()
