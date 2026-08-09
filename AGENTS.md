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
- 게이트는 `.\test.ps1`(web build → npm test → Ruff → Pyright → pytest). `scripts/` 를
  고쳤으면 전체 게이트와 별개로 `uv run ruff check scripts` 도 명시 실행한다.
- 커밋 메시지는 한국어 Conventional Commits + PR 번호.
- **머지를 막는 것은 `quality-gate` 하나다.** 봇 리뷰는 자문이라 게이트가 아니다 — 읽고
  판단해서 고칠 것은 고치고, 나머지는 이슈로 남긴다. 머지 뒤 도착한 지적은 스윕 PR 로 회수한다.
- 애매하면 조용히 추측하지 않는다. 이 저장소의 핵심 계약은 **「묻고 확정하게 하거나,
  시끄럽게 알린다」** 다 — 법적 효력이 있는 문서를 만드는 도구이기 때문이다.
