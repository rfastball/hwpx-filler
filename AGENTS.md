# AGENTS.md

이 파일은 **진입점**이다. 규율의 본문은 다른 곳이 소유한다 — 여기 옮겨 적으면 두 벌이
따로 늙는다.

## 먼저 읽을 것

| 무엇 | 어디 |
|---|---|
| 저장소 구조·아키텍처·작업 규율 | `CLAUDE.md` |
| 환경·게이트·패키징·릴리스 | `docs/DEVELOPMENT_ENVIRONMENT.md` |
| 문서 지도와 각 문서의 권위 | `docs/README.md` |

`CLAUDE.md` 는 Claude Code 전용 파일이 아니다. **어느 에이전트로 작업하든 그것이 규율의
정본**이고, 이 파일은 그리로 보내는 표지판이다.

## 최소한 이것만은

- 환경은 전부 `uv` 가 소유한다. 시스템 Python·수동 venv 를 만들지 않는다.
- 환경·게이트·예외 검사 명령은 `docs/DEVELOPMENT_ENVIRONMENT.md`, 문서 검토는
  `docs/MAINTENANCE.md` 를 따른다.
- 커밋 메시지는 한국어 Conventional Commits + PR 번호.
- **머지를 막는 것은 `quality-gate` 하나다.** 봇 리뷰는 자문이라 게이트가 아니다 — 읽고
  판단해서 고칠 것은 고치고, 나머지는 이슈로 남긴다. 머지 뒤 도착한 지적은 스윕 PR 로 회수한다.
- 애매하면 조용히 추측하지 않는다. 이 저장소의 핵심 계약은 **「묻고 확정하게 하거나,
  시끄럽게 알린다」** 다 — 법적 효력이 있는 문서를 만드는 도구이기 때문이다.

<!-- >>> codex-orchestration >>>
## Recursive model delegation

The root orchestrator is gpt-6-astra. It owns requirements, decomposition,
integration, final verification, and the user-facing answer.

Follow this Codex delegation policy; it is enforced through instructions, not runtime access controls.
This block owns Codex model selection over other-agent model names while preserving repository
correctness and test contracts.

Root-only rules:

- Before root implementation, assign independent substantial work to a named suitable worker.
  Start implementation and integration with Sol. Downgrade only clearly easy bounded changes
  with settled requirements, local impact, and low risk to Terra; uncertainty stays with Sol.
  Luna is mechanical/read-heavy. Do not require a failed Terra attempt before Sol.
- Do not spawn for inseparable or genuinely trivial work. The root may edit directly only for
  trivial spawn overhead, a small integration correction to reviewed worker work, a worker
  reported unavailable after an attempted handoff, an unresolved blocker after a Sol attempt,
  or an explicit user request; state why first. Otherwise Terra failures report to their parent
  for scoped Sol escalation.

Shared delegation rules:

- Downgrade implementation only when the easy-task criteria are clearly met. One worker is normal,
  not a required chain; parallelize only independent useful work. Use only
  named agent types sol, terra, or luna for delegated work.
- Scope handoffs with files and acceptance checks, default to fork_turns: none to save context,
  and reuse children. Workers report evidence or blockers to their parent.
- Do not duplicate worker implementation or unchanged checks without reason; repeat checks only
  after changes, failures, unresolved concerns, or required final gates. Completion reports roles
  used and any root-edit reason.

Roles: sol (gpt-6-sol) leads default implementation/integration and handles
ambiguity/high impact; terra (gpt-5.6-terra) handles clearly easy bounded changes,
analysis, review, and verification; luna (gpt-6-luna)
handles search, inventory, extraction, and mechanical transforms.

Allowed downward edges: Astra -> Sol, Terra, Luna; Sol -> Terra, Luna; Terra -> Luna; Luna -> none.
A parent remains responsible for checking child results.
<!-- <<< codex-orchestration <<< -->
