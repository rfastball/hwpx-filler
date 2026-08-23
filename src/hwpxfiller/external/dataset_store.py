"""데이터셋 풀 영속 경계 — JSON 파일 레지스트리·원자 쓰기·공유 잠금(External Adapter, P2-22 #570).

옛 dataset pool이 들고 있던 persistence codec·슬롯 키·파일 레지스트리·
프로세스 내 공유 쓰기 잠금을 원문 이동으로 승계한다. 값·수명·정체성 규칙은
:mod:`hwpxfiller.domain.dataset_reference` 가 소유하고, 여기는 그 값을 디스크와 오가게 하는
어댑터다. 기본 위치 해석(``~/.hwpxfiller/datasets``)은
:func:`hwpxfiller.host.locations.default_dataset_pool_dir` 로 갔다.

ADR J 축확정: 데이터 수명 = 계약 사이클(발주~지급, 최소 60일)이라 세션-일회 recents 로는
부족 → 데이터는 **durable 풀 항목**이되 **연결/참조**(엑셀 경로·나라 쿼리)로만 저장하고
실행 때 재읽기("싱크")한다. 사이클 종료 = **보관**(add/delete 아닌 archive — 실행 후보에서만 제외).
"데이터·행 미저장" 불변식(포인터만 직렬화)을 유지한다 — 풀 항목은 **소스를 어떻게 다시
여는가**(kind + opts)만 담고 레코드는 담지 않는다.

**정체성 = 경로+시트, 이름 = 순수 라벨**(U2 §5.3 판정 C, #347): 엑셀/CSV 참조의 정체성은
``normcase(abspath(path)) + sheet`` 다(:func:`~hwpxfiller.domain.dataset_reference.excel_identity`)
— 같은 워크북의 다른 시트는 다른 데이터(#33)이고, 같은 경로·시트는 이름이 달라도 같은
데이터다. ``name`` 은 중복 허용·개명 자유·정체성 무관의 표시 라벨로 강등됐다. 그래서
파일명도 이름 slug 가 아니라 **불투명 슬롯 키**(파일 stem)이고, 그 키는 **내용에서 파생되지
않는다**(내용물 교체가 정상 수명 사건이라 — 4R 판정, 클래스 주석 참조). 구판(slug 파일명)
파일은 그 stem 그대로 유효한 슬롯이라 디스크 마이그레이션이 없다(읽는 김에 디스크를 고치지
않는다).

**P2-22 persistence 모델**: 구 ``DatasetPoolItem(DatasetReference)`` — Domain 값을 subclass
해 ``save``/``load`` 를 붙이던 호환 타입 — 은 폐기됐다. byte I/O 는 모듈 함수
:func:`save_reference`/:func:`load_reference` 가 지고(저장 bytes 는 구판과 완전 동일),
레지스트리는 Domain :class:`~hwpxfiller.domain.dataset_reference.DatasetReference` 를 그대로
주고받는다. **확정 결속 semantic op**(``*_confirmed``·:meth:`DatasetPoolRegistry.resolve_duplicates`)
은 잠금 안에서 지금 상태의 지문(:func:`~hwpxfiller.application.dataset_pool.confirm_basis`)을
대조한 뒤에만 실행한다 — 물리 잠금은 이 어댑터 내부 구현이고 Application 은 잠금을 잡지
않는다(#570 불변식).

**보안 불변식**([[confirm-or-alarm-principle]]): 나라장터 항목은 **ServiceKey 를 담지
않는다**. opts 는 쿼리(기간·건수·페이지)뿐이고, 키는 실행 복원 시점에만 OS 자격증명 저장소
(N1 SecretStore)에서 주입한다(복원 로직은 :func:`~hwpxfiller.data.factory.source_from_pool_item`).

직렬화는 :class:`~hwpxfiller.domain.job.Job` 의 JSON 관례(UTF-8·``ensure_ascii=False``·``indent=2``·
``to_dict``/``from_dict``·가산 필드 하위호환)를 그대로 미러한다.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from .atomic import write_text_atomic
from .write_locks import shared_write_lock
from hwpxfiller.application.dataset_pool import (
    CorruptDatasetEntry,
    StaleConfirmError,
    bound_state,
    confirm_basis,
)
from hwpxfiller.domain.job import load_isolated
from hwpxfiller.domain.dataset_reference import (
    DatasetReference,
    excel_identity,
    reference_identity,
)

# 같은 디렉터리를 보는 인스턴스들의 공유 쓰기 경계는 :mod:`.write_locks` 가 소유한다
# (S9-01 #827 에서 원문 승격 — Preset 레지스트리가 같은 규율을 인라인 재구현하지 않게).


# ------------------------------------------------------------------ persistence codec
def save_reference(path: "str | Path", ref: DatasetReference) -> None:
    """참조 1건을 슬롯 파일에 원자 저장 — 구 ``DatasetPoolItem.save`` 원문(bytes 완전 동일).

    원자 쓰기(RC-01) — 저장 중 실패가 기존 풀 항목 JSON 을 파괴하지 않는다.
    """
    write_text_atomic(path, json.dumps(ref.to_dict(), ensure_ascii=False, indent=2))


def load_reference(path: "str | Path") -> DatasetReference:
    """슬롯 파일 → Domain 참조 — 구 ``DatasetPoolItem.load`` 원문."""
    return DatasetReference.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 레지스트리
class DatasetPoolRegistry:
    """데이터셋 풀 레지스트리 — 디렉터리에 항목당 JSON 1개. 데이터 선택 다이얼로그의 원천.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, GUI 는
    :func:`~hwpxfiller.host.locations.default_dataset_pool_dir`).

    **키 = 파일 stem(불투명 슬롯 키), 이름 = 라벨**(U2 §5.3 판정 C): 이름이 중복 허용
    라벨로 강등돼 파일명·조회 키가 될 수 없다. 항목 조작(:meth:`load`·:meth:`mutate`·
    :meth:`delete`)은 슬롯 키로 하고, 데이터 축의 **중복 판정**은 정체성
    (:func:`~hwpxfiller.domain.dataset_reference.excel_identity` — :meth:`find_identity`)으로 한다.

    **키는 내용에서 파생되지 않는다**(코덱스 4R 근본 조치). 한때 새 슬롯 키가 정체성
    다이제스트였는데, 그것은 #347 이 ``dataset_id`` 를 기각한 근거(*"내용물 교체가 정상
    수명 사건"*)를 **파일명에 다시 심는** 구조였다: 파일 A 로 만든 슬롯을 B 로 재연결하면
    슬롯은 ``hash(identity(A))`` 를 계속 점유하고, 나중에 A 를 다시 고정하려는 사람은
    정체성 조회는 통과하는데(A 를 참조하는 항목이 없다) 키 충돌로 막혀 「없는 것과
    충돌한다」는 말을 듣는다. 수명 보존(슬롯은 산다)과 정체성 추적(내용은 갈린다)이 한
    값에 얹혀 있던 것이 원인이므로, 키는 **내용 무관 불투명 토큰**(:meth:`new_slot_key`)
    으로 발급하고 정체성은 내용에서 **읽을 때** 파생한다(:meth:`find_identity` — 인덱스가
    아니라 질의). 같은 데이터 2건 봉쇄는 키가 아니라 그 질의가 진다.

    구판(이름 slug) 파일은 그 stem 그대로 유효한 슬롯이다 — 키가 불투명해졌으므로
    디스크 마이그레이션은 여전히 없다. 구판이 남긴 다른 이름·같은 정체성 슬롯 2개는
    Application 이 목록 스캔에서 파생해 표면화한다(:meth:`~hwpxfiller.application.
    dataset_pool.DatasetPoolViewModel.duplicates` — 조용한 병합·드롭 금지, 사용자 확정
    후 :meth:`resolve_duplicates` 로만 삭제).
    """

    SUFFIX = ".dataset.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)
        self._write_lock = shared_write_lock(self.directory)

    # ------------------------------------------------------------- 슬롯 키
    def slot_path(self, key: str) -> Path:
        """슬롯 키 → 파일 경로. 웹 페이로드가 흘러드는 자리라 경로 탈출을 loud 거절한다."""
        if (
            not key
            or key != Path(key).name  # 구분자·상위 참조가 들어간 키 = 경로 탈출 시도
            or key in (".", "..")
        ):
            raise ValueError(f"올바른 등록 데이터 키가 아닙니다: {key!r}")
        return self.directory / (key + self.SUFFIX)

    def new_slot_key(self) -> str:
        """빈 슬롯 키 발급 — **내용 무관 불투명 토큰**(위 클래스 주석의 4R 판정).

        내용에서 파생하지 않으므로 슬롯은 참조가 갈려도(다시 연결) 자기 자리를 지키고,
        놓아준 데이터는 다른 슬롯이 자유롭게 다시 고정할 수 있다 — 수명 보존과 정체성
        추적이 서로를 막지 않는다. 파일 존재로 재발급해 같은 디렉터리 안 충돌을 없앤다
        (쓰기 잠금 안에서 부른다 — 발급과 생성 사이의 경합 봉쇄).
        """
        for _ in range(8):
            key = uuid.uuid4().hex[:16]
            if not self.slot_path(key).exists():
                return key
        raise RuntimeError("빈 등록 데이터 슬롯 키를 발급하지 못했습니다.")  # 사실상 불가

    # ------------------------------------------------------------- 쓰기
    def add(self, item: DatasetReference) -> str:
        """새 항목 추가 → 슬롯 키 반환. 같은 정체성이 이미 있으면 loud 거절.

        중복 확인·병합은 호출측(등록 게이트)이 :meth:`find_identity` 로 먼저 판정해
        사용자에게 재진술한다 — 여기 거절은 그 판정을 우회한 호출을 잡는 백스톱이다.
        **거절 근거는 키가 아니라 정체성 질의**다(4R): 키가 내용에서 파생되던 시절엔
        「지금 아무도 안 쓰는 데이터」가 옛 슬롯 키와 부딪혀 거절됐다.
        """
        with self._write_lock:
            ident = reference_identity(item)
            if ident is not None:
                found = self.find_identity_raw(ident)
                if found is not None:
                    raise ValueError(
                        f"같은 데이터(경로·시트)가 이미 '{found[1].name}' 으로 고정돼 "
                        "있습니다."
                    )
            self.directory.mkdir(parents=True, exist_ok=True)
            key = self.new_slot_key()
            save_reference(self.slot_path(key), item)
            return key

    def save_at(self, key: str, item: DatasetReference) -> None:
        """슬롯에 항목을 원자 저장 — 갱신은 :meth:`mutate` 를 쓰고 이건 그 몸통이다."""
        with self._write_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            save_reference(self.slot_path(key), item)

    def write_lock(self) -> "threading.RLock":
        """이 디렉터리의 모든 레지스트리 인스턴스가 공유하는 쓰기 잠금.

        **어댑터 내부 구현이다**(#570): Application 은 이 잠금을 잡지 않고, 확정 결속
        연산(``*_confirmed``·:meth:`resolve_duplicates`)이 잠금 안 대조·실행을 대신 진다.
        이 accessor 는 writer 완결성 계약을 검증하는 테스트를 위한 관측구다.
        """
        return self._write_lock

    def mutate(self, key: str, change) -> DatasetReference:
        """기존 항목을 잠금 안에서 다시 읽고 ``change(item)`` 적용 후 원자 저장한다.

        항목이 잠금 획득 전에 삭제됐으면 :meth:`load` 가 ``FileNotFoundError`` 를 내고 저장은
        수행되지 않는다. 오래된 화면 스냅샷이 삭제된 항목을 되살리는 것을 막는 핵심 경계다.
        (콜백 표면은 Application port 에서 제거됐다(#570) — 이 메서드는 어댑터 내부
        semantic op 들의 공용 몸통이자 테스트의 외부-writer 시뮬레이션 관측구로 남는다.)
        """
        with self._write_lock:
            item = self.load(key)
            change(item)
            self.save_at(key, item)
            return item

    def delete(self, key: str) -> None:
        with self._write_lock:
            p = self.slot_path(key)
            if p.exists():
                p.unlink()

    # ------------------------------------------------------------- 읽기
    def exists(self, key: str) -> bool:
        return self.slot_path(key).exists()

    def load(self, key: str) -> DatasetReference:
        return load_reference(self.slot_path(key))

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX), key=lambda p: p.name)

    def list_entries(
        self,
        status: "str | None" = None,
        *,
        corrupted: "list[tuple[Path, str]] | None" = None,
    ) -> "list[tuple[str, DatasetReference]]":
        """(슬롯 키, 항목) 목록 — 이름순(동명은 키순). 격리 계약은 :meth:`list_items` 와 같다."""
        entries: "list[tuple[str, DatasetReference]]" = load_isolated(
            self._files(),
            lambda p: (Path(p).name[: -len(self.SUFFIX)], load_reference(p)),
            corrupted,
        )
        entries.sort(key=lambda e: (e[1].name, e[0]))
        if status is not None:
            entries = [e for e in entries if e[1].status == status]
        return entries

    def list_items(
        self,
        status: "str | None" = None,
        *,
        corrupted: "list[tuple[Path, str]] | None" = None,
    ) -> "list[DatasetReference]":
        """항목 목록(이름순). ``status`` 지정 시 그 상태만(예: 실행 후보=``STATUS_ACTIVE``).

        **파일 단위 격리(RC-05, :func:`~hwpxfiller.domain.job.load_isolated` 공유):**
        손상된 ``.dataset.json`` 1개(손편집·구버전·잘림)가 목록 전체(→풀 뷰모델·앱 부팅·
        실행 겨눔 피커)를 죽이지 않도록, ``corrupted`` 리스트를 넘긴 호출측에는 파싱 실패를
        파일별로 잡아 ``(경로, 오류 문자열)`` 로 수집해 준다 — 호출측이 시끄럽게 표면화할
        책임을 진다(확인-또는-경보).

        **``corrupted`` 미전달 시에는 읽기 실패가 그대로 raise 된다(C5)** — 한때 미전달
        호출자에게 손상 항목을 무표시로 드롭했는데, 실행 피커·카운트에서 데이터셋이
        조용히 증발하는 정합 결함이었다. 격리를 원하는 표면은 명시적으로 수집 리스트를
        넘기고 손상 건수를 병기하라(풀 화면·피커·홈 KPI 가 그렇게 한다).
        """
        return [item for _key, item in self.list_entries(status, corrupted=corrupted)]

    def list_references(
        self, status: "str | None" = None
    ) -> "tuple[list[tuple[str, DatasetReference]], list[CorruptDatasetEntry]]":
        """한 스캔으로 (정상 항목, 손상 값 객체) — Application port 표면(P2-22 #570).

        손상은 ``(Path, str)`` 좌표가 아니라 값 객체
        (:class:`~hwpxfiller.application.dataset_pool.CorruptDatasetEntry`)로 준다 —
        APPLICATION 소비자(풀 VM·홈 KPI)가 ``Path``·suffix 를 알 필요가 없다. 표시
        문자열(``file_name`` = 종전 ``path.name``)은 불변이다.
        """
        corrupted: "list[tuple[Path, str]]" = []
        entries = self.list_entries(status, corrupted=corrupted)
        return entries, [
            CorruptDatasetEntry(file_name=p.name, error=err) for p, err in corrupted
        ]

    def names(self) -> "list[str]":
        return [it.name for it in self.list_items()]

    # ------------------------------------------------------------- 정체성 조회
    def find_identity_raw(
        self, ident: str
    ) -> "tuple[str, DatasetReference] | None":
        """정체성 문자열로 슬롯 조회 — 손상 파일은 건너뛴다(손상 표면화는 목록 계약 소관)."""
        for key, item in self.list_entries(corrupted=[]):
            if reference_identity(item) == ident:
                return (key, item)
        return None

    def find_identity(
        self, path: "str | Path", sheet: "str | None" = ""
    ) -> "tuple[str, DatasetReference] | None":
        """경로+시트로 슬롯 조회 — 등록 게이트의 중복 판정 입구(같은 데이터인가?)."""
        return self.find_identity_raw(excel_identity(path, sheet))

    # ------------------------------------------------------------- semantic op(#570)
    # Application 은 잠금을 잡지 않는다: 업무 전이 하나 = 잠금 안 원자 실행 하나.
    # 확정 결속판(``*_confirmed``)은 지금 상태의 지문을 잠금 안에서 다시 지어
    # ``expected_basis`` 와 대조한다 — 다르거나 미동봉(None)이면 파괴·갱신 0건 +
    # :class:`~hwpxfiller.application.dataset_pool.StaleConfirmError`(fail-closed).

    def _slot_or_missing(self, key: str) -> DatasetReference:
        """확정 결속 연산의 로드 — 부재·불량 키·손상 전부 「이미 삭제된 항목」으로 접는다."""
        try:
            return self.load(key)
        except (FileNotFoundError, ValueError):
            raise FileNotFoundError(f"등록 데이터를 찾을 수 없습니다: {key}") from None

    def _check_basis(self, expected: "str | None", states: "list[dict[str, str]]") -> None:
        if expected != confirm_basis(states):
            raise StaleConfirmError("확인 근거가 지금 상태와 다릅니다.")

    def archive(self, key: str) -> DatasetReference:
        """보관 전이 — 잠금 안 읽기-수정-쓰기(실행 후보에서만 제외, 참조 보존)."""
        return self.mutate(key, lambda item: item.archive())

    def activate(self, key: str) -> DatasetReference:
        """활성 전이 — :meth:`archive` 의 역방향."""
        return self.mutate(key, lambda item: item.activate())

    def relabel(self, key: str, name: str, *, note: str = "") -> DatasetReference:
        """라벨·메모만 갱신(수명·참조 보존). 빈 ``note`` = 진술 없음(보존 — 조용한 소거 금지)."""

        def _update(current: DatasetReference) -> None:
            current.name = name
            if note:
                current.note = note

        return self.mutate(key, _update)

    def relabel_confirmed(
        self, path: str, sheet: "str | None", name: str, *,
        note: str = "", expected_basis: "str | None",
    ) -> "tuple[str, DatasetReference]":
        """「같은 데이터 재등록 = 라벨 갱신」의 확정 착지 — 정체성 보유 슬롯을 잠금 안 대조 후 갱신.

        확인 모달이 열린 사이 그 슬롯이 삭제됐으면 ``FileNotFoundError`` — 확정을 신규
        등록 승인으로 바꿔 부활시키지 않는다. 이름·비고가 바뀌었으면 지문이 갈려
        :class:`StaleConfirmError` — 사용자가 승인한 것은 1차가 보여준 옛 라벨이다(3R P2-2).
        """
        with self._write_lock:
            same = self.find_identity(path, sheet or "")
            if same is None:
                raise FileNotFoundError(f"등록 데이터를 찾을 수 없습니다: {name}")
            key, existing = same
            self._check_basis(expected_basis, [bound_state(key, existing)])
            return key, self.relabel(key, name, note=note)

    def _relink_locked(
        self, key: str, path: str, *, sheet: "str | None", note: str, name: str,
    ) -> DatasetReference:
        """다시 연결의 공용 몸통 — 정체성 검사와 변이가 **한 잠금 안**이다(코덱스 1R P2).

        잠금 밖 선검사는 서로 다른 슬롯 둘을 같은 경로+시트로 동시 재연결할 때 둘 다
        통과시키고 변이만 직렬화돼 **같은 정체성의 슬롯 2개**가 남는다 — 레지스트리
        불변식(같은 데이터 = 슬롯 1개)이 조용히 깨진다. :meth:`add` 가 자기 잠금 안에서
        검사하는 것과 같은 규율이다.

        **kind 정규화(r4)**: opts 만 갈아끼우고 kind 를 방치하면 nara/pipeline 항목이
        ``kind="nara" + opts={"path": …}`` 하이브리드로 손상된다 — 엑셀 참조 확정은
        kind 도 excel 로 착지한다(cross-kind 전이 재진술은
        :func:`~hwpxfiller.application.dataset_pool.kind_transition_clause`).
        """
        opts: "dict[str, object]" = {"path": path}
        if sheet:
            opts["sheet"] = sheet

        def _update(current: DatasetReference) -> None:
            # 호출자가 본 행은 확인 모달 전 스냅샷일 수 있다. 현재 디스크 항목을 잠금 안에서
            # 다시 읽어 참조 필드만 바꿔야 동시 보관 상태·메모를 되돌리거나 삭제를 부활시키지 않는다.
            current.kind = "excel"  # kind/opts 정합 — 하이브리드 손상 항목 금지(r4)
            current.opts = opts
            if note:
                current.note = note
            if name:  # 라벨은 정체성이 아니라(§5.3 C) 같은 확정에 함께 갱신해도 안전하다
                current.name = name

        with self._write_lock:
            taken = self.find_identity(path, sheet or "")
            if taken is not None and taken[0] != key:
                raise ValueError(
                    f"그 파일·시트는 이미 '{taken[1].name}' 으로 고정돼 있습니다. "
                    "그 항목을 쓰거나 먼저 정리하세요."
                )
            return self.mutate(key, _update)

    def relink_excel(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
    ) -> DatasetReference:
        """다시 연결 — 같은 슬롯의 참조(kind+opts)만 갱신한다(수명 보존, C3).

        새 항목으로 통째 교체하면 보관 상태가 조용히 active 로 복귀해 실행 후보에
        재등장하고 note·created_at 이 소실된다. 내용물 교체가 이 개체의 **정상 수명
        사건**이라(월별 파일 갈아끼우기) 정체성이 바뀌어도 슬롯은 산다 — §5.3 이 id 축을
        기각한 바로 그 근거다. 새 참조가 **다른 슬롯의 정체성**과 겹치면 loud 거절.
        """
        return self._relink_locked(key, path, sheet=sheet, note=note, name=name)

    def relink_confirmed(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
        expected_basis: "str | None",
    ) -> DatasetReference:
        """확정 결속 다시 연결 — 1차가 보여준 슬롯 상태의 지문 대조 후 :meth:`relink_excel`.

        모달이 열린 사이 다른 호출이 같은 슬롯을 재연결·개명하면 정체성 검사는 통과하므로,
        결속이 없으면 사용자가 본 적 없는 더 새로운 참조를 덮어쓴다(코덱스 2R P2).
        대조부터 변이까지가 한 쓰기 잠금 안이라 그 사이에 다른 writer 가 끼지 못한다.
        """
        with self._write_lock:
            current = self._slot_or_missing(key)
            self._check_basis(expected_basis, [bound_state(key, current)])
            return self._relink_locked(key, path, sheet=sheet, note=note, name=name)

    def delete_confirmed(self, key: str, *, expected_basis: "str | None") -> DatasetReference:
        """확정 결속 삭제 — 지문 대조 후 삭제, 지워진 항목을 반환한다(결과 문구 소재).

        파괴 앞에서 「무엇을 지우는지」가 승인 시점과 갈리면 그게 곧 조용한 파괴다(3R).
        """
        with self._write_lock:
            item = self._slot_or_missing(key)
            self._check_basis(expected_basis, [bound_state(key, item)])
            self.delete(key)
            return item

    def resolve_duplicates(
        self, keep: str, *, expected_basis: "str | None"
    ) -> "tuple[str, int]":
        """같은 정체성 그룹에서 ``keep`` 만 남기고 삭제 — ``(남은 이름, 삭제 건수)``.

        잠금 안에서 그룹을 **다시** 유도한다(같은 정체성 = Domain
        :func:`~hwpxfiller.domain.dataset_reference.reference_identity`): 확인 사이 멤버가
        늘거나(1R P1) 이름·비고가 바뀌면(2R P1) 지문이 갈려 아무것도 지우지 않는다.
        ``keep`` 이 사라졌거나 그룹이 해소됐으면 ``FileNotFoundError`` — 낡은 확정을
        실행하지 않는다.
        """
        with self._write_lock:
            entries = self.list_entries(corrupted=[])
            ident_by_key = {k: reference_identity(it) for k, it in entries}
            target = ident_by_key.get(keep)
            group = [
                (k, it) for k, it in entries
                if target is not None and ident_by_key[k] == target
            ]
            if target is None or len(group) < 2:
                raise FileNotFoundError("병합할 중복 등록이 더는 없습니다.")
            self._check_basis(
                expected_basis, [bound_state(k, it) for k, it in group]
            )
            kept = dict(group)[keep]
            removed = 0
            for k, _it in group:
                if k != keep:
                    self.delete(k)
                    removed += 1
            return kept.name, removed
