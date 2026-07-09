"""얇은 CLI — 자동화·수동 검증용.

    python -m hwpxfiller.cli --template T.hwpx --data data.xlsx --out ./out \
        --pattern "공고서-{{계약명}}"
    python -m hwpxfiller.cli --template T.hwpx --fields   # 요구 필드만 출력
    # 나라장터 취득 → 매핑 프로파일로 템플릿 채우기(영문키→한글필드)
    python -m hwpxfiller.cli --template T.hwpx --source nara \
        --service-key KEY --bgn 202606010000 --end 202606302359 \
        --profile mapping.json --out ./out
    python -m hwpxfiller.cli diff OLD.hwpx NEW.hwpx [--html out.html]  # 개정 비교
    python -m hwpxfiller.cli schema T.hwpx [--out schema.json]  # 템플릿 스키마 추출
    python -m hwpxfiller.cli fieldize T.hwpx [--out compiled.hwpx]  # {{토큰}}→누름틀
    python -m hwpxfiller.cli lint T.hwpx [--vocab words.txt]  # 템플릿 위생 점검
    python -m hwpxfiller.cli drift OLD.hwpx NEW.hwpx  # 판본 간 필드 드리프트
    python -m hwpxfiller.cli render TPL.txt --data d.xlsx [--profile p.json] [--record N] [--clip]  # 텍스트 치환
"""

from __future__ import annotations

import argparse
import sys

from .batch import generate_batch
from .core.engine import HwpxEngine
from .core.validate import validate
from .data.excel import ExcelDataSource


def _diff_main(argv: "list[str]") -> int:
    """``diff`` 하위명령 — 두 HWPX 를 비교해 요약 출력, 선택적 HTML 저장."""
    from .core.diff import diff_files, render_html, render_summary

    ap = argparse.ArgumentParser(prog="hwpxfiller diff")
    ap.add_argument("old", help="이전 판본 HWPX 경로")
    ap.add_argument("new", help="새 판본 HWPX 경로")
    ap.add_argument("--html", default=None, help="HTML 리포트 저장 경로")
    args = ap.parse_args(argv)

    result = diff_files(args.old, args.new)
    print(render_summary(result), end="")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(result))
        print(f"\nHTML 리포트 저장: {args.html}", file=sys.stderr)
    return 0


def _schema_main(argv: "list[str]") -> int:
    """``schema`` 하위명령 — 템플릿 스키마(필드·타입·표 영역)를 JSON 으로 출력/저장."""
    import json

    from .core.schema import extract_schema

    ap = argparse.ArgumentParser(prog="hwpxfiller schema")
    ap.add_argument("template", help="HWPX 템플릿 경로")
    ap.add_argument("--out", default=None, help="JSON 저장 경로(생략 시 표준출력)")
    args = ap.parse_args(argv)

    payload = json.dumps(extract_schema(args.template).to_dict(), ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"스키마 저장: {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


def _fieldize_main(argv: "list[str]") -> int:
    """``fieldize`` 하위명령 — 평문 ``{{토큰}}`` 을 누름틀로 컴파일.

    명시성 원칙: ``--out`` 없으면 dry-run(무엇을 바꿀지 미리보기만), ``--out`` 지정 시에만
    실제 컴파일 후 저장.
    """
    from .core.authoring import compile_document, scan_tokens

    ap = argparse.ArgumentParser(prog="hwpxfiller fieldize")
    ap.add_argument("template", help="평문 토큰이 든 HWPX 경로")
    ap.add_argument("--out", default=None, help="컴파일 결과 저장 경로(생략 시 미리보기만)")
    args = ap.parse_args(argv)

    if not args.out:
        sites = scan_tokens(args.template)
        compilable = [s for s in sites if s.compilable]
        skipped = [s for s in sites if not s.compilable]
        print(f"[미리보기] 컴파일 가능 {len(compilable)}개 / 건너뜀 {len(skipped)}개")
        for s in compilable:
            print(f"  + {s.name}  ({s.context})")
        for s in skipped:
            print(f"  ! {s.name}  — {s.reason}", file=sys.stderr)
        print("실제 변환하려면 --out <경로> 를 지정하세요.")
        return 0

    pkg, report = compile_document(args.template)
    for s in report.skipped:
        print(f"  [건너뜀] {s.name} — {s.reason}", file=sys.stderr)
    if not report.modified:
        print("컴파일할 토큰이 없습니다(이미 누름틀이거나 토큰 없음).")
        return 0
    pkg.save(args.out)
    print(f"컴파일 완료: 필드 {len(report.compiled)}개 -> {args.out}")
    return 0


def _lint_main(argv: "list[str]") -> int:
    """``lint`` 하위명령 — 단일 템플릿 위생 점검(유사 필드명·미치환 토큰·어휘).

    이슈가 있으면 종료코드 1(자동화에서 게이트로 쓰기 위함).
    """
    from .core.lint import lint_template

    ap = argparse.ArgumentParser(prog="hwpxfiller lint")
    ap.add_argument("template", help="HWPX 템플릿 경로")
    ap.add_argument("--vocab", default=None, help="통제 어휘 사전(한 줄에 필드명 하나)")
    args = ap.parse_args(argv)

    vocabulary = None
    if args.vocab:
        with open(args.vocab, encoding="utf-8") as fh:
            vocabulary = [ln.strip() for ln in fh if ln.strip()]

    report = lint_template(args.template, vocabulary=vocabulary)
    if not report.findings:
        print("이슈 없음.")
        return 0
    for f in report.findings:
        print(f"  [{f.severity}] {f.kind}: {f.message}")
    return 1 if report.has_issues else 0


def _drift_main(argv: "list[str]") -> int:
    """``drift`` 하위명령 — 두 템플릿의 필드셋 변화(추가/삭제/개명)."""
    from .core.lint import diff_schema

    ap = argparse.ArgumentParser(prog="hwpxfiller drift")
    ap.add_argument("old", help="이전 판본 HWPX")
    ap.add_argument("new", help="새 판본 HWPX")
    args = ap.parse_args(argv)

    drift = diff_schema(args.old, args.new)
    if not drift.has_changes:
        print("필드셋 변화 없음.")
        return 0
    for n in drift.added:
        print(f"  + 추가: {n}")
    for n in drift.removed:
        print(f"  - 삭제: {n}")
    for r in drift.renamed:
        print(f"  ~ 개명(추정): {r['old']} -> {r['new']} (유사도 {r['score']})")
    return 0


def _copy_to_clipboard(text: str) -> None:
    """결과를 OS 클립보드로 복사(best-effort). 실패해도 표준출력/파일 경로가 있으니 치명 아님."""
    import subprocess

    try:
        if sys.platform.startswith("win"):
            # PowerShell Set-Clipboard 가 유니코드(한글)를 안전하게 처리.
            cmd = ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"]
        elif sys.platform == "darwin":
            cmd = ["pbcopy"]
        else:
            cmd = ["xclip", "-selection", "clipboard"]
        subprocess.run(cmd, input=text, text=True, check=True)
        print("클립보드로 복사했습니다.", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[안내] 클립보드 복사 실패({exc}). 표준출력/--out 을 쓰세요.", file=sys.stderr)


def _render_main(argv: "list[str]") -> int:
    """``render`` 하위명령 — 텍스트 템플릿에 데이터 1건을 치환(온나라 기안 등 즉각 복사용).

    순수 ``{{필드}}`` 치환이다. ``--profile`` 을 주면 소스 레코드에 매핑 프로파일을 적용해
    **표시형까지 서식된 값**(예: `150,000,000원`)으로 채운다(HWPX 생성 경로와 동일 모델).
    없으면 원본 값 그대로. 데이터에 없는 필드는 토큰을 남기고 stderr 로 시끄럽게 신고한다.
    """
    from .core.text_render import render_record

    ap = argparse.ArgumentParser(prog="hwpxfiller render")
    ap.add_argument("template", help="텍스트 템플릿 경로(.txt 등, {{필드}} 토큰)")
    ap.add_argument("--data", required=True, help="엑셀/CSV 데이터 경로")
    ap.add_argument("--profile", default=None,
                    help="매핑 프로파일 JSON(소스→필드 + 표시형 적용). 없으면 원본 값 치환")
    ap.add_argument("--record", type=int, default=1, help="렌더할 레코드 번호(1-based, 기본 1)")
    ap.add_argument("--sheet", default=None, help="엑셀 시트명(기본: 첫 시트)")
    ap.add_argument("--out", default=None, help="출력 파일 경로(생략 시 표준출력)")
    ap.add_argument("--clip", action="store_true", help="결과를 클립보드로 복사")
    args = ap.parse_args(argv)

    with open(args.template, encoding="utf-8") as fh:
        template = fh.read()
    records = ExcelDataSource(args.data, sheet=args.sheet).records()
    if not records:
        print("데이터에 레코드가 없습니다.", file=sys.stderr)
        return 1
    idx = args.record - 1
    if idx < 0 or idx >= len(records):
        print(f"--record {args.record} 범위 밖(1..{len(records)}).", file=sys.stderr)
        return 1

    record = records[idx]
    if args.profile:
        from .core.mapping import MappingProfile
        record = MappingProfile.load(args.profile).apply(record)  # 표시형까지 서식된 값

    text, report = render_record(template, record)
    if report.missing_fields:
        print(f"[경고] 데이터에 없는 필드(토큰 유지): {', '.join(report.missing_fields)}",
              file=sys.stderr)
    if report.empty_fields:
        print(f"[안내] 값이 비어있는 필드: {', '.join(report.empty_fields)}", file=sys.stderr)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"렌더 저장: {args.out}", file=sys.stderr)
    else:
        print(text)
    if args.clip:
        _copy_to_clipboard(text)
    return 0


def _load_records(ap: argparse.ArgumentParser, args) -> "list[dict[str, str]]":
    """``--source`` 에 따라 데이터 소스를 만들고 레코드를 취득한다.

    나라장터는 영문 코드 키를 반환하므로, 한글 템플릿 필드로 채우려면 대개 ``--profile``
    이 함께 필요하다(호출부에서 적용). 필수 인자 누락은 ``ap.error`` 로 종료.
    """
    if args.source == "nara":
        from .data.nara import NaraStdDataSource

        missing = [
            name for name, val in
            (("--service-key", args.service_key), ("--bgn", args.bgn), ("--end", args.end))
            if not val
        ]
        if missing:
            ap.error(f"--source nara 에는 {', '.join(missing)} 가 필요합니다")
        src = NaraStdDataSource(
            args.service_key, args.bgn, args.end,
            num_rows=args.num_rows, page_no=args.page,
        )
        records = src.records()
        print(f"[나라장터] {len(records)}건 취득 (기간 {args.bgn}~{args.end})", file=sys.stderr)
        if not args.profile:
            print("[주의] 나라장터 키는 영문 코드입니다. --profile 없이는 한글 템플릿 필드와 "
                  "맞지 않아 대부분 빈칸으로 생성됩니다.", file=sys.stderr)
        return records

    # 기본: 엑셀/CSV
    if not args.data:
        ap.error("--data 가 필요합니다 (또는 --fields, 또는 --source nara)")
    return ExcelDataSource(args.data, sheet=args.sheet).records()


def main(argv: "list[str] | None" = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "diff":
        return _diff_main(argv[1:])
    if argv and argv[0] == "schema":
        return _schema_main(argv[1:])
    if argv and argv[0] == "fieldize":
        return _fieldize_main(argv[1:])
    if argv and argv[0] == "lint":
        return _lint_main(argv[1:])
    if argv and argv[0] == "drift":
        return _drift_main(argv[1:])
    if argv and argv[0] == "render":
        return _render_main(argv[1:])

    ap = argparse.ArgumentParser(prog="hwpxfiller")
    ap.add_argument("--template", required=True, help="HWPX 템플릿 경로")
    ap.add_argument("--source", choices=["excel", "nara"], default="excel",
                    help="데이터 소스 (기본: excel)")
    ap.add_argument("--data", help="엑셀/CSV 데이터 경로 (--source excel)")
    ap.add_argument("--out", default="./out", help="결과 저장 폴더")
    ap.add_argument("--pattern", default="output-{{ID}}", help="파일명 패턴({{키}})")
    ap.add_argument("--sheet", default=None, help="엑셀 시트명(기본: 첫 시트)")
    ap.add_argument("--profile", default=None,
                    help="매핑 프로파일 JSON(소스 키→템플릿 필드; 나라장터 영문키에 사실상 필수)")
    ap.add_argument("--fields", action="store_true", help="템플릿 요구 필드만 출력")
    # 나라장터 취득 옵션(--source nara)
    ap.add_argument("--service-key", default=None, help="data.go.kr ServiceKey (--source nara)")
    ap.add_argument("--bgn", default=None, help="공고 시작일시 YYYYMMDDHHMM (--source nara)")
    ap.add_argument("--end", default=None, help="공고 종료일시 YYYYMMDDHHMM (bgn 과 1개월 이내)")
    ap.add_argument("--num-rows", type=int, default=100, help="나라장터 페이지당 건수(기본 100)")
    ap.add_argument("--page", type=int, default=1, help="나라장터 페이지 번호(기본 1)")
    args = ap.parse_args(argv)

    engine = HwpxEngine()

    if args.fields:
        for f in engine.required_fields(args.template):
            print(f)
        return 0

    records = _load_records(ap, args)

    if args.profile:
        from .core.mapping import MappingProfile
        profile = MappingProfile.load(args.profile)
        records = profile.apply_all(records)

    report = validate(engine.required_fields(args.template), records)
    if report.missing_columns:
        print(f"[경고] 데이터에 없는 필드(빈칸 생성): {', '.join(report.missing_columns)}",
              file=sys.stderr)
    if report.empty_valued:
        print(f"[경고] 값이 비어있는 필드: {', '.join(report.empty_valued)}", file=sys.stderr)

    batch = generate_batch(args.template, records, args.out, args.pattern, engine)
    print(f"완료: {batch.succeeded}/{batch.total} 성공 -> {args.out}")
    for res in batch.results:
        if not res.ok:
            print(f"  [실패] {res.output_path}: {res.error}", file=sys.stderr)
    return 0 if batch.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
