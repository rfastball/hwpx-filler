/* TXT 저작 린트메모장의 **vendor lifecycle owner**(S10-05 · #862 · #299 회수).
 *
 * CodeMirror 6 를 아는 **유일한** 소스 파일이다(#588 dependency containment:
 * `tests/architecture_contract.toml` `[vendor_integration.codemirror]` 의
 * `allowed_source_roots` 가 이 파일 하나를 가리키고, mount/update/dispose 소유 심볼도
 * 여기 셋뿐이다). 밖으로 나가는 타입에 CodeMirror 타입이 하나도 없다는 것이 그 봉쇄의
 * 검사 가능한 얼굴이다 — `LintpadHandle` 은 `host` 엘리먼트만 드러내고 `EditorView` 는
 * 모듈 지역 `WeakMap` 안에서만 산다.
 *
 * **판정은 여기 없다.** 무엇이 필드 토큰이고 무엇이 구간 마커인지, 표기가 어디서 깨졌는지는
 * 전부 Python 이 말한다(`tpl/txt_lint` → 링0 `scan_text_structure` ·
 * `scan_text_token_spans`). 이 모듈이 하는 일은 그 **문자 오프셋을 데코레이션으로 얹는
 * 것**뿐이다 — 여기서 `{{…}}` 를 다시 정규식으로 가르면 sigil 선행 분류가 두 곳에서
 * 갈리고, 같은 토큰이 표면과 백엔드에서 다른 것이 된다.
 *
 * **키맵을 세우지 않는다.** `@codemirror/commands` 를 들이지 않으므로 Escape·Tab 은
 * CodeMirror 가 소비하지 않고 document 까지 올라간다 — 모달 엔진
 * (`frontend/src/overlay/engine.ts`)의 Escape=이탈 가드·Tab=포커스 트랩 판정이 그대로
 * 선다. 이 창의 출구는 모달 계약 하나여야 하고, 편집기 안쪽 키맵이 그것을 먹으면 dirty
 * 가드가 조용히 우회된다. */
import { EditorState, StateEffect, StateField } from "@codemirror/state";
import type { Extension, Range } from "@codemirror/state";
import { Decoration, EditorView } from "@codemirror/view";
import type { DecorationSet } from "@codemirror/view";

/** Python 이 낸 토큰 좌표 1건 — `domain/text_structure.py::TextTokenSpan` 의 JSON 얼굴. */
export type LintpadSpan = {
  /** `"field"`(누름틀 토큰) 또는 `"marker"`(구간 표기). 여기서 판정하지 않는다. */
  kind: string;
  /** 0-기반 문자 오프셋(반열린 구간). */
  start: number;
  end: number;
};

/** 마운트된 메모장 1개의 **불투명 손잡이** — vendor 타입을 밖으로 내지 않는다. */
export type LintpadHandle = {
  readonly host: HTMLElement;
};

export type LintpadMountSpec = {
  /** 편집기가 들어갈 빈 컨테이너. React 가 소유하는 노드이고 내용은 CodeMirror 가 채운다. */
  host: HTMLElement;
  /** 최초 본문. */
  doc: string;
  /** 컨텐츠 DOM 에 실을 `id`(기존 표면 계약 승계 — 초기 포커스·selftest 프로브가 겨눈다). */
  contentId: string;
  /** 스크린리더용 이름 — 문안 소유는 호출자(표면)다. */
  ariaLabel: string;
  /** 사용자가 친 결과. 매 변경마다 전문(全文)으로 부른다. */
  onDocChanged: (text: string) => void;
};

export type LintpadUpdateSpec = {
  /**
   * 외부에서 갈아 끼울 본문. 지금 문서와 같으면 아무것도 하지 않는다 — 매 키 입력마다
   * 되돌려 넣으면 캐럿이 문서 끝으로 튄다(React 값-되먹임 결함류).
   */
  doc?: string;
  /** 강조 좌표 전집. 넘기지 않으면 기존 강조를 그대로 둔다(문서 변경에 따라 매핑된다). */
  spans?: readonly LintpadSpan[];
};

/** 손잡이 → 실제 뷰. 이 `WeakMap` 이 vendor 타입 봉쇄의 자리다. */
const VIEWS = new WeakMap<LintpadHandle, EditorView>();

const SPAN_CLASS: Record<string, string> = {
  field: "cm-txtField",
  marker: "cm-txtMarker",
};

const setSpans = StateEffect.define<readonly LintpadSpan[]>();

/** 데코를 얹을 수 있는 조각만 남긴 **순수** 투영 — vendor 타입이 없어 단위로 잰다.
 *
 *  Python 의 좌표와 지금 문서 사이에는 늘 시차가 있다(디바운스 왕복). 그래서 세 규칙을
 *  여기서 집행한다: ① 문서 길이로 자른다 ② 앞 조각의 끝보다 뒤에서만 시작한다(RangeSet 은
 *  정렬을 요구하고, 겹친 마크는 얹는 순간 던진다) ③ 모르는 `kind` 는 버린다 —
 *  판정 어휘가 늘었는데 표면이 아직 모르면 **칠하지 않는 것**이 조용히 틀리는 것보다 낫다. */
export function usableSpans(
  spans: readonly LintpadSpan[], docLength: number,
): { from: number; to: number; className: string }[] {
  const usable: { from: number; to: number; className: string }[] = [];
  let cursor = 0;
  for (const span of spans) {
    const className = SPAN_CLASS[span.kind];
    const from = Math.max(cursor, Math.min(span.start, docLength));
    const to = Math.min(span.end, docLength);
    if (className === undefined || to <= from) continue;
    usable.push({ from, to, className });
    cursor = to;
  }
  return usable;
}

/** 좌표 → 데코레이션(위 투영의 vendor 얼굴). */
function decorate(state: EditorState, spans: readonly LintpadSpan[]): DecorationSet {
  const ranges: Range<Decoration>[] = usableSpans(spans, state.doc.length).map(
    (span) => Decoration.mark({ class: span.className }).range(span.from, span.to),
  );
  return Decoration.set(ranges);
}

/** 강조 상태 — 문서가 바뀌면 좌표를 **매핑**해 따라가고, 새 판정이 오면 갈아 끼운다.
 *
 *  매핑이 있어야 왕복(디바운스 180ms)이 도는 사이에도 강조가 글자에 붙어 있다. 새 판정이
 *  도착하면 그 순간의 전집으로 덮으므로 매핑의 누적 오차는 남지 않는다. */
const spanField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    let next = value.map(tr.changes);
    for (const effect of tr.effects) {
      if (effect.is(setSpans)) next = decorate(tr.state, effect.value);
    }
    return next;
  },
  provide: (field) => EditorView.decorations.from(field),
});

/** 메모장 기본 모습 — 색·굵기는 제품 CSS(`frontend/css/editor.css`)가 토큰으로 소유한다.
 *  여기서는 레이아웃만 세운다(vendor 테마가 제품 팔레트를 발명하지 않게 한다). */
const BASE_THEME: Extension = EditorView.theme({
  "&": { fontSize: "var(--fs-body)" },
  "&.cm-focused": { outline: "none" },       // 초점 표지는 제품 CSS 가 그린다
  ".cm-content": { padding: "var(--sp-10)" },
  ".cm-scroller": { lineHeight: "1.6" },
});

/** 마운트 — vendor 인스턴스 생성의 **유일한** 자리(`mount_owner`). */
export function mountLintpad(spec: LintpadMountSpec): LintpadHandle {
  const handle: LintpadHandle = { host: spec.host };
  const view = new EditorView({
    parent: spec.host,
    state: EditorState.create({
      doc: spec.doc,
      extensions: [
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({
          id: spec.contentId,
          "aria-label": spec.ariaLabel,
        }),
        spanField,
        BASE_THEME,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) spec.onDocChanged(update.state.doc.toString());
        }),
      ],
    }),
  });
  VIEWS.set(handle, view);
  return handle;
}

/** 외부 상태 → 뷰(`update_owner`). 문서 교체와 강조 갱신을 **한 트랜잭션**으로 보낸다. */
export function updateLintpad(handle: LintpadHandle, spec: LintpadUpdateSpec): void {
  const view = VIEWS.get(handle);
  if (view === undefined) return;
  const current = view.state.doc.toString();
  const replacing = spec.doc !== undefined && spec.doc !== current;
  if (!replacing && spec.spans === undefined) return;
  view.dispatch({
    changes: replacing
      ? { from: 0, to: view.state.doc.length, insert: spec.doc }
      : undefined,
    effects: spec.spans === undefined ? undefined : setSpans.of(spec.spans),
  });
}

/** 해제(`dispose_owner`) — React 언마운트가 부른다. 두 번 불러도 안전하다. */
export function disposeLintpad(handle: LintpadHandle): void {
  const view = VIEWS.get(handle);
  if (view === undefined) return;
  VIEWS.delete(handle);
  view.destroy();
}
