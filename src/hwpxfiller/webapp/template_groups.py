"""템플릿 라이브러리 그룹 모델 — 매체별 그룹 지정·접힘의 단일 소유자(R-info 2부 결정 2·3·8).

작업 목록의 그룹+접힘 모델을 **그대로 재사용**한다("배울 규칙은 그룹 하나"). 단 저장 기제는
작업과 다르다: 작업 그룹은 각 ``.job.json`` 안에 살지만(레지스트리가 소유), 템플릿은 생 파일
(``.hwpx``/``.txt``)이라 메타를 실을 자리가 없어 **앱 설정**(``settings.py``, webview 저장소
금지 #74 전례)이 매체별로 ``{식별키: 그룹명}`` 을 이고 있는다.

이 모델이 한 매체(hwpx | txt)의 그룹 상태(지정 + 접힘)를 **함께** 소유한다 — 작업에서
레지스트리(지정)와 화면(접힘)이 나눠 지던 두 몫을 여기 한 곳으로 모은다(템플릿엔 지정을
품을 파일 메타가 없어 어차피 별도 스토어가 필요하고, 관리 화면·에디터 1단계 피커 두 소비자가
같은 규칙을 재사용하려면 단일 출처가 이롭다).

**식별키**(결정 8) = 라이브러리 루트 상대경로(POSIX). 루트 직속 파일은 곧 파일명이고, 관용된
하위폴더 파일(결정 5)은 ``하위폴더/이름.hwpx``. Explorer 개명·이동으로 키가 살아있는 파일과
안 맞으면 그 지정은 **고아**가 되어 조용히 소멸하지 않고 「그룹 없음」으로 복귀한다 —
:meth:`build_sections` 가 live 행만 묶으므로 그루핑에서 자동으로 빠지고, :meth:`reconcile` 이
스캔 뒤 유령 항목을 걷어 설정을 깔끔히 한다(작업 퇴화-코퍼스 불변식 동형).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import settings

_BAD_NAME = re.compile(r'[\\/:*?"<>|]')


def validate_template_name(raw_name: str) -> str:
    """새 템플릿 이름 검증 — 확장자·경로 문자를 배제한 순수 이름만. 실패는 loud raise.

    저작 경로가 둘(관리 화면 「새 TXT」·빠른 기안 「템플릿으로 저장」)이라 여기 단일 출처로
    둔다 — 규칙이 갈라지면 한쪽에서 만들 수 없는 이름이 다른 쪽에선 만들어져 라이브러리에
    루트 밖 경로나 이중 확장자가 들어앉는다(:func:`rel_key` 를 여기 올린 것과 같은 이유).
    """
    name = raw_name.strip()
    if not name:
        raise ValueError("템플릿 이름을 입력해 주세요.")
    if name.lower().endswith(".txt") or _BAD_NAME.search(name) or name in (".", ".."):
        raise ValueError("확장자와 경로 문자를 제외한 이름만 입력해 주세요.")
    return name


def rel_key(path: "str | Path", root: "Path | None") -> str:
    """루트 상대경로(POSIX)를 그룹 식별키로(결정 8). 루트 직속 파일은 곧 파일명, 관용된
    하위폴더 파일은 ``하위폴더/이름``. 루트 밖(방어)·루트 미지정이면 파일명으로 폴백.

    관리 화면·에디터 1단계 피커가 **같은 키 규칙**으로 같은 그룹 지정을 소비하는 단일 출처
    (한쪽만 basename, 다른쪽 상대경로면 같은 파일이 두 키로 갈라져 그룹이 어긋난다)."""
    p = Path(path)
    if root is not None:
        try:
            return p.relative_to(root).as_posix()
        except ValueError:
            pass
    return p.name


class TemplateGroupModel:
    """한 매체의 템플릿 그룹 지정 + 접힘 상태. 설정에서 로드하고 변경 시 즉시 영속한다.

    ``settings_module`` 은 테스트 주입점(기본 = 실 :mod:`~hwpxfiller.webapp.settings`) — 실
    모듈은 ``HWPXFILLER_HOME`` 을 존중하므로 헤드리스 테스트는 임시 홈만 가리키면 된다.
    """

    def __init__(self, media: str, *, settings_module=settings):
        settings_module._check_media(media)  # 오타 매체는 loud (confirm-or-alarm)
        self.media = media
        self._settings = settings_module
        self._assign: "dict[str, str]" = dict(
            settings_module.load_template_group_map(media)
        )
        self._collapsed: "set[str]" = set(
            settings_module.load_template_collapsed_groups(media)
        )

    # -------------------------------------------------------------- 지정
    def group_of(self, key: str) -> str:
        """식별키의 그룹(미지정=``""``=「그룹 없음」)."""
        return self._assign.get(key, "")

    def set_group(self, key: str, group: str) -> None:
        """그룹 지정/해제 — 소속이 곧 존재(빈 그룹명은 스토어에서 부재, 「그룹 없음」과 동치)."""
        group = group.strip()
        new = dict(self._assign)
        if group:
            new[key] = group
        else:
            new.pop(key, None)
        self._persist(new, self._collapsed)

    def existing_groups(self, keys: "list[str] | None" = None) -> "list[str]":
        """소속이 있는(=live 멤버가 있는) 그룹 이름들, 이름순 — 이동 다이얼로그 후보.

        ``keys`` 를 주면 그 살아있는 키의 멤버만 세어 고아 지정은 후보에서 빠진다(결정 8).
        미전달이면 지정 전체를 본다(reconcile 직후엔 동치)."""
        if keys is None:
            values = self._assign.values()
        else:
            live = set(keys)
            values = [g for k, g in self._assign.items() if k in live]
        return sorted({g for g in values if g})

    def rename_group(self, old: str, new: str) -> int:
        """그룹 일괄 개명 — 소속 수 반환. 새 이름이 기존 그룹이면 결과는 **병합**이다(병합 여부의
        확인 재진술은 화면 게이트 소관 — 모델은 기계적 remap만; JobRegistry.rename_group 동형).

        접힘 승계: 순수 개명(새 이름이 없던 그룹)이면 옛 접힘을 새 이름으로 옮긴다. 병합(새
        이름이 이미 존재)이면 **대상 그룹의 접힘 상태를 존중**하고 옛 이름만 접힘 집합에서 걷는다
        (screen_job._do_rename_group 동형 — 여기선 접힘도 이 모델이 소유해 한 곳에서 처리)."""
        old, new = old.strip(), new.strip()
        if not old:
            raise ValueError("대상 그룹 이름이 비어 있습니다")
        if not new:
            raise ValueError("그룹 이름이 비어 있습니다")
        if old == new:
            return sum(1 for g in self._assign.values() if g == old)
        new_preexisting = any(g == new for g in self._assign.values())
        new_assign = dict(self._assign)
        count = 0
        for key, g in self._assign.items():
            if g == old:
                new_assign[key] = new
                count += 1
        new_collapsed = set(self._collapsed)
        if old in new_collapsed:
            new_collapsed.discard(old)
            if not new_preexisting:
                new_collapsed.add(new)  # 순수 개명 = 같은 그룹, 접힘 유지
        # 지정·접힘을 한 원자 저장으로(F5) — 반쪽 상태(개명 멤버 + 옛 접힘) 방지.
        self._persist(new_assign, new_collapsed)
        return count

    def disband_group(self, old: str) -> int:
        """그룹 해산(결정 43·2부 결정 2) — 소속은 「그룹 없음」으로(지정 삭제). 소속 수 반환."""
        old = old.strip()
        if not old:
            # ""(그룹 없음)은 그룹이 아니라 부재 — 일괄 대상으로 받으면 무그룹 전원이 조용히
            # 움직인다(호출 버그의 파급 상한을 loud 로 자른다; JobRegistry 동형).
            raise ValueError("대상 그룹 이름이 비어 있습니다")
        new_assign = {k: g for k, g in self._assign.items() if g != old}
        count = len(self._assign) - len(new_assign)
        new_collapsed = set(self._collapsed)
        new_collapsed.discard(old)
        self._persist(new_assign, new_collapsed)  # 지정·접힘 원자 저장(F5)
        return count

    def reconcile(self, live_keys: "list[str]") -> None:
        """스캔 뒤 유령 지정(파일이 사라진 키)을 걷어 설정을 깔끔히 한다 — 변경 시에만 저장.

        고아→「그룹 없음」 복귀는 :meth:`build_sections` 가 live 행만 묶어 이미 성립하고,
        이 정리는 설정 파일이 삭제된 파일의 지정으로 무한히 부풀지 않게 하는 위생일 뿐이다.
        루트 전수 스캔의 부재 = 진짜 삭제(로컬 디렉터리)라 일시 부재 오판 위험은 무시할 수준."""
        live = set(live_keys)
        new_assign = {k: g for k, g in self._assign.items() if k in live}
        if len(new_assign) != len(self._assign):  # 유령 있었음 → 변경 시에만 저장
            self._persist(new_assign, self._collapsed)

    # -------------------------------------------------------------- 접힘
    def is_collapsed(self, group: str) -> bool:
        return group in self._collapsed

    def toggle_collapse(self, group: str) -> None:
        """그룹 접힘/펼침 토글 — 마지막 상태 영속(결정 6-①). ``""``=「그룹 없음」 구획."""
        new_collapsed = set(self._collapsed)
        new_collapsed.symmetric_difference_update({group})
        self._persist(self._assign, new_collapsed)

    # ---------------------------------------------------------- 구획 뷰
    def build_sections(self, items: "list", key_of) -> "tuple[list[dict], bool]":
        """행 목록 → ``(sections, flat)`` (screen_job._job_sections 동형).

        - 그룹 배열 = 이름순 안정(결정 4), 「그룹 없음」(``group==""``)은 마지막.
        - ``flat=True`` = 명명 그룹 0개 **퇴화 불변식**: 헤더·들여쓰기 없는 평면(현행 모습).
          이때도 sections 는 무그룹 1구획으로 돌아가 표면이 분기 없이 그린다.
        - ``collapsed`` 는 영속 접힘 집합의 사영(``flat`` 이면 항상 펼침).
        각 section: ``{"group", "collapsed", "count", "items"}`` — items 는 넘어온 행 그대로.
        """
        grouped: "dict[str, list]" = {}
        for it in items:
            grouped.setdefault(self.group_of(key_of(it)), []).append(it)
        named = sorted(g for g in grouped if g)
        flat = not named
        order = named + ([""] if "" in grouped else [])
        sections = [
            {
                "group": g,
                "collapsed": (not flat) and g in self._collapsed,
                "count": len(grouped[g]),
                "items": grouped[g],
            }
            for g in order
        ]
        return sections, flat

    # ----------------------------------------------------------- 영속
    def _persist(self, new_assign: "dict[str, str]", new_collapsed: "set[str]") -> None:
        """지정+접힘을 원자 저장한 **뒤에만** 라이브 상태를 교체한다(#136 리뷰 F4·F5).

        F4(영속-후-교체): 저장이 PermissionError 로 최종 실패하면 ``self._assign``/
        ``self._collapsed`` 는 이전 값 그대로 남아 ``group_of`` 가 실패한 변경을 반환하거나
        다음 저장이 실패분을 뒤늦게 영속하는 일이 없다. F5(원자성): 지정·접힘을 한 번의
        변이로 함께 써 반쪽 상태를 막는다. 저장이 던지면 인메모리 미변경(호출측이 재진술)."""
        self._settings.save_template_group_state(
            self.media, new_assign, sorted(new_collapsed)
        )
        self._assign = new_assign
        self._collapsed = set(new_collapsed)
