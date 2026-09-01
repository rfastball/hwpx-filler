"""저장 폴더 지정의 **실 조건**을 재현하는 테스트 헬퍼(저장 폴더 전역화).

`JobController.set_output_folder` 는 전역 설정값을 갈고 도출을 다시 세운다. 그 도출은
「설정한 폴더가 지금도 있는가」를 파일 시스템에 묻고, 없으면 기본값으로 내리며 사유를
남긴다(조용한 하향 금지). 그래서 **없는 경로를 건네는 테스트는 제품에서 만들어질 수 없는
상태를 만든다** — 네이티브 폴더 피커는 있는 폴더만 돌려주기 때문이다(새로 만들기를 골라도
피커가 만들어 놓고 돌려준다).

세션별 명시 지정 축이 있던 동안에는 그 축이 존재 확인을 건너뛰어 없는 경로도 그대로
섰다. 축이 걷힌 뒤 그 편의는 사라졌고, 테스트가 「고른다」를 말하려면 피커의 보증까지
같이 말해야 한다. 이 헬퍼가 그 한 줄이다.

폴더를 **여기서 만드는 것**과 제품이 만들지 않는 것은 서로 다른 사실이다: 도출·관찰은
폴더를 만들지 않는다는 계약(`test_delivery_unreadable_directory_is_loud_and_never_created`)은
그대로이고, 여기서 만드는 것은 피커가 이미 만들어 돌려준 폴더의 대역이다.
"""

from __future__ import annotations

from pathlib import Path


def pick_output_folder(ctrl, path: "str | Path") -> str:
    """폴더 피커가 ``path`` 를 돌려준 것처럼 저장 폴더를 세운다(폴더는 실재하게 만든다)."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    ctrl.set_output_folder(str(target))
    return str(target)
