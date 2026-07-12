"""파괴적 액션 공용 확인 헬퍼 — 분열된 확인 정책의 단일 출처(RC-15).

확인 정책이 호출부 로컬로 흩어지면(축약형 ``QMessageBox.question``) 강화 패턴 이후
추가된 확인들이 Qt 기본형으로 회귀한다 — 기본 버튼 미지정 시 Qt 가 첫 AcceptRole
버튼을 자동 기본으로 승격해 **Enter 반사 1타가 파괴를 확정**했다(런타임 실증).
여기 한 곳이 ADR-E 강화 패턴(원형: wizard ``_ack_partial``)을 소유한다:

- **기본 버튼 = '취소'** — 반사적 Enter/Space 로는 파괴가 확정되지 않는다.
- **한국어 명시 라벨**(``action_label``) — 영어 Yes/No 반사 클릭을 차단하고,
  버튼 자체가 무엇을 하는지 말한다("삭제"·"덮어쓰기" 등).
- ``text`` 는 **무엇이 파괴되는가를 구체 이름으로 재진술**해야 한다(호출부 책임) —
  범용 문구는 반사적 dismiss 에 저항하지 못한다.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget


def _build_confirm_box(
    parent: "QWidget | None", title: str, text: str, action_label: str
) -> "tuple[QMessageBox, QPushButton, QPushButton]":
    """확인 상자 조립(미표시) — 테스트가 exec 없이 기본버튼·라벨 의미론을 검증하는 이음새."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    proceed = box.addButton(action_label, QMessageBox.AcceptRole)
    cancel = box.addButton("취소", QMessageBox.RejectRole)
    box.setDefaultButton(cancel)  # 반사적 Enter/Space 로는 확정되지 않음(ADR-E)
    return box, proceed, cancel


def confirm_destructive(
    parent: "QWidget | None", title: str, text: str, action_label: str
) -> bool:
    """파괴적 액션 직전의 명시 확인 — **True 를 반환할 때만** 진행하라.

    모달로 띄우고, 사용자가 ``action_label`` 버튼을 **직접 클릭**했을 때만 True.
    취소·창 닫기(Esc 포함)·Enter 반사는 전부 False(파괴 없음).
    """
    box, proceed, _cancel = _build_confirm_box(parent, title, text, action_label)
    box.exec()
    return box.clickedButton() is proceed
