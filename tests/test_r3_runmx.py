"""코드리뷰 3차(runmx 클러스터) 회귀 가드 — 풀 래퍼 공용화(K4)·소스 라벨 합성(K8).

K4: ``_do_pool_sources``/``_do_load_pool`` 이 실행 표면 컨트롤러들에 독스트링까지
복붙돼 있었다 — :class:`~hwpxfiller.webapp.screens.PoolTargetingMixin` 하나로 수렴하고
화면별 차이(job=작업 선택 전제·행 선택 초기화)는 훅으로만 남긴다. 사본이
조용히 재유입되는 회귀를 동일성 검사로 차단한다.

K8: ``data_source_label`` 은 항상 '파일: '+data_label / '등록 데이터: '+이름 으로
``data_label`` 과 쌍으로 6개 지점에서 리셋되던 전(全)파생 중복 상태였다 — 저장 상태에서
제거하고 소스 종류 플래그(``data_source``: ''|'file'|'pool')에서 스냅샷이 합성한다
(:func:`~hwpxfiller.webapp.screens.source_label` 단일 출처). JS 의 사어 폴백
``s.data_source_label || s.data_label`` 도 정리 — 정적으로 재유입을 가드한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screens import PoolTargetingMixin, source_label
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

WEB_JS = Path(__file__).resolve().parents[1] / "web" / "js"


# ------------------------------------------------------------------ 공용 픽스처 헬퍼
def _write_template(path: Path, fields) -> None:
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


def _registry(tmp_path: Path) -> JobRegistry:
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    return reg


def _data_csv(tmp_path: Path) -> str:
    csv = tmp_path / "d.csv"
    csv.write_text("bidNtceNm,공고명\n전산장비,전산장비\n사무비품,사무비품\n", encoding="utf-8")
    return str(csv)


def _pool(tmp_path: Path) -> DatasetPoolRegistry:
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    return pool


def _sink() -> "tuple[list, callable]":
    pushes: list = []
    return pushes, lambda s, snap: pushes.append((s, snap))


# ============================================================ K4 — 풀 래퍼 공용화(믹스인)
def test_pool_wrappers_are_shared_not_copied():
    """컨트롤러의 풀 래퍼가 믹스인 단일 구현이어야 한다 — 복붙 재유입 가드(K4).

    draft 는 화면 사망(F6 PR-B) — 남은 소비자는 job 하나지만, 믹스인이 단일 출처라는
    계약 자체는 살아 있다(다음 소비자가 생겨도 사본이 아니라 상속으로 온다).
    """
    for ctrl_cls in (JobController,):
        assert issubclass(ctrl_cls, PoolTargetingMixin), (
            f"{ctrl_cls.__name__} 이 PoolTargetingMixin 을 상속하지 않습니다(K4)."
        )
        # `_do_pool_sources` 는 사망(재작성 F1) — 목록의 소비자가 pool 컨트롤러 스냅샷으로
        # 바뀌어 활성-only 페이로드가 불필요해졌다. 남은 공용 래퍼는 겨눔 하나다.
        for meth in ("_do_load_pool",):
            assert getattr(ctrl_cls, meth) is getattr(PoolTargetingMixin, meth), (
                f"{ctrl_cls.__name__}.{meth} 가 믹스인 구현이 아닙니다 — 래퍼 사본 재유입(K4)."
            )


def test_job_pool_mount_without_job_is_session_owned(tmp_path):
    """job 훅 개정(데이터-우선 §18.2): 작업 미선택 겨눔을 거절하지 않는다 — 세션이
    데이터를 소유하고, 구 「작업 먼저」 전제(K4 job 가드)는 방향 반전으로 죽었다."""
    pushes, sink = _sink()
    ctrl = JobController(_registry(tmp_path), sink, pool_registry=_pool(tmp_path))
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["has_data"] is True
    assert snap["data_source_label"] == "등록 데이터: 7월공고"


def test_job_pool_load_resets_selection_via_hook(tmp_path):
    """job 훅: 풀 겨눔 성공 = 파일과 동일하게 **선택 0건** 초기화(§18.2, K4 훅 경유)."""
    pushes, sink = _sink()
    ctrl = JobController(_registry(tmp_path), sink, pool_registry=_pool(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 7월공고"
    snap = ctrl.snapshot()
    assert snap["record_count"] == 2 and snap["selected_count"] == 0  # 새 데이터 = 선택 0건


# (test_draft_pool_load_uses_default_hooks 삭제 — 대상 DraftController 사망, F6 PR-B.
#  훅 기본값 경로의 소비자가 사라져 job 훅 테스트들이 남은 계약 전부를 덮는다.)


# ============================================================ K8 — 소스 라벨 = 합성 파생
def test_source_label_synthesis_and_loud_unknown():
    """source_label 단일 출처 — 두 소스 문법 + 미지 플래그는 시끄럽게(조용한 빈 라벨 금지)."""
    assert source_label("", "무엇이든") == ""
    assert source_label("file", "d.csv") == "파일: d.csv"
    assert source_label("pool", "7월공고") == "등록 데이터: 7월공고"
    with pytest.raises(ValueError, match="알 수 없는 데이터 소스"):
        source_label("nara", "x")


def test_no_stored_data_source_label_attribute(tmp_path):
    """data_source_label 은 저장 상태가 아니어야 한다 — 전파생 중복 상태 재유입 가드(K8)."""
    pushes, sink = _sink()
    controllers = [
        JobController(_registry(tmp_path), sink, pool_registry=_pool(tmp_path)),
    ]
    for ctrl in controllers:
        assert not hasattr(ctrl, "data_source_label"), (
            f"{type(ctrl).__name__} 이 data_source_label 을 다시 저장합니다 — "
            "스냅샷 합성(source_label)으로 되돌리세요(K8)."
        )
        assert ctrl.data_source == ""                       # 초기 = 미겨눔
        assert ctrl.snapshot()["data_source_label"] == ""   # 합성 결과도 빈 라벨


def test_snapshot_label_follows_source_flag_transitions(tmp_path):
    """파일→풀→작업 재선택 전이마다 스냅샷 라벨이 플래그·표시명에서 정확히 합성된다(K8).

    예전 구현의 결함 모드 = 6개 리셋 지점 중 하나를 빠뜨리면 낡은 라벨이 잔존 — 파생
    합성에선 리셋할 두 번째 상태 자체가 없다.
    """
    pushes, sink = _sink()
    ctrl = JobController(_registry(tmp_path), sink, pool_registry=_pool(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["data_source_label"] == "파일: d.csv"
    ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert ctrl.snapshot()["data_source_label"] == "등록 데이터: 7월공고"
    ctrl.dispatch("select_job", {"name": "공고서"})          # 작업 재선택 = 데이터 보존(§18.2)
    assert ctrl.snapshot()["data_source_label"] == "등록 데이터: 7월공고"
    assert ctrl.snapshot()["data_label"] == "7월공고"


def test_js_dead_fallback_removed():
    """JS 사어 폴백 ``s.data_source_label || s.data_label`` 재유입 가드(K8).

    라벨은 서버가 항상 합성해 내려보내므로(data_source_label 키 상존) 구 라벨 폴백은
    도달 불가한 죽은 분기다 — 제거 상태를 유지해야 한다.
    """
    # draftsession.js 는 화면 사망으로 파일째 삭제(F6 PR-B) — 남은 소비자는 job 뿐.
    for rel in ("screens/job.js",):
        src = (WEB_JS / rel).read_text(encoding="utf-8")
        assert "data_source_label" in src, f"{rel} 이 data_source_label 을 소비하지 않습니다."
        assert "data_source_label || s.data_label" not in src, (
            f"{rel} 에 사어 폴백(s.data_source_label || s.data_label)이 재유입됐습니다(K8)."
        )
