"""R4-03 static→React ID successor exact map.

형제 둘(``test_r4_static_to_js_successor_map`` R4-01 · ``test_r4_editor_...`` R4-02)과 같은
질문을 실행·결과 표면에 묻는다: **정적 HTML 에 있던 안정 ID 가 어느 React 생산자로 갔는가.**

51 = 거울 4 + 결과 17 + 저장 폴더 행 3 + 액션바 8 + 확인 면 19. 이 다섯은 이관 전
``docs/react_ownership_inventory.toml`` 의 subtree ``members_expected`` 였고, 그 수가 0 이
되면서 같은 ID 들이 여기로 옮겨 왔다 — **두 자리가 같은 51 을 든다**.

52 번째는 ``jobStatus`` 다. 이 자리만 정적 shell 로 남길 수 없었다: ``data-level`` 이 Python
판정의 파생이라 shell 이 그것을 들면 판정을 두 곳이 하게 된다. 그래서 ``jobStatusHost``
portal 을 신설하고 React 가 ``jobStatus`` 를 만든다(delta D20).

**이 파일이 52 의 정본이다.** 소유권 원장과 형제 지도는 각자 세지 않고 여기를 참조한다 —
세 곳이 각자 세면 하나가 늦게 늘어도 조용하다.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]

#: 이 지도의 정의역 — R4-03 이 세운 파일 다섯. 오늘 ID 를 만드는 것은 셋뿐이지만 소유는
#: 다섯이다: 나머지 둘이 나중에 ID 를 만들면 **어느 지도도 안 드는 자리**가 되지 않는다.
OWNED_FILES = (
    "frontend/src/screens/job_run.ts",
    "frontend/src/screens/job_result.ts",
    "frontend/src/screens/job_preview.ts",
    "frontend/src/screens/job_run_state.ts",
    "frontend/src/screens/job_relink.ts",
)

#: 이관 전 `#jobMirrorZone` subtree 4.
MIRROR = {"jobMirror", "jobMirrorLine", "jobMirrorSummary", "jobMirrorPreviewOpen"}
#: 이관 전 `#jobResultZone` subtree 17 — 결과 3태 + 증거 접힘 + 실행 기록.
RESULT = {
    "jobGenBar", "jobResult", "jobResultTitle", "jobResultFailedSel", "jobResultRename",
    "jobResultClose", "jobResultSummary", "jobResultStale", "jobResultDir",
    "jobResultTrack", "jobResultFails", "jobResultEvidence", "jobResultEvidenceCap",
    "jobResultEvidenceBody", "jobRunLog", "jobRunLogLast", "jobGenLog",
}
#: 이관 전 `#jobOutRow` subtree 3.
OUT_ROW = {"jobOutDir", "jobBtnPickFolder", "jobOutTrack"}
#: 이관 전 `#jobActionBar` subtree 8.
ACTION_BAR = {
    "jobActionName", "jobActionConn", "jobActionRelink", "jobPreviewOpen",
    "jobReviewFlag", "jobGenBtn", "jobGenCancel", "jobGate",
}
#: 이관 전 `#previewSheet` subtree 19.
PREVIEW = {
    "previewTitle", "previewClose", "previewPrev", "previewPos", "previewNext",
    "previewBlankOnly", "previewEmpty", "previewEvidence", "previewEvidenceCap",
    "previewEvidenceReason", "previewEvidenceRows", "previewEvidenceNote",
    "previewValuesCap", "previewRows", "previewFilename", "previewFixFilename",
    "previewNamePlan", "previewEdit", "previewApprove",
}

MIGRATED = MIRROR | RESULT | OUT_ROW | ACTION_BAR | PREVIEW

#: 정적 골격에 없던 ID — React 생산자가 새로 만든다. `jobStatus` 하나이고 사유는 위 참조.
ADDED_BY_REACT = {"jobStatus"}

#: R4-03 이 만드는 안정 ID 전수. **이 값이 정본이다**(A·C 레인이 참조한다).
R4_03_SITE_COUNT = 52

#: 동적 prefix — 값이 아니라 **접두**가 계약이다(신원은 인코딩된 인덱스가 진다).
DYNAMIC_PREFIXES = {"jobResultFail-"}

#: 정적 shell 이 자리만 남기고 안쪽을 통째로 넘긴 portal target. 여기 있는 id 는 index 에
#: **정확히 한 번** 서야 하고(React 가 그 안을 채운다), MIGRATED 는 index 에 **없어야** 한다.
PORTAL_TARGETS = {
    "jobStatusHost", "jobPreflight", "jobMirrorZone", "jobRunCap", "jobOutRow",
    "jobRestate", "jobResultZone", "jobActionBar", "previewSheet",
}


def _axes() -> dict[str, list[str]]:
    result = subprocess.run(
        ["node", "scripts/extract_js_ast_axes.mjs", "--repo-root", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _sites() -> list[tuple[str, str, str]]:
    rows = []
    for member in _axes()["js_template_ids"]:
        path_line, kind, value = member.rsplit(":", 2)
        path = path_line.rsplit(":", 1)[0]
        if path in OWNED_FILES:
            rows.append((path, kind, value))
    return rows


def test_r4_03_static_to_js_successor_sets_are_exact() -> None:
    static = [value for _, kind, value in _sites() if kind == "static"]
    assert (len(MIRROR), len(RESULT), len(OUT_ROW), len(ACTION_BAR), len(PREVIEW)) == (
        4, 17, 3, 8, 19,
    )
    assert len(MIGRATED) == 51, "다섯 subtree 사이에 같은 ID 가 겹치면 안 됩니다."
    assert set(static) == MIGRATED | ADDED_BY_REACT
    assert len(MIGRATED | ADDED_BY_REACT) == R4_03_SITE_COUNT


def test_r4_03_ids_are_produced_once_each() -> None:
    """같은 ID 를 두 자리가 만들면 DOM 이 둘을 낳고 되읽기가 어느 쪽을 본지 모른다.

    예외는 **분기**다: 한 render 안에서 조건별로 갈리는 자리는 같은 ID 를 두 번 적지만
    동시에 서지 않는다. 오늘 그런 자리는 없다 — 목록이 자라면 이 단언이 먼저 붉다.
    """
    counts = Counter(value for _, kind, value in _sites() if kind == "static")
    branched = {name for name, count in counts.items() if count > 1}
    assert branched == set(), branched


def test_r4_03_dynamic_prefixes_are_registered() -> None:
    dynamic = {value for _, kind, value in _sites() if kind == "dynamic"}
    assert dynamic == DYNAMIC_PREFIXES


def test_migrated_ids_left_static_html_and_portal_targets_remain() -> None:
    """옮긴 51 은 index 에서 사라지고, 자리를 넘긴 아홉은 **정확히 한 번** 남는다.

    두 방향을 함께 재는 것이 요점이다. 부재만 재면 portal target 이 함께 지워져도 초록이고
    (그 상태의 앱은 mount 에서 추락한다), 실재만 재면 정적 재도입이 조용하다(생산자가 둘이
    되어 되읽기가 어느 쪽을 본지 모른다).
    """
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    for migrated in MIGRATED:
        assert f'id="{migrated}"' not in html, migrated
    for target in PORTAL_TARGETS:
        assert html.count(f'id="{target}"') == 1, target


def test_run_surface_holds_no_edge_into_a_sibling_screen() -> None:
    """실행 표면은 형제 화면을 직접 import 하지 않는다 — 간선은 port 가 진다.

    `.ts` 가 legacy `.js` 를 직접 끌어오지 않는다도 같은 규칙의 다른 얼굴이다: 그렇게 하면
    `.ts` 소유 경계가 `.js` 파일의 수명에 묶인다(R4-03 이 `relink.js` 를 지우며 실제로 물렸고,
    처분은 공유 합성기를 **주입**으로 돌린 것이다).
    """
    for name in OWNED_FILES:
        source = (ROOT / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            if not line.startswith("import "):
                continue
            assert "../../js/" not in line, f"{name}: legacy .js 직접 import — {line.strip()}"
            for sibling in ("editor", "library", "workbench", "job_read", "data_zone"):
                assert f'screens/{sibling}"' not in line, f"{name}: 화면 간 import — {line.strip()}"
