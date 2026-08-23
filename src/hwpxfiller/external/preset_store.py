"""Preset 영속 경계 — 홈 하위 독립 디렉터리에 항목당 JSON 1개(S9-01 · #827).

Preset 저장소는 Work 저장소(:mod:`hwpxfiller.external.work_configuration_store`)·Template
authority 저장소(:mod:`hwpxfiller.external.work_template_store` 등)와 **파일·권위 모두
분리**된다(#821 D2). ServiceKey·레코드·Template 구조를 담지 않는다 — 파일에 들어가는 것은
:func:`~hwpxfiller.domain.preset.encode_preset` 이 내는 6개 필드뿐이고, 그 밖의 것이 섞이면
읽기에서 loud 거절된다.

**Work-bound lease + CAS 를 쓰지 않는다**(#821 D2): 경합 프로필이 다르다. Work configuration
은 실행 파이프라인이 배후에서 건드리는 공유 상태라 확정 결속이 필요하지만, Preset 은 단일
사용자의 명시 조작(저장·삭제)뿐이라 :class:`~hwpxfiller.external.dataset_store.DatasetPoolRegistry`
급 얇은 레지스트리로 충분하다. 쓰기 경계는 :func:`~hwpxfiller.external.write_locks.shared_write_lock`
하나를 공유하고 저장은 전부 원자 쓰기다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .atomic import write_text_atomic
from .write_locks import shared_write_lock
from hwpxfiller.domain.job import load_isolated
from hwpxfiller.domain.preset import (
    CorruptPresetEntry,
    SelectionPreset,
    decode_preset,
    encode_preset,
)


# ------------------------------------------------------------------ persistence codec
def save_preset(path: "str | Path", preset: SelectionPreset) -> None:
    """Preset 1건을 슬롯 파일에 원자 저장 — 저장 중 실패가 기존 파일을 파괴하지 않는다."""
    write_text_atomic(
        path, json.dumps(encode_preset(preset), ensure_ascii=False, indent=2)
    )


def load_preset(path: "str | Path") -> SelectionPreset:
    """슬롯 파일 → Domain 값. 손상·미상 버전·미지 필드는 codec 이 loud 거절한다."""
    return decode_preset(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 레지스트리
class PresetRegistry:
    """Preset 레지스트리 — 디렉터리에 항목당 JSON 1개.

    위치-불가지: 생성자가 디렉터리를 받는다(테스트는 ``tmp_path``, 앱은
    :func:`~hwpxfiller.host.locations.default_preset_dir`).

    **키 = 파일 stem(불투명 슬롯 키), 이름 = 사용자 라벨**: 이름은 사용자가 고르고 개명할 수
    있으므로 파일명이 될 수 없다(개명이 파일 이동이 되면 개명 도중 실패가 항목을 잃는다).
    항목 조작은 슬롯 키로 하고, **이름 유일성**은 이 저장소가 스캔으로 집행한다 — 같은 이름
    두 개는 사용자가 「어느 것을 적용했는지」 말할 수 없게 만든다.
    """

    SUFFIX = ".preset.json"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)
        self._write_lock = shared_write_lock(self.directory)

    # ------------------------------------------------------------- 슬롯 키
    def slot_path(self, key: str) -> Path:
        """슬롯 키 → 파일 경로. 웹 페이로드가 흘러들 자리라 경로 탈출을 loud 거절한다."""
        if (
            not key
            or key != Path(key).name  # 구분자·상위 참조가 들어간 키 = 경로 탈출 시도
            or key in (".", "..")
        ):
            raise ValueError(f"올바른 프리셋 키가 아닙니다: {key!r}")
        return self.directory / (key + self.SUFFIX)

    def new_slot_key(self) -> str:
        """빈 슬롯 키 발급 — 내용 무관 불투명 토큰(dataset 슬롯 키 규율 동형).

        파일 존재로 재발급해 같은 디렉터리 안 충돌을 없앤다(쓰기 잠금 안에서 부른다 —
        발급과 생성 사이의 경합 봉쇄).
        """
        for _ in range(8):
            key = uuid.uuid4().hex[:16]
            if not self.slot_path(key).exists():
                return key
        raise RuntimeError("빈 프리셋 슬롯 키를 발급하지 못했습니다.")  # 사실상 불가

    # ------------------------------------------------------------- 쓰기
    def add(self, preset: SelectionPreset) -> str:
        """새 Preset 추가 → 슬롯 키 반환. 같은 이름이 이미 있으면 loud 거절.

        확인 왕복(덮어쓸지 물어보기)은 command 층 소관이고 여기 거절은 그것을 우회한
        호출을 잡는 **백스톱**이다 — 조용한 덮기는 사용자가 승인한 적 없는 파괴다.
        """
        with self._write_lock:
            if self.find_name(preset.name) is not None:
                raise ValueError(f"같은 이름의 프리셋이 이미 있습니다: {preset.name}")
            self.directory.mkdir(parents=True, exist_ok=True)
            key = self.new_slot_key()
            save_preset(self.slot_path(key), preset)
            return key

    def save_at(self, key: str, preset: SelectionPreset) -> None:
        """슬롯에 Preset 을 원자 저장(덮어쓰기 확정 경로의 몸통).

        **다른** 슬롯이 그 이름을 이미 들고 있으면 거절한다 — 확정된 덮어쓰기가 옆 항목의
        이름을 침범해 유일성 불변식을 조용히 깨뜨리지 못하게 하는 경계다.
        """
        with self._write_lock:
            path = self.slot_path(key)
            taken = self.find_name(preset.name)
            if taken is not None and taken[0] != key:
                raise ValueError(f"같은 이름의 프리셋이 이미 있습니다: {preset.name}")
            self.directory.mkdir(parents=True, exist_ok=True)
            save_preset(path, preset)

    def delete(self, key: str) -> None:
        with self._write_lock:
            p = self.slot_path(key)
            if p.exists():
                p.unlink()

    # ------------------------------------------------------------- 읽기
    def exists(self, key: str) -> bool:
        return self.slot_path(key).exists()

    def load(self, key: str) -> SelectionPreset:
        return load_preset(self.slot_path(key))

    def _files(self) -> "list[Path]":
        if not self.directory.exists():
            return []
        return sorted(self.directory.glob("*" + self.SUFFIX), key=lambda p: p.name)

    def list_entries(
        self, *, corrupted: "list[tuple[Path, str]] | None" = None
    ) -> "list[tuple[str, SelectionPreset]]":
        """(슬롯 키, Preset) 목록 — 이름순(이름은 유일하지만 안정 정렬로 키를 tiebreak).

        **파일 단위 격리**(:func:`~hwpxfiller.domain.job.load_isolated` 공유): ``corrupted``
        리스트를 넘긴 호출측에는 파싱 실패를 파일별로 잡아 ``(경로, 오류 문자열)`` 로
        수집해 준다. **미전달(None) 이면 읽기 실패가 그대로 raise 된다(C5)** — 수집처가
        없는데 격리하면 손상 항목이 무표시로 증발한다(조용한 드롭 금지).
        """
        entries: "list[tuple[str, SelectionPreset]]" = load_isolated(
            self._files(),
            lambda p: (Path(p).name[: -len(self.SUFFIX)], load_preset(p)),
            corrupted,
        )
        entries.sort(key=lambda e: (e[1].name, e[0]))
        return entries

    def list_presets(
        self,
    ) -> "tuple[list[tuple[str, SelectionPreset]], list[CorruptPresetEntry]]":
        """한 스캔으로 (정상 항목, 손상 값 객체) — 손상 항목 표면화의 원천.

        손상을 숨기지 않는다: 목록에서 사라지는 대신 값 객체로 함께 나와, 소비 표면이
        비활성 + 사유 병기로 재진술한다(확인-또는-경보).
        """
        corrupted: "list[tuple[Path, str]]" = []
        entries = self.list_entries(corrupted=corrupted)
        return entries, [
            CorruptPresetEntry(file_name=p.name, error=err) for p, err in corrupted
        ]

    def find_name(self, name: str) -> "tuple[str, SelectionPreset] | None":
        """이름으로 슬롯 조회 — 손상 파일은 건너뛴다(손상 표면화는 목록 계약 소관)."""
        for key, preset in self.list_entries(corrupted=[]):
            if preset.name == name:
                return (key, preset)
        return None
