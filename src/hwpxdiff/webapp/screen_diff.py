"""diff 화면 컨트롤러 — 비교 엔진(:mod:`hwpxdiff.diff`)을 소유·위임하는 얇은 어댑터.

filler webapp 의 컨트롤러 패턴을 그대로 따른다(webview 비의존 → 헤드리스 테스트 가능).
브리지가 화면 id → 컨트롤러로 라우팅하고, Python→웹은 관측 푸시(``push('diff', snapshot)``)로
민다. 푸시 sink 는 생성자 주입 — 앱에선 ``window.evaluate_js``, 테스트에선 리스트 수집.

**엔진 무변경 제약(RC-17)**: ``diff.py`` 의 결과 dataclass 를 그대로 직렬화한다. 색/라벨/
낱말 성형(``coalesce_word_ops``)·그룹화(``change_groups``)는 전부 core 소유값을 snapshot 에
실어 보내고, 웹(diff.js)은 표현만 만든다 — VM 로직 재구현 금지. Qt ``_render_doc_html`` 의
HTML 문자열 빌드는 포팅하지 않는다(웹은 구조화 데이터에서 DOM 을 짓는다).

**#6 비동기**: Qt 는 diff 계산을 UI 스레드에서 동기 실행해 대형 문서에서 창이 동결됐다. 웹은
``compare()`` 가 워커 스레드로 ``diff_files`` 를 돌리고 완료 시 push 한다 — 세대 토큰으로 낡은
결과를 폐기한다. 엔진은 단일 불투명 호출이라 중도 취소·진행% 는 없다(무한 스피너만).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable

from ..diff import (
    KIND_COLORS,
    KIND_LABELS,
    KIND_TINTS,
    NO_CHANGES_MESSAGE,
    WordOp,
    coalesce_word_ops,
    diff_files,
    row_group_key,
)

# 푸시 sink: (화면 id, 스냅샷 dict) → None. 앱=evaluate_js, 테스트=수집.
PushSink = Callable[[str, dict], None]

_RECENT_MAX = 5


def default_recent_path() -> Path:
    """최근 비교 쌍 저장 위치 — 사용자 홈(``~/.hwpxdiff/recent.json``).

    Qt ``QSettings`` 의 Qt-free 대체. ``HWPXDIFF_HOME`` 으로 재지정(테스트·이식성).
    """
    root = os.environ.get("HWPXDIFF_HOME") or (Path.home() / ".hwpxdiff")
    return Path(root) / "recent.json"


class DiffController:
    """판본 2개 → 변경 그룹 리스트 + 전문 신구대비표. 읽기 도구(단일 화면)."""

    name = "diff"

    def __init__(self, push: PushSink, recent_path: "Path | None" = None) -> None:
        self._push_sink = push
        self._old = ""       # 구판 경로
        self._new = ""       # 신판 경로
        self._result = None  # DiffResult | None
        self._status = "idle"  # idle/running/done/error
        self._error = ""
        self._gen = 0        # 세대 토큰 — 최신 compare 요청만 유효
        self._recent_path = recent_path or default_recent_path()

    # -------------------------------------------------- 관측 푸시(Python→웹)
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # -------------------------------------------------- 스냅샷(결과 → 웹 계약)
    def _rows_payload(self, rows) -> list:
        """전문 대조 행을 직렬화 — Qt ``_render_doc_html`` 의 데이터판.

        낱말 성형은 core(``coalesce_word_ops``)가 소유하고, 웹은 op→del/ins 매핑만 한다.
        """
        out: list = []
        for r in rows:
            item = {
                "kind": r.kind,
                "unit": r.unit,
                "label": r.label,
                "group_key": row_group_key(r.label),  # 라벨→그룹 헤더 역산도 core 소유
                "old_text": r.old_text,
                "new_text": r.new_text,
                "seq": r.seq,
            }
            if r.kind in ("changed", "renumber"):
                ops = coalesce_word_ops(r.word_ops) or [
                    WordOp("replace", old=r.old_text, new=r.new_text)
                ]
                item["ops"] = [w.to_dict() for w in ops]
            out.append(item)
        return out

    def snapshot(self) -> dict:
        base = {
            "status": self._status,
            "error": self._error,
            "old_label": Path(self._old).name if self._old else "",
            "new_label": Path(self._new).name if self._new else "",
            "can_compare": bool(self._old and self._new),
            "recent": self._recent_payload(),
            # 색/라벨/틴트는 core 단일 출처를 그대로 전달(CSS 하드코딩 금지 — RC-17·#3).
            "kind_labels": KIND_LABELS,
            "kind_colors": KIND_COLORS,
            "kind_tints": KIND_TINTS,
        }
        if self._result is None:
            base["has_result"] = False
            return base
        s = self._result.summary
        base.update(
            {
                "has_result": True,
                "summary": {k: s.get(k, 0) for k in ("added", "removed", "changed", "renumber")},
                "change_count": len(self._result.changes),
                "no_changes_message": NO_CHANGES_MESSAGE,  # core 단일 출처
                "groups": [
                    {"kind": g.kind, "label": g.label, "detail": g.detail, "seq": g.seqs[0]}
                    for g in self._result.change_groups
                ],
                "rows": self._rows_payload(self._result.rows),
            }
        )
        return base

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태."""
        return self.snapshot()

    # -------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅 후 푸시. 미지 액션은 시끄럽게 거부."""
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 diff 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_select_recent(self, p: dict) -> None:
        """최근 쌍 선택 → 구/신 경로를 겨눈다(비교는 사용자가 별도로 누른다)."""
        self._old = str(p["old"])
        self._new = str(p["new"])
        self._invalidate()

    def _do_reset(self, p: dict) -> None:
        """판본·결과 비움(새 비교 준비)."""
        self._old = self._new = ""
        self._invalidate()

    def _invalidate(self) -> None:
        """결과 무효화 — 경로가 바뀌면 이전 결과는 더 이상 진실이 아니다."""
        self._result = None
        self._status = "idle"
        self._error = ""

    # ------------------------------------------------ 네이티브 보조(브리지가 다이얼로그 담당)
    def load_old_path(self, path: str) -> None:
        """구판 경로 지정(결과 무효화 후 푸시). 브리지가 다이얼로그 뒤 호출."""
        self._old = path
        self._invalidate()
        self._push()

    def load_new_path(self, path: str) -> None:
        """신판 경로 지정(결과 무효화 후 푸시). 브리지가 다이얼로그 뒤 호출."""
        self._new = path
        self._invalidate()
        self._push()

    # ------------------------------------------------ 비교(#6 워커 + 세대 토큰)
    def compare(self) -> dict:
        """비동기 비교 시작 — 워커 스레드로 ``diff_files`` 실행, 완료 시 push.

        즉시 ``running`` 상태를 push 하고 반환한다. 사용자가 판본을 바꿔 재비교하면
        세대 토큰이 낡은 워커 결과를 폐기한다(stale 화면 방지).
        """
        if not (self._old and self._new):
            return {"ok": False, "error": "구판·신판을 모두 선택하세요."}
        self._gen += 1
        gen = self._gen
        self._status = "running"
        self._error = ""
        self._push()  # JS: 무한 스피너 + 리스트/표 비움
        threading.Thread(
            target=self._run_compare, args=(gen,), daemon=True, name="hwpxdiff-compare"
        ).start()
        return {"ok": True, "status": "running"}

    def compare_sync(self) -> dict:
        """워커를 우회한 동기 비교 — 테스트·헤드리스 스모크(--selfcheck)용."""
        if not (self._old and self._new):
            return {"ok": False, "error": "구판·신판을 모두 선택하세요."}
        self._gen += 1
        self._run_compare(self._gen)
        return {"ok": True, "status": self._status}

    def _run_compare(self, gen: int) -> None:
        """워커 본체 — 엔진 무변경 동기 호출. 세대가 밀렸으면 결과를 버린다."""
        try:
            result = diff_files(self._old, self._new)
        except Exception as exc:  # noqa: BLE001  (엔진 실패를 사용자에 시끄럽게)
            if gen == self._gen:
                self._result = None
                self._status = "error"
                self._error = str(exc)
                self._push()
            return
        if gen != self._gen:
            return  # 사용자가 새 비교 시작 → 낡은 결과 폐기
        self._result = result
        self._status = "done"
        self._error = ""
        self._remember(self._old, self._new)
        self._push()

    # ------------------------------------------------ 최근 비교(Qt-free JSON 저장)
    def _recent_payload(self) -> list:
        out = []
        for pair in self._load_recent():
            out.append(
                {
                    "old": pair["old"],
                    "new": pair["new"],
                    "old_label": Path(pair["old"]).name,
                    "new_label": Path(pair["new"]).name,
                }
            )
        return out

    def _load_recent(self) -> list:
        try:
            data = json.loads(self._recent_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        # 방어적 정규화 — old/new 키를 가진 dict 만.
        return [p for p in data if isinstance(p, dict) and "old" in p and "new" in p][:_RECENT_MAX]

    def _remember(self, old: str, new: str) -> None:
        """성공한 비교 쌍을 최근 목록 맨 앞에(중복 제거·최대 5). 저장 실패는 조용히 무시.

        최근 목록은 편의 자산이라 저장 실패가 비교 결과를 막아선 안 된다(그 실패는 기능
        저하일 뿐 데이터 위험이 아니다) — confirm-or-alarm 의 '알림' 대상이 아니다.
        """
        pairs = [p for p in self._load_recent() if not (p["old"] == old and p["new"] == new)]
        pairs.insert(0, {"old": old, "new": new})
        pairs = pairs[:_RECENT_MAX]
        try:
            self._recent_path.parent.mkdir(parents=True, exist_ok=True)
            self._recent_path.write_text(
                json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
