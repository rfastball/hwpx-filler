/* R4-02 — 편집 표면 local draft reducer(`frontend/src/screens/editor_state.ts`)의 불변식.
 *
 * 이 파일이 재는 것은 **소유**다. 전송 스냅샷과 사용자가 치고 있는 값 중 누가 어느 칸의
 * 주인인가. legacy 는 이 문제를 「재구성 뒤 캐럿 되찾기 + `pendingFieldEdit` 1슬롯」으로
 * 풀었고, 그 기제는 관측 불가능한 자리(실제 포커스·캐럿)에 살아 단위로 잴 수 없었다.
 * reducer 로 옮기면서 같은 성질이 **값의 함수**가 됐다 — 그래서 여기 음성 대조가 선다.
 *
 * 패킷 rev2 §2.2 의 여섯 규칙이 그대로 이 파일의 목차다:
 *  1. full push 는 새 `serverValue`/`baseRevision` 을 저장한다.
 *  2. `dirty || focused || composing` 인 field 의 `draftValue` 는 덮지 않는다.
 *  3. 손대지 않은 field 만 새 server 값을 흡수한다.
 *  4. 변이는 단조 증가 token 을 발급하고, 응답은 session·token 이 **모두** 맞을 때만 반영된다.
 *  5. 늦은 성공·실패는 현재 draft 를 지우지 않고 stale 관측으로 남는다.
 *  6. Python 이 새 값을 확인한 뒤에만 draft 가 clean 으로 승격한다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  NAME_FIELD, PATTERN_FIELD, editorRevision, editorServerValues, editorSession,
  emptyDraft, fieldError, hasInFlight, hasPendingEdits, ingestSnapshot, issueToken,
  markField, rowField, settle, typeInto, valueOf,
} from "../../frontend/src/screens/editor_state.ts";
import {
  TARGET_FONT_FIELD, checked, mapField, workbenchRevision, workbenchServerValues, workbenchSession,
} from "../../frontend/src/screens/workbench_state.ts";

const SESSION = "job:작업A";

function seeded(values, options = {}) {
  return ingestSnapshot(emptyDraft(), {
    session: options.session ?? SESSION,
    revision: options.revision ?? 1,
    values,
  });
}

/* ================= 규칙 1·3 — 흡수 ================= */

test("규칙 1·3 — 손대지 않은 field 는 새 server 값을 그대로 흡수한다", () => {
  let state = seeded({ [NAME_FIELD]: "옛 이름" });
  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "새 이름" },
  });
  assert.equal(valueOf(state, NAME_FIELD), "새 이름");
  assert.equal(state.fields[NAME_FIELD].serverValue, "새 이름");
  assert.equal(state.fields[NAME_FIELD].baseRevision, 2);
  assert.equal(state.fields[NAME_FIELD].dirty, false);
});

test("규칙 3 — 스냅샷이 들지 않은 키는 발명하지 않고, 없는 키 판독은 loud 다", () => {
  const state = seeded({ [NAME_FIELD]: "이름" });
  assert.deepEqual(Object.keys(state.fields), [NAME_FIELD]);
  assert.throws(() => valueOf(state, PATTERN_FIELD), /스냅샷에 없습니다/);
});

/* ================= 규칙 2 — push 는 들고 있는 값을 덮지 않는다 ================= */

test("음성 — 타이핑 중 도착한 push 가 친 값을 덮지 않는다(typing→push)", () => {
  let state = seeded({ [NAME_FIELD]: "옛 이름" });
  state = typeInto(state, NAME_FIELD, "치는 중");
  assert.equal(state.fields[NAME_FIELD].dirty, true);

  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "서버가 민 값" },
  });
  assert.equal(valueOf(state, NAME_FIELD), "치는 중", "사용자가 든 값이 주인이다");
  assert.equal(state.fields[NAME_FIELD].serverValue, "서버가 민 값", "서버 값은 갱신된다");
  assert.equal(state.fields[NAME_FIELD].baseRevision, 2);
});

test("음성 — IME 조합 중 도착한 push 가 조합 중인 값을 덮지 않는다(composition→push)", () => {
  let state = seeded({ [NAME_FIELD]: "" });
  state = markField(state, NAME_FIELD, { composing: true });
  /* 조합 중에는 아직 dirty 가 아닐 수 있다(첫 자모). 그래도 덮으면 조합이 깨진다. */
  assert.equal(state.fields[NAME_FIELD].dirty, false);
  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "서버 값" },
  });
  assert.equal(valueOf(state, NAME_FIELD), "", "조합 중 draft 는 보존된다");
  assert.equal(state.fields[NAME_FIELD].serverValue, "서버 값");
});

test("음성 — 포커스만 있어도 push 가 그 칸을 덮지 않는다", () => {
  let state = seeded({ [NAME_FIELD]: "옛" });
  state = markField(state, NAME_FIELD, { focused: true });
  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "새" },
  });
  assert.equal(valueOf(state, NAME_FIELD), "옛");
  assert.equal(state.fields[NAME_FIELD].dirty, true,
    "든 값이 서버 값과 갈렸으면 dirty 다 — 「든다」와 「같다」는 다른 축이다");
});

test("양성 대조 — 같은 push 가 손대지 않은 이웃 칸은 갱신한다(덮지 않음이 전면 정지가 아니다)", () => {
  let state = seeded({ [NAME_FIELD]: "옛", [PATTERN_FIELD]: "옛 규칙" });
  state = typeInto(state, NAME_FIELD, "치는 중");
  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "새", [PATTERN_FIELD]: "새 규칙" },
  });
  assert.equal(valueOf(state, NAME_FIELD), "치는 중");
  assert.equal(valueOf(state, PATTERN_FIELD), "새 규칙");
});

test("dirty 는 「서버 값과 다른가」로만 정한다 — 되돌려 치면 clean 이다", () => {
  let state = seeded({ [NAME_FIELD]: "원본" });
  state = typeInto(state, NAME_FIELD, "바꿈");
  assert.equal(hasPendingEdits(state), true);
  state = typeInto(state, NAME_FIELD, "원본");
  assert.equal(state.fields[NAME_FIELD].dirty, false);
  assert.equal(hasPendingEdits(state), false);
});

/* ================= 규칙 4·5 — token/session 정산 ================= */

test("규칙 4 — token 은 화면 전체에서 단조 증가한다", () => {
  let state = seeded({ [NAME_FIELD]: "a", [PATTERN_FIELD]: "b" });
  const first = issueToken(state, NAME_FIELD);
  const second = issueToken(first.state, PATTERN_FIELD);
  assert.equal(first.token, 1);
  assert.equal(second.token, 2);
  assert.equal(second.state.lastToken, 2);
  state = second.state;
  assert.equal(hasInFlight(state), true);
});

test("음성 — token N 뒤에 온 N-1 응답은 아무것도 바꾸지 않고 stale 로 센다", () => {
  let state = seeded({ [NAME_FIELD]: "서버" });
  state = typeInto(state, NAME_FIELD, "첫 편집");
  const first = issueToken(state, NAME_FIELD);
  state = typeInto(first.state, NAME_FIELD, "둘째 편집");
  const second = issueToken(state, NAME_FIELD);
  state = second.state;

  const before = valueOf(state, NAME_FIELD);
  state = settle(state, {
    ok: true, session: SESSION, token: first.token, key: NAME_FIELD, serverValue: "첫 편집",
  });
  assert.equal(valueOf(state, NAME_FIELD), before, "늦은 옛 응답이 지금 값을 지우지 않는다");
  assert.equal(state.fields[NAME_FIELD].pendingToken, second.token, "최신 대기는 살아 있다");
  assert.equal(state.staleResponses, 1, "무시했다는 사실이 관측된다(조용한 무시 금지)");
});

test("음성 — 세션이 바뀐 뒤 도착한 응답은 새 세션의 draft 를 건드리지 않는다", () => {
  let state = seeded({ [NAME_FIELD]: "A" });
  const issued = issueToken(state, NAME_FIELD);
  state = ingestSnapshot(issued.state, {
    session: "job:작업B", revision: 1, values: { [NAME_FIELD]: "B" },
  });
  state = typeInto(state, NAME_FIELD, "새 세션 편집");
  state = settle(state, {
    ok: true, session: SESSION, token: issued.token, key: NAME_FIELD, serverValue: "A2",
  });
  assert.equal(valueOf(state, NAME_FIELD), "새 세션 편집");
  assert.equal(state.staleResponses, 1);
});

test("규칙 5 — 실패 응답은 draft 를 지우지 않고 사유를 남긴다", () => {
  let state = seeded({ [NAME_FIELD]: "서버" });
  state = typeInto(state, NAME_FIELD, "내가 친 값");
  const issued = issueToken(state, NAME_FIELD);
  state = settle(issued.state, {
    ok: false, session: SESSION, token: issued.token, key: NAME_FIELD, error: "이름 중복",
  });
  assert.equal(valueOf(state, NAME_FIELD), "내가 친 값", "실패가 입력을 되돌리지 않는다");
  assert.equal(state.fields[NAME_FIELD].dirty, true);
  assert.equal(fieldError(state, NAME_FIELD), "이름 중복");
  assert.equal(hasInFlight(state), false, "대기는 풀린다");
});

test("다시 치면 직전 실패 사유는 걷힌다(낡은 빨강을 들고 있지 않는다)", () => {
  let state = seeded({ [NAME_FIELD]: "서버" });
  const issued = issueToken(state, NAME_FIELD);
  state = settle(issued.state, {
    ok: false, session: SESSION, token: issued.token, key: NAME_FIELD, error: "이름 중복",
  });
  state = typeInto(state, NAME_FIELD, "고친 이름");
  assert.equal(fieldError(state, NAME_FIELD), "");
});

/* ================= 규칙 6 — 확인 뒤에만 clean 승격 ================= */

test("규칙 6 — Python 이 새 값을 확인해 준 성공만 draft 를 clean 으로 올린다", () => {
  let state = seeded({ [NAME_FIELD]: "서버" });
  state = typeInto(state, NAME_FIELD, "새 이름");
  const issued = issueToken(state, NAME_FIELD);

  const unconfirmed = settle(issued.state, {
    ok: true, session: SESSION, token: issued.token, key: NAME_FIELD,
  });
  assert.equal(unconfirmed.fields[NAME_FIELD].dirty, true,
    "확인 없는 성공은 「보낸 것이 곧 저장된 것」이라는 두 번째 판정자를 만든다");
  assert.equal(unconfirmed.fields[NAME_FIELD].pendingToken, 0);

  const confirmed = settle(issued.state, {
    ok: true, session: SESSION, token: issued.token, key: NAME_FIELD, serverValue: "새 이름",
  });
  assert.equal(confirmed.fields[NAME_FIELD].dirty, false);
  assert.equal(confirmed.fields[NAME_FIELD].serverValue, "새 이름");
});

test("규칙 6 — 승격의 다른 경로: Python 이 같은 값을 push 하면 그때 clean 이 된다", () => {
  let state = seeded({ [NAME_FIELD]: "서버" });
  state = typeInto(state, NAME_FIELD, "새 이름");
  const issued = issueToken(state, NAME_FIELD);
  state = settle(issued.state, { ok: true, session: SESSION, token: issued.token, key: NAME_FIELD });
  assert.equal(state.fields[NAME_FIELD].dirty, true, "응답만으로는 아직 아니다");

  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "새 이름" },
  });
  assert.equal(state.fields[NAME_FIELD].dirty, false,
    "확인이 오면 승격한다 — 안 그러면 저장 뒤에도 화면이 영영 미저장이라고 말한다");
  assert.equal(valueOf(state, NAME_FIELD), "새 이름");
});

test("음성 — 확인된 값이 내가 든 값과 다르면 dirty 로 남는다(승격이 무차별이 아니다)", () => {
  let state = seeded({ [NAME_FIELD]: "서버" });
  state = typeInto(state, NAME_FIELD, "내 값");
  state = ingestSnapshot(state, {
    session: SESSION, revision: 2, values: { [NAME_FIELD]: "남이 바꾼 값" },
  });
  assert.equal(state.fields[NAME_FIELD].dirty, true);
  assert.equal(valueOf(state, NAME_FIELD), "내 값");
});

/* ================= 세션 교체 — 되돌릴 자리 없는 대기는 버린다 ================= */

test("세션이 바뀌면 draft 를 들고 가지 않는다(되돌릴 자리 없는 대기 금지)", () => {
  let state = seeded({ [NAME_FIELD]: "A" });
  state = typeInto(state, NAME_FIELD, "편집 중");
  state = ingestSnapshot(state, {
    session: "job:작업B", revision: 1, values: { [NAME_FIELD]: "B" },
  });
  assert.equal(valueOf(state, NAME_FIELD), "B");
  assert.equal(state.staleResponses, 0, "새 세션은 stale 계수도 새로 센다");
});

test("서버가 더 이상 들지 않는 field 의 draft 는 사라진다(탭 이동으로 행이 없어진 형상)", () => {
  let state = seeded({ [rowField(0, "const")]: "값" });
  state = typeInto(state, rowField(0, "const"), "편집 중");
  state = ingestSnapshot(state, { session: SESSION, revision: 2, values: {} });
  assert.deepEqual(Object.keys(state.fields), []);
  assert.equal(hasPendingEdits(state), false, "열린 저장 버튼의 거짓 근거를 남기지 않는다");
});

/* ================= 스냅샷 사영 — 두 화면이 같은 reducer 를 쓴다 ================= */

test("편집기 사영 — 이름·규칙과 행 축 넷이 키가 되고 세션은 편집 대상이 정한다", () => {
  const snapshot = {
    name: "작업A", pattern: "{{이름}}", editing_origin: "작업A",
    revisions: { binding: 2, template: 3 },
    rows: [{ index: 0, source: "성명", type: "text", fmt: "", const: "" }],
  };
  assert.deepEqual(editorServerValues(snapshot), {
    [NAME_FIELD]: "작업A",
    [PATTERN_FIELD]: "{{이름}}",
    [rowField(0, "source")]: "성명",
    [rowField(0, "type")]: "text",
    [rowField(0, "fmt")]: "",
    [rowField(0, "const")]: "",
  });
  assert.equal(editorSession(snapshot), "job:작업A");
  assert.equal(editorSession({ is_draft: true }), "draft");
  assert.equal(editorRevision(snapshot), 2003);
});

test("작업대 사영 — 행 정체는 index 가 아니라 토큰 이름이다", () => {
  const snapshot = {
    open: true, job_name: "작업A", target_font: "gulimche",
    revision: { binding: 1, template: 4 },
    rows: [{ name: "납품기한", own: "auto", source: "기한", fmt_kind: "date", fmt_code: "ymd", value: "", confirmed: true }],
  };
  const values = workbenchServerValues(snapshot);
  assert.equal(values[TARGET_FONT_FIELD], "gulimche");
  assert.equal(values[mapField("납품기한", "source")], "기한");
  assert.equal(values[mapField("납품기한", "confirmed")], "1");
  assert.equal(workbenchSession(snapshot), "wb:작업A");
  assert.equal(workbenchSession({ open: false, job_name: "작업A" }), "",
    "닫힌 작업대는 draft 를 들고 가지 않는다");
  assert.equal(workbenchRevision(snapshot), 1004);

  const state = seeded(values, { session: workbenchSession(snapshot) });
  assert.equal(checked(state, mapField("납품기한", "confirmed")), true);
  assert.equal(checked(state, mapField("납품기한", "value")), false);
});

test("직접 입력 행의 데이터 열은 빈 값으로 사영된다(자동만 열을 든다)", () => {
  const values = workbenchServerValues({
    rows: [{ name: "비고", own: "man", source: "옛 열", value: "손으로 씀" }],
  });
  assert.equal(values[mapField("비고", "source")], "");
  assert.equal(values[mapField("비고", "value")], "손으로 씀");
});
