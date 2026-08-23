"""S7-03(#825) — 결과 존 문서 목록·산출물 관찰 시트·「다른 이름으로 저장」의 헤드리스 계약.

관찰 커널 자체의 진실은 :mod:`tests.test_artifact_observation` 이, 구조 투영의 진실은
:mod:`tests.test_artifact_view_state` 가 소유한다. 여기가 재는 것은 **배선**이다:

- managed 결과 dict 가 배달 문서를 개별 단위로 싣는가(완주·되읽기 실패·중단 세 갈래).
- ``artifact_open`` 이 매번 커널을 다시 불러 성립/거절을 **구분된 상태**로 내는가.
- 세션 수명 — 데이터 교체·작업 전환 뒤 그 좌표가 남의 데이터를 가리키지 않는가.
- ``save_artifact_as`` 의 저장 bytes 가 **관찰 bytes = 원본 안착 파일**과 byte-identical 한가
  (#820 D2 — 검증되지 않은 bytes 는 저장의 원료가 못 된다).

fixture 는 실 HWPX bytes 를 실제 파일로 앉힌다(합성 package → ``to_bytes`` → disk). managed
파이프라인 자체는 :mod:`tests.test_managed_generation` 이 실 store 로 소유하므로 여기서는
그 결과 타입만 세워 컨트롤러 층 seam 을 태운다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.external.artifact_observation import (
    ARTIFACT_DIGEST_MISMATCH,
    ARTIFACT_FILE_MISSING,
)
from hwpxfiller.external.content_digest import blob_digest
from hwpxfiller.external.delivery_coordinator import (
    DeliveredDocument,
    DeliveryAborted,
    DeliveryCompleted,
)
from hwpxfiller.gui.artifact_view_state import ARTIFACT_PARTIAL_COVERAGE
from hwpxfiller.webapp import app as app_module
from hwpxfiller.webapp import screen_job as screen_job_module
from hwpxfiller.webapp.managed_generation import ManagedReadBackFailed
from hwpxfiller.webapp.screen_job import (
    ARTIFACT_NOT_IN_SESSION,
    ARTIFACT_OBSERVED,
)

from tests.test_webapp_job_binding_review import WORK_REF, _controller, _mount_rows

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _paragraph(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _hwpx_bytes(*paragraphs: str, unknown: str = "") -> bytes:
    """최소 HWPX 문서 bytes — ``unknown`` 을 실으면 CoverageLedger 가 못 본 구간을 남긴다."""
    package = HwpxPackage()
    package.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    package.stored.add(MIMETYPE_NAME)
    body = "".join(_paragraph(text) for text in paragraphs) + unknown
    package.entries["Contents/section0.xml"] = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{body}</hs:sec>'
    ).encode("utf-8")
    return package.to_bytes()


def _seat(tmp_path: Path, out: Path, blobs: "list[bytes]") -> "tuple[DeliveredDocument, ...]":
    """문서들을 실제로 앉히고 그 안착 사실(경로 + 기록 digest)을 낸다."""
    documents = []
    for ordinal, blob in enumerate(blobs):
        name = f"공고서-{ordinal:03d}.hwpx"
        (out / name).write_bytes(blob)
        documents.append(
            DeliveredDocument(
                item_ordinal=ordinal,
                record_identity=f"rec-{ordinal}",
                relative_path=name,
                absolute_path=str(out / name),
                collision_disposition="WRITE_NEW",
                output_digest=blob_digest(blob),
                execution_notes=(),
            )
        )
    return tuple(documents)


def _ready_controller(tmp_path: Path):
    """managed 실행 직전까지 선 컨트롤러 + 저장 폴더."""
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("select_job", {"name": WORK_REF})
    ctrl.dispatch("resolve_execution", {})
    rows = [{"이름": "A"}, {"이름": "B"}]
    _mount_rows(ctrl, rows)

    class Source:
        def records(self) -> list[dict]:
            return rows

    ctrl.datasource = Source()
    assert ctrl.vm is not None
    ctrl.vm.set_acquired(ctrl.datasource, rows)
    out = tmp_path / "delivery"
    out.mkdir()
    ctrl.set_output_folder(str(out))
    return ctrl, out


def _run_with(ctrl, monkeypatch, outcome):
    monkeypatch.setattr(screen_job_module, "run_managed_generation", lambda **kw: outcome)
    return ctrl.generate(run_token="tk-artifact")


def _completed(tmp_path: Path, ctrl, out: Path, monkeypatch, blobs=None):
    blobs = blobs or [_hwpx_bytes("첫째 문서 본문"), _hwpx_bytes("둘째 문서 본문")]
    documents = _seat(tmp_path, out, blobs)
    result = _run_with(
        ctrl, monkeypatch,
        DeliveryCompleted(output_directory=str(out), delivered=documents),
    )
    assert result["ok"] is True, result.get("error")
    return documents, result


# ═══ 결과 dict — 배달 문서가 개별 단위로 실린다(세 갈래) ═══════════════════════════════
def test_completed_result_lists_every_delivered_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    documents, result = _completed(tmp_path, ctrl, out, monkeypatch)

    assert result["delivered"] == [
        {
            "ordinal": doc.item_ordinal,
            "filename": doc.relative_path,
            "disposition": doc.collision_disposition,
            "path": doc.absolute_path,
        }
        for doc in documents
    ]


def test_read_back_failure_still_lists_the_documents_that_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """되읽기 실패는 **안착 사실을 부정하지 않는다** — 목록은 그대로 서고 관찰이 사유를 낸다."""
    ctrl, out = _ready_controller(tmp_path)
    documents = _seat(tmp_path, out, [_hwpx_bytes("첫째"), _hwpx_bytes("둘째")])
    result = _run_with(
        ctrl, monkeypatch,
        ManagedReadBackFailed(
            code=ARTIFACT_DIGEST_MISMATCH, detail="내용이 안착 기록과 다르다",
            failed_item_ordinal=1, delivered=documents,
        ),
    )
    assert [row["ordinal"] for row in result["delivered"]] == [0, 1]
    assert ctrl.delivered_artifact(1) is documents[1]


def test_aborted_result_lists_only_what_actually_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    documents = _seat(tmp_path, out, [_hwpx_bytes("첫째")])
    result = _run_with(
        ctrl, monkeypatch,
        DeliveryAborted(
            code="WRITE_FAILED", detail="둘째에서 멈췄다",
            failed_item_ordinal=1, delivered=documents,
        ),
    )
    assert [row["filename"] for row in result["delivered"]] == ["공고서-000.hwpx"]
    assert ctrl.delivered_artifact(1) is None


# ═══ artifact_open — 성립·거절이 각각 구분된 상태다 ═════════════════════════════════════
def test_open_observes_the_landed_file_and_projects_its_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)

    ctrl.dispatch("artifact_open", {"ordinal": 0})
    view = ctrl.snapshot()["artifact_view"]

    assert view["open"] is True
    assert view["ordinal"] == 0
    assert view["filename"] == "공고서-000.hwpx"
    assert view["status"] == ARTIFACT_OBSERVED
    assert view["detail"] == ""
    assert view["structure"]["kind"] == "artifact-observation/v1"
    # 실제 그 문서의 문단이다 — 다른 문서의 상을 그리지 않는다.
    assert [b["text"] for b in view["structure"]["sections"][0]["blocks"]] == [
        "첫째 문서 본문"
    ]
    # 부분 포섭 병기는 **언제나** 실린다(비어 있어도 키가 있다, #820 D3).
    assert view["structure"]["partial_coverage"] is False
    assert view["structure"]["coverage_code"] == ""
    assert view["structure"]["unrendered_regions"] == {"counts": {}, "examples": {}}


def test_partial_coverage_is_carried_beside_a_standing_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """부분 포섭은 거절이 아니다 — 관찰은 서고 사유만 옆에 붙는다(#820 §3)."""
    ctrl, out = _ready_controller(tmp_path)
    _completed(
        tmp_path, ctrl, out, monkeypatch,
        blobs=[_hwpx_bytes("본문", unknown="<hp:mystery/>"), _hwpx_bytes("둘째")],
    )

    ctrl.dispatch("artifact_open", {"ordinal": 0})
    view = ctrl.snapshot()["artifact_view"]

    assert view["status"] == ARTIFACT_OBSERVED
    assert view["structure"]["partial_coverage"] is True
    assert view["structure"]["coverage_code"] == ARTIFACT_PARTIAL_COVERAGE
    assert view["structure"]["unrendered_regions"]["counts"]


def test_tampered_file_opens_as_a_loud_mismatch_not_a_blank_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    documents, _ = _completed(tmp_path, ctrl, out, monkeypatch)

    Path(documents[0].absolute_path).write_bytes(b"tampered")
    ctrl.dispatch("artifact_open", {"ordinal": 0})
    view = ctrl.snapshot()["artifact_view"]

    assert view["open"] is True  # 면은 뜬다 — 조용한 무시가 아니다
    assert view["status"] == ARTIFACT_DIGEST_MISMATCH
    assert documents[0].output_digest in view["detail"]
    assert view["structure"] is None


def test_missing_file_and_out_of_session_are_different_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """파일 부재(무결성 사건)와 세션 좌표 밖(준비 안 됨)을 같은 빈 화면으로 접지 않는다."""
    ctrl, out = _ready_controller(tmp_path)
    documents, _ = _completed(tmp_path, ctrl, out, monkeypatch)

    Path(documents[1].absolute_path).unlink()
    ctrl.dispatch("artifact_open", {"ordinal": 1})
    assert ctrl.snapshot()["artifact_view"]["status"] == ARTIFACT_FILE_MISSING

    ctrl.dispatch("artifact_open", {"ordinal": 99})
    view = ctrl.snapshot()["artifact_view"]
    assert view["status"] == ARTIFACT_NOT_IN_SESSION
    assert view["open"] is True and view["detail"]


def test_close_releases_the_open_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)

    ctrl.dispatch("artifact_open", {"ordinal": 0})
    assert ctrl.snapshot()["artifact_view"]["open"] is True
    ctrl.dispatch("artifact_close", {})
    view = ctrl.snapshot()["artifact_view"]
    assert view["open"] is False and view["structure"] is None


def test_observation_rereads_the_file_on_every_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bytes 캐시 금지(#820 D1) — 두 번째 열기가 **그 사이 바뀐 실물**을 본다."""
    ctrl, out = _ready_controller(tmp_path)
    documents, _ = _completed(tmp_path, ctrl, out, monkeypatch)

    ctrl.dispatch("artifact_open", {"ordinal": 0})
    assert ctrl.snapshot()["artifact_view"]["status"] == ARTIFACT_OBSERVED
    Path(documents[0].absolute_path).write_bytes(b"changed after the first look")
    ctrl.dispatch("artifact_open", {"ordinal": 0})
    assert ctrl.snapshot()["artifact_view"]["status"] == ARTIFACT_DIGEST_MISMATCH


# ═══ 세션 수명 — 좌표는 이 데이터·이 작업의 것이다 ═════════════════════════════════════
def test_data_swap_discards_the_delivered_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)
    ctrl.dispatch("artifact_open", {"ordinal": 0})

    ctrl._init_filter()  # 데이터 교체가 지나는 자리(필터 재생성 = 새 레코드 집합)

    assert ctrl.delivered_artifact_paths() == ()
    assert ctrl.snapshot()["artifact_view"]["open"] is False
    ctrl.dispatch("artifact_open", {"ordinal": 0})
    assert ctrl.snapshot()["artifact_view"]["status"] == ARTIFACT_NOT_IN_SESSION


def test_work_switch_discards_the_delivered_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)
    ctrl.dispatch("artifact_open", {"ordinal": 0})

    ctrl.dispatch("select_job", {"name": ""})  # 작업 해제 = 실행 증거 폐기

    assert ctrl.delivered_artifact_paths() == ()
    assert ctrl.snapshot()["artifact_view"] == {
        "open": False, "ordinal": -1, "filename": "",
        "status": "", "detail": "", "structure": None,
    }


# ═══ 「다른 이름으로 저장」 — 원료는 관찰한 그 bytes 하나다(#820 D2) ══════════════════
class _Frontend:
    """`save_artifact_as` 만 태우는 최소 대역 — 창·pywebview 를 세우지 않는다."""

    def __init__(self, job) -> None:
        self._job = job

    def _controller(self, screen: str):
        assert screen == "job"
        return self._job

    save_artifact_as = app_module.WebFrontend.save_artifact_as


def _frontend(ctrl, monkeypatch, answer):
    calls: list[tuple] = []

    def fake_dialog(default_name, filters, default_ext):
        calls.append((default_name, filters, default_ext))
        return answer

    monkeypatch.setattr(app_module, "_save_dialog", fake_dialog)
    return _Frontend(ctrl), calls


def test_saved_copy_is_byte_identical_to_the_observed_and_landed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    documents, _ = _completed(tmp_path, ctrl, out, monkeypatch)
    target = tmp_path / "사본.hwpx"
    frontend, calls = _frontend(ctrl, monkeypatch, str(target))

    result = frontend.save_artifact_as(0)

    assert result == {"ok": True, "status": "saved", "detail": "", "path": str(target)}
    # 종료 조건: 저장 bytes == 관찰 bytes == 원본 안착 파일 bytes.
    landed = Path(documents[0].absolute_path).read_bytes()
    assert target.read_bytes() == landed
    assert blob_digest(target.read_bytes()) == documents[0].output_digest
    # 기본 이름은 안착 파일 이름이고 필터는 단일 출처 파생이다.
    assert calls == [("공고서-000.hwpx", app_module._ARTIFACT_SAVE_FILTERS, "hwpx")]


def test_cancelled_dialog_writes_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)
    frontend, _calls = _frontend(ctrl, monkeypatch, None)

    result = frontend.save_artifact_as(0)

    assert result["ok"] is False and result["status"] == "cancelled"
    assert list(tmp_path.glob("*.hwpx")) == []


def test_write_failure_is_reported_apart_from_the_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """관찰은 성립했고 옮겨 쓰기가 실패했다 — 무결성 실패로 접지 않는다(#820 §3)."""
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)
    frontend, _calls = _frontend(ctrl, monkeypatch, str(tmp_path / "없는폴더" / "a.hwpx"))

    result = frontend.save_artifact_as(0)

    assert result["ok"] is False
    assert result["status"] == app_module.SAVE_COPY_FAILED
    assert result["detail"]


def test_tampered_original_yields_the_observation_refusal_not_a_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검증되지 않은 bytes 는 저장의 원료가 못 된다(#820 D2) — 다이얼로그도 열리지 않는다."""
    ctrl, out = _ready_controller(tmp_path)
    documents, _ = _completed(tmp_path, ctrl, out, monkeypatch)
    Path(documents[0].absolute_path).write_bytes(b"tampered")
    frontend, calls = _frontend(ctrl, monkeypatch, str(tmp_path / "사본.hwpx"))

    result = frontend.save_artifact_as(0)

    assert result["ok"] is False
    assert result["status"] == ARTIFACT_DIGEST_MISMATCH
    assert result["detail"] and result["path"] == ""
    assert calls == []  # 관찰이 서기 전에는 저장 피커를 열지 않는다


def test_delivered_paths_enter_the_owned_whitelist_without_weakening_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """행 어포던스(폴더에서 보기·경로 복사)가 결과 파일을 겨눌 수 있는 유일한 근거.

    등록의 원천은 「앱 자신이 그 파일을 냈다」는 사실이고, 판정은 그대로 exact 대조다 —
    같은 폴더의 남의 파일은 여전히 거절된다(화이트리스트가 넓어질 뿐 검증이 약해지지 않는다).
    """
    from hwpxfiller.external.dataset_store import DatasetPoolRegistry
    from hwpxfiller.external.job_store import JobRegistry

    ctrl, out = _ready_controller(tmp_path)
    documents, _ = _completed(tmp_path, ctrl, out, monkeypatch)

    class _Editor:
        template_path = ""
        data_path = ""

    class _Owner:
        _job_registry = JobRegistry(tmp_path / "owned-jobs")
        _pool_registry = DatasetPoolRegistry(tmp_path / "owned-pool")
        _owned_path_base = str(tmp_path)
        _validate_owned = app_module.WebFrontend._validate_owned

        def _controller(self, screen: str):
            return _Editor() if screen == "editor" else ctrl

    owner = _Owner()
    assert owner._validate_owned(documents[0].absolute_path) == documents[0].absolute_path

    stranger = out / "남의문서.hwpx"
    stranger.write_bytes(b"not ours")
    with pytest.raises(ValueError):
        owner._validate_owned(str(stranger))

    # 좌표가 죽으면 어포던스의 근거도 죽는다 — 같은 수명이다.
    ctrl._discard_delivered_artifacts()
    with pytest.raises(ValueError):
        owner._validate_owned(documents[0].absolute_path)


def test_out_of_session_ordinal_and_bad_payload_are_distinct_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, out = _ready_controller(tmp_path)
    _completed(tmp_path, ctrl, out, monkeypatch)
    frontend, calls = _frontend(ctrl, monkeypatch, str(tmp_path / "사본.hwpx"))

    assert frontend.save_artifact_as(99)["status"] == ARTIFACT_NOT_IN_SESSION
    assert frontend.save_artifact_as("0")["status"] == app_module.SAVE_COPY_FAILED
    assert calls == []
