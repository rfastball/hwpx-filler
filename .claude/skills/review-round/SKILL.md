---
name: review-round
description: PR 의 리뷰 지적을 정산하고 머지 가능 여부를 판정한다. 리뷰가 도착했을 때, 머지 직전에, 또는 머지 훅이 거절했을 때 쓴다.
---

# 리뷰 라운드 정산

규칙 원문은 `docs/REVIEW_POLICY.md` 다. 여기 옮겨 적지 않는다 — 두 벌은 따로 늙는다.
이 스킬은 그 절차를 **순서대로 밟는 방법**만 담는다.

## 1. 상태를 읽는다

```powershell
uv run python scripts/review_rounds.py
```

`READY` 면 7번으로 간다. 미정산 지적이 있으면 2번, 지적 없이 `WAIT` 면 6번(감시)으로 간다.

## 2. 미정산 지적마다 판정한다

정책 §1 리트머스를 그대로 적용한다. 판정은 둘뿐이다.

- **차단** — ①오늘 사용자가 밟는다 ②릴리스·영속·파괴 경로가 깨진다 ③계약이 거짓말한다
  (표시·테스트·문서 ≠ 실제 상태). 셋 중 하나라도 참이면 차단이다.
- **분리** — 그 외 전부. 오독이든 이미 가드된 것이든 **이슈로 남긴다.**

판정 전에 **코드를 직접 확인한다.** 리뷰어의 지적이 맞는지 읽지 않고 분리로 넘기면 이
절차 전체가 형식이 된다.

## 3. 스레드 안에 정산을 남긴다

판정은 지적 스레드 **안의 답글**로 남긴다 — 판정이 지적 옆에 남아 문맥이 보존되고, 코멘트
id 를 옮겨 적는 부기가 없다.

```powershell
# 차단 — 리트머스 조항 번호(1|2|3)를 반드시 함께 적는다
gh api repos/{owner}/{repo}/pulls/<PR>/comments/<comment-id>/replies -f body="triage: block:2"

# 분리 — 이슈를 먼저 만들고 번호로 지목한다
gh issue create --label review-dismissed --title "..." --body "..."
gh api repos/{owner}/{repo}/pulls/<PR>/comments/<comment-id>/replies -f body="triage: defer #<issue>"
```

`<comment-id>` 는 1번 출력의 첫 숫자다. 분리의 이슈 번호는 **실재해야** 통과한다 — 번호만
적으면 게이트가 막는다. 분리로 정산한 스레드는 그 자리에서 **해결 처리까지 한다** — 대화
해결 필수 룰셋이 미해결 스레드의 머지를 막는다(차단 스레드의 해결은 4번, 고친 뒤다).

## 4. 차단만 이 PR 에서 고친다 — 한 커밋으로 묶는다

분리 항목은 손대지 않는다. **루프가 안 닫히면 먼저 「이걸 정말 이 PR 에서 고쳐야 하는가」를
묻는다** — 분리는 head 를 안 바꾸므로 그 자리에서 닫힌다.

이번 정산의 픽스는 **한 커밋으로 묶는다.** 지적 하나마다 커밋·push 를 반복하면 리뷰어가
중간 상태를 읽고, 코멘트가 push 마다 불어난다 — 정산 한 바퀴에 push 는 한 번이다.

**멈춰야 하는 신호가 있다.** 게이트는 이것을 막지 않으므로 — 판정이 `READY` 여도 — 여기
적혀 있지 않으면 그냥 지나간다: **재호출 예산은 2회다.** 세 번째 재리뷰 호출을 부르기
전에 멈춘다. 지적이 매번 달라도 같은 **결함류**일 수 있고, 그때는 하나씩 고치는 것이 답이
아니다 — 파생 판정 단일화·가드 계약·타입 봉합처럼, 다음에 같은 가족이 나오지 못하게 류를
구조로 닫는다(정책 §3).

고친 뒤에는 그 스레드를 **해결 처리한다.** 그것이 해소 신호다 — 코멘트가 outdated 가 되기를
기다리면 안 된다. GitHub 은 앵커 hunk 가 살아 있는 한 코멘트를 최신 커밋으로 재앵커하므로
실제로 고쳐도 살아남는 경우가 흔하고, 그러면 게이트가 `BLOCKED` 에 머문다.

```powershell
# 스레드 id 는 GraphQL 로 찾는다
gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}' -F t=<thread-id>
```

## 5. 게이트를 돌리고 **푸시한 뒤** 재리뷰를 부른다

```powershell
.\test.ps1
uv run ruff check scripts   # scripts/ 를 고쳤다면 — test.ps1 은 이걸 안 본다
git push
```

**순서가 계약이다.** push 보다 먼저 부르면 리뷰어가 **옛 head 를 읽고**, 그 뒤 push 로 head 가
바뀌어 정작 픽스는 안 읽힌 채 남는다 — push 는 더 이상 리뷰를 부르지 않으므로 그대로 회수
창까지 기다리게 된다.

```powershell
gh pr comment <PR> --body "@codex review"
```

**차단을 고쳤으면 반드시 부른다.** 자동 리뷰는 PR 당 한 번뿐이고 재리뷰는 저절로 오지
않는다. 게이트가 강제하므로 안 부르면 초록이 되지 않는다 — 회수 창도 재호출 뒤에만 돈다.
분리만 했다면 코드가 안 바뀌었으니 부르지 않는다.

6번으로 간다.

## 6. 감시한다 — 폴링 + 무활동 종료

리뷰 대기의 1차 주체는 이 루프다(정책 §4). ~90초 간격으로 다시 읽는다:

```powershell
uv run python scripts/review_rounds.py <PR> --json
```

- 지적이 새로 왔으면 → 2번으로 돌아간다.
- `READY` → 7번. `BLOCKED` → 남은 정산이 있다, 2번으로.
- `WAIT` 가 회수 창(10분)을 넘겨 계속되면 — 리액션·창 경과는 이벤트를 만들지 않는 축이다 —
  재판정을 한 번 깨운다:

```powershell
gh workflow run review-gate.yml -f pr=<PR>
```

그래도 `WAIT` 면 **멈추고 사람에게 보고한다** — 무한 폴링 루프를 만들지 않는다.

## 7. 머지 — 체크런을 먼저 동기화한다

로컬 판정과 원격 체크런은 따로 논다 — READY 로 넘어온 마지막 전이가 이벤트 없는 축
(리액션 `+1`·스레드 해결)이었다면 체크런은 아직 낡은 색이다. 머지 전에 확인하고, 낡았으면
같은 킥으로 동기화한 뒤 초록을 보고 머지한다:

```powershell
gh pr checks <PR>              # review-gate 가 로컬 판정과 다르면 ↓
gh workflow run review-gate.yml -f pr=<PR>
gh pr merge <PR> --squash
```

훅이 거절하면 그 사유가 곧 남은 일이다. 훅은 하한일 뿐이고 실제 게이트는 `review-gate`
required check 다 — 그것이 초록이 아니면 머지는 어차피 안 된다.
