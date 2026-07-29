"""WebView dispatch contract: screen/action allow-list and payload-key schemas.

The browser bridge is an untyped boundary.  Keep its complete vocabulary here so
that a caller cannot accidentally reach an arbitrary ``_do_*`` method and a
misspelled/stale payload cannot be ignored silently by ``dict.get``.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class PayloadSchema:
    """Allowed keys for one action; values remain domain-controller owned."""

    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()

    @property
    def allowed(self) -> frozenset[str]:
        return self.required | self.optional


def _schema(required: str = "", optional: str = "") -> PayloadSchema:
    return PayloadSchema(frozenset(required.split()), frozenset(optional.split()))


# 존 변이는 **대상 세계**를 함께 실어 보낸다(재작성 F3 리뷰 4R): `epoch` 는 발신 시점에 웹이
# 보고 있던 범위 세계의 세대다. 초안이 열리거나 닫히거나(적용·취소) 데이터가 갈리면 세대가
# 오르고, 그 전에 예약·발신된 변이는 **도착해도 남의 세계의 편집**이라 적용되지 않는다.
# 선택 필드로 두는 이유: 세대 개념이 없는 옛 호출부의 무검사 통과 하위호환(소유는 job 하나 —
# 구 「기안」 공유 소비자는 F6 PR-B 에서 화면과 함께 걷혔다).
_ZONE_MUTATIONS = {
    "toggle_record": _schema("index value", "epoch"),
    "select_range": _schema("indices value", "epoch"),
    "set_all": _schema(optional="epoch"),
    "set_none": _schema(optional="epoch"),
    "filter_search": _schema(optional="text epoch"),
    "filter_col_text": _schema("column", "text epoch"),
    "filter_col_values": _schema("column", "values epoch"),
    "filter_col_range": _schema("column", "first second joiner epoch"),
    "filter_prune": _schema("column", "epoch"),
    "filter_clear": _schema(optional="epoch"),
    "filter_clear_col": _schema("column", "epoch"),
    "filter_reapply": _schema(optional="epoch"),
}
#: 세대 검사 대상 = 존 **변이** 액션 이름(컨트롤러가 dispatch 관문에서 소비).
#: 표시순서(`set_view_order`)도 같은 범위 상태를 바꾸므로 여기 든다 — 화면별 액션이지만
#: 세대의 소속은 **무엇을 바꾸는가**로 정한다(체인 키를 상태 단위로 둔 것과 같은 근거).
ZONE_MUTATIONS = frozenset(_ZONE_MUTATIONS) | {"set_view_order"}

_DATA_ZONE = {
    **_ZONE_MUTATIONS,
    # 무변이 질의 — 세대와 무관하다(상태를 안 바꾸니 늦게 도착해도 해가 없다).
    "filter_panel": _schema("column"),
}

_POOL_TARGETING = {
    "load_pool": _schema("name"),
}

_REGISTRY: dict[str, dict[str, PayloadSchema]] = {
    # 「문서 작업」 전역 라이브러리(§19.6·§19.7) — 구 `home` 채널의 승계자(재작성 F2).
    # 좌 목록 관리 동사 중 **열린 세션의 정체와 결속된 것**(rename_job·set_group·
    # rename_group·disband_group)은 여기 없다 — 「문서 만들기」(`job`)가 계속 소유하고
    # 라이브러리 표면이 교차 화면 dispatch 로 부른다(지도 §10.8 판정 F).
    "library": {
        "set_view": _schema(optional="view"),
        "set_mode": _schema(optional="mode"),
        "set_query": _schema(optional="text"),
        "toggle_facet": _schema("axis value"),
        "clear_facets": _schema(),
        "clear_filters": _schema(),
        "toggle_group": _schema("group"),
        "select_work": _schema(optional="name"),
        "toggle_favorite": _schema("name value"),
        "delete_job": _schema("name", "confirm"),
        "undo_delete_job": _schema(),
        "clone_job": _schema("name"),
        "relink_template": _schema("name", "path confirm"),
        # `select` = 정체가 바뀌는 관리 동사(이름 변경)가 새 이름을 실어 선택을 승계하는 자리.
        "refresh": _schema(optional="select"),
        "set_tags": _schema("name", "tags"),
        "delete_corrupt": _schema("path", "confirm"),
    },
    "editor": {
        "use_library_template": _schema("path"),
        # `media` 가 밴드(hwpx/txt)를 고른다 — 신규 액션 대신 기존 액션의 키 확장(§10.15.15 판정 F).
        "toggle_library_group": _schema("group media"),
        "new_session": _schema(),
        "discard_session": _schema(),
        # 탭 이동 — `disposition` 은 3택 가드를 통과했다는 표지(웹이 저장·버리기를 먼저
        # 마친 뒤 실어 보낸다). 선택적인 이유: 처분할 것이 없는 이동이 대다수다.
        "goto_section": _schema("section", "disposition"),
        # `section` 은 탭 가드의 「버리고 이동」 — **그 자리만** 되돌린다(2R P2).
        # 없으면 세션 전체 되돌리기(footer 「변경 버리기」·이탈의 「버리고 나가기」).
        "discard_patch": _schema(optional="section"),
        "ack_gate": _schema(),
        "skip_data": _schema(),
        "use_all_headers": _schema(),
        "use_none": _schema(),
        "toggle_source_active": _schema("field"),
        "mapping_reset_stakes": _schema(),
        "set_source": _schema("index source"),
        "revert_source": _schema("index"),
        "resuggest_all": _schema(),
        "set_type": _schema("index type"),
        "set_fmt": _schema("index fmt"),
        "set_const": _schema("index const"),
        "set_confirmed": _schema("index confirmed"),
        "confirm_all": _schema(),
        "confirm_blanks": _schema(optional="fields"),
        "unconfirm_all": _schema(),
        "restore_confirmed": _schema(),
        "step_preview": _schema("delta"),
        "set_name": _schema("name"),
        "set_pattern": _schema("pattern"),
        "set_dataset_name": _schema("name"),
        "save": _schema(optional="confirm_dataset confirm_overwrite confirmed_overwrite_text"),
    },
    # 「문서 만들기」(v6 nav 1) — 화면 키는 `job` 그대로다(Job 은 도메인 개체 이름이라 화면이
    # 개명돼도 어휘가 갈리지 않는다 — 지도 §10.9 판정 A). 좌 목록 사망(F2 PR-B)으로 접힘·
    # 복제·삭제·복원은 여기서 걷혔다: 라이브러리가 자기 채널에서 소유한다. 반대로 개명·그룹
    # 이동/개명/해산은 **열린 세션의 정체와 결속**돼 있어 여기 남고, 라이브러리 표면이 교차
    # 화면 dispatch 로 부른다(§10.8 판정 F).
    "job": {
        **_DATA_ZONE,
        **_POOL_TARGETING,
        "guard_state": _schema(),
        "refresh": _schema(),
        # 전체 표시순서 축(§18.10, 재작성 F3) — 데이터 존 공유 액션이 **아니다**: 「기안」
        # 화면은 원본 순서 고정으로 산다. TXT 는 F6 합류로 **이 화면에서** 축을 얻었다:
        # 작업대는 데이터 존이 없고 표시순 투영을 통과한 고정 사본을 받기 때문이다.
        "set_view_order": _schema("value", "epoch"),
        # TXT 검토·복사 작업대 진입(§11, 재작성 F6) — 무페이로드: 무엇을 넘길지(고정 사본)는
        # Python 이 소유한다. 웹이 index 를 실어 보내면 그 사이 바뀐 표의 남의 행을 복사한다.
        "open_workbench": _schema(),
        # 전문 범위 편집기 초안(§18.10, 재작성 F3) — 열기·적용·취소·보기 토글. 존 13액션은
        # **그대로** 초안을 향한다(같은 동사가 대상만 바꾼다, 지도 §10.11 판정 A).
        "range_draft_open": _schema(),
        "range_draft_apply": _schema(),
        "range_draft_cancel": _schema(),
        # 미리보기 드로어(§7 Value preview·§13-2·4, 재작성 F5) — 열림·자리는 **Python 소유**라
        # 웹은 이동 방향만 보낸다(레코드 index 를 되돌려주지 않는다, 지도 §10.12 판정 M).
        # 승인은 무페이로드 명시 사건이다: 무엇을 승인했는지는 Python 이 든 요구가 정한다.
        # `at` 은 판정 M 의 carve-out 이 아니라 동류다(§10.15.15 판정 C): deep-link 복귀가
        # 같은 자리로 서기 위한 값이고, 출처가 **Python 자신이 push 한 스냅샷**(preview.pos)
        # 의 왕복이며 Python 이 클램프해 권위를 유지한다 — 값을 프런트가 짓지 않는다.
        "preview_open": _schema(optional="at"),
        "preview_close": _schema(),
        "preview_move": _schema("delta"),
        "preview_approve": _schema(),
        "set_selected_only": _schema("value"),
        "select_job": _schema("name", "confirm"),
        "toggle_favorite": _schema("name value"),
        # 라이브러리 「문서 만들기에서 사용」의 착지(§19.8) — 분기 판정은 Python 이 낸다.
        "prefer_work": _schema("name"),
        "browse_tab": _schema(optional="tab"),
        "browse_query": _schema(optional="text"),
        "relink_template": _schema("name", "path confirm"),
        "rename_job": _schema("name", "new"),
        "cancel_generation": _schema(),
        # 결과 3태의 「실패한 N건만 선택」(지도 §10.10 판정 F) — 무페이로드: 실패 index 는
        # Python 이 소유한다(웹이 들고 있다 되돌려주면 그 사이 교체된 데이터의 남의 행을 고른다).
        "select_failed": _schema(),
        "set_group": _schema("name", "group"),
        "rename_group": _schema("name", "new confirm seen"),
        "disband_group": _schema("name", "confirm seen"),
        "ack_field": _schema("field"),
        "unack_field": _schema("field"),
    },
    # TXT 검토·복사 작업대(v6 S7 · 계약 §11, 재작성 F6) — 데이터 존이 **없다**: 데이터·범위
    # 선택은 「문서 만들기」가 끝내고 여기는 고정 사본을 받는다(§13-13). 필드 연결 동사는
    # 「기안」 맞추기 표와 같은 이름이다 — 같은 판정(MappingModel)을 부르므로 어휘를 갈라
    # 두면 그 자체가 드리프트다.
    "workbench": {
        "step": _schema("delta"),
        "set_current": _schema("index"),
        "toggle_advance": _schema("value"),
        "set_view": _schema(optional="view"),
        "set_target_font": _schema(optional="font"),
        "set_fullwidth": _schema("value"),
        # 맞추기 동사 6종은 「기안」과 **같은 규약**이다(F6 3R — 공용 MappingVerbsMixin).
        # 정체는 **토큰 이름**이다: 행 index 는 템플릿을 다시 읽으면 흔들리지만 이름은 그
        # 표의 안정 식별자이고, 없는 이름은 `index_of` 가 시끄럽게 거절한다.
        "set_source": _schema("name", "col confirm"),
        "set_map_value": _schema("name", "text"),
        "set_map_fmt": _schema("name", "code"),
        "set_map_type": _schema("name type"),
        "set_confirmed": _schema("name value"),
        "revert_map": _schema("name"),
        "copy_precheck": _schema(),
        # 「기본 규칙으로 저장…」(§11) — 확인 왕복. 이 저장은 **다음 실행부터의 기본 규칙**을
        # 바꾸므로(override 없음, 지도 §10.14) dirty 필드를 전부 나열한 뒤에만 성사된다.
        # `confirmed_text` = 사용자가 **본 문안 그대로**(「기안으로 저장」·에디터 덮어쓰기와
        # 같은 관용구): 백엔드가 잠금 안에서 문안을 다시 지어 대조하므로, 모달이 열린 사이
        # 대상이 바뀌면 새 문안으로 다시 묻는다. 불리언 플래그로는 「이 상황을 확인했다」와
        # 「어떤 상황을 확인했다」가 구별되지 않는다(1R P2).
        "save_rules": _schema(optional="confirm confirmed_text"),
        "leave_guard": _schema(),
        "close": _schema(),
    },
    "pool": {
        "refresh": _schema(),
        "archive": _schema("name"),
        "activate": _schema("name"),
        "delete": _schema("name", "confirm"),
        "register_excel": _schema("name path", "sheet note confirm"),
    },
    "tpl": {
        "refresh": _schema(),
        "compile": _schema("path", "confirm"),
        "review": _schema("path"),
        "set_group": _schema("media key", "group"),
        "toggle_group": _schema("media group"),
        "rename_group": _schema("media group", "new confirm"),
        "disband_group": _schema("media group", "confirm"),
        "delete": _schema("media path", "confirm"),
        "undo_delete": _schema(),
        "txt_new": _schema("name content"),
        "txt_edit": _schema("path content"),
        "txt_content": _schema("path"),
    },
}

ACTION_REGISTRY: Mapping[str, Mapping[str, PayloadSchema]] = MappingProxyType(
    {screen: MappingProxyType(actions) for screen, actions in _REGISTRY.items()}
)


def validate_dispatch(screen: str, action: str, payload: object) -> dict:
    """Validate one browser dispatch and return the original payload as a dict."""

    actions = ACTION_REGISTRY.get(screen)
    if actions is None:
        raise ValueError(f"등록되지 않은 화면: {screen!r}")
    schema = actions.get(action)
    if schema is None:
        raise ValueError(f"등록되지 않은 {screen!r} 액션: {action!r}")
    if not isinstance(payload, dict):
        raise ValueError(
            f"{screen!r}/{action!r} payload는 객체여야 합니다: {type(payload).__name__}"
        )
    keys = set(payload)
    missing = schema.required - keys
    unexpected = keys - schema.allowed
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"필수 키 누락={sorted(missing)!r}")
        if unexpected:
            details.append(f"미등록 키={sorted(unexpected)!r}")
        raise ValueError(f"{screen!r}/{action!r} payload 스키마 불일치: " + ", ".join(details))
    return payload
