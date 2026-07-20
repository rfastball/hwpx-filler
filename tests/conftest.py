"""테스트 전역 격리 — 어떤 테스트도 실 사용자 홈(``~/.hwpxfiller``)을 읽거나 쓰지 않는다.

설정·그룹 영속(``settings.json``·``template_groups``·접힘)이 개발 머신 상태에 좌우되거나
그것을 오염하지 않게 ``HWPXFILLER_HOME`` 을 테스트별 임시 폴더로 못박는다. 특히 템플릿 그룹
:meth:`~hwpxfiller.webapp.template_groups.TemplateGroupModel.reconcile`(#108 결정 8)은 살아있는
파일이 없으면 유령 지정을 **삭제·영속**하므로, 격리 없이 빈 라이브러리를 스냅샷하면(에디터
1단계 피커·관리 화면) 실 사용자의 템플릿 그룹 지정이 조용히 지워질 수 있다.

자기 홈을 명시 지정하는 테스트(``home`` 픽스처 등)는 이 autouse 뒤에 ``setenv`` 로 덮어
이긴다(무해) — 이 격리는 홈을 명시 안 하는 테스트의 안전망이다.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_app_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / ".hwpxfiller-home"))
