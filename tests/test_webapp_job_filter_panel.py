"""열 머리 필터 패널 질의(`filter_panel`)의 값 목록 — 같은 열 조건과 「그리고」(#1137).

술어·값 목록 산출은 :mod:`hwpxfiller.viewmodel.filter_state` 가 소유하고 ``tests/test_filter_state.py``
가 잰다. 여기가 재는 것은 그 답이 dispatch 경로로 패널 질의에 **재조립 없이** 실려, 값을 끄고
켠 뒤의 표가 패널 목록과 같은 말을 하는가다. 하네스는 ``tests/test_webapp_job.py`` 의 세션을 쓴다.
"""
from __future__ import annotations

from tests.test_webapp_job import _session


def test_filter_panel_values_follow_same_column_text(tmp_path):
    """같은 열의 부분일치가 값 선택 목록에 반영된다(#1137) — 목록과 표가 같은 말을 한다.

    부분일치와 값 체크리스트는 「그리고」다. 그래서 목록은 맞는 값으로 좁혀지고, 「(전체)」
    (checked=None)는 그 값 전부다. 그 뒤 값을 끄고 켜도 표가 목록을 그대로 따른다.
    """
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_col_text", {"column": "bidNtceNm", "text": "전산"})
    res = ctrl.dispatch("filter_panel", {"column": "bidNtceNm"})
    assert res["text"] == "전산" and res["checked"] is None
    assert res["options"] == ["전산장비"]                # 「사무비품」은 부분일치가 이미 배제했다
    assert ctrl.snapshot()["table"]["visible_count"] == 1
    ctrl.dispatch("filter_col_values", {"column": "bidNtceNm", "values": []})  # 「(전체)」 끄기
    res = ctrl.dispatch("filter_panel", {"column": "bidNtceNm"})
    assert res["options"] == ["전산장비"] and res["checked"] == []  # 끈 값도 다시 켤 수 있게 남는다
    assert ctrl.snapshot()["table"]["visible_count"] == 0
    ctrl.dispatch("filter_col_values", {"column": "bidNtceNm", "values": None})  # 「(전체)」 켜기
    assert ctrl.snapshot()["table"]["visible_count"] == 1
    ctrl.dispatch("filter_col_text", {"column": "bidNtceNm", "text": ""})
    res = ctrl.dispatch("filter_panel", {"column": "bidNtceNm"})
    assert res["options"] == ["전산장비", "사무비품"] and res["checked"] is None
