/* R4-03 실행 표면의 순수 합성기·문안 표 — 전부 인자만 읽는 순수 함수·상수다(브리지 호출·
   상태 없음). job_run.ts의 `JobActionBar`·`JobDelivery`·`JobTemplateChange`와 컨트롤러가
   가져와 쓴다. */
import type { JobRunControllerDeps } from "./job_run.ts";

type Obj = Record<string, any>;

/** 산출물 관찰이 서지 않은 사유의 **제목**(S7-03 · #825, #820 §3). 본문 사유는 Python 이
 *  낸 `detail` 그대로다 — 수치·경로·기대값이 거기 있고, 표면이 다시 지으면 두 벌이 된다.
 *  넷은 서로 겹치지 않는다: 세션에 없다 / 파일이 없다 / 내용이 다르다 / 열리지 않는다. */
export const ARTIFACT_REFUSAL_TITLE: Record<string, string> = {
  ARTIFACT_FILE_MISSING: "문서 파일을 찾을 수 없습니다",
  ARTIFACT_DIGEST_MISMATCH: "문서 내용이 만든 직후와 다릅니다",
  ARTIFACT_REPARSE_FAILED: "문서를 다시 열지 못했습니다",
  ARTIFACT_NOT_IN_SESSION: "이 문서는 지금 결과에 없습니다",
};

/** 「다른 이름으로 저장」 결과 한 줄 — 네 갈래가 서로 다른 문장을 받는다(#820 §3).
 *  `SAVE_COPY_FAILED` 는 관찰 상태와 **독립**이라 '문서가 깨졌다' 로 읽힐 말을 쓰지 않는다. */
export function saveArtifactMessage(result: Obj): string {
  const status = String(result.status || "");
  if (result.ok === true) return `저장했습니다: ${String(result.path || "")}`;
  if (status === "cancelled") return "저장을 취소했습니다.";
  if (status === "SAVE_COPY_FAILED") {
    return `저장하지 못했습니다. ${String(result.detail || "")}`;
  }
  const title = ARTIFACT_REFUSAL_TITLE[status] || "문서를 확인하지 못했습니다";
  return `${title}. ${String(result.detail || "")}`;
}

export const DELIVERY_DISPOSITION_COPY: Record<string, string> = {
  WRITE_NEW: "새 파일",
  WRITE_ADD_SUFFIX: "번호를 붙인 새 파일",
  WRITE_OVERWRITE: "기존 파일 덮어쓰기",
};

/** 게이트 지목의 **어휘 지도** — 링1 이 낸 사유 축 이름 → 그 축을 소유한 구획 캡션.
 *  판정(무엇이 막는가·무엇이 먼저인가)은 게이트가 하고 여기는 이름을 자리로 옮기기만 한다.
 *  표면이 상태를 다시 읽어 지목을 만들면 서열이 두 곳에 살고, 실제로 그렇게 샜다. */
const GATE_ZONE: Record<string, string> = {
  no_data: "현재 데이터 · ",
  no_rows: "현재 데이터 · ",
  // 결속 부재는 데이터 축이 아니라 **작업 축**이다(#932 U4-C) — 고칠 자리가 피커가 아니라
  // 편집기라, 데이터 머리에 함께 선 「데이터 연결하기…」가 그 자리다.
  data_unbound: "현재 데이터 · ",
  no_candidates: "이 데이터에 사용할 문서 · ",
  no_job: "이 데이터에 사용할 문서 · ",
  // 드리프트·미해소 토큰의 지목도 **빈 문자열**이다 — 그 축을 소유하던 「본문 확인」 존은
  // 존 재편에서 죽었고, 두 사유의 위험 배너도 legacy HWPX 갈래와 함께 걷혔다(#1081 PR2).
  // 없는 구획을 가리키느니 안 가리킨다(`template_missing` 동형).
  drift: "",
  name_tokens: "",
  // 템플릿 축은 **빈 문자열**이다 — 그 축을 소유하던 「선택한 작업」 존은 죽었고 복구는
  // 같은 액션바 줄의 연결 상태·재연결이 곁에서 진다. 없는 구획을 가리키느니 안 가리킨다.
  template_missing: "",
  template_unreadable: "",
};

/** 사전검증 게이트가 선 자리의 지목 접두 — 「게이트 지목의 어휘 지도」를 읽어 적용한다. */
export function gateStep(s: Obj, g: Obj): string {
  if (!g || g.enabled || !g.text) return "";
  const named = GATE_ZONE[String(g.reason || "")];
  if (named !== undefined) return named;
  // 이름 없는 게이트만 자리로 유추한다 — 데이터·행이 안 갖춰졌으면 그게 먼저다.
  const noRows = !s.has_data || !(Number(s.selected_count) > 0);
  if (!s.has_job) return noRows ? GATE_ZONE.no_data : GATE_ZONE.no_job;
  if (noRows) return GATE_ZONE.no_data;
  return "";
}

/* ------------------------------------------------------------------ 순수 합성기 */

/** 덮어쓰기 확인 본문 — 총량·파괴분·신규분을 종류별로 재진술한다(결정 36). */
export function overwriteBody(res: Obj): string {
  const names = (res.conflict_names || []) as string[];
  const more = res.conflict_more ? `\n외 ${res.conflict_more}개` : "";
  return `${res.total}건을 생성합니다. 이 중 ${res.overwrite_count}건이 기존 파일을 덮어씁니다:\n`
    + `${names.join("\n")}${more}\n\n나머지 ${res.new_count}건은 새 파일입니다.`;
}

/** 파괴 전이 가드 본문 — 손실 열거는 **실제로 파기되는 집합**과 일치해야 한다
 *  (과경고도 누락도 거짓말이다). 선택 한 줄은 주입받은 공유 합성기가 낸다. */
export function composeGuardBody(
  selectionLine: JobRunControllerDeps["selectionLine"],
): (g: Obj, verbPhrase: string) => string {
  return (g, verbPhrase) => {
    const lost = [selectionLine(g.sel_count, g.filter_active, g.in_def, g.extra)];
    if (g.filter_parts > 0) lost.push(`필터 정의(${g.filter_parts}개 조건)`);
    const stash = g.filter_parts > 0
      ? "\n필터 정의는 이 데이터로 돌아오면 「직전 필터 재적용」으로 되살릴 수 있습니다." : "";
    return `${verbPhrase} 이 세션의 선택이 사라집니다.\n`
      + `사라지는 것: ${lost.join(" · ")}.${stash}`;
  };
}

/* ------------------------------------------------------------------ 템플릿 변경(S3-09) */

/** prepare intent 재전송 키 — Python 이 `[A-Za-z0-9._-]{1,64}` 로 fail-closed 검증한다. */
export function newTplRequestId(): string {
  return `r${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 제품 status → 상태 문안. 정본 어휘는 contract.gen.ts 의 TEMPLATE_PREPARATION_STATUSES —
 *  표에 없는 status 는 조용히 비우지 않고 원문을 그대로 보인다(조용한 폴백 금지). */
export const TPL_STATUS_COPY: Record<string, string> = {
  checking: "변경사항을 확인하는 중입니다…",
  ready: "적용할 수 있는 변경사항이 있습니다.",
  no_change: "변경사항이 없습니다 — 지금 템플릿이 이미 적용된 상태입니다.",
  invalid: "변경된 템플릿이 검사를 통과하지 못했습니다. 기존 템플릿이 계속 사용됩니다.",
  error: "확인 중 오류가 났습니다. 다시 확인해 주세요.",
  interrupted: "확인이 끝나기 전에 중단되었습니다. 다시 확인해 주세요.",
  source_changed: "확인하는 동안 템플릿 연결이 바뀌었습니다.",
  changed_while_checking: "확인하는 동안 작업의 템플릿 상태가 바뀌었습니다.",
  superseded: "새 확인이 시작되어 이 결과는 대체되었습니다.",
  applied: "확인한 변경사항이 현재 작업에 적용되어 있습니다.",
  conflict: "확인 이후 작업 상태가 바뀌어 이 변경사항은 적용할 수 없습니다.",
  rejected: "이 변경사항은 더 이상 적용할 수 없습니다.",
};

/** 초기 등록 실패 재진술의 **단일 출처** — 존 상태 문안과 확인 거절 재진술이 같은 문장을
 *  쓴다(#804). 존이 그리는 자리와 dispatch 가 답하는 자리가 갈리면 같은 사실을 두 문장이
 *  말하게 되고, 그중 하나가 늙는다. */
export const TPL_INITIALIZATION_REQUIRED_COPY =
  "템플릿 초기 등록에 실패해 변경사항을 확인할 수 없습니다. "
  + "템플릿을 수정하거나 다시 연결한 뒤 확인하세요.";

/** [변경사항 확인] 거절(`ok:false`) 한 줄 — **판정은 Python, 문안만 여기**(#804).
 *
 *  백엔드가 `error` 문장을 실어 보냈으면 그것이 정본이라 그대로 쓴다(좌석 해제처럼 사유와
 *  다음 행동을 아는 쪽이 Python 인 경우). 그 밖에는 `reason` 코드를 존이 이미 쓰는 문안으로
 *  옮기고, 표에 없는 사유도 **조용히 비우지 않는다** — 재진술 없는 거절이 곧 막다른 길이다. */
export function tplCheckRefusalNotice(res: Obj): string {
  const error = String(res.error ?? "").trim();
  if (error) return error;
  const reason = String(res.reason ?? "").trim();
  if (reason === "initialization_required") return TPL_INITIALIZATION_REQUIRED_COPY;
  return reason
    ? `변경사항을 확인하지 못했습니다: ${reason}`
    : "변경사항을 확인하지 못했습니다.";
}

/** 존 이름 — 조치가 있을 때만 뜨는 존과 적용 직후 결과 재진술을 구분한다.
 *
 *  종결 이름이 따로 있는 이유: 적용 직후에는 조치가 남지 않았는데도 결과 재진술 때문에 존이
 *  한 번 더 선다. 그 순간까지 「조치 필요」라고 부르면 방금 끝낸 일을 다시 시키는 말이 된다. */
export const TPL_ZONE_CAP_ACTION = "템플릿 조치 필요";
export const TPL_ZONE_CAP_SETTLED = "템플릿 변경사항";

/** 존이 섰는데 status 가 없는 자리는 술어상 없다 — 그래도 **빈 칸으로 새지
 *  않는다**(조용한 폴백 금지). 이 줄이 보이면 술어와 문안 표가 갈렸다는 뜻이다. */
export const TPL_STANDING_FALLBACK_COPY =
  "템플릿 상태를 확인해 주세요.";

/** FAIL(invalid)과 오류·중단·대체를 다른 행동 문구로 가른다 — 재확인 라벨이 그 분리다. */
export const TPL_RECHECK_LABEL: Record<string, string> = {
  error: "다시 확인",
  interrupted: "다시 확인",
  conflict: "현재 상태로 다시 확인",
  superseded: "현재 상태로 다시 확인",
  source_changed: "현재 상태로 다시 확인",
  changed_while_checking: "현재 상태로 다시 확인",
};

/** 적용 결과 한 줄 재진술 — TemplateApplyStatus 전집. rollback 경로는 없다(#659). */
export function applyNotice(res: Obj): string {
  switch (String(res.status || "")) {
    case "applied": return "변경사항을 적용했습니다.";
    case "already_applied": return "이미 적용되어 있는 변경사항입니다.";
    case "applied_then_advanced":
      return "이 변경사항은 적용된 뒤 다른 적용이 이어졌습니다. 현재 상태로 다시 확인하세요.";
    case "conflict": return "확인 이후 작업 상태가 바뀌어 적용하지 못했습니다. 현재 상태로 다시 확인하세요.";
    case "superseded": return "새 확인이 시작되어 이 변경사항은 대체되었습니다.";
    case "rejected": return "이 변경사항은 더 이상 적용할 수 없습니다.";
    default: return `적용 결과: ${String(res.status || "미상")}`;
  }
}
