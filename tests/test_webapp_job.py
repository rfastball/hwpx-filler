"""「작업」 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스, R-flow 슬라이스 1 #90).

패널 4존이 소비하는 링1 배선(부록 A-1)을 창 없이 되읽는다: 좌 목록 → 작업 선택 → 데이터 겨눔
→ 미입력 강제 확인 게이트(ADR-E) → 덮어쓰기 재진술(RC-02) → 생성 end-to-end. JobController 는
실행 화면(screen_run)을 재사용하지 않는 별개 링2 표면이되 **같은 링1 계약**을 소비하므로,
실행 화면 회귀 심(test_webapp_run)과 평행한 단언으로 배선 동등을 못박는다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.webapp.screen_job import JobController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

MULTI_SHEET = Path(__file__).resolve().parents[0] / "fixtures" / "multi_sheet.xlsx"


def _write_template(path, fields) -> None:
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


def _registry(tmp_path) -> JobRegistry:
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    return reg


def _controller(tmp_path):
    pushes: list = []
    ctrl = JobController(_registry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def _data_csv(tmp_path) -> str:
    # rec0 은 추정가격 빈값(→ '미입력'), rec1 은 채움 — 강제 확인 게이트를 태운다.
    csv = tmp_path / "d.csv"
    csv.write_text("bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n", encoding="utf-8")
    return str(csv)


# ---------------------------------------------------------------- 좌 목록 + 스냅샷 골격
def test_initial_lists_jobs_and_loud_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["has_job"] is False
    # 좌 master 목록 = 저장된 작업(선택 표지 포함).
    assert snap["job_rows"] == [{"name": "공고서", "selected": False}]
    assert snap["gate"]["enabled"] is False and "작업을 선택" in snap["gate"]["text"]


def test_select_job_marks_master_and_sets_session(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    assert snap["job_rows"] == [{"name": "공고서", "selected": True}]  # 좌 목록 선택 표지
    # 저장 폴더 기본값 = 템플릿 폴더/Results(실행 화면 동형).
    assert snap["out_dir"].endswith("Results")


def test_select_job_then_data_populates_records_and_badges(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 2  # 데이터 겨눔 = 전체 선택 초기화
    assert snap["template_path"].endswith("t.hwpx")  # 추적성 로케이트용 전체 경로(#53-B)
    # 본문 존 거울 행(비-drift 필드) — 이름·상태·값 병기.
    states = {s["name"]: s["state"] for s in snap["mirror"]}
    assert states["공고명"] == "filled"
    assert states["추정가격"] == "missing"  # rec0 빈값 → 미입력


# ------------------------------------------------------ 식별 요약 링1 소비(A-1-15, PR-1)
def test_record_summary_consumes_ring1_identity_not_keyed_temp(tmp_path):
    """식별 요약은 링1 ``identity_summary`` 소비 — 원본 값만 병기(임시 'key: value' 판 폐기).

    슬라이스 1의 임시 요약은 ``bidNtceNm: 전산장비`` 처럼 키를 접두했다. 링1 판은 사용자가
    데이터에서 본 값만 ``' · '`` 로 병기한다(A-1-15) — 키 접두가 사라졌음을 못박는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    summaries = [r["summary"] for r in ctrl.snapshot()["records"]]
    assert all("bidNtceNm" not in s for s in summaries)  # 임시 판의 키 접두 폐기(값만 병기)
    # display_for: rec0 은 presmptPrce 빈값이라 마커로 자리 보존(매달린 구분자 아님), rec1 은
    # 두 값 병기. 인지층 = 왼쪽 2열(bidNtceNm·presmptPrce).
    assert summaries == ["전산장비 · (빈칸)", "사무비품 · 2000000"]


def test_filename_token_mode_back_resolves_and_excludes_non_carriers(tmp_path):
    """파일명이 나르는 템플릿 필드를 매핑 ``source``(원본 열)로 역해소(결정 37 토큰 모드).

    파일명 토큰은 **매핑 후** 네임스페이스(``공고명``)인데 식별 요약은 **원본 열**(``bidNtceNm``)
    을 본다 — 역해소가 없으면 토큰 모드가 엉뚱한 네임스페이스로 오발한다(confirm-or-alarm).
    세 배제 가드를 모두 태운다: ``const``(리터럴, source 무의존)·``blank``·부재 source.
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "상수", "빈칸", "유령"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),          # text·present → 포함
            FieldMapping(template_field="상수", source="dmndInsttNm", type="const", const="고정"),  # const → 배제
            FieldMapping(template_field="빈칸", source="ntceInsttNm", type="blank"),  # blank → 배제
            FieldMapping(template_field="유령", source="does_not_exist"),        # 부재 source → 배제
        ]),
        # 네 템플릿 필드를 모두 파일명이 요구(가드가 없으면 넷 다 토큰 모드로 샘).
        filename_pattern="{{공고명}}-{{상수}}-{{빈칸}}-{{유령}}-{{seq:001}}",
    ))
    csv = tmp_path / "d.csv"
    csv.write_text(
        "bidNtceNm,presmptPrce,dmndInsttNm,ntceInsttNm\n전산장비,,조달청,조달청\n사무비품,2000000,경찰청,경찰청\n",
        encoding="utf-8",
    )
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(str(csv))
    # text·present 인 공고명(→bidNtceNm)만 나르는 열. const·blank·부재 source 는 배제.
    assert ctrl._filename_source_columns() == ["bidNtceNm"]


# ---------------------------------------------------------------- 게이트·생성(링1 계약)
def test_missing_gate_blocks_generate_until_acked(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))

    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and "미입력" in snap["gate"]["text"]

    # 생성 시도도 방어적으로 차단(worker/API 우회 방지).
    res = ctrl.generate()
    assert res["ok"] is False and "미입력" in res["error"]

    # 배지 클릭 = 직접 확인 → 게이트 열림.
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_generate_writes_documents_and_marks_missing(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True
    assert res["succeeded"] == 2 and res["failed"] == 0
    assert "미입력 표시 필드" in res["summary"]  # 낙관 서사 해소
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]
    # 진행 델타가 최소 1회 푸시됐다(진행바 갱신 계약).
    assert any(isinstance(snap, dict) and "progress" in snap for _s, snap in pushes)


def test_generation_stamps_last_run_at(tmp_path):
    """완주 = 역사(#129) — 생성이 작업에 실행 시각을 영속해야 홈 이력·KPI 가 산다."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.registry.load("공고서").last_run_at == ""      # 선조건: 미실행
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True and res["level"] == "ok"
    stamped = ctrl.registry.load("공고서").last_run_at
    # 소비처(home_state·screen_home)가 fromisoformat 파싱 + 원시 문자열 정렬로 쓴다.
    assert datetime.fromisoformat(stamped)
    assert len(stamped) == len("2026-07-21T09:00:00")           # 초 단위 고정폭 = 정렬 가능
    assert ctrl.vm.job.last_run_at == stamped                   # 인메모리 사본도 동행


def test_generation_stamp_does_not_clobber_disk_edits(tmp_path):
    """스탬프는 단일 필드 뮤테이션 — 세션이 든 옛 사본으로 디스크 최신 편집을 되돌리지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    # 세션이 열린 사이 다른 표면(에디터)이 같은 작업을 편집·저장했다.
    edited = ctrl.registry.load("공고서")
    edited.filename_pattern = "edited-{{seq:001}}"
    ctrl.registry.save(edited, allow_overwrite=True)

    assert ctrl.generate()["ok"] is True
    after = ctrl.registry.load("공고서")
    assert after.filename_pattern == "edited-{{seq:001}}"       # 디스크 편집 보존
    assert after.last_run_at != ""                              # 그리고 스탬프도 남는다


def test_stamp_goes_to_the_job_the_run_started_on(tmp_path, monkeypatch):
    """생성 중 작업 전환이 일어나도 역사는 **그 런의 작업**에 적힌다(Codex 리뷰 P1).

    생성 중 좌 목록은 잠기지 않고(busy 잠금은 선언 요소만), 기본 전체 선택 세션은 무장이
    아니라 전환이 확인도 안 거친다. 브리지가 별도 스레드라 배치 도중 세션이 B 로 옮겨갈 수
    있는데, 완주 뒤 현재 상태를 읽으면 A 의 실행이 B 의 역사가 되고 A 는 이력을 잃는다.
    """
    import hwpxfiller.webapp.screen_job as sj

    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _second_job(ctrl, tmp_path)                       # 전환 대상(공고서2) 등록
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    real_batch = sj.generate_batch

    def _switch_midflight(*a, **k):
        result = real_batch(*a, **k)
        ctrl.dispatch("select_job", {"name": "공고서2"})   # 배치 도는 사이 세션이 옮겨갔다
        return result

    monkeypatch.setattr(sj, "generate_batch", _switch_midflight)
    assert ctrl.generate()["ok"] is True
    assert ctrl.registry.load("공고서").last_run_at != ""   # 실제로 돈 작업에 역사
    assert ctrl.registry.load("공고서2").last_run_at == ""  # 없던 실행을 지어내지 않는다
    assert ctrl.vm is not None and ctrl.vm.job.name == "공고서2"
    assert ctrl.vm.job.last_run_at == ""                    # 남의 VM 도 안 만진다


def test_stamp_uses_the_serialized_registry_path(tmp_path, monkeypatch):
    """스탬프는 레지스트리의 **잠긴 경로**로만 쓴다(#129 리뷰 2R P1) — 직렬화 이탈 회귀 차단.

    load→save 를 여기서 다시 손으로 엮으면 잠금 밖이라 에디터 저장과 lost update 가 난다
    (둘 중 늦게 착지한 저장이 상대 변경을 통째로 되돌린다). 그 회귀는 결과값으로는 잘 안
    드러나므로 경로 자체를 못박는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    calls: list = []
    real = ctrl.registry.stamp_last_run

    def spy(name, when):
        calls.append((name, when))
        return real(name, when)

    monkeypatch.setattr(ctrl.registry, "stamp_last_run", spy)
    assert ctrl.generate()["ok"] is True
    assert [n for n, _ in calls] == ["공고서"]


def test_stamp_failure_is_loud_not_silent(tmp_path, monkeypatch):
    """기록 실패를 삼키지 않는다(confirm-or-alarm) — 문서는 남기고 사유를 완료 요약에 병기."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    def _boom(job, **kwargs):
        raise OSError("디스크 쓰기 거부")

    monkeypatch.setattr(ctrl.registry, "save", _boom)
    res = ctrl.generate()
    assert res["ok"] is True and res["succeeded"] == 2          # 생성 자체는 완주
    assert sorted(p.name for p in out.glob("*.hwpx")) == ["doc-001.hwpx", "doc-002.hwpx"]
    assert "실행 기록을 남기지 못했습니다" in res["summary"]
    assert "디스크 쓰기 거부" in res["summary"]                  # 사유 재진술
    assert res["level"] == "danger"                             # 조용한 초록 금지


def test_partial_failure_does_not_stamp_last_run_at(tmp_path, monkeypatch):
    """부분 실패는 완주가 아니다 — 무장 해제와 스탬프가 같은 술어를 공유한다(#129)."""
    import hwpxfiller.webapp.screen_job as sj

    class _FakeResult:
        ok = False
        output_path = "x.hwpx"
        error = "boom"

    class _FakeBatch:
        succeeded, failed, total = 1, 1, 2
        results = [_FakeResult()]

    monkeypatch.setattr(sj, "generate_batch", lambda *a, **k: _FakeBatch())
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    assert ctrl.generate()["failed"] == 1
    assert ctrl.registry.load("공고서").last_run_at == ""       # 미완주 = 역사 없음


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.generate()["ok"] is True  # 최초 생성

    # 같은 폴더 재생성 → 조용한 덮어쓰기 금지: 수치 합성 재진술 요구(총량·파괴분·신규분).
    res = ctrl.generate()
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert res["total"] == 2 and res["overwrite_count"] == 2 and res["new_count"] == 0
    assert len(res["conflict_names"]) == 2 and res["conflict_more"] == 0
    # 확인 후 재호출 → 생성.
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


# ---------------------------------------------- 본문 존 거울(블록 6 D2 ⓑ, PR-2)
def _mirror_job(tmp_path) -> JobRegistry:
    """거울 케이스용 작업 — 채움(text)·미입력(amount, rec0 빈값)·의도적 빈칸 3필드."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격", "비고"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce", type="amount"),
            FieldMapping(template_field="비고", type="blank"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    return reg


def test_mirror_value_display_filled_sample_missing_blank(tmp_path):
    """거울 행 = 필드별 값 집계(재구현 아님, mapped_records 소비). 상태별 값·표시형 병기."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    # 공고명: 선택 2행 값이 달라 표본 명시 병기(S10) — 서로 다른 값 1개 더, text 라 표시형 아님.
    assert m["공고명"]["state"] == "filled"
    assert m["공고명"]["value"] == "전산장비 (표본 · 외 1개 값)"
    assert m["공고명"]["formatted"] is False
    # 추정가격: rec0 빈값 → missing, 값 = 빈 행수 재진술(낙관 서사 해소), amount → 표시형.
    assert m["추정가격"]["state"] == "missing"
    assert "선택 2행 중 1행" in m["추정가격"]["value"]
    assert m["추정가격"]["formatted"] is True
    # 비고: 의도적 빈칸 표지.
    assert m["비고"]["state"] == "blank" and m["비고"]["value"] == "(의도적 빈칸)"


def test_mirror_filled_same_value_is_not_labeled_sample(tmp_path):
    """선택 N>1 이라도 값이 다 같으면 표본 라벨 없이 그냥 값(허위 '행마다 다름' 금지)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "same.csv"
    csv.write_text("bidNtceNm,presmptPrce\n동일공고,100\n동일공고,200\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    assert m["공고명"]["value"] == "동일공고"  # 표본 라벨 없음


def test_mirror_sample_counts_distinct_values_not_rows(tmp_path):
    """표본 병기 '외 K개 값'은 서로 다른 값 수로 센다 — 대부분 같고 하나만 달라도 과장 없음."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "mostly_same.csv"
    # 4행 '전산장비' + 1행 '사무비품' → 서로 다른 값은 2종(외 1개), 행 수(5)로 세면 과장(외 4).
    csv.write_text(
        "bidNtceNm,presmptPrce\n전산장비,1\n전산장비,2\n전산장비,3\n전산장비,4\n사무비품,5\n",
        encoding="utf-8",
    )
    ctrl.load_data_path(str(csv))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    assert m["공고명"]["value"] == "전산장비 (표본 · 외 1개 값)"  # 행 수 아님(외 4행 금지)


def test_mirror_empty_when_no_selection(tmp_path):
    """선택 0 = 생성될 문서 없음 → 거울 행 없음(빈 값을 '채움'으로 오도하지 않는다)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["mirror"] == [] and snap["drift"] == []


def test_mirror_drift_split_into_blocking_list(tmp_path):
    """drift(구조 불일치) 필드는 거울 표에서 빠져 별도 drift 목록으로 — 차단 배너 분리(결정 36)."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "유령"])  # 유령 = 템플릿 전용(매핑 미커버) → drift
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["drift"] == ["유령"]
    assert [r["name"] for r in snap["mirror"]] == ["공고명"]  # drift 필드는 표에서 제외


def test_snapshot_carries_unresolved_name_tokens_for_banner(tmp_path):
    """미해소 파일명 토큰이 스냅샷에 실린다(#128) — 거울 자리 차단 배너의 재료.

    종전엔 이 danger 가 게이트 캡션 한 줄로만 살아서, 거울은 전 행 「채움」으로 건강해
    보이고 재진술 블록은 danger 라 말없이 사라졌다(신호 없는 차단). 게이트 문안과 같은
    사실이므로 산출은 run_state 단일 출처를 그대로 싣는다.
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{미해소}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["name_tokens"] == ["미해소"]
    assert snap["gate"]["level"] == "danger" and snap["gate"]["enabled"] is False
    # 거울 표는 여전히 「채움」으로 건강하다 — 그래서 배너가 없으면 신호가 사라진다.
    assert [r["state"] for r in snap["mirror"]] == ["filled"]
    ctrl.dispatch("select_job", {"name": ""})           # 미겨눔 골격도 키를 갖춘다
    assert ctrl.snapshot()["name_tokens"] == []


def test_name_token_banner_yields_to_template_read_error(tmp_path):
    """게이트 서열을 거울이 재유도하지 않는다(리뷰 F2) — 템플릿을 못 읽으면 그쪽이 이긴다.

    토큰 미해소는 템플릿 상태와 무관하게 참이라, 사실만 보고 배너를 그리면 게이트는
    "구조를 읽을 수 없다"고 막는데 거울은 "파일명을 고치라"고 말한다 — 사용자를 엉뚱한
    수리로 보낸다(#128 이 없앤 어긋남의 반대 방향 재발).
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{미해소}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["name_tokens"] == ["미해소"]     # 정상 지형에선 토큰이 이긴다
    template.write_bytes(b"not a zip")                      # 템플릿 손상 → 구조 재읽기 실패
    snap = ctrl.snapshot()
    assert snap["gate"]["level"] == "danger" and "읽을 수 없어" in snap["gate"]["text"]
    assert snap["name_tokens"] == [], (
        "템플릿을 못 읽는데 거울이 파일명 토큰 배너를 세웁니다 — 게이트와 다른 수리를 지시."
    )


def test_select_none_closes_record_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 0
    assert snap["gate"]["enabled"] is False and "생성할 문서" in snap["gate"]["text"]


def test_deselect_job_returns_to_empty_panel(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("select_job", {"name": ""})  # 선택 해제
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["job_name"] == ""
    assert snap["job_rows"] == [{"name": "공고서", "selected": False}]


def test_refresh_invalidates_session_when_job_deleted(tmp_path):
    """master-detail 불변식(리뷰 #2): 선택된 작업이 다른 화면에서 삭제돼 레지스트리에서 사라지면
    refresh 가 세션을 무효화한다 — 존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께
    남아 유령 작업에서 생성되는 것을 막는다."""
    reg = _registry(tmp_path)
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["has_job"] is True

    reg.delete("공고서")  # 다른 화면이 삭제(그 화면으로 가려면 작업 화면 이탈 → 복귀 시 refresh)
    ctrl.dispatch("refresh", {})
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["job_name"] == ""
    assert snap["job_rows"] == []  # 좌 목록에서도 사라져 상실이 보인다
    # 유령 작업 생성 시도도 loud 차단(세션 무효화 후).
    res = ctrl.generate()
    assert res["ok"] is False


def test_refresh_keeps_session_when_job_still_present(tmp_path):
    """refresh 가 멀쩡한 세션을 건드리지 않는다 — 무효화는 삭제/개명된 작업에만(과잉 리셋 방지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("refresh", {})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    assert snap["record_count"] == 2  # 데이터 겨눔도 보존


def test_unknown_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 작업 화면 액션"):
        ctrl.dispatch("frobnicate", {})


def test_generate_without_job_is_loud_not_silent(tmp_path):
    ctrl, _ = _controller(tmp_path)
    res = ctrl.generate()
    assert res["ok"] is False and "작업" in res["error"]


# ---------------------------------------------------------------- #87 구조 가드(링1 위임)
def test_panel_delegates_to_ring1_view_models(tmp_path):
    """#87: 패널이 링1 VM 을 **소유·위임**한다 — 재구현이 아니라 임포트한 VM 인스턴스.

    작업 선택 시 세션의 결정 상태가 RunViewModel/SelectionModel 그 자체여야 한다(별도
    스냅샷 클래스로 우회 재구현하지 않는다). 정적 임포트·무재구현 가드는 test_architecture.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert isinstance(ctrl.vm, RunViewModel)
    assert isinstance(ctrl.selection, SelectionModel)


# ---------------------------------------------------------------- #26 #6 — 2소스(등록 데이터)
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry


def _pool_controller(tmp_path):
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path), lambda s, snap: pushes.append((s, snap)),
        pool_registry=pool,
    )
    return ctrl, pool


def test_load_pool_targets_excel_reference(tmp_path):
    """등록 데이터 겨눔 성공 — 실행 시점 재읽기(싱크) + 소스 병기 라벨 + 선택 초기화."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 7월공고"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["record_count"] == 2


def test_load_pool_without_job_is_loud(tmp_path):
    """겨눔 전제 = 작업 선택 — 미선택이면 공용 래퍼가 오류 dict 로 재진술(조용한 실패 금지)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is False and "작업" in res["error"]


# --------------------------------------- 기본 데이터셋 자동 조준(#53-A, A-1-11) — 리뷰 F4
# 실행 화면 사망(슬라이스 3)으로 test_webapp_run 의 자동 조준 회귀 심이 사라졌다 — JobController
# 의 '조용한 폴백 금지'(성공=ok 재진술 / 실패=warn 미겨눔) 계약을 여기서 이어 가드한다.
def _job_with_default(ctrl, pool, tmp_path, ref, *, register=True):
    """'공고서' 작업에 기본 데이터셋 참조를 붙여 재저장. register=True 면 동명 CSV 풀 항목 등록."""
    job = ctrl.registry.load("공고서")
    job.default_dataset_ref = ref
    ctrl.registry.save(job, allow_overwrite=True)
    if register:
        pool.save(DatasetPoolItem(name=ref, kind="excel", opts={"path": _data_csv(tmp_path)}))


def test_select_job_auto_aims_default_dataset(tmp_path):
    """기본 데이터셋 참조가 있으면 작업 선택 시 실행 시점에 다시 읽어 자동 조준(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2      # 자동 재읽기(싱크)
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["selected_count"] == 2                                  # 겨눔 = 전체 선택 초기화
    assert snap["data_notice"]["level"] == "ok" and "자동" in snap["data_notice"]["text"]


def test_select_job_dead_default_ref_is_loud_no_silent_fallback(tmp_path):
    """죽은 기본 참조는 조용한 폴백 금지 — 미겨눔 + 원인·복구 동선(다시 연결)을 재진술(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "없는참조", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False                       # 자동 겨눔 실패 = 미겨눔(폴백 없음)
    assert snap["data_source_label"] == ""
    assert snap["data_notice"]["level"] == "warn"
    assert "없는참조" in snap["data_notice"]["text"] and "다시 연결" in snap["data_notice"]["text"]


def test_auto_aim_nara_ref_is_frozen_warn(tmp_path):
    """기본 참조가 나라 항목이면 자동 조준도 동결 거절 warn — 공유 관문 문구 그대로(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(
        name="나라기본", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    _job_with_default(ctrl, pool, tmp_path, "나라기본", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"]["level"] == "warn"
    assert "동결" in snap["data_notice"]["text"]


def test_auto_aim_ambiguous_sheet_ref_is_warn(tmp_path):
    """기본 참조가 시트 미지정 다중시트면 자동 조준도 조용한 첫 시트 대신 warn 거절(#33·#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="모호기본", kind="excel", opts={"path": str(MULTI_SHEET)}))
    _job_with_default(ctrl, pool, tmp_path, "모호기본", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"]["level"] == "warn"
    assert "시트" in snap["data_notice"]["text"]


def test_manual_data_clears_auto_aim_notice(tmp_path):
    """자동 조준 후 사용자가 직접 데이터를 겨누면 자동 조준 재진술이 소거된다(임시 데이터=기본 불변)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["data_notice"] is not None
    ctrl.load_data_path(_data_csv(tmp_path))               # 수동 파일 겨눔
    snap = ctrl.snapshot()
    assert snap["data_notice"] is None
    assert snap["data_source_label"].startswith("파일:")
    assert ctrl.registry.load("공고서").default_dataset_ref == "7월공고"  # 임시 override, 기본 불변


# --------------------------------------------- 템플릿 다시 연결(#67, A-1-2 계열) — 리뷰 F5
# 실행 화면 사망으로 test_webapp_run 의 relink 회귀 심(x6)이 사라졌다 — 패널의 재연결 흐름
# (경로 재진술·드리프트 병기·읽기불가 하드차단·선택 작업 stale VM 재적재)을 여기서 잇는다.
def test_relink_template_needs_confirm_restates_paths(tmp_path):
    """1차 호출 = 기존→새 경로 재진술 확인 요구. 구조 동일이면 드리프트 문구 없음(#67)."""
    ctrl, _ = _controller(tmp_path)
    new_tpl = tmp_path / "moved.hwpx"
    _write_template(new_tpl, ["공고명", "추정가격"])       # 같은 구조 — 드리프트 0
    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(new_tpl)})
    assert res["ok"] is True and res["needs_confirm"] is True
    assert "t.hwpx" in res["confirm_text"] and "moved.hwpx" in res["confirm_text"]  # 양경로 재진술
    assert "구조가" not in res["confirm_text"]             # 무드리프트 = 소음 금지
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")  # 확인 전 durable 불변


def test_relink_template_drift_restated_in_confirm(tmp_path):
    """새 파일 구조가 확정 매핑과 다르면 확인 문구에 드리프트 상세+생성 차단 경고 병기(#67)."""
    ctrl, _ = _controller(tmp_path)
    new_tpl = tmp_path / "changed.hwpx"
    _write_template(new_tpl, ["공고명", "낙찰자"])         # 추정가격 소멸 + 낙찰자 유입
    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(new_tpl)})
    assert res["needs_confirm"] is True and "구조가" in res["confirm_text"]
    assert "낙찰자" in res["confirm_text"] and "추정가격" in res["confirm_text"]  # describe() 단일 출처
    assert "생성이 차단됩니다" in res["confirm_text"]      # 기존 게이트 백스톱 재진술


def test_relink_template_unreadable_is_blocked(tmp_path):
    """읽을 수 없는 파일은 확인으로도 템플릿이 될 수 없다 — 하드 차단 + JSON 불변(#67)."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch(
        "relink_template",
        {"name": "공고서", "path": str(tmp_path / "없는파일.hwpx"), "confirm": True})
    assert res["ok"] is False and "연결을 바꾸지 않았습니다" in res["error"]
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")


def test_relink_selected_job_reloads_vm_and_restates(tmp_path):
    """지금 선택된 작업을 재연결하면 stale VM 을 재적재하고 상태 초기화를 재진술한다(#67)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))               # 데이터 겨눔(재적재로 초기화될 상태)
    new_tpl = tmp_path / "moved.hwpx"
    _write_template(new_tpl, ["공고명", "추정가격"])
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(new_tpl), "confirm": True})
    assert res["relinked"] is True
    assert "다시 불러왔으니" in res["restated"]             # 조용한 상태 소실 금지(재적재 재진술)
    assert ctrl.vm.job.template_path == str(new_tpl)       # VM 재구성


# ---- 실행 화면 사망(슬라이스 3)으로 test_webapp_run 에서 유실된 confirm-or-alarm 회귀 심 승계
# ---- (별도세션 리뷰 #99-1~5, CONFIRMED). JobController 동작은 살아 있으나 무테스트였다.
def test_load_data_honors_confirmed_sheet(tmp_path):
    """다중 시트 확정 게이트(#33, 리뷰 #99-1) — load_data_path(sheet=) 가 확정 시트를 관통.

    작업 선택 후 낙찰현황(3건)을 확정하면 첫 시트(공고목록 2건)가 아니라 그 시트가 실린다 —
    조용한 첫 시트 강등이 아니라 확정값 반영(test_webapp_bridge 의 job 컨트롤러측 대응물).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = ctrl.snapshot()
    assert snap["data_label"] == "multi_sheet.xlsx"
    assert snap["has_data"] is True and snap["record_count"] == 3


def test_record_names_follow_selection_not_invented(tmp_path):
    """미선택 행 이름은 지어내지 않는다(F33, 리뷰 #99-2) — {{seq}}·충돌 접미사는 선택 집합에
    따라 달라지므로 선택 변경 시 남은 행 이름이 생성 결과대로 재계산된다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    rows = ctrl.snapshot()["records"]
    assert rows[0]["name"] == "" and rows[0]["selected"] is False   # 미선택 = 이름 없음
    # 남은 1건만 생성하면 그 파일이 doc-001 — 미리보기도 같은 사실을 말한다.
    assert rows[1]["name"] == "doc-001.hwpx" and rows[1]["selected"] is True


def test_generate_uses_previewed_name_timestamp(tmp_path):
    """미리보기가 보여준 시각 = 생성 파일명 시각(RC-02 표시=확인=생성, 리뷰 #99-3).

    시·분·초 date 토큰 패턴에서 미리보기 스냅샷과 생성 클릭 사이 시계가 흘러도, generate 는
    마지막 미리보기(``_names_now``)의 시각을 재사용해 화면이 보여준 실파일명 그대로 생성한다.
    """
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    # 스냅샷 미리보기가 시각을 캡처 → 이후 시계 전진을 결정적으로 모사(주입) → 생성이 캡처값 재사용.
    assert ctrl.snapshot()["records"][0]["name"].startswith("doc-")
    ctrl._names_now = datetime(2026, 1, 2, 3, 4, 5)
    res = ctrl.generate()
    assert res["ok"] is True
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made and all(n.startswith("doc-030405-") for n in made)  # 주입 시각 그대로


def test_snapshot_reports_template_missing_only_when_file_gone(tmp_path):
    """template_missing 은 파일이 실제로 없을 때만 True(F30, 리뷰 #99-4) — 웹이 이 플래그로
    「템플릿 다시 연결」 복구 동선을 조건부 노출한다(Python 층 실행 — JS 렌더 가드와 별개)."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["template_missing"] is False               # 미선택 = 버튼 표면 자체가 없음
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["template_missing"] is False               # 정상 = 복구 동선 숨김
    Path(snap["template_path"]).unlink()                    # 템플릿 파일 소실 재현
    assert ctrl.snapshot()["template_missing"] is True      # 부재 = 복구 동선 노출


def test_unresolved_pattern_gate_surfaces_in_snapshot(tmp_path):
    """미해소 파일명 토큰 작업 = 스냅샷 게이트 danger 차단 + 생성 백스톱(F34, 리뷰 #99-5)."""
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "공고서-{{ID}}"                 # 101 워크스루 실증 지뢰(데이터에 ID 없음)
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and snap["gate"]["level"] == "danger"
    assert "{{ID}}" in snap["gate"]["text"]
    res = ctrl.generate()
    assert res["ok"] is False and "{{ID}}" in res["error"]  # 생성 백스톱도 리터럴 방지


# ------------------------------------------------- 필터 배선(블록 4, 슬라이스 4 PR-2b)
def _session(tmp_path):
    """작업 선택 + 데이터 겨눔까지 마친 컨트롤러 — 필터 계약 테스트 공용."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    return ctrl, pushes


def test_filter_lifecycle_session_scoped(tmp_path):
    """필터 = 세션 수명(결정 24): 데이터 겨눔에 생성, 작업 전환에 소멸, 재겨눔에 재생성."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.filter is not None
    # 매핑 확정 유형(text)이 힌트로 우선한다 — 수치 열이어도 사용자 확정 존중.
    snap = ctrl.snapshot()
    kinds = {c["name"]: c["kind"] for c in snap["filter"]["columns"]}
    assert kinds == {"bidNtceNm": "text", "presmptPrce": "text"}
    ctrl.dispatch("filter_search", {"text": "전산"})
    assert ctrl.filter.is_active()
    ctrl.dispatch("select_job", {"name": ""})  # 작업 전환 = 필터 소멸(세션 휘발, 결정 8)
    assert ctrl.filter is None
    assert ctrl.snapshot()["filter"] == {
        "active": False, "reapply_available": False, "reapply_hint": "", "search": "",
        "chips": [], "definition": "", "branches": [], "columns": [],
    }


def test_filter_search_shapes_table_and_chips(tmp_path):
    """전열 검색 → 재현 OR 그룹: 가시 행·가지·칩·셀 세그먼트가 스냅샷으로 온다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    snap = ctrl.snapshot()
    t = snap["table"]
    assert t["columns"] == ["bidNtceNm", "presmptPrce"]
    assert t["visible_count"] == 1 and [r["index"] for r in t["rows"]] == [0]
    assert snap["filter"]["branches"] == ["bidNtceNm"]
    assert any("전산" in c for c in snap["filter"]["chips"])
    # 셀 = 하이라이트 세그먼트(파이썬이 잘라 조각으로 — 인덱스 무전달, jamo 계약).
    # 파이썬 층에선 튜플, json.dumps 가 배열로 직렬화한다.
    cells = t["rows"][0]["cells"]
    assert cells[0] == [("전산", True), ("장비", False)]
    assert cells[1] == []  # 빈 셀 = 빈 세그먼트


def test_set_all_is_additive_over_matches(tmp_path):
    """「전체 선택」 = 매치 전체 가산(결정 4·26) — 필터 밖 기존 선택은 유지(관통, 결정 3)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})   # 매치 = 0행뿐
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 필터 밖 행 직접 선택
    ctrl.dispatch("set_all", {})                        # 매치(0행) 가산
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 2                  # 1행 선택이 지워지지 않았다
    # 필터 밖 선택 = 스트립 소재(결정 3 — 상시 가시).
    assert [r["index"] for r in snap["table"]["hidden_selected"]] == [1]


def test_select_range_propagates_anchor_state(tmp_path):
    """Shift 범위 = 앵커 상태 전파(결정 2) — 선택도 해제도 범위로."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("select_range", {"indices": [0, 1], "value": True})
    assert ctrl.snapshot()["selected_count"] == 2
    ctrl.dispatch("select_range", {"indices": [1], "value": False})
    assert ctrl.snapshot()["selected_count"] == 1


def test_restate_origin_by_set_comparison(tmp_path):
    """선택 유래 = 집합 비교 무상태 판정: 매치 전체=정의-유래, 이탈=직접+수치 병기(S4)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("set_all", {})
    r = ctrl.snapshot()["restate"]
    assert r["origin"] == "definition" and r["filter_active"] is True
    assert r["in_def"] == 1 and r["extra"] == 0
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 정의 밖 가산 → 혼합
    r = ctrl.snapshot()["restate"]
    assert r["origin"] == "manual" and r["in_def"] == 1 and r["extra"] == 1
    assert set(r["sample"]) <= {0, 1} and len(r["sample"]) <= 3


def test_filter_range_on_amount_column_and_inline_error(tmp_path):
    """범위 조건 배선 — 매핑 amount 확정 열, 오독 피연산자는 인라인 오류 dict(비폭발)."""
    template = tmp_path / "t2.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    reg = JobRegistry(tmp_path / "jobs2")
    reg.save(Job(
        name="금액작업", template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce", type="amount"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "금액작업"})
    ctrl.load_data_path(_data_csv(tmp_path))
    kinds = {c["name"]: c["kind"] for c in ctrl.snapshot()["filter"]["columns"]}
    assert kinds["presmptPrce"] == "amount"              # 매핑 확정 유형 힌트
    res = ctrl.dispatch("filter_col_range", {
        "column": "presmptPrce", "first": {"op": "ge", "operand": "1억"}})
    assert res["ok"] is False and "읽을 수 없습니다" in res["error"]
    res = ctrl.dispatch("filter_col_range", {
        "column": "presmptPrce", "first": {"op": "ge", "operand": "1000000"}})
    assert res["ok"] is True
    assert ctrl.snapshot()["table"]["visible_count"] == 1  # 2000000 행만
    # 빈 첫 절 = 조건 해제.
    res = ctrl.dispatch("filter_col_range", {"column": "presmptPrce", "first": None})
    assert res["ok"] is True and ctrl.snapshot()["table"]["visible_count"] == 2


def test_filter_panel_query_returns_options_and_state(tmp_path):
    """열 패널 질의 — 현 조건 + 값 목록((빈값)="" 일급, 말미)."""
    ctrl, _ = _session(tmp_path)
    res = ctrl.dispatch("filter_panel", {"column": "presmptPrce"})
    assert res["kind"] == "text" and res["checked"] is None and res["range"] is None
    assert res["options"] == ["2000000", ""]             # 빈 셀 = 정식 값, 말미
    ctrl.dispatch("filter_col_values", {"column": "presmptPrce", "values": [""]})
    res = ctrl.dispatch("filter_panel", {"column": "presmptPrce"})
    assert res["checked"] == [""]
    assert ctrl.snapshot()["table"]["visible_count"] == 1  # 빈값 행(0행)만


def test_filter_actions_without_data_are_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    with pytest.raises(ValueError, match="데이터를 먼저"):
        ctrl.dispatch("filter_search", {"text": "x"})


def test_set_all_reports_added_count_for_dead_button_honesty(tmp_path):
    """「전체 선택」 반환 added — 전멸 필터의 무동작(0)을 표면이 알린다(리뷰 #9)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("set_all", {}) == {"added": 2}      # 필터 없음 = 전체
    ctrl.dispatch("filter_search", {"text": "존재하지않는말"})  # 전멸
    assert ctrl.dispatch("set_all", {}) == {"added": 0}      # 무동작 정직 보고
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("set_all", {}) == {"added": 1}      # 매치만 가산


def test_table_cell_preserves_falsy_values(tmp_path):
    """셀 텍스트 = cell_text 단일 출처(리뷰 #8) — 0 이 빈칸으로 붕괴하지 않는다."""
    ctrl, _ = _session(tmp_path)
    ctrl.vm.records[1]["presmptPrce"] = 0                    # 풀(JSON) 유래 수치형 재현
    snap = ctrl.snapshot()
    row1 = next(r for r in snap["table"]["rows"] if r["index"] == 1)
    assert row1["cells"][1] == [("0", False)]                # 필터가 보는 그대로 표면도


# ------------------------------------------------- 세션 가드(블록 4, 결정 26·27, PR-3)
def _data_csv3(tmp_path) -> str:
    """3행 코퍼스 — 2행 판에선 '정의 밖 가산'이 곧 전체 선택(비무장)이 되어 무장 케이스를
    못 가른다(가드 술어의 전체=1클릭 재현 절과 겹침)."""
    csv = tmp_path / "d3.csv"
    csv.write_text(
        "bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n책상,500\n",
        encoding="utf-8",
    )
    return str(csv)


def _second_job(ctrl, tmp_path):
    """가드 전환 테스트용 두 번째 작업 — 같은 템플릿 재사용."""
    job = ctrl.registry.load("공고서")
    ctrl.registry.save(Job(
        name="공고서2", template_path=job.template_path, mapping=job.mapping,
        filename_pattern=job.filename_pattern,
    ))


def test_guard_armed_by_set_comparison(tmp_path):
    """무장 술어(결정 27) — 전체/빈/정의-유래/완주 집합은 비무장, 수작업 열거만 무장."""
    ctrl, _ = _session(tmp_path)
    ctrl.load_data_path(_data_csv3(tmp_path))
    assert ctrl.snapshot()["guard"]["armed"] is False       # 초기 전체 선택 = 1클릭 재현
    ctrl.dispatch("set_none", {})
    assert ctrl.snapshot()["guard"]["armed"] is False       # 빈 선택 = 지킬 것 없음
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    g = ctrl.snapshot()["guard"]
    assert g["armed"] is True and g["sel_count"] == 1       # 필터 없는 부분 선택 = 수작업
    # 정의-유래(매치 전체)는 정의줄이 재현을 담보 — 비무장.
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("set_all", {})
    g = ctrl.snapshot()["guard"]
    assert g["armed"] is False and g["filter_active"] is True and g["filter_parts"] == 1
    # 정의 이탈(밖 행 가산) = 무장 + 수치 병기 소재.
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})
    g = ctrl.snapshot()["guard"]
    assert g["armed"] is True and g["in_def"] == 1 and g["extra"] == 1


def test_guard_disarmed_by_generation_completion(tmp_path):
    """완료 이벤트 = 무장 해제(결정 27) — 내역은 완료 존이 담보. 재편집 시 재무장."""
    ctrl, _ = _session(tmp_path)
    ctrl.load_data_path(_data_csv3(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 수작업 1행(빈칸 없는 행)
    assert ctrl.snapshot()["guard"]["armed"] is True
    res = ctrl.generate()
    assert res["ok"] is True
    assert ctrl.snapshot()["guard"]["armed"] is False       # 완주 집합과 일치 = 해제
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})  # 완주 밖 재편집 = 재무장
    assert ctrl.snapshot()["guard"]["armed"] is True


def test_guard_blocks_job_switch_until_confirmed(tmp_path):
    """T1 가드 왕복(RC-02 동형) — 무변이 needs_confirm, confirm=True 만 전환."""
    ctrl, _ = _session(tmp_path)
    _second_job(ctrl, tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})  # 무장
    res = ctrl.dispatch("select_job", {"name": "공고서2"})
    assert res["needs_confirm"] is True and res["kind"] == "switch_job"
    assert res["sel_count"] == 1 and res["target"] == "공고서2"
    snap = ctrl.snapshot()
    assert snap["job_name"] == "공고서"                      # 무변이 — 세션 그대로
    assert snap["has_data"] is True
    ctrl.dispatch("select_job", {"name": "공고서2", "confirm": True})
    assert ctrl.snapshot()["job_name"] == "공고서2"          # 확인 후 전환


def test_guard_free_paths_do_not_block(tmp_path):
    """비무장 전환·같은 작업 재선택·레지스트리 소실 무효화는 가드에 안 걸린다."""
    ctrl, _ = _session(tmp_path)
    _second_job(ctrl, tmp_path)
    assert ctrl.dispatch("select_job", {"name": "공고서2"}) is None  # 비무장 = 즉시 전환
    assert ctrl.snapshot()["job_name"] == "공고서2"
    # 소실 무효화(C6) — 무장 상태여도 유령 세션으로 좌초시키지 않는다(confirm 승계).
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    ctrl.registry.delete("공고서2")
    ctrl.dispatch("refresh", {})
    assert ctrl.snapshot()["has_job"] is False


def test_guard_state_query_is_live_and_pushless(tmp_path):
    """guard_state = 실시간 무변이 질의(리뷰 #4·#8) — 판정은 항상 Python 이 지금 내린다.

    스냅샷 캐시(LAST.guard)는 generate(디스패치 밖, 무푸시) 뒤 stale — 표면 사전 확인이
    이 질의를 소비해 거짓 모달/무확인 통과 양방향 오판을 막는다. 질의는 push 도 없다.
    """
    ctrl, pushes = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    before = len(pushes)
    g = ctrl.dispatch("guard_state", {})
    assert g["armed"] is True and g["sel_count"] == 1
    assert len(pushes) == before                       # 무변이 질의 = push 생략


def test_needs_confirm_does_not_push(tmp_path):
    """가드 차단 왕복은 무변이 — 동일 스냅샷 전량 재계산·재렌더를 얹지 않는다(리뷰 #8)."""
    ctrl, pushes = _session(tmp_path)
    _second_job(ctrl, tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    before = len(pushes)
    res = ctrl.dispatch("select_job", {"name": "공고서2"})
    assert res["needs_confirm"] is True
    assert len(pushes) == before                       # 차단 = 상태 그대로 = push 생략


def test_partial_failure_keeps_guard_armed(tmp_path, monkeypatch):
    """부분 실패 런은 완주가 아니다(리뷰 #1) — 실패분 재시도 선택을 무확인 파괴에서 지킨다."""
    import hwpxfiller.webapp.screen_job as sj

    class _FakeResult:
        def __init__(self):
            self.ok = False
            self.output_path = "x.hwpx"
            self.error = "boom"  # describe_result_error 는 문자열 계약

    class _FakeBatch:
        succeeded, failed, total = 0, 1, 1
        results = [_FakeResult()]

    monkeypatch.setattr(sj, "generate_batch", lambda *a, **k: _FakeBatch())
    ctrl, _ = _session(tmp_path)
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 수작업 1행
    res = ctrl.generate()
    assert res["ok"] is True and res["failed"] == 1
    assert ctrl.dispatch("guard_state", {})["armed"] is True     # 무장 유지(재시도 보호)


# ------------------------------------------- 건 연속성(직전 필터 재적용, 결정 28, PR-4)
def test_reapply_slot_written_on_session_death_and_source_gated(tmp_path):
    """슬롯 = 정의 가진 세션이 죽을 때 덮어씀 · 소스 일치 게이트(다른 소스엔 미제공)."""
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    assert ctrl.snapshot()["filter"]["reapply_available"] is False  # 아직 산 세션
    ctrl.load_data_path(_data_csv3(tmp_path))               # 데이터 교체 = 옛 정의 슬롯행
    snap = ctrl.snapshot()
    assert snap["filter"]["active"] is False                # 새 세션 필터는 백지
    assert snap["filter"]["reapply_available"] is False     # 소스 다름(d.csv≠d3.csv) — 게이트
    ctrl.load_data_path(csv1)                               # 같은 소스로 복귀
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_restores_definition_only_two_click_split(tmp_path):
    """재적용 = 정의(보기)만 복원 — 선택 불변(전체 선택과 2클릭 분리, 결정 28)."""
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.load_data_path(_data_csv3(tmp_path))               # 죽음 → 슬롯
    ctrl.load_data_path(csv1)                               # 같은 소스 재겨눔
    ctrl.dispatch("set_none", {})
    before_sel = ctrl.snapshot()["selected_count"]
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is True and res["dropped"] == []
    snap = ctrl.snapshot()
    assert snap["filter"]["active"] is True
    assert snap["table"]["visible_count"] == 1              # 「전산」 재적용 — 보기 좁힘
    assert snap["selected_count"] == before_sel             # 선택은 그대로(2클릭 분리)


def test_reapply_full_drop_refused_without_touching_current(tmp_path):
    """전탈락 = 거부 + 이유(결정 28 백스톱, 외부 편집 edge) — 현 정의를 건드리지 않는다.

    열 결손은 같은 경로(소스 일치)인데 파일이 밖에서 편집돼 열 지형이 바뀐 경우에만
    생긴다(정본 명시 edge) — 다른 파일이면 소스 게이트가 애초에 재적용을 안 준다.
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_col_values", {"column": "bidNtceNm", "values": ["전산장비"]})
    other = tmp_path / "other.csv"
    other.write_text("colA,colB\nx,y\n", encoding="utf-8")
    ctrl.load_data_path(str(other))                         # 죽음 → 슬롯(csv1 열 조건만)
    Path(csv1).write_text("colA,colB\nx,y\n", encoding="utf-8")  # 외부 편집 — 열 전면 교체
    ctrl.load_data_path(csv1)                               # 같은 경로 재겨눔 → 소스 일치
    assert ctrl.snapshot()["filter"]["reapply_available"] is True
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is False and "하나도 남지 않아" in res["error"]
    assert ctrl.snapshot()["filter"]["active"] is False     # 부분 설치 없음(현 정의 무변이)


def test_reapply_without_slot_is_loud(tmp_path):
    ctrl, _ = _session(tmp_path)
    with pytest.raises(ValueError, match="직전 필터가 없습니다"):
        ctrl.dispatch("filter_reapply", {})


def test_reapply_gated_off_while_current_filter_is_live(tmp_path):
    """게이트 3연언의 '현 필터 빈 상태'(#127) — 조건을 세워 둔 위에는 재적용을 제공하지 않는다.

    제공했다면 클릭 한 번이 현 정의를 **확인 없이 원자 교체**한다(파괴 경로). 표면이 어긋나
    직접 호출되더라도 백엔드가 사유를 구분해 시끄럽게 거부한다.
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.load_data_path(_data_csv3(tmp_path))               # 죽음 → 슬롯
    ctrl.load_data_path(csv1)                               # 같은 소스 복귀 = 슬롯·소스 연언 충족
    assert ctrl.snapshot()["filter"]["reapply_available"] is True   # 백지 상태에선 제공
    ctrl.dispatch("filter_col_values", {"column": "bidNtceNm", "values": ["사무비품"]})
    assert ctrl.snapshot()["filter"]["reapply_available"] is False  # 정의가 서면 회수
    with pytest.raises(ValueError, match="현재 필터가 설정돼 있어"):
        ctrl.dispatch("filter_reapply", {})
    snap = ctrl.snapshot()
    assert snap["filter"]["active"] is True and snap["table"]["visible_count"] == 1
    ctrl.dispatch("filter_clear", {})                       # 지우면 복원 어포던스가 돌아온다
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_hint_describes_the_dying_session_not_the_incoming_data(tmp_path):
    """정의줄은 **죽는 세션의 데이터**로 지어야 한다(리뷰 F1) — 겨눔 경로가 레코드를 먼저
    갈아치우므로, 스태시 시점에 새로 지으면 남의 데이터에 대고 옛 정의를 묘사하게 된다.

    증상: 새 소스에 매치가 없으면 describe 가 「매치 없음」으로 떨어져, 원 소스로 돌아왔을 때
    버튼이 "매치 없음"이라는 거짓을 업고 뜬다(그 소스에선 멀쩡히 매치되는 정의인데도).
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    alive = ctrl.snapshot()["filter"]["definition"]
    assert "전산" in alive and "매치 없음" not in alive
    other = tmp_path / "other.csv"                       # 열도 값도 다른 소스(매치 0)
    other.write_text("colA,colB\nx,y\n", encoding="utf-8")
    ctrl.load_data_path(str(other))                      # 죽음 → 슬롯(레코드는 이미 교체됨)
    ctrl.load_data_path(csv1)                            # 원 소스 복귀
    hint = ctrl.snapshot()["filter"]["reapply_hint"]
    assert hint == alive, f"슬롯 문안이 죽는 세션이 아니라 새 데이터로 지어졌습니다: {hint!r}"


def test_reapply_hint_carries_definition_to_be_installed(tmp_path):
    """버튼이 설치할 정의를 업는다(#127 조치 2 — 목업 칩 문법 승계).

    어포던스가 회수되면 문안도 함께 내려간다(죽은 힌트가 남으면 그 자체가 거짓 진술).
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.load_data_path(_data_csv3(tmp_path))               # 죽음 → 슬롯(정의줄 동반)
    assert ctrl.snapshot()["filter"]["reapply_hint"] == ""  # 소스 불일치 = 문안도 없음
    ctrl.load_data_path(csv1)
    hint = ctrl.snapshot()["filter"]["reapply_hint"]
    assert "전산" in hint, hint
    ctrl.dispatch("filter_search", {"text": "사무"})         # 정의가 서면 어포던스·문안 회수
    assert ctrl.snapshot()["filter"]["reapply_hint"] == ""


def test_reapply_source_key_distinguishes_sheets(tmp_path):
    """소스 키 = 경로+시트(리뷰 #0) — 같은 워크북의 다른 시트는 다른 소스다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(str(MULTI_SHEET), sheet="공고목록")
    ctrl.dispatch("filter_search", {"text": "물"})           # 정의 있는 세션
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")  # 같은 파일·다른 시트
    assert ctrl.snapshot()["filter"]["reapply_available"] is False  # 교차 재사용 차단
    ctrl.load_data_path(str(MULTI_SHEET), sheet="공고목록")  # 같은 시트 복귀
    # 무정의 세션(낙찰현황)의 죽음은 슬롯을 보존한다 — 공고목록 정의가 제 시트에 제공.
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_source_key_normalizes_path_spelling(tmp_path):
    """경로 표기 변형(대소문자)에도 같은 실파일이면 소스 일치(리뷰 #8 — 조용한 강등 방지)."""
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.load_data_path(_data_csv3(tmp_path))               # 죽음 → 슬롯(csv1 키)
    ctrl.load_data_path(csv1.upper())                       # 같은 파일, 표기만 다름(Windows)
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_pool_key_includes_reference_identity(tmp_path):
    """풀 소스 키 = 이름+참조 정체(리뷰 #6) — 같은 이름 재등록(다른 파일)은 다른 소스."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("load_pool", {"name": "7월공고"})
    ctrl.dispatch("filter_search", {"text": "전산"})
    # 같은 이름으로 다른 파일 재등록(참조 교체) 후 재겨눔 — 이름만 같은 다른 소스.
    pool.save(DatasetPoolItem(name="7월공고", kind="excel",
                              opts={"path": _data_csv3(tmp_path)}), allow_overwrite=True)
    ctrl.dispatch("load_pool", {"name": "7월공고"})          # 죽음 → 슬롯(옛 참조 키)
    assert ctrl.snapshot()["filter"]["reapply_available"] is False


def test_reapply_abandons_pruning_when_branches_all_lost(tmp_path):
    """가지 소실 시 프루닝 복원 포기(리뷰 #2) — 거짓 「매치 없음」 빈 화면을 만들지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    both = tmp_path / "both.csv"
    both.write_text("bidNtceNm,memo\n전산장비,전산비고\n사무비품,일반\n", encoding="utf-8")
    ctrl.load_data_path(str(both))
    ctrl.dispatch("filter_search", {"text": "전산"})         # 가지 = bidNtceNm·memo
    ctrl.dispatch("filter_prune", {"column": "bidNtceNm"})   # 가지 하나 쳐냄(memo 잔존)
    ctrl.load_data_path(_data_csv(tmp_path))                 # 죽음 → 슬롯
    # 외부 편집: memo 열 소실 — 프루닝 대상(bidNtceNm)만 남는 지형.
    both.write_text("bidNtceNm\n전산장비\n사무비품\n", encoding="utf-8")
    ctrl.load_data_path(str(both))
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is True
    assert any("프루닝" in d for d in res["dropped"])         # 포기 고지
    snap = ctrl.snapshot()
    assert snap["table"]["visible_count"] == 1               # 매치가 산다(거짓 전멸 아님)
    assert snap["filter"]["branches"] == ["bidNtceNm"]       # 가지 부활


# ---------------------------------------------------------------- 좌 목록 관리(결정 43)
def test_sections_flat_when_no_groups(tmp_path):
    # 퇴화 불변식(R-info 결정 5): 그룹 0개 = 헤더·들여쓰기 없는 평면(현행 모습 그대로).
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert snap["job_flat"] is True
    assert snap["job_group_names"] == []
    assert [s["group"] for s in snap["job_sections"]] == [""]
    assert snap["job_sections"][0]["rows"] == snap["job_rows"]
    assert snap["job_sections"][0]["collapsed"] is False


def test_sections_group_order_and_counts(tmp_path):
    # 그룹 배열 = 이름순 안정, 「그룹 없음」 = 마지막(R-info 결정 4·5). 두 뷰는 같은 판독에서 파생.
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    reg.save(Job(name="나 작업"))
    reg.set_group("나 작업", "하 그룹")
    reg.save(Job(name="다 작업"))
    reg.set_group("다 작업", "가 그룹")
    snap = ctrl.snapshot()
    assert snap["job_flat"] is False
    assert [s["group"] for s in snap["job_sections"]] == ["가 그룹", "하 그룹", ""]
    assert snap["job_group_names"] == ["가 그룹", "하 그룹"]
    by_group = {s["group"]: s for s in snap["job_sections"]}
    assert [r["name"] for r in by_group[""]["rows"]] == ["공고서"]
    assert by_group["가 그룹"]["count"] == 1 and by_group["하 그룹"]["count"] == 1
    # 평면 뷰(job_rows)는 전체 집합 이름순 그대로 — 구획 뷰와 같은 원천.
    assert [r["name"] for r in snap["job_rows"]] == ["공고서", "나 작업", "다 작업"]


def test_toggle_group_collapses_persists_and_keeps_selection(tmp_path):
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    reg.set_group("공고서", "입찰")
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["selected_count"] == 2
    ctrl.dispatch("toggle_group", {"group": "입찰"})
    snap = ctrl.snapshot()
    assert next(s for s in snap["job_sections"] if s["group"] == "입찰")["collapsed"] is True
    assert snap["selected_count"] == 2  # 접힘은 보기만 — 선택 유지(결정 6-⑤)
    # 마지막 상태 영속(Python 설정) — 새 컨트롤러(재부팅 동형)가 접힘을 복원한다.
    ctrl2 = JobController(reg, lambda s, snap: None)
    snap2 = ctrl2.snapshot()
    assert next(s for s in snap2["job_sections"] if s["group"] == "입찰")["collapsed"] is True
    # 재토글 = 펼침 복원.
    ctrl2.dispatch("toggle_group", {"group": "입찰"})
    assert next(
        s for s in ctrl2.snapshot()["job_sections"] if s["group"] == "입찰"
    )["collapsed"] is False


def test_rename_job_follows_open_session(tmp_path):
    # 이름 변경은 비파괴 — 열린 세션의 정체(job_name·헤더)가 새 이름을 추종한다.
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("rename_job", {"name": "공고서", "new": " 개명 공고서 "})
    assert res == {"ok": True}
    snap = ctrl.snapshot()
    assert snap["job_name"] == "개명 공고서" and snap["has_job"] is True
    assert ctrl.registry.exists("개명 공고서") and not ctrl.registry.exists("공고서")


def test_rename_job_collision_and_empty_are_restated(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(Job(name="둘째"))
    res = ctrl.dispatch("rename_job", {"name": "공고서", "new": "둘째"})
    assert res["ok"] is False and "사용 중" in res["error"]
    res = ctrl.dispatch("rename_job", {"name": "공고서", "new": "  "})
    assert res["ok"] is False and "비어" in res["error"]
    assert ctrl.registry.exists("공고서")  # 실패 무손상


def test_delete_open_session_job_confirm_roundtrip_closes_panel(tmp_path):
    # RC-02 왕복 동형: 무확인 = 재진술 자료 반환·무변이, 확인 = 삭제 + 세션 닫힘(빈 패널 재진술).
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})  # 수작업 선택 = 무장
    res = ctrl.dispatch("delete_job", {"name": "공고서"})
    assert res["needs_confirm"] is True and res["open_session"] is True
    assert res["armed"] is True and res["sel_count"] == 1  # 파괴 전모(세션 선택 소실) 수치 동봉
    assert ctrl.registry.exists("공고서")  # 무확인 = 무변이
    ctrl.dispatch("delete_job", {"name": "공고서", "confirm": True})
    snap = ctrl.snapshot()
    assert not ctrl.registry.exists("공고서")
    assert snap["has_job"] is False and snap["job_rows"] == []


def test_delete_other_job_restates_without_session_fields(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(Job(name="둘째"))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("delete_job", {"name": "둘째"})
    assert res["needs_confirm"] is True and res["open_session"] is False
    assert "armed" not in res  # 열린 세션이 아니면 세션 수치를 싣지 않는다(오귀속 방지)
    ctrl.dispatch("delete_job", {"name": "둘째", "confirm": True})
    assert ctrl.snapshot()["job_name"] == "공고서"  # 무관 세션 무영향


def test_clone_job_returns_unique_name_and_inherits_group(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    res = ctrl.dispatch("clone_job", {"name": "공고서"})
    assert res["ok"] is True and res["name"] == "공고서 (복사본)"
    assert ctrl.registry.load(res["name"]).group == "입찰"  # 인접(같은 그룹) 승계


def test_set_group_moves_between_sections(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_group", {"name": "공고서", "group": "입찰"})
    snap = ctrl.snapshot()
    assert snap["job_group_names"] == ["입찰"]
    ctrl.dispatch("set_group", {"name": "공고서", "group": ""})  # 해제 = 그룹 없음
    assert ctrl.snapshot()["job_flat"] is True


def test_rename_group_merge_needs_confirm_roundtrip(tmp_path):
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    reg.save(Job(name="둘째"))
    reg.set_group("공고서", "입찰")
    reg.set_group("둘째", "수의")
    res = ctrl.dispatch("rename_group", {"name": "수의", "new": "입찰"})
    assert res["needs_confirm"] is True and res["kind"] == "merge_group"
    assert res["count"] == 1 and res["target_count"] == 1  # 병합 수치 재진술
    assert set(reg.groups()) == {"수의", "입찰"}  # 무변이
    res2 = ctrl.dispatch("rename_group", {"name": "수의", "new": "입찰", "confirm": True})
    assert res2["ok"] is True and reg.groups() == ["입찰"]


def test_rename_group_carries_collapse_state(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    ctrl.dispatch("toggle_group", {"group": "입찰"})
    ctrl.dispatch("rename_group", {"name": "입찰", "new": "2026 입찰"})
    snap = ctrl.snapshot()
    assert next(
        s for s in snap["job_sections"] if s["group"] == "2026 입찰"
    )["collapsed"] is True  # 이름만 바뀐 같은 그룹 — 접힘 승계


def test_disband_group_confirm_roundtrip(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    ctrl.dispatch("toggle_group", {"group": "입찰"})
    res = ctrl.dispatch("disband_group", {"name": "입찰"})
    assert res["needs_confirm"] is True and res["count"] == 1
    assert ctrl.registry.groups() == ["입찰"]  # 무확인 = 무변이
    res2 = ctrl.dispatch("disband_group", {"name": "입찰", "confirm": True})
    assert res2["ok"] is True and ctrl.registry.groups() == []
    # 사라진 그룹의 접힘 잔재는 걷는다 — 같은 이름 재생성 시 유령 접힘 방지.
    from hwpxfiller.webapp.settings import load_job_collapsed_groups
    assert "입찰" not in load_job_collapsed_groups()


# ---------------- 실 공개 writer × 스탬프 동시성(#129 리뷰 3R P1) ----------------
#
# 리뷰 요구: "협조적인 테스트용 writer 뿐 아니라 실제 공개 delete·태그·재연결 경로와 스탬프를
# 겹치는 회귀 테스트". 그래서 아래 세 테스트는 화면이 실제로 부르는 경로를 그대로 쓴다
# (HomeViewModel.delete / HomeViewModel.set_tags / relink_job_template).
def _pause_stamp(monkeypatch):
    """스탬프 저장을 잠금 안에서 한 번 멈춰 세우는 장치 — (진입 이벤트, 해제 이벤트)."""
    import threading

    entered, release = threading.Event(), threading.Event()
    real_save = Job.save
    fired = {"once": False}

    def slow_save(self, path):
        if not fired["once"] and self.last_run_at:   # 스탬프 저장만 붙잡는다
            fired["once"] = True
            entered.set()
            release.wait(3)
        return real_save(self, path)

    monkeypatch.setattr(Job, "save", slow_save)
    return entered, release


def _home_vm(registry):
    from hwpxfiller.gui.home_state import HomeViewModel

    return HomeViewModel(registry, None, None)


def test_public_delete_during_stamp_does_not_resurrect_the_job(tmp_path, monkeypatch):
    """삭제 도중 스탬프가 끼어도 지운 작업이 되살아나지 않는다(리뷰 3R P1).

    잠금 밖 삭제라면: ①스탬프가 A 를 읽고 ②삭제가 파일을 지우고 성공을 반환하고 ③스탬프가
    사본을 저장해 **A 가 부활**한다. "지웠다"고 말한 뒤 되살아나는 것은 조용한 소실의 거울상이다.
    """
    import threading

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    vm = _home_vm(reg)
    entered, release = _pause_stamp(monkeypatch)

    stamper = threading.Thread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    assert entered.wait(3)

    done = threading.Event()

    def delete_job():
        vm.delete("공고서")      # 홈 카드 「삭제」가 타는 실제 경로
        done.set()

    deleter = threading.Thread(target=delete_job)
    deleter.start()
    assert not done.wait(0.2), "삭제가 스탬프의 임계구역 안으로 끼어들었습니다."
    release.set()
    stamper.join(3)
    deleter.join(3)
    assert not reg.exists("공고서"), "지운 작업이 스탬프 저장으로 되살아났습니다."


def test_public_set_tags_during_stamp_keeps_both_changes(tmp_path, monkeypatch):
    """태그 편집과 스탬프가 겹쳐도 둘 다 남는다 — 늦은 저장이 상대를 되돌리지 않는다."""
    import threading

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    vm = _home_vm(reg)
    entered, release = _pause_stamp(monkeypatch)

    stamper = threading.Thread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    assert entered.wait(3)
    tagger = threading.Thread(target=lambda: vm.set_tags("공고서", {"부서": "계약"}))
    tagger.start()
    release.set()
    stamper.join(3)
    tagger.join(3)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"   # 태그 저장이 시각을 지우지 않았다
    assert saved.tags == {"부서": "계약"}                # 스탬프가 태그를 되돌리지 않았다


def test_public_relink_during_stamp_keeps_both_changes(tmp_path, monkeypatch):
    """템플릿 재연결과 스탬프가 겹쳐도 둘 다 남는다(확인 왕복이 있어 창이 특히 넓은 경로)."""
    import threading

    from hwpxfiller.webapp.screens import relink_job_template

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    new_template = tmp_path / "새서식.hwpx"
    _write_template(new_template, ["공고명", "추정가격"])
    entered, release = _pause_stamp(monkeypatch)

    stamper = threading.Thread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    assert entered.wait(3)
    linker = threading.Thread(
        target=lambda: relink_job_template(reg, "공고서", str(new_template), confirm=True)
    )
    linker.start()
    release.set()
    stamper.join(3)
    linker.join(3)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"
    assert saved.template_path == str(new_template)
