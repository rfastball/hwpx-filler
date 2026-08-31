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
    # 사용자 열 선별(U2 §2.19, #341) — 표시 축뿐(숨긴 열도 필터·검색·생성에 그대로 참여).
    # 세션 소유·데이터 교체 시 소멸이라 존 변이와 같은 세대 검사를 받는다.
    "hide_column": _schema("column", "epoch"),
    "unhide_columns": _schema(optional="epoch"),
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

# 겨눔 대상은 슬롯 `key` 다(U2 §5.3 — 이름은 중복 허용 라벨이라 겨눔의 정체가 못 된다).
_POOL_TARGETING = {
    "load_pool": _schema("key"),
}

_REGISTRY: dict[str, dict[str, PayloadSchema]] = {
    # 「문서 작업」 전역 라이브러리(§19.6·§19.7) — 구 `home` 채널의 승계자(재작성 F2).
    # 좌 목록 관리 동사 중 **열린 세션의 정체와 결속된 것**(rename_job)은 여기 없다 —
    # 「문서 만들기」(`job`)가 계속 소유하고 라이브러리 표면이 교차 화면 dispatch 로
    # 부른다(지도 §10.8 판정 F). 그룹·태그·facet 동사는 U4 §2-30 에서 표면과 함께
    # 사라졌다 — 판정·영속은 링1·모델에 동결로 남고 액션 좌표만 걷혔다.
    "library": {
        "set_view": _schema(optional="view"),
        "set_mode": _schema(optional="mode"),
        "set_query": _schema(optional="text"),
        "clear_filters": _schema(),
        "select_work": _schema(optional="name"),
        "toggle_favorite": _schema("name value"),
        "delete_job": _schema("name", "confirm"),
        "undo_delete_job": _schema(),
        "clone_job": _schema("name"),
        "relink_template": _schema("name", "path confirm"),
        # `select` = 정체가 바뀌는 관리 동사(이름 변경)가 새 이름을 실어 선택을 승계하는 자리.
        "refresh": _schema(optional="select"),
        "delete_corrupt": _schema("path", "confirm"),
    },
    "editor": {
        "use_library_template": _schema("path"),
        "new_session": _schema(),
        "discard_session": _schema(),
        # 탭 이동 — 갈 자리 하나만 싣는다. 종전의 `disposition`(3택 가드를 통과했다는 표지)은
        # 확인 모달과 함께 사망했다: 막는 patch 는 컨트롤러가 자동으로 되돌리므로 웹이 처분을
        # 먼저 마쳤다고 선언할 자리가 없다.
        "goto_section": _schema("section"),
        # `section` 은 탭 이동의 자동 버리기 — **그 자리만** 되돌린다(2R P2).
        # 없으면 세션 전체 되돌리기(footer 「변경 버리기」·이탈의 자동 버리기).
        "discard_patch": _schema(optional="section"),
        "ack_gate": _schema(),
        # 세션 통지 닫기(U4 계열1-20) — 통지를 **세우는** 전이는 그대로 두고 사용자가
        # 끄는 문만 연다. 해소를 자동 감지해 지우려면 통지마다 해소 술어를 지어야 하고
        # 그 술어가 곧 두 번째 판정이다. 다시 필요해지면 같은 트리거가 다시 세운다.
        "dismiss_notice": _schema(),
        # 등록 데이터(풀)에서 고르기(#932 U4-C S2-5) — 조회 1 + 겨눔 1. `job` 화면의
        # `load_pool` 과 이름을 나눠 쓰지 않는다: 이 표가 곧 화면별 경계의 정의라 같은
        # 이름이 두 화면에 걸리면 「누가 무엇을 받는가」가 이름 하나로는 안 읽힌다.
        # (구 `skip_data` 는 여기서 사라졌다 — 데이터 결속이 저장 게이트가 된 이상
        #  「데이터 없이 진행」은 저장할 수 없는 세션으로 가는 링크였다.)
        "pool_options": _schema(),
        "use_pool_data": _schema("key"),
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
        # (set_dataset_name·confirm_dataset 은 #347 에서 사망 — 저장 시 데이터 자동등록
        #  (#18·#26)이 U2 §5.3 판정 D 로 폐기됐다. 등록은 데이터 선택 면의 「이 데이터
        #  고정」 명시 행동 하나다.)
        "save": _schema(optional="confirm_overwrite confirmed_overwrite_text"),
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
        # 현재 마운트 재읽기(U4 항목 5 · #932 U4-C) — 겨눔 성분을 payload 로 받지 **않는다**:
        # 재료는 세션이 마운트 시점에 포획해 둔 한 벌이고, 웹이 실어 보내면 그사이 갈린
        # 화면과 다른 데이터를 새로고침한다. 파괴 확인 왕복이라 `confirm` 만 받는다.
        "remount_data": _schema(optional="confirm"),
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
        # managed HWPX 승인은 backend preview_token 을 왕복한다. legacy 는 무페이로드 의미를 유지한다.
        # `at` 은 판정 M 의 carve-out 이 아니라 동류다(§10.15.15 판정 C): deep-link 복귀가
        # 같은 자리로 서기 위한 값이고, 출처가 **Python 자신이 push 한 스냅샷**(preview.pos)
        # 의 왕복이며 Python 이 클램프해 권위를 유지한다 — 값을 프런트가 짓지 않는다.
        "preview_open": _schema(optional="at"),
        "preview_close": _schema(),
        "preview_move": _schema("delta"),
        # 「빈 값 있는 건만 보기」(U2 §2.13) — ‹ › 이동을 빈 값 있는 건으로 한정하는 면의
        # 보기 상태. 열림·자리와 같은 이유로 Python 소유라 웹은 의도한 값만 보낸다.
        "preview_blank_only": _schema("value"),
        "preview_approve": _schema(optional="preview_token"),
        # 산출물 관찰 시트(S7-03 · #825, #820 D1·D4) — 생성 **후** 실물을 다시 읽어 보는
        # 면이라 미리보기와 어휘가 갈린다. 겨눔의 정체는 배달 문서의 `ordinal` 이다:
        # 표시 index·파일명은 그 사이 갈릴 수 있는 값이고 ordinal 은 그 실행이 고정한
        # 좌표다. 열림 여부는 Python 소유라 닫기는 무페이로드다(preview_close 선례).
        "artifact_open": _schema("ordinal"),
        "artifact_close": _schema(),
        "set_selected_only": _schema("value"),
        "select_job": _schema("name", "confirm"),
        "toggle_favorite": _schema("name value"),
        # 라이브러리 「문서 만들기에서 사용」의 착지(§19.8) — 분기 판정은 Python 이 낸다.
        "prefer_work": _schema("name"),
        "browse_tab": _schema(optional="tab"),
        "browse_query": _schema(optional="text"),
        # 데이터 통지 닫기(U4 §2.12 · #945) — 편집기 `dismiss_notice` 와 같은 문법이다:
        # 세우는 전이는 그대로 두고 사용자가 끄는 문만 연다. 무페이로드인 이유는 채널이
        # 하나라서다(지울 대상을 웹이 지목하면 그 지목이 곧 두 번째 판정이 된다).
        "dismiss_data_notice": _schema(),
        "relink_template": _schema("name", "path confirm"),
        # 템플릿 변경 확인·적용(S3-09 #659) — work 는 세션의 현재 작업이라 payload 에 없다.
        # request_id 는 prepare intent 재전송 단위(웹 발급), change_token 은 opaque token.
        "template_check": _schema("request_id"),
        "template_apply": _schema("change_token"),
        # S4 Working Slot Configuration Product command(SX-02 #725) — work 는 세션의 현재 작업이라
        # payload 에 없다(template_check 선례). configuration_token 은 직전 응답이 되돌려준 opaque
        # HMAC token(프런트가 계산하지 않는다), request_id 는 프런트 발급 재전송 단위. open 은
        # 무페이로드 조회, refresh 는 optional token(무이면 최초 조회), select 는 mutation.
        # `clear_slot_selection` 은 #903 에서 제거됐다: 유일한 트리거가 detached 정리 버튼이었고,
        # detached 는 SG-01(#733) 이후 제품 경로에서 구조적으로 생기지 않는다. v1 제어면은
        # EXACTLY_ONE 이라 「선택 비우기」는 완성 상태를 blocked 로 되돌릴 뿐 사용자 목적이 없다.
        "open_slot_configuration": _schema(),
        "refresh_slot_configuration": _schema(optional="configuration_token"),
        "select_slot_option": _schema("configuration_token slot_id option_id request_id"),
        # Selection Preset(S9-03 #829) — 선택 묶음의 Work 밖 보관·적용. `request_id` 가 없는
        # 이유: 저장은 이름 유일성 + 확인 왕복(`confirmed_overwrite_key` = 사용자가 본 그
        # 항목의 키)이, 적용은 token version CAS 가 재전송을 닫는다(S9-02 는 원장 대신 그
        # 둘을 썼다). 겨눔의 정체는 슬롯 `key` 다 — 이름은 사용자가 바꿀 수 있는 라벨이다.
        "save_selection_preset": _schema(
            "configuration_token name", "confirmed_overwrite_key"
        ),
        "apply_selection_preset": _schema("configuration_token preset_key"),
        # SX-04A record issue recovery — exact backend target만 되돌려 받는다.
        "recover_record_issue": _schema("target"),
        # SX-04B session delivery intent. output directory 는 native picker가 좁은
        # set_output_folder command로 세운다. 충돌 처리는 고르는 값이 아니라 기본값
        # 하나이고(U4 계열2-27 — `DEFAULT_COLLISION_POLICY`), 그래서 그것을 바꾸는 액션도
        # 그 계획을 다시 세는 액션도 여기 없다. 계획은 그것을 바꾸는 전이에서 무효화된다.
        # 작업대 execution 확인(SX-03 #726) — 무페이로드: 무엇을 봉인·관찰할지(현재 작업)는 Python 이
        # 소유한다. resolve_execution 은 자동 확인의 명시 재실행(수동 seal 관리 동사 아님),
        # refresh_observation 은 마지막 Plan 재관찰(새 seal 아님). 둘 다 seal 서비스 경로를 지난다.
        "resolve_execution": _schema(),
        "refresh_observation": _schema(),
        "rename_job": _schema("name", "new"),
        "cancel_generation": _schema(),
        # 결과 3태의 「실패한 N건만 선택」(지도 §10.10 판정 F) — 무페이로드: 실패 index 는
        # Python 이 소유한다(웹이 들고 있다 되돌려주면 그 사이 교체된 데이터의 남의 행을 고른다).
        "select_failed": _schema(),
        # (ack_field·unack_field 는 필드축 ack 폐기와 함께 사망 — U2 §2.13. 표식 삽입
        #  동의는 확인 면의 승인(preview_approve)이 겸한다.)
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
    # 항목 조작은 슬롯 `key`, 등록은 라벨 `name` + 참조(U2 §5.3 — 정체성=경로+시트).
    # **파괴·덮어쓰기 확정 왕복 넷**(delete·register_excel 라벨 갱신·relink·
    # resolve_duplicate)의 `basis` = 1차가 **보여준 상태의 지문** 왕복이다
    # (screen_pool.confirm_basis) — 확정은 그 지문과 지금 상태를 대조해야 하고, 미동봉이면
    # fail-closed 거절이다(고지 없는 삭제·덮어쓰기 봉쇄). 넷이 기제 하나를 공유한다.
    "pool": {
        "refresh": _schema(),
        "archive": _schema("key"),
        "activate": _schema("key"),
        "delete": _schema("key", "confirm basis"),
        "register_excel": _schema("name path", "sheet note confirm basis"),
        # 계약 목록(pclm) 등록 — 엑셀 등록의 거울이되 좌표가 다르다(경로+시트 → DB+뷰).
        # `db` 가 선택인 이유는 **빈 값이 「기본 자리」라는 뜻**이기 때문이고(미기재가 아니다),
        # 그 해석은 링1 `resolve_pclm_db` 가 등록 시점에 한다. `view` 는 필수다 —
        # 뷰는 사용자가 고르는 확정이지 기본값으로 추측할 것이 아니다(ADR N).
        "register_pclm": _schema("name view", "db note confirm basis"),
        # 다시 연결(#67) — 같은 슬롯의 참조 교체(수명 보존). 확인 라운드트립.
        "relink": _schema("key path", "sheet note name confirm basis"),
        # 구판(이름=키) 마이그레이션의 병합 확정 — 남길 슬롯 1건, 확인 라운드트립.
        "resolve_duplicate": _schema("keep", "confirm basis"),
    },
    "tpl": {
        "refresh": _schema(),
        # 동봉 예제 세트 설치(#891 · ONBOARDING_TUTORIAL.md §4.1~4.2) — 확인 왕복. 1차는
        # 홈에 아무것도 쓰지 않고 재진술만 돌려주고, `confirm` 2차가 실행이다. 이 채널이
        # 소유하는 이유는 설치가 템플릿 라이브러리 + 그룹 지정이기 때문이고, 라이브러리 빈
        # 상태 버튼은 교차 화면 dispatch 로 부른다(library→job 전례).
        "install_examples": _schema(optional="confirm"),
        # 설치한 예제 일괄 제거(#892 · 같은 문서 §1 D4) — 설치와 대칭인 확인 왕복. 1차는
        # 무엇이 몇 건 사라지는지 재진술만 하고, `confirm` 2차가 **manifest 기재분만** 걷는다.
        # 벌크 undo 슬롯은 없다(되돌리기 = 재설치) — 그 사실도 1차 문안이 말한다.
        "remove_examples": _schema(optional="confirm"),
        "compile": _schema("path", "confirm"),
        "review": _schema("path"),
        # 컴파일된 Slot 관리(S8-03 #834). 개명은 구조 무변형이라 무확인이고, 표기로 풀기·
        # 삭제는 확인 왕복이다(`confirm` 2차 호출).
        "slot_rename": _schema("path slot_id", "label"),
        "slot_decompile": _schema("path slot_id", "confirm"),
        # 전체판 풀기(U4-E3 #939)는 **문서 하나**를 겨눈다 — `slot_id` 를 받지 않는 것이
        # 계약이다(빈 값·오타난 id 가 「전부」로 접히는 경로를 만들지 않는다).
        "slot_decompile_all": _schema("path", "confirm"),
        "slot_remove": _schema("path slot_id", "confirm"),
        "delete": _schema("media path", "confirm"),
        "undo_delete": _schema(),
        "txt_new": _schema("name content"),
        # 저장은 편집 창이 열릴 때 읽은 원문(`baseline`)을 함께 싣는다 — 그 사이 밖에서
        # 바뀌었으면 확인 왕복(`confirm_fingerprint` 2차 호출)으로만 덮는다(#216 이월 2).
        "txt_edit": _schema("path content baseline", "confirm_fingerprint"),
        "txt_content": _schema("path"),
        # 저작 중 본문의 표기 판정 — 파일이 아니라 **창이 든 문자열**을 받는다(S10-05 #862).
        # 읽기 전용이라 확인 왕복이 없고, 새 TXT 창에는 경로가 아직 없으므로 키도 없다.
        "txt_lint": _schema("content"),
    },
    # 온보딩 튜토리얼 체크리스트(#894 · ONBOARDING_TUTORIAL.md §4.3) — **화면이 아니라 채널**
    # 이다: DOM 루트도 탭도 없고 표면은 셸 레벨 React 패널이다. 그래도 화면 키를 갖는 이유는
    # 스냅샷 채널과 디스패치 어휘가 이 표에서만 유도되기 때문이고(`SCREEN_ACTIONS` 손 목록
    # 금지), 같은 형태의 선례가 화면 사망 후 채널만 남은 `pool` 이다.
    # 마일스톤 **통지**는 여기 없다 — 그것은 웹이 부르는 표면이 아니라 컨트롤러 간 seam 이다
    # (tpl→편집기 재정산 선례). 웹이 소유하는 것은 종료·재개, 순간 카드 소비 되알림, 그리고
    # 안내 초점 지정·해제다 — 전부 「무엇을 보여줄까」이지 「무엇을 달성했는가」가 아니다.
    "tutorial": {
        "dismiss": _schema(),
        "resume": _schema(),
        # 동시 1장·억제·자동 소멸은 표면 몫이라 링1 은 미소비 목록만 낸다. 표면이 띄운 한
        # 장을 되알리지 않으면 같은 카드가 다음 스냅샷에서 다시 뜬다 — 그래서 소비가 액션이다.
        "consume_moment": _schema("milestone"),
        # 안내 초점 축(#918 C) — **달성 기록을 되돌리는 액션이 아니다**. 기록은 단조·영속이고
        # 여기서 옮기는 것은 안내가 겨누는 과정뿐이다. 초점은 표시 이력이라 영속하지 않는다.
        "focus_tier": _schema("tier"),
        "clear_focus": _schema(),
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
