/* 산출물 관찰 시트 — 만들어진 문서의 실물을 읽기 전용으로 보는 면(S7-03 · #825).

   ## 예고가 아니라 실물이다(#820 D4)

   이 파일이 그리는 것은 **생성 후** 실물, 그것도 디스크에서 다시 읽어 기록 digest 와 대조를
   통과한 bytes 의 구조다. 생성 **전** 값을 그리던 확인 면(`job_preview.ts`)은 #957 에서
   철거됐으므로 어휘가 갈릴 상대도 없지만, 그 어휘 규율은 남는다 — 골격 관용구
   (`.modal-card .sheet-card`·`.sheet-head`/`.sheet-body`)만 공유하고 클래스는 `artifact-*`,
   제목과 문안은 '산출물 관찰' 계열로 간다.

   ## 상태를 여기서 판정하지 않는다

   열림·대상·성립 여부·구조·사유는 전부 Python 스냅샷(`artifact_view`)에서 온다. 이 층이
   하는 일은 그 값을 자리에 놓는 것뿐이다 — 코드가 뜻하는 바를 문안으로 옮기는 지도 하나만
   여기 산다.

   ## 못 본 것을 본 것처럼 그리지 않는다(#820 D3)

   구조 뷰는 문단과 표만 그린다. 커널이 모델링하지 못한 구간은 '표시하지 못한 구간'으로
   **항상 병기**한다. 부분 포섭은 거절이 아니므로 관찰은 그대로 서고 그 옆에 사유가 붙는다.
   관찰이 아예 서지 않은 넷은 각각 다른 문장으로 말한다. 빈 화면으로 접지 않는다. */

import { Fragment, createElement } from "react";
import type { ReactNode } from "react";

import type { JobRunController } from "./job_run.ts";
import { ARTIFACT_REFUSAL_TITLE, useRun, useRunSnapshot } from "./job_run.ts";

type Obj = Record<string, any>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 셀 하나 — 병합 메타(`span`)는 그대로 colspan/rowspan 이 된다. 값이 없으면 속성을 걸지
 *  않는다: 1을 명시하면 병합이 없는 표와 있는 표가 DOM 에서 구분되지 않는다. */
function Cell(props: { cell: Obj; keyName: string }): ReactNode {
  const cell = props.cell;
  // 키 이름은 원문 `cellSpan`/`cellAddr` 그대로다(hwpxcore 가 해석 없이 나른다).
  const span = (cell.span || {}) as Obj;
  const colspan = Number(span.colSpan || 1);
  const rowspan = Number(span.rowSpan || 1);
  const addr = (cell.addr || {}) as Obj;
  return h("td", {
    key: props.keyName,
    colSpan: colspan > 1 ? colspan : undefined,
    rowSpan: rowspan > 1 ? rowspan : undefined,
    "data-addr": `${String(addr.rowAddr ?? "")},${String(addr.colAddr ?? "")}`,
  }, ...blocks((cell.blocks || []) as Obj[], `${props.keyName}-b`));
}

/** 문단·표를 문서 순서대로 — 표 셀 안에는 다시 블록이 있으므로 재귀한다(중첩 표 포함). */
function blocks(list: Obj[], keyPrefix: string): ReactNode[] {
  return list.map((block, index) => {
    const key = `${keyPrefix}-${index}`;
    if (block.type === "paragraph") {
      return h("p", { key, className: "artifact-para" }, String(block.text || ""));
    }
    const rows = (block.rows || []) as Obj[][];
    return h("table", { key, className: "artifact-table" },
      h("tbody", null,
        ...rows.map((row, rowIndex) => h("tr", { key: `${key}-r${rowIndex}` },
          ...row.map((cell, cellIndex) => createElement(Cell as any, {
            key: `${key}-r${rowIndex}-c${cellIndex}`,
            keyName: `${key}-r${rowIndex}-c${cellIndex}`,
            cell,
          }))))));
  });
}

function Region(props: { region: Obj; label: string; keyName: string }): ReactNode {
  return h("section", { className: "picker-sec", key: props.keyName },
    h("div", { className: "cap" }, props.label),
    ...blocks((props.region.blocks || []) as Obj[], props.keyName));
}

/** 표시하지 못한 구간 — **언제나** 선다(#820 D3). 없으면 '없음' 이라고 말한다: 키째 지우면
 *  완전한 관찰과 부분 관찰이 화면에서 같아 보이고, 사용자는 못 본 구간을 본 것으로 읽는다. */
function Unrendered(props: { structure: Obj }): ReactNode {
  const regions = (props.structure.unrendered_regions || {}) as Obj;
  const counts = (regions.counts || {}) as Record<string, number>;
  const examples = (regions.examples || {}) as Record<string, unknown>;
  const names = Object.keys(counts).sort();
  const partial = props.structure.partial_coverage === true;
  return h("section", {
    className: "picker-sec artifact-unrendered", id: "artifactUnrendered",
    "data-partial": partial ? "true" : "false",
    "aria-labelledby": "artifactUnrenderedCap",
  },
    h("div", { className: "cap", id: "artifactUnrenderedCap" }, "표시하지 못한 구간"),
    partial
      ? createElement(Fragment, null,
          h("p", { className: "note warnbox", id: "artifactCoverageCode" },
            `이 문서에는 여기서 그리지 못한 구간이 있습니다(${String(props.structure.coverage_code || "")}). 실제 문서를 열어 확인하세요.`),
          h("ul", { className: "plain-list capnote", id: "artifactUnrenderedList" },
            ...names.map((name) => h("li", { key: name },
              `${name}: ${String(counts[name])}곳`,
              examples[name] ? ` (예: ${String(examples[name])})` : ""))))
      : h("p", { className: "muted capnote" }, "없음. 문서 전체를 구조로 읽었습니다."));
}

/** 미치환 표식 — 빈 값이 빈칸으로 새지 않고 표식으로 남는 것이 제품 계약이라, 실물에 그
 *  표식이 남았다면 세어서 드러낸다. 0건이면 그 사실을 말한다(침묵은 정보가 아니다). */
function MissingMarkers(props: { structure: Obj }): ReactNode {
  const markers = (props.structure.missing_value_markers || []) as Obj[];
  return h("section", {
    className: "picker-sec artifact-markers", id: "artifactMarkers",
    "aria-labelledby": "artifactMarkersCap",
  },
    h("div", { className: "cap", id: "artifactMarkersCap" }, "빈 값 표식"),
    markers.length
      ? h("ul", { className: "plain-list capnote", id: "artifactMarkerList" },
          ...markers.map((marker) => h("li", { key: String(marker.field || "") },
            `${String(marker.field || "")}: ${String(marker.count || 0)}곳`)))
      : h("p", { className: "muted capnote" }, "없음."));
}

export function JobArtifactSheet(props: { controller: JobRunController }): ReactNode {
  const snapshot = useRunSnapshot(props.controller);
  const run = useRun(props.controller);
  const view = (snapshot?.artifact_view || {}) as Obj;
  const status = String(view.status || "");
  const structure = (view.structure || null) as Obj | null;
  const filename = String(view.filename || "");
  const observed = status === "observed" && structure !== null;
  const sections = (structure?.sections || []) as Obj[];
  const headers = (structure?.headers || []) as Obj[];
  const footers = (structure?.footers || []) as Obj[];
  const saved = run.artifactSave;

  return h("div", { className: "modal-card sheet-card artifact-sheet" },
    h("div", { className: "sheet-head" },
      h("h3", { id: "artifactTitle" },
        filename ? `산출물 관찰: ${filename}` : "산출물 관찰"),
      h("button", {
        className: "btn", id: "artifactClose", type: "button",
        onClick: props.controller.closeArtifact,
      }, "닫기")),
    h("div", { className: "sheet-body artifact-sheet-body" },
      h("p", { className: "modal-sub" },
        "만들어진 문서를 다시 읽어 그린 내용입니다. 글꼴과 쪽 모양은 그리지 않습니다."),
      observed
        ? createElement(Fragment, null,
            ...headers.map((region, index) => createElement(Region as any, {
              key: `h${index}`, keyName: `h${index}`, region, label: "머리말",
            })),
            ...sections.map((region, index) => createElement(Region as any, {
              key: `s${index}`, keyName: `s${index}`, region, label: "본문",
            })),
            ...footers.map((region, index) => createElement(Region as any, {
              key: `f${index}`, keyName: `f${index}`, region, label: "꼬리말",
            })),
            createElement(MissingMarkers as any, { structure }),
            createElement(Unrendered as any, { structure }))
        : h("section", {
            className: "picker-sec artifact-refused", id: "artifactRefused",
            "data-status": status,
          },
            h("p", { className: "note dangerbox", id: "artifactRefusedTitle" },
              ARTIFACT_REFUSAL_TITLE[status] || "문서를 확인하지 못했습니다"),
            h("p", { className: "capnote", id: "artifactRefusedDetail" },
              String(view.detail || "")))),
    h("div", { className: "modal-actions" },
      h("span", {
        className: "capnote", id: "artifactSaveNote", role: "status",
        "aria-live": "polite",
      }, saved),
      h("button", {
        className: "btn primary", id: "artifactSaveAs", type: "button",
        // 저장의 원료는 관찰한 bytes 다. 관찰이 서지 않은 상태에서 버튼을 살려 두면
        // 「저장할 수 있을 것 같은」 미끼가 되고, 실제로 눌리면 백엔드가 거절한다.
        disabled: !observed,
        onClick: () => { void props.controller.saveArtifactAs(); },
      }, "다른 이름으로 저장")));
}
