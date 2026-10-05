"""저작 작업대의 「데이터로 필드 찾기」(#1156) 액션 — ``propose_*`` 다섯과 탭 스냅숏의 ``proposal``.

저작 컨트롤러가 세션 확인(revision 거절)·미리보기를 넘겨 주고, 이 패널은 제안 상태를 세션에 둔다.
「필드로 만들기」는 새 적용 경로가 아니다 — 묶음을 ``create_field``(여럿이면 ``create_fields``) 명령으로 지어
컨트롤러의 기존 미리보기에 넣고, 그 결과(와 명령)를 돌려준다. 표면은 그것을 다른 명령과 같은 미리보기→적용
사슬로 확정하므로 편집기 실행 취소 한 단위·보존 검사·``links_existing`` 이 손으로 만든 필드와 같다.
연결 초안·시험 값은 그 확정이 문서에 닿을 때 세션이 정산한다(:class:`AuthoringSession`).
"""

from __future__ import annotations

from collections.abc import Callable

from ..application.field_proposal import (
    STATE_FAILED,
    STATE_NEEDS_DATA,
    FieldProposalState,
    LoadedRows,
    ProposalDataPort,
    all_command,
    drafts,
    empty_view,
    group_command,
    normalize_rows,
    pick_column,
    seed_mappings,
    SEEDABLE_APPLY,
    proposal_view,
    toast_many,
    toast_one,
)
from ..application.template_authoring_session import AuthoringSession, content_digest
from ..domain.dataset_reference import STATUS_ACTIVE
from ..domain.job import JOB_MAPPING_AUTHORITY
from ..external.hwpx_field_proposal import read_hwpx, read_txt, spot_location
from ..viewmodel.run_state import resolve_pool_source
from .screens import load_pool_into

_NO_GROUP = "제안을 찾을 수 없습니다. 제안 목록에서 다시 고르세요."


def pool_source_of(data) -> tuple[str, str | None] | None:
    """「문서 작업」이 지금 쓰는 등록 데이터(풀 키·시트) — 풀이 아닌 마운트(파일 직접 열기)는 없음이다."""
    return (data.pool_key, data.sheet or None) if data.pool_key else None


class PoolProposalData:
    """:class:`ProposalDataPort` 의 실제 구현 — 데이터 풀 레지스트리와 「문서 작업」이 지금 쓰는 데이터."""

    def __init__(self, pool_registry, source_factory, current: Callable[[], tuple[str, str | None] | None]) -> None:
        self._registry = pool_registry
        self._source_factory = source_factory
        self._current = current

    def datasets(self) -> list[dict]:
        entries, _corrupted = self._registry.list_references(STATUS_ACTIVE)
        return [{"key": key, "name": item.name} for key, item in entries]

    def load(self, key: str, sheet: str | None) -> LoadedRows:
        def records(item) -> list:
            return resolve_pool_source(item, source_factory=self._source_factory)[1]

        result = load_pool_into(self._registry, key, records, sheet=sheet)
        if not result["ok"]:
            return LoadedRows(error=str(result["error"]))
        return normalize_rows(result["item"].name, result["records"])

    def current(self) -> tuple[str, str | None] | None:
        return self._current()


class ProposalPanel:
    """``propose_*`` 액션과 스냅숏 투영. 세션 확인·미리보기·문서 해석은 컨트롤러의 것을 받아 쓴다."""

    def __init__(self, session_of: Callable[..., AuthoringSession], preview: Callable[[dict], dict],
                 parse: Callable[[str, bytes], object], data: ProposalDataPort | None,
                 job_registry=None) -> None:
        self._session_of = session_of
        self._preview = preview
        self._parse = parse
        self._data = data
        self._jobs = job_registry

    def applied(self, job_name: str, session: AuthoringSession, result: dict) -> dict:
        """작업 적용 결과에 연결 초안 심기를 더한다 — ``seeded_bindings`` 는 새로 더한 필드 연결 수다."""
        return {**result, "seeded_bindings": self._seed(job_name, session, result)}

    def _seed(self, job_name: str, session: AuthoringSession, result: dict) -> int:
        """적용한 템플릿이 작업의 현재 템플릿이 됐으면, 초안이 있는 새 필드의 연결을 작업에 더해 저장한다.

        편집기 저장과 같은 규칙이다 — 레지스트리 쓰기 잠금 안에서 디스크의 작업을 다시 읽고 고쳐 저장한다(다른
        프로세스가 쓰기 소유권을 쥐었으면 잠금이 거절한다). 연결의 권위가 작업 연결(``job-mapping/v1``)인 작업만
        고친다 — 그렇지 않은 작업의 연결은 다른 판본이 권위라 여기서 쓰면 무시된다.
        """
        if not session.proposal_bindings or self._jobs is None or result.get("status") not in SEEDABLE_APPLY \
                or result.get("is_current") is False:
            return 0
        fields = {str(item.get("name")) for item in session.analysis.get("fields", [])}
        with self._jobs.write_lock():
            job = self._jobs.load(job_name)
            if job.binding_authority != JOB_MAPPING_AUTHORITY:
                return 0
            added = seed_mappings(job.mapping.mappings, fields, session.proposal_bindings)
            if added:
                job.mapping.mappings.extend(added)
                self._jobs.save(job, allow_overwrite=True)
        return len(added)

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        """액션 이름 → 처리기. 이름은 ``_do_<액션>`` 이다(배선 게이트가 컨트롤러와 함께 센다)."""
        return {name.removeprefix("_do_"): getattr(self, name) for name in vars(type(self)) if name.startswith("_do_")}

    # ------------------------------------------------------------ snapshot
    def view(self, session: AuthoringSession) -> dict | None:
        state = session.proposal
        if not isinstance(state, FieldProposalState):
            return None
        if state.cache is None or state.cache[0] != self._key(session, state):
            result = self._compute(session, state)
            # 계산이 행을 고정할 수 있다(가장 많이 맞는 행) — 열쇠는 계산 뒤의 상태로 짓는다.
            state.cache = (self._key(session, state), result)
        return state.cache[1]

    @staticmethod
    def _key(session: AuthoringSession, state: FieldProposalState) -> tuple:
        fields = tuple(sorted(str(item.get("name", "")) for item in session.analysis.get("fields", [])))
        return (session.revision, state.pool_key, state.sheet, state.row, frozenset(state.dismissed),
                tuple(sorted(state.picks.items())), id(state.loaded), fields)

    def _datasets(self) -> list[dict]:
        return self._data.datasets() if self._data is not None else []

    def _compute(self, session: AuthoringSession, state: FieldProposalState) -> dict:
        datasets = self._datasets()
        if state.loaded is None:
            return empty_view(STATE_NEEDS_DATA, session.revision, datasets)
        if state.loaded.error or not state.loaded.rows:
            return empty_view(STATE_FAILED, session.revision, datasets, state.loaded.error, state)
        document = self._parse(session.media, session.content)
        if session.media == "txt":
            assert isinstance(document, str)
            paragraphs, places = read_txt(document)
        else:
            paragraphs, places = read_hwpx(document)

        def locate(index: int, start: int, end: int) -> dict:
            return spot_location(session.media, document, places[index], start, end)

        existing = [str(item.get("name")) for item in session.analysis.get("fields", [])]
        return proposal_view(state=state, revision=session.revision, paragraphs=paragraphs, locate=locate,
                             existing=existing, datasets=datasets)

    # ------------------------------------------------------------ actions
    def _do_propose_fields(self, p: dict) -> dict:
        """띠 켜기·데이터나 행 바꾸기·다시 계산 — 고른 데이터, 세션이 기억한 데이터, 「문서 작업」의 데이터 순."""
        session = self._session_of(p, revision=True)
        state = session.proposal if isinstance(session.proposal, FieldProposalState) else FieldProposalState()
        requested = p.get("pool_key")
        if isinstance(requested, str) and requested:
            self._load(state, requested, p.get("sheet"))
        elif not state.pool_key:
            source = self._data.current() if self._data is not None else None
            if source is not None:
                self._load(state, *source)
        row = p.get("row")
        if type(row) is int and row >= 1:
            state.row = row
        session.proposal = state
        state.cache = None
        view = self.view(session)
        assert view is not None
        return view

    def _load(self, state: FieldProposalState, key: str, sheet: object) -> None:
        """데이터를 (다시) 읽는다 — 행 고름은 새 데이터의 가장 많이 맞는 행으로 돌아간다."""
        state.pool_key, state.sheet, state.row = key, sheet if isinstance(sheet, str) and sheet else None, None
        state.loaded = self._data.load(key, state.sheet) if self._data is not None else None

    def _group(self, session: AuthoringSession, group_id: object) -> tuple[dict, dict]:
        view = self.view(session)
        if view is None:
            raise ValueError(_NO_GROUP)
        group = next((item for item in view["groups"] if item["id"] == group_id), None)
        if group is None:
            raise ValueError(_NO_GROUP)
        return view, group

    def _prepared(self, session: AuthoringSession, command: dict, groups: list, toast: str) -> dict:
        result = self._preview({"session_id": session.id, "revision": session.revision, "command": command})
        if result.get("ok") is False:
            return result
        bindings, values = drafts(groups)
        assert session.last_preview is not None  # 성공한 미리보기는 늘 그 본문을 세션에 남긴다
        session.proposal_pending = (content_digest(session.last_preview[0]), bindings, values)
        return {**result, "command": command, "toast": toast}

    def _do_propose_make(self, p: dict) -> dict:
        """묶음 하나(또는 ``spot_id`` 자리 하나)를 필드로 만드는 미리보기 — 확정은 표면의 적용 사슬이 한다."""
        session = self._session_of(p, revision=True)
        _view, group = self._group(session, p.get("group_id"))
        command = group_command(group, p.get("spot_id"))
        return self._prepared(session, command, [group], toast_one(str(group["name"])))

    def _do_propose_make_all(self, p: dict) -> dict:
        """제안 묶음 전부(보류 제외)를 한 명령으로 — 편집기에는 한 문서로 들어가 실행 취소 한 단위다."""
        session = self._session_of(p, revision=True)
        view = self.view(session)
        if view is None:
            raise ValueError(_NO_GROUP)
        command, groups = all_command(view)
        return self._prepared(session, command, list(groups), toast_many(len(groups)))

    def _do_propose_dismiss(self, p: dict) -> dict:
        """「그대로 두기」 — 그 (열, 값) 묶음을 이 세션 동안 다시 내지 않는다(문서가 바뀌어도)."""
        session = self._session_of(p, revision=True)
        _view, group = self._group(session, p.get("group_id"))
        state = session.proposal
        assert isinstance(state, FieldProposalState)
        state.dismissed.add((str(group["column"]), str(group["raw"])))
        view = self.view(session)
        assert view is not None
        return view

    def _do_propose_off(self, p: dict) -> dict:
        """띠 끄기 — 제안 상태와 「그대로 두기」 집합을 비운다(만든 필드의 연결 초안은 남는다)."""
        session = self._session_of(p)
        session.proposal = None
        session.proposal_pending = None
        return {"ok": True}

    def _do_propose_pick_column(self, p: dict) -> dict:
        """팝오버 머리의 열 고르기 — 같은 값의 열 가운데 하나로 이 묶음을 다시 판정한다(문서가 바뀌어도 남는다)."""
        session = self._session_of(p, revision=True)
        _view, group = self._group(session, p.get("group_id"))
        state = session.proposal
        assert isinstance(state, FieldProposalState)
        pick_column(state, group, p.get("column"))
        view = self.view(session)
        assert view is not None
        return view
