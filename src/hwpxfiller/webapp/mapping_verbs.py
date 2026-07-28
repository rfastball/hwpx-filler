"""맞추기 표의 **동사 6종** 공용 본체 — 「기안」 세션과 검토·복사 작업대가 공유한다.

두 표면은 같은 표를 그리고 같은 :class:`~hwpxfiller.gui.mapping_state.MappingModel` 을
부른다. F6 PR-A 는 그걸 알면서도 작업대 쪽 핸들러를 **손으로 다시 짰고**, 리뷰 3R 이 그
대가를 세 건으로 청구했다:

- ``set_map_fmt`` 가 이름 API(:meth:`MappingModel.set_fmt_for`)에 **행 index** 를 넘겨
  표시형 변경이 **전부** ``ValueError`` 로 터졌다.
- ``revert_map`` 이 스니핑 유형을 안 넘겨, 일반명 필드에 결속된 숫자·날짜 열이 되돌릴 때
  **text 로 떨어졌다**.
- ``set_source`` 가 직접 입력한 값을 **확인 없이** 덮었다(리뷰가 짚지 않은 세 번째 —
  옮겨 오지 않은 게이트).

즉 옮겨야 했던 것은 판정(링1 모델)만이 아니라 **동사의 호출 규약과 그에 딸린 게이트**였다.
「승계는 거처만 옮긴다」(지도 §10.15 판정 G)의 *거처* 에는 그것들이 포함된다. 한 벌로
만들면 갈릴 자리가 없어진다 — PR-B 에서 「기안」이 죽으면 소비자는 하나가 되고, 이 모듈은
그때 작업대의 것이 된다.

**정체는 토큰 이름이다**(행 index 가 아니다). 템플릿을 다시 읽으면 행 순서는 바뀔 수 있지만
토큰 이름은 그 표의 안정 식별자이고, 없는 이름은 :meth:`MappingModel.index_of` 가 시끄럽게
거절한다(confirm-or-alarm).

**소비자 계약**(훅 3개):

- ``self.mapping`` — :class:`MappingModel`
- ``_map_source_fields()`` — 지금 데이터의 열 이름들(결속 후보·유효성 판정)
- ``_map_kind_of(source)`` — 그 열의 스니핑 유형(``""`` = 미상)
- ``_after_mapping_edit()`` — 편집 뒤 훅(「기안」은 미저장 표지, 작업대는 파생이라 무동작)
"""
from __future__ import annotations


class MappingVerbsMixin:
    """맞추기 표의 동사 6종 — 두 표면이 **같은 규약**으로 부른다."""

    def _after_mapping_edit(self) -> None:
        """편집 성사 뒤 훅. 기본은 무동작 — 파생으로 dirty 를 재는 표면(작업대)용."""

    def _do_set_source(self, p: dict) -> "dict | None":
        """토큰 결속·해제(드롭다운·제안 원클릭 공유) — 결정 5·30.

        ``col`` = 데이터 열이면 자동 결속(auto, 유형은 값 스니핑), 빈 값이면 해제(무결속 →
        근사 제안·재결속 대기). **수기 값 덮어쓰기 확인**: 직접 입력한 값이 있는 자리에 열을
        붙이면 그 값은 되돌릴 수 없이 사라지므로 첫 호출은 확인 요구(``{"confirm": 문안}``)를
        돌려주고, 웹이 확인받아 ``confirm=True`` 로 다시 부른다(빠른 기안·relink 게이트 문법).
        """
        name, col = p["name"], (p.get("col") or "")
        idx = self.mapping.index_of(name)
        if col:
            if col not in self._map_source_fields():
                raise ValueError(f"데이터에 없는 열입니다: {col}")  # confirm-or-alarm
            row = self.mapping.rows[idx]
            if row.type == "const" and row.const.strip() and not p.get("confirm"):
                return {
                    "confirm": (
                        f"{{{{{name}}}}} 에 직접 입력한 값 '{row.const}'은 '{col}' 열의 값으로 "
                        "바뀌고 되돌릴 수 없습니다. 계속하시겠습니까?"
                    )
                }
            self.mapping.bind_column(idx, col, self._map_kind_of(col))
        else:
            self.mapping.unbind(idx)  # 무결속 — 값 동결 없음(행마다 값이 달라 단건 문법 부적용)
        self._after_mapping_edit()
        return None

    def _do_set_map_value(self, p: dict) -> dict:
        """토큰 값 직접 입력(man) — 상수 강등. 결속 소스는 기억(되돌리기로 복귀, 사용자 결정).

        _NO_PUSH: 포커스된 값 입력을 서버 푸시가 재구성하지 않게 **반환 스냅샷**으로 돌려준다
        (빠른 기안 `set_token` 선례). 값은 **전 행 공통 상수**다 — 큐에서 '어느 행의 값'인지
        모호한 hand 대신 상수로 낙착한다.
        """
        self.mapping.set_manual(self.mapping.index_of(p["name"]), p.get("text", ""))
        self._after_mapping_edit()
        return self.snapshot()

    _do_set_map_value.is_no_push = True  # type: ignore[attr-defined]

    def _do_set_map_fmt(self, p: dict) -> None:
        """표시형(유형 내 프리셋) 정정 — 결속 열에서 오는 값에만 뜻이 있다(결정 34 2층)."""
        self.mapping.set_fmt_for(p["name"], p.get("code", ""))
        self._after_mapping_edit()

    def _do_set_map_type(self, p: dict) -> None:
        """값 유형 정정(#148 슬라이스 4, 결정 12) — 값 스니핑 오판을 사람이 이긴다.

        결속(auto) 값의 운반 유형(text/date/amount)을 사람이 고른다: 이름에 「금액」이 없어도
        값이 숫자면 금액 스니핑이 맞지만, 틀렸을 때 사람 선택이 언제나 이긴다
        (:meth:`MappingModel.set_type` 이 ``touched=True`` — 시스템 재제안 차단). 유형이 바뀌면
        이전 표시형 프리셋은 무효라 기본으로 떨어진다(모델 계약). 미지 유형은 조용히 무시하지
        않고 시끄럽게 거부한다(열거형 검증 — confirm-or-alarm). 표면은 결속 행에만 이 컨트롤을
        띄운다(const·무결속엔 운반 유형이 뜻이 없어 dead control 금지).
        """
        self.mapping.set_type(self.mapping.index_of(p["name"]), p["type"])
        self._after_mapping_edit()

    def _do_set_confirmed(self, p: dict) -> None:
        """행별 확정 토글(#148 슬라이스 4, 결정 12) — 확정+무내용 = 확정-비움(「비운다」 선언).

        확정-비움은 렌더가 데이터-빈값 ``blank`` 와 같되(〈빈 값〉) 복사 전 빈칸 게이트에서
        빠진다(:meth:`MappingModel.declared_blank_fields` 가 가른다).
        """
        self.mapping.set_confirmed(self.mapping.index_of(p["name"]), bool(p.get("value")))
        self._after_mapping_edit()

    def _do_revert_map(self, p: dict) -> None:
        """man→auto 되돌리기 — 기억한 결속 소스 복귀(막다른 강등 금지, 결정 31).

        직접 입력으로 상수 강등된 자리를 원 결속 열로 되살린다. **스니핑 유형을 함께 넘긴다**:
        빼면 유형이 토큰 **이름**에서 재유도돼(일반명 필드면 text) 숫자·날짜 열이 되돌아올 때
        조용히 다른 유형이 된다(3R P2). 소스 기억이 없으면 무동작(표면은 기억이 있을 때만
        되돌리기를 띄운다).
        """
        idx = self.mapping.index_of(p["name"])
        kind = self._map_kind_of(self.mapping.rows[idx].source)
        if self.mapping.revert_binding(idx, kind):
            self._after_mapping_edit()
