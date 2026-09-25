# 작업 진입점

공통 작업·검증·문서 작성 절차는 [CONTRIBUTING.md](CONTRIBUTING.md), 현재 제품 계약의
읽기·작성 목적지는 [문서 지도](docs/README.md)를 따른다. 새 문서를 만들기 전에
`uv run python scripts/docs_contract.py --route`로 기존 소유 절을 확인한다.

아래는 Codex에만 적용하는 위임 설정이다. 공통 제품 계약을 여기 복제하지 않는다.

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
