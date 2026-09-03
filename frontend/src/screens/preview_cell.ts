/* 미리보기 칸 — **산출물이 담을 것**을 그대로 말한다(U6 §2.2).
 *
 *  두 호스트가 이 한 렌더러를 쓴다(U6-F #980 리뷰 8): 편집기 2단계의 「미리보기」 열과
 *  「문서 작업」 상세의 「첫 행」 열이다. 둘 다 같은 링1 투영(`row_projection`)의 같은
 *  `preview_kind` 를 받으므로, 스위치를 두 벌 두면 **닫힌 집합이 두 곳에서 갈린다** —
 *  실제로 갈렸다(한쪽이 `blank` 와 `none` 을 한 문자로 접었다).
 *
 *  빈 값이 빈칸으로 새지 않는 것이 이 칸의 존재 이유다: 결속됐는데 이 행에서 값이 없으면
 *  Python 이 실제 표식(`domain/job.MISSING_MARKER`)을 실어 보내고 여기서는 그 문자열을
 *  그대로 그린다(웹이 문안을 짓지 않는다 — 그건 UI 문구가 아니라 문서에 박히는 데이터다).
 *
 *  호스트마다 갈리는 것은 **오류의 문장** 하나다: 편집기에서 `error` 는 이 행의 값 계산이
 *  실패했다는 뜻이고, 상세에서는 데이터 파일을 읽지 못했다는 뜻이라 그 사유가 존 수준에서
 *  온다(행마다 같은 문장이므로 행에 복제하지 않는다). */
import { createElement } from "react";
import type { ReactNode } from "react";

type Obj = Record<string, any>;

/** 빈 칸 마커 — 홑 글자 하나라 `docs/COPY_STYLE_GUIDE.md` §3-1(문장 안 em dash 금지)의
 *  예외다. 문장이 아니라 「여기 값이 없다」는 표식이다. */
export const BLANK_MARK = "—";

/** 값 계산이 실패한 칸의 기본 문장(편집기 어휘). */
const PREVIEW_ERROR_TEXT = "(미리보기 오류)";

export function PreviewCell(props: { row: Obj; errorText?: string }): ReactNode {
  const { row } = props;
  const kind = String(row.preview_kind);
  const span = (className: string, text: string): ReactNode =>
    createElement("span", { className }, text);
  /* `pending`(첫 행을 아직 못 읽음)은 편집기에서 **나오지 않는다** — 그 화면은 데이터를
     이미 들고 있다. 그래도 여기 서는 이유는 집합이 하나이기 때문이다. */
  if (kind === "pending") return span("pv pending", String(row.preview || BLANK_MARK));
  if (kind === "error") return span("pv err", props.errorText || PREVIEW_ERROR_TEXT);
  if (kind === "missing") return span("pv missing", String(row.preview));
  if (kind === "blank") return span("pv blank", "");
  if (kind === "none") return span("pv none", BLANK_MARK);
  return span("pv", String(row.preview));
}
