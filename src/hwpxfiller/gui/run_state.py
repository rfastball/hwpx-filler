"""집행(Run) 화면 ViewModel — Qt 비의존 집행 결정(데이터·대상·사전검증·게이트).

위젯(:class:`~hwpxfiller.gui.run_view.RunView`)에서 백엔드로 새던 부분을 여기로 옮겼다:
``DataSource`` 포트(팩토리 경유)·``HwpxEngine``·``RunRequest`` 는 이 뷰모델만 만지고,
위젯은 QThread·QMessageBox·QFileDialog 같은 Qt 오케스트레이션만 남긴다(링1: PySide6 금지).
**매핑 재확정 없음** — 매핑은 작업 정의 때 확정됐고 여기선 사전검증만 한다.

이 뷰모델 표면(dataclass 결과 + 메서드)이 목업 집행 화면이 겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.engine import HwpxEngine
from ..core.job import Job, RunRequest
from ..data import source_for_path


@dataclass
class PreflightResult:
    """사전검증 표시용 — 빠진 소스키(치명)·빈 출력값(경고)."""

    missing_columns: "list[str]" = field(default_factory=list)
    empty_valued: "list[str]" = field(default_factory=list)
    level: str = ""          # ""/"ok"/"warn"/"danger" (style.mark 레벨)
    text: str = ""

    def issues(self) -> "list[str]":
        """로그용 이슈 목록(소스 누락 + 빈값, 문서순 중복제거)."""
        return list(dict.fromkeys(list(self.missing_columns) + list(self.empty_valued)))


@dataclass
class PrevNote:
    """누적 모드 이전 출력 정합 고지(비차단)."""

    text: str
    level: str  # ""/"warn"/"danger"


@dataclass
class GateError:
    """생성 차단 사유 — 위젯이 message/level 로 대화상자를 띄운다."""

    message: str
    level: str  # "warn"(확인) / "danger"(오류)


class RunViewModel:
    """작업 1건 집행 상태·결정. 데이터·대상 문서는 DataSource 이음새 뒤에 둔다."""

    def __init__(self, job: Job):
        self.job = job
        self.datasource = None                 # DataSource 포트(팩토리가 생성)
        self.records: "list[dict]" = []
        # 누적치환: 이전 출력이 **템플릿 자리**에 온다(데이터 소스 아님 — 이음새 무관).
        self.template_override: "str | None" = None
        self.target_mode = "new"               # "new" | "continue"

    # ------------------------------------------------------------ 대상 문서
    def effective_template(self) -> str:
        """생성이 겨눌 문서 — 누적 모드면 이전 출력, 아니면 작업 템플릿."""
        return self.template_override or self.job.template_path

    def set_target_mode(self, mode: str) -> None:
        """신규/누적 전환. 신규 복귀 시 이전 출력 override 해제."""
        self.target_mode = mode
        if mode != "continue":
            self.template_override = None

    def set_prev_output(self, path: str) -> PrevNote:
        """이전 출력을 겨누고 정합 고지를 계산한다(값 겹침 덮어씀을 시끄럽게 — ADR G).

        누름틀은 채운 뒤에도 재발견되므로(engine.required_fields) 교집합으로 판정.
        값 수준 '이미 채워짐' 검사는 필드 값 읽기 API 부재로 파킹.
        """
        self.template_override = path
        try:
            doc_fields = set(HwpxEngine().required_fields(path))
        except Exception as exc:  # noqa: BLE001
            return PrevNote(f"이전 출력을 읽을 수 없습니다: {exc}", "danger")
        ours = set(self.job.template_fields())
        inter = doc_fields & ours
        if not inter:
            return PrevNote("이 작업의 필드가 이 문서에 하나도 없습니다 — 파일을 확인하세요.", "danger")
        return PrevNote(
            f"이 작업의 필드 {len(ours)}개 중 {len(inter)}개가 문서에 있습니다. "
            "이미 값이 있는 겹침 필드는 덮어씁니다 — 단계별 필드는 서로소로 설계하세요.",
            "warn" if len(inter) < len(ours) else "",
        )

    # ------------------------------------------------------------ 데이터
    def load_data(self, path: str) -> "list[dict]":
        """겨눈 경로에서 레코드를 읽는다(팩토리가 종류 선택). 로드 실패는 raise,
        레코드 0건이면 상태를 바꾸지 않고 빈 리스트 반환(위젯이 경고)."""
        source = source_for_path(path)
        records = source.records()
        if not records:
            return []
        self.datasource = source
        self.records = records
        return records

    # ------------------------------------------------------------ 사전검증
    def request(self, indices: "list[int]") -> RunRequest:
        return RunRequest(self.job, self.datasource, list(indices))

    def preflight(self, indices: "list[int]") -> PreflightResult:
        """빠진 소스키(치명)·매핑 출력의 빈값(경고)을 판정만 한다(재확정 아님)."""
        if self.datasource is None:
            return PreflightResult()
        req = self.request(indices)
        src = req.source_report()
        out = req.output_report()
        parts: "list[str]" = []
        if src.missing_columns:
            parts.append("[치명] 데이터에 없는 소스키(빈칸 생성됨): " + ", ".join(src.missing_columns))
        if out.empty_valued:
            parts.append("[경고] 값이 비어 있는 필드: " + ", ".join(out.empty_valued))
        if src.missing_columns:
            level = "danger"
        elif out.empty_valued:
            level = "warn"
        else:
            level = "ok"
        return PreflightResult(
            list(src.missing_columns), list(out.empty_valued), level,
            "\n".join(parts) if parts else "사전검증 통과 — 누락/빈 값 없음.",
        )

    def blank_fields(self, indices: "list[int]") -> "list[str]":
        """미충족 빈칸 필드(ADR-E 상시 인라인 게이트의 seam). 데이터 없으면 빈 목록."""
        if self.datasource is None:
            return []
        return list(self.request(indices).output_report().empty_valued)

    # ------------------------------------------------------------ 생성 게이트
    def validate_generate(self, indices: "list[int]", out_dir: str) -> "list[GateError]":
        """생성 전 가드 — 첫 차단 사유만 반환(없으면 빈 목록)."""
        indices = list(indices)
        if self.datasource is None:
            return [GateError("먼저 데이터를 선택하세요.", "warn")]
        if self.target_mode == "continue" and not self.template_override:
            return [GateError("이어채울 이전 출력(.hwpx)을 선택하세요.", "warn")]
        template = self.effective_template()
        if template and not Path(template).exists():
            return [GateError(f"템플릿을 찾을 수 없습니다:\n{template}", "danger")]
        if not out_dir:
            return [GateError("저장 폴더를 지정하세요.", "warn")]
        if not indices:
            return [GateError("생성할 레코드를 최소 1건 선택하세요.", "warn")]
        if self.template_override and len(indices) != 1:
            # 누적 v1 = 단건. 배치 누적(이전출력↔레코드 파일키 매칭)은 별개 설계 — 파킹.
            return [GateError(
                "이전 출력 이어채우기는 레코드 1건만 지원합니다 — 문서 1개에 여러 "
                "레코드를 겹쳐 쓸 수 없습니다. 레코드를 1건만 선택하세요.", "warn")]
        return []

    def mapped_records(self, indices: "list[int]", mark_missing: str = "") -> "list[dict]":
        """선택 레코드에 매핑 적용 → {템플릿필드: 값}. mark_missing 시 빈 키에 표식 주입."""
        return self.request(indices).mapped_records(mark_missing=mark_missing)
