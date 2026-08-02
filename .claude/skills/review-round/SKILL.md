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

`READY` 면 6번으로 간다. 판정이 `WAIT` 면 **폴링하지 않는다** — 리뷰 대기는 CI 가 진다
(정책 §4). 다른 일을 하다 돌아와 다시 읽는다.

## 2. 미정산 지적마다 판정한다

정책 §1 리트머스를 그대로 적용한다. 판정은 둘뿐이다.

- **차단** — ①오늘 사용자가 밟는다 ②릴리스·영속·파괴 경로가 깨진다 ③계약이 거짓말한다
  (표시·테스트·문서 ≠ 실제 상태). 셋 중 하나라도 참이면 차단이다.
- **분리** — 그 외 전부. 오독이든 이미 가드된 것이든 **이슈로 남긴다.**

판정 전에 **코드를 직접 확인한다.** 리뷰어의 지적이 맞는지 읽지 않고 분리로 넘기면 이
절차 전체가 형식이 된다.

## 3. 정산 마커를 게시한다

```powershell
gh pr comment <PR> --body "triage: <comment-id> block"
gh issue create --label review-dismissed --title "..." --body "..."   # 분리인 경우
gh pr comment <PR> --body "triage: <comment-id> defer #<issue>"
```

`<comment-id>` 는 1번 출력의 첫 숫자다. 분리의 이슈 번호는 **실재하고 열려 있어야** 통과한다
— 번호만 적으면 게이트가 막는다.

## 4. 차단만 이 PR 에서 고친다

분리 항목은 손대지 않는다. **루프가 안 닫히면 먼저 「이걸 정말 이 PR 에서 고쳐야 하는가」를
묻는다** — 고치면 push 가 생기고 push 가 리뷰를 부른다. 분리는 head 를 안 바꾸므로 그 자리에서
닫힌다.

**회귀 후보가 하나라도 표시되면** 그 자리에서 점별 픽스를 멈춘다(정책 §3 — 첫 재발부터
근본 조치다). 판정은 아직 `READY` 일 수 있으니 게이트가 대신 세워 주지 않는다.

판정이 `ESCALATE` 면 **고치는 것으로는 풀리지 않는다.** 점별 픽스를 멈추고 근본 조치·범위
재단·중단 중 하나를 정한 뒤 그 판단을 남긴다. **사유 없는 마커는 거절된다** — 자리표시자를
그대로 복사한 것도 마찬가지다.

```powershell
gh pr comment <PR> --body "triage: escalated <head-sha> — 무엇을 어떻게 정했는지"
```

고친 뒤에는 그 스레드를 **`Resolve conversation` 으로 닫는다** — 그것이 해소 신호다.
코멘트가 outdated 가 되기를 기다리면 안 된다. GitHub 은 앵커 hunk 가 살아 있는 한 코멘트를
최신 커밋으로 재앵커하므로, 실제로 고쳐도 살아남는 경우가 흔하다.

```powershell
gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){clientMutationId}}' -F t=<thread-id>
```

## 5. 게이트를 돌리고 푸시한다

```powershell
.\test.ps1
uv run ruff check scripts   # scripts/ 를 고쳤다면 — test.ps1 은 이걸 안 본다
git push
```

푸시가 곧 다음 라운드 트리거다. 1번으로 돌아간다.

## 6. 머지

```powershell
gh pr merge <PR> --squash
```

훅이 거절하면 그 사유가 곧 남은 일이다. 훅은 하한일 뿐이고 실제 게이트는 `review-gate`
required check 다 — 그것이 초록이 아니면 머지는 어차피 안 된다.
