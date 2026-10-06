"""얇은 CLI — 자동화·수동 검증용.

    python -m hwpxfiller.cli --template T.hwpx --data data.xlsx --out ./out \
        --pattern "공고서-{{계약명}}"
    python -m hwpxfiller.cli --template T.hwpx --fields   # 요구 필드만 출력
    # 나라장터 취득 → 매핑 프로파일로 템플릿 채우기(영문키→한글필드)
    python -m hwpxfiller.cli --template T.hwpx --source nara \
        --service-key KEY --bgn 202606010000 --end 202606302359 \
        --profile mapping.json --out ./out
    python -m hwpxfiller.cli schema T.hwpx [--out schema.json]  # 템플릿 스키마 추출
    python -m hwpxfiller.cli fieldize T.hwpx [--out compiled.hwpx]  # {{토큰}}→누름틀
    python -m hwpxfiller.cli lint T.hwpx [--vocab words.txt]  # 템플릿 위생 점검
    python -m hwpxfiller.cli drift OLD.hwpx NEW.hwpx  # 판본 간 필드 드리프트
    python -m hwpxfiller.cli render TPL.txt --data d.xlsx [--profile p.json] [--record N] [--clip]  # 텍스트 치환
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from datetime import datetime
from typing import TYPE_CHECKING

from pathlib import Path

if TYPE_CHECKING:  # 런타임 결합 회피 — 저장소는 덕타이핑으로 충분.
    from .data.secret_store import SecretStore
from .external.hwpx_engine import make_hwpx_engine
from .external.hwpx_package_io import read_hwpx_package, write_hwpx_package
from .external.atomic import write_text_atomic
from .domain.job import DEFAULT_FILENAME_PATTERN
from .data.nara import NaraFetchError
from .viewmodel.result_errors import describe_fill_note
from .naming import pattern_field_tokens
from .domain.validation import validate
from .data.excel import ExcelDataSource, ambiguous_sheets


def _schema_main(argv: "list[str]") -> int:
    """``schema`` 하위명령 — 템플릿 스키마(필드·타입·표 영역)를 JSON 으로 출력/저장."""
    import json

    from .domain.schema import extract_schema

    ap = argparse.ArgumentParser(prog="hwpxfiller schema")
    ap.add_argument("template", help="HWPX 템플릿 경로")
    ap.add_argument("--out", default=None, help="JSON 저장 경로(생략 시 표준출력)")
    args = ap.parse_args(argv)

    payload = json.dumps(
        extract_schema(read_hwpx_package(args.template)).to_dict(), ensure_ascii=False, indent=2
    )
    if args.out:
        write_text_atomic(args.out, payload)  # 원자 쓰기(RC-01) — 실패해도 기존 파일 무손상
        print(f"스키마 저장: {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


def _fieldize_main(argv: "list[str]") -> int:
    """``fieldize`` 하위명령 — 평문 ``{{토큰}}`` 을 누름틀로 컴파일.

    명시성 원칙: ``--out`` 없으면 dry-run(무엇을 바꿀지 미리보기만), ``--out`` 지정 시에만
    실제 컴파일 후 저장.
    """
    from .domain.authoring import compile_document, scan_tokens

    ap = argparse.ArgumentParser(
        prog="hwpxfiller fieldize",
        description="누름틀 변환 — 평문 {{토큰}}을 누름틀 필드로 바꿉니다(GUI '누름틀 변환'과 동일).",
    )
    ap.add_argument("template", help="평문 토큰이 든 HWPX 경로")
    ap.add_argument("--out", default=None, help="누름틀 변환 결과 저장 경로(생략 시 미리보기만)")
    args = ap.parse_args(argv)

    if not args.out:
        sites = scan_tokens(read_hwpx_package(args.template))
        compilable = [s for s in sites if s.compilable]
        skipped = [s for s in sites if not s.compilable]
        print(f"[미리보기] 변환 가능 {len(compilable)}개 / 건너뜀 {len(skipped)}개")
        for s in compilable:
            print(f"  + {s.name}  ({s.context})")
        for s in skipped:
            print(f"  ! {s.name}  — {s.reason}", file=sys.stderr)
        print("실제 변환하려면 --out <경로> 를 지정하세요.")
        return 0

    package = read_hwpx_package(args.template)
    _, report = compile_document(package)
    for s in report.skipped:
        print(f"  [건너뜀] {s.name} — {s.reason}", file=sys.stderr)
    if not report.modified:
        print("변환할 토큰이 없습니다(이미 누름틀이거나 토큰 없음).")
        return 0
    write_hwpx_package(args.out, package)
    print(f"누름틀 변환 완료: 필드 {len(report.compiled)}개 -> {args.out}")
    return 0


def _lint_main(argv: "list[str]") -> int:
    """``lint`` 하위명령 — 단일 템플릿 위생 점검(유사 필드명·미치환 토큰·어휘).

    이슈가 있으면 종료코드 1(자동화에서 게이트로 쓰기 위함).
    """
    from .external.template_inspection import lint_template_file

    ap = argparse.ArgumentParser(prog="hwpxfiller lint")
    ap.add_argument("template", help="HWPX 템플릿 경로")
    ap.add_argument("--vocab", default=None, help="통제 어휘 사전(한 줄에 필드명 하나)")
    args = ap.parse_args(argv)

    vocabulary = None
    if args.vocab:
        # utf-8-sig: 메모장·PowerShell(Set-Content -Encoding utf8) 기본이 BOM 을 남긴다 —
        # 첫 필드명이 '﻿필드명'으로 오염돼 위양성 게이트 실패가 되는 것을 차단(RC-33).
        with open(args.vocab, encoding="utf-8-sig") as fh:
            vocabulary = [ln.strip() for ln in fh if ln.strip()]

    report = lint_template_file(args.template, vocabulary=vocabulary)
    if not report.findings:
        print("이슈 없음.")
        return 0
    for f in report.findings:
        print(f"  [{f.severity}] {f.kind}: {f.message}")
    return 1 if report.has_issues else 0


def _drift_main(argv: "list[str]") -> int:
    """``drift`` 하위명령 — 두 템플릿의 필드셋 변화(추가/삭제/개명)."""
    from .external.template_inspection import diff_template_schemas

    ap = argparse.ArgumentParser(prog="hwpxfiller drift")
    ap.add_argument("old", help="구판 HWPX")
    ap.add_argument("new", help="신판 HWPX")
    args = ap.parse_args(argv)

    drift = diff_template_schemas(args.old, args.new)
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

    **구간 표기가 있는 템플릿은 거절한다**(S10-04 · #861). 그 템플릿을 물질화하려면 「포함할
    내용」 선택과 그 선택을 봉인한 실행 계획이 있어야 하는데, CLI 에는 Work 도 선택 축도 없다.
    선택 없이 치환만 하면 산출물은 **고르지 않은 선택지와 마커 텍스트를 그대로 실은** 문서가
    된다 — 조용히 그것을 내주는 대신 작업대를 안내하고 멈춘다.
    """
    from .domain.text_render import render_record
    from .domain.text_structure import scan_text_structure

    ap = argparse.ArgumentParser(prog="hwpxfiller render")
    ap.add_argument("template", help="텍스트 템플릿 경로(.txt 등, {{필드}} 토큰)")
    ap.add_argument("--data", required=True, help="엑셀/CSV 데이터 경로")
    ap.add_argument("--profile", default=None,
                    help="매핑 프로파일 JSON(소스→필드 + 표시형 적용). 없으면 원본 값 치환. "
                         "작업(.job.json)의 mapping 과 같은 형식의 독립 JSON 입니다")
    ap.add_argument("--record", type=int, default=1, help="렌더할 레코드 번호(1-based, 기본 1)")
    ap.add_argument("--sheet", default=None, help="엑셀 시트명(기본: 첫 시트)")
    ap.add_argument("--out", default=None, help="출력 파일 경로(생략 시 표준출력)")
    ap.add_argument("--clip", action="store_true", help="결과를 클립보드로 복사")
    args = ap.parse_args(argv)

    with open(args.template, encoding="utf-8") as fh:
        template = fh.read()
    markers = scan_text_structure(template).summary.markers
    if markers:
        print(
            f"구간 표기가 {markers}건 있는 템플릿입니다 — 이 명령은 '포함할 내용'을 고를 수 "
            "없어 문서를 만들 수 없습니다.\n"
            "문서나르미의 '문서 만들기'에서 이 작업을 실행하고 검토·복사 작업대에서 복사하세요.",
            file=sys.stderr,
        )
        return 1
    _require_sheet_if_ambiguous(ap, args.data, args.sheet)
    records = ExcelDataSource(args.data, sheet=args.sheet).records()
    if not records:
        print("데이터에 레코드가 없습니다.", file=sys.stderr)
        return 1
    idx = args.record - 1
    if idx < 0 or idx >= len(records):
        print(f"--record {args.record} 범위 밖(1..{len(records)}).", file=sys.stderr)
        return 1

    record: dict[str, object] = dict(records[idx])
    if args.profile:
        from .external.mapping_store import load_mapping_profile

        record = dict(load_mapping_profile(args.profile).apply(record))  # 표시형까지 서식된 값

    text, report = render_record(template, record)
    if report.missing_fields:
        print(f"[경고] 데이터에 없는 필드(토큰 유지): {', '.join(report.missing_fields)}",
              file=sys.stderr)
    if report.empty_fields:
        print(f"[안내] 값이 비어있는 필드: {', '.join(report.empty_fields)}", file=sys.stderr)

    if args.out:
        write_text_atomic(args.out, text)  # 원자 쓰기(RC-01) — 실패해도 기존 파일 무손상
        print(f"렌더 저장: {args.out}", file=sys.stderr)
    else:
        print(text)
    if args.clip:
        _copy_to_clipboard(text)
    return 0


def _resolve_service_key(
    ap: argparse.ArgumentParser, args, store: "SecretStore | None",
) -> "str | None":
    """나라 ServiceKey 를 우선순위대로 해석한다(없으면 ``None``).

    우선순위(스펙: 1급 입력 > 비권장 입력 > 저장된 키):
        ``--service-key-file`` > ``DATA_GO_KR_KEY`` 환경변수 > ``--service-key``(비권장) > 저장된 키.

    근거: ``--service-key-file`` 과 환경변수는 노출 없는 **1급 입력**(브리핑 명세)이라 최상위 —
    파일이 더 명시적이라 환경변수보다 앞선다. 인라인 ``--service-key`` 는 프로세스 목록·셸
    히스토리에 노출되는 **비권장·제거 예정** 경로라 1급 입력들 아래로 강등하되(경고 발행),
    수동적으로 저장된 키보다는 위에 둬 명시적 override 가 동작하게 한다. 저장소(OS 자격증명)는
    재공급 없이 재사용하는 마지막 폴백.
    """
    if getattr(args, "service_key_file", None):
        try:
            with open(args.service_key_file, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            ap.error(f"--service-key-file 읽기 실패: {exc}")
    env = os.environ.get("DATA_GO_KR_KEY")
    if env and env.strip():
        return env.strip()
    if getattr(args, "service_key", None):
        print("[보안 경고] --service-key 로 키를 명령행에 직접 넘기면 프로세스 목록·셸 "
              "히스토리에 노출됩니다(비권장·향후 제거 예정). --service-key-file 또는 "
              "DATA_GO_KR_KEY 환경변수를 쓰세요.", file=sys.stderr)
        return args.service_key
    from .data.secret_store import NARA_SERVICE_KEY_NAME, default_secret_store

    if store is None:
        store = default_secret_store()
    return store.get(NARA_SERVICE_KEY_NAME)


def _require_sheet_if_ambiguous(
    ap: argparse.ArgumentParser, path: str, sheet: "str | None"
) -> None:
    """다중 시트 워크북에서 ``--sheet`` 미지정을 loud 게이트 — 조용한 첫 시트 추측 금지(#2).

    ``--sheet`` 가 명시됐거나 CSV·단일 시트면 통과("모호할 때만 묻는다"). 2+ 시트인데
    미지정이면 시트 목록을 stderr 에 나열하고 ``ap.error`` 로 중단(exit 2, ``--sheet`` 요구).
    판정 단일 출처는 :func:`ambiguous_sheets`(빈 목록=CSV·단일=물을 것 없음, 비면 모호) —
    웹 시트 선택 게이트(#33)와 같은 판정을 공유한다.
    """
    if sheet is not None:
        return
    overview = ambiguous_sheets(path)
    if overview:
        listing = "\n".join(
            f"  - {name} ({rows}행 x {cols}열)" for name, rows, cols in overview
        )
        ap.error(
            f"'{path}' 에 시트가 여러 개입니다 — 조용히 첫 시트를 쓰지 않습니다. "
            f"--sheet <이름> 으로 지정하세요:\n{listing}"
        )


def _load_records(
    ap: argparse.ArgumentParser, args, store: "SecretStore | None" = None,
) -> "list[dict[str, str]]":
    """``--source`` 에 따라 데이터 소스를 만들고 레코드를 취득한다.

    나라장터는 영문 코드 키를 반환하므로, 한글 템플릿 필드로 채우려면 대개 ``--profile``
    이 함께 필요하다(호출부에서 적용). 필수 인자 누락은 ``ap.error`` 로 종료.
    """
    if args.source == "pclm":
        from .data.pclm import PclmDataSource, list_sqlite_sheets

        # DB 자리는 사람이 짚는다 — 다른 프로그램의 설치 자리를 추측하던 기본 자리는
        # 걷혔다(그 배치에 기대는 조용한 기본값). 나라 소스의 필수 인자 문형 그대로 멈춘다.
        if not args.db:
            ap.error("--source pclm 에는 --db 가 필요합니다")
        # 시트마다 한 줄의 뜻이 달라 문서 건수가 갈린다 — 고르지 않은 채로 한 면을
        # 추측하면 계약 20건 대신 품목 200건이 조용히 나온다. 그래서 그 DB 의 시트
        # 목록(뷰 먼저, 다음 표 — 고정 허용목록은 걷혔다)을 보이고 멈춘다.
        if not args.view:
            try:
                sheets = list_sqlite_sheets(args.db)
            except RuntimeError as exc:
                # 열기 실패를 원시 traceback 으로 흘리지 않는다(RC-16). 파일 부재는
                # OSError 라 최상위 번역 경계가 받는다.
                ap.error(str(exc))
            listing = "\n".join(f"  {name}" for name in sheets)
            ap.error(
                "--source pclm 에는 --view <이름> 이 필요합니다 — 조용히 기본 뷰를 "
                f"쓰지 않습니다:\n{listing}"
            )
        src = PclmDataSource(db=args.db, view=args.view)
        try:
            records = src.records()
        except (RuntimeError, ValueError) as exc:
            # 열기·읽기 실패와 그 DB 에 없는 시트(쓸 수 있는 시트를 재진술한다)를 원시
            # traceback 으로 흘리지 않는다(RC-16). 파일 부재는 OSError 라 최상위 번역
            # 경계가 받는다.
            ap.error(str(exc))
        # 읽은 DB 의 경로를 소스가 든 그대로 되뇐다 — 어디를 읽었는지가 조용하면 다른 DB 를
        # 읽고도 알 수 없다(경로 재해석 금지, src.db 가 단일 출처).
        print(f"[계약 목록] {src.db} 의 {src.view} 에서 {len(records)}건", file=sys.stderr)
        return records

    if args.source == "nara":
        from .data.nara import NaraStdDataSource

        service_key = _resolve_service_key(ap, args, store)
        missing = [
            name for name, val in (("--bgn", args.bgn), ("--end", args.end)) if not val
        ]
        if not service_key:
            missing.append("서비스키(--service-key-file/--service-key/DATA_GO_KR_KEY/저장된 키)")
        if missing:
            ap.error(f"--source nara 에는 {', '.join(missing)} 가 필요합니다")
        assert service_key is not None
        src = NaraStdDataSource(
            service_key, args.bgn, args.end,
            num_rows=args.num_rows, page_no=args.page,
        )
        records = src.records()
        print(f"[나라장터] {len(records)}건 취득 (기간 {args.bgn}~{args.end})", file=sys.stderr)
        if not args.profile:
            print("[주의] 나라장터 키는 영문 코드입니다. --profile 없이는 한글 템플릿 필드와 "
                  "맞지 않아 대부분 빈 값으로 생성됩니다.", file=sys.stderr)
        return records

    # 기본: 엑셀/CSV
    if not args.data:
        ap.error("--data 가 필요합니다 (또는 --fields, 또는 --source nara/--source pclm)")
    _require_sheet_if_ambiguous(ap, args.data, args.sheet)
    return ExcelDataSource(args.data, sheet=args.sheet).records()


# 최상위 --help 가 실제 CLI 표면(하위명령 6종)을 그대로 보이게 한다(RC-21) —
# 디스패치가 pre-argparse 수동 비교라 subparsers 없이는 epilog 가 유일한 노출면.
_SUBCOMMANDS_EPILOG = """\
하위명령(자세한 도움말: hwpxfiller <하위명령> --help):
  schema TPL.hwpx           템플릿 스키마(필드·타입·표 영역)를 JSON 으로 추출
  fieldize TPL.hwpx         평문 {{토큰}} → 누름틀 변환(--out 없으면 미리보기)
  lint TPL.hwpx             템플릿 위생 점검(--vocab 통제 어휘) — 이슈 있으면 exit 1
  drift OLD.hwpx NEW.hwpx   판본 간 필드 드리프트(추가/삭제/개명)
  render TPL.txt --data D   텍스트 템플릿 치환(온나라 기안 등)
  diff                      별도 제품·별도 저장소로 분리됨(hwpxdiff OLD.hwpx NEW.hwpx)
"""


def _force_utf8_output() -> None:
    """Windows redirected consoles에서도 한국어 CLI 출력을 손실 없이 쓴다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: "list[str] | None" = None, *, secret_store: "SecretStore | None" = None) -> int:
    """CLI 진입점 — 최상위 오류 번역 경계(RC-16).

    일상 실패(파일 접근·손상 HWPX·나라장터 취득)를 원시 traceback 대신 '[오류]'
    한국어 1줄로 번역하고 **exit 2** 로 끝낸다 — lint 의 '이슈 게이트 exit 1'
    (문서화된 계약)·생성 부분실패 exit 1 과 크래시를 종료코드로 구분해 자동화의
    실패 종류 오분류(성공 배치 재실행 유발 등)를 막는다.
    """
    _force_utf8_output()
    try:
        return _run(argv, secret_store=secret_store)
    except NaraFetchError as exc:
        print(f"[오류] 나라장터 취득 실패: {exc}", file=sys.stderr)
        return 2
    except zipfile.BadZipFile as exc:
        print(f"[오류] HWPX(zip) 파일이 아니거나 손상됐습니다: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        name = getattr(exc, "filename", None)
        detail = f"{name} — {exc.strerror or exc}" if name else str(exc)
        print(f"[오류] 파일을 읽거나 쓸 수 없습니다: {detail}", file=sys.stderr)
        return 2
    except ValueError as exc:
        # 프로파일/매핑 로드의 버전 스큐·손편집(미지 transform 등)이 원시 traceback 으로
        # 새지 않게 최상위에서 번역한다(RC-16). 생성 경계의 ValueError 는 _run 내부에서
        # 이미 exit 1 로 처리되므로 여기까지 오는 건 로드·구성 단계의 실패다.
        print(f"[오류] {exc}", file=sys.stderr)
        return 2


def _run(argv: "list[str] | None" = None, *, secret_store: "SecretStore | None" = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "diff":
        # 개정 비교는 별도 제품·별도 저장소(hwpxdiff)다 — 손에 익은 진입점만 안내.
        print("diff 는 별도 제품 hwpxdiff 입니다: hwpxdiff OLD.hwpx NEW.hwpx [--html out.html]\n"
              "  설치: https://github.com/rfastball/hwpx-diff",
              file=sys.stderr)
        return 2
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

    # 여기까지 왔으면 알려진 하위명령이 아니다. generate(기본 경로)는 positional 을
    # 받지 않으므로, 대시로 시작하지 않는 첫 토큰은 오타난 하위명령이다 — 조용히
    # generate 로 흘려보내 '--template 필요'로 오도(사용자는 하위명령을 의도)하지 말고,
    # 이름을 짚어 시끄럽게 거절한다(confirm-or-alarm: 조용한 추측 금지).
    if argv and not argv[0].startswith("-"):
        print(f"[오류] 알 수 없는 하위명령: {argv[0]!r}", file=sys.stderr)
        print("문서 생성은 'hwpxfiller --template ...' 이고, 하위명령은 아래와 같습니다:",
              file=sys.stderr)
        print(_SUBCOMMANDS_EPILOG, file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(
        prog="hwpxfiller",
        epilog=_SUBCOMMANDS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--template", required=True, help="HWPX 템플릿 경로")
    ap.add_argument("--source", choices=["excel", "nara", "pclm"], default="excel",
                    help="데이터 소스 (기본: excel). pclm 은 계약 목록 DB 의 시트(뷰·표)이며 "
                         "--view 가 필수입니다")
    ap.add_argument("--data", help="엑셀/CSV 데이터 경로 (--source excel)")
    ap.add_argument("--out", default="./out", help="결과 저장 폴더")
    ap.add_argument("--pattern", default=DEFAULT_FILENAME_PATTERN,
                    help="파일명 패턴({{필드}}, 기본 %(default)s). 토큰은 템플릿 필드 이름이며 "
                         "연결된 값으로 채워집니다 — 풀 수 없는 토큰은 오류")
    ap.add_argument("--sheet", default=None, help="엑셀 시트명(기본: 첫 시트)")
    ap.add_argument("--profile", default=None,
                    help="매핑 프로파일 JSON(소스 키→템플릿 필드; 나라장터 영문키에 사실상 필수). "
                         "작업(.job.json)의 mapping 과 같은 형식의 독립 JSON 입니다")
    ap.add_argument("--fields", action="store_true", help="템플릿 요구 필드만 출력")
    ap.add_argument("--overwrite", action="store_true",
                    help="같은 이름의 기존 산출물 덮어쓰기 허용(옵트인). 없으면 대상 "
                         "파일이 하나라도 이미 있을 때 생성 전체를 차단하고 종료코드 1")
    ap.add_argument("--ack-empty", action="store_true",
                    help="값이 비어 있는 필드를 확인했음을 표시(옵트인) — 빈 필드에 "
                         "미입력 표식(〘미입력·필드명〙)을 넣고 진행. 없으면 빈 값 "
                         "발견 시 생성 전체를 차단하고 종료코드 1")
    ap.add_argument("--ledger", action="store_true",
                    help="생성 원장 JSON 사이드카를 out 폴더에 저장(opt-in) — "
                         "소스 프로파일·dry-run 매니페스트·주입 되읽기 증거. "
                         "값은 텍스트이며 HWPX 렌더가 아님")
    # 나라장터 취득 옵션(--source nara)
    ap.add_argument("--service-key", default=None,
                    help="data.go.kr ServiceKey 인라인(비권장·노출 위험). "
                         "--service-key-file/DATA_GO_KR_KEY/저장된 키를 우선 쓰세요")
    ap.add_argument("--service-key-file", default=None,
                    help="ServiceKey 를 담은 파일 경로(권장 — 프로세스 목록/히스토리 미노출)")
    ap.add_argument("--bgn", default=None, help="공고 시작일시 YYYYMMDDHHMM (--source nara)")
    ap.add_argument("--end", default=None, help="공고 종료일시 YYYYMMDDHHMM (bgn 과 1개월 이내)")
    ap.add_argument("--num-rows", type=int, default=100, help="나라장터 페이지당 건수(기본 100)")
    ap.add_argument("--page", type=int, default=1, help="나라장터 페이지 번호(기본 1)")
    # 계약 목록(pclm) 옵션(--source pclm)
    ap.add_argument("--db", default=None,
                    help="pclm SQLite 경로 (필수, --source pclm)")
    ap.add_argument("--view", default=None,
                    help="pclm 시트(뷰·표) 이름 (필수, --source pclm). 이름 목록은 미지정 시 안내")
    args = ap.parse_args(argv)

    engine = make_hwpx_engine()

    if args.fields:
        for f in engine.required_fields(args.template):
            print(f)
        return 0

    from .data.nara import NaraFetchError

    try:
        records = _load_records(ap, args, secret_store)
    except NaraFetchError as exc:
        # 데이터 경계 게이트(RC-03) — 인증 실패/기간 위반을 '0건 성공'으로 넘기지 않는다.
        print(f"[오류] 나라장터 취득 실패: {exc}", file=sys.stderr)
        return 1
    source_records = records  # managed 는 매핑 전 원천 값을 받는다(연결 판본이 매핑한다).

    from .domain.mapping import FieldMapping, MappingProfile

    # 이 실행의 기준 시각 — 사전 게이트의 값 계산(``today`` 유형 등)이 쓴다.
    now = datetime.now()
    required = engine.required_fields(args.template)
    source_keys = _source_schema_keys(source_records)
    profile = None
    if args.profile:
        from .domain.fill_ledger import template_path_drift
        from .external.mapping_store import load_mapping_profile

        profile = load_mapping_profile(args.profile)
        drift = template_path_drift(args.template, profile, engine=engine)
        if drift.has_drift:
            # 문구는 describe() 단일화(RC-03) — GUI 경계와 같은 문장.
            print("[오류] 템플릿 구조 드리프트 — " + drift.describe(sep="; "),
                  file=sys.stderr)
            return 1
        records = profile.apply_all(records, now=now)
    # 프로파일 없는 직접 채우기 — 「같은 이름 열을 그대로」의 항등 연결이다. 데이터에 없는
    # 필드는 **명시적 비움**(빈 고정값)으로 연결한다: 연결되지 않은 필드는 실행 계획이
    # 서지 않으므로, 종전 경고(「빈 값 생성」)가 말하던 결과를 연결로 선언한다.
    mapping = profile or MappingProfile(
        mappings=[
            FieldMapping(f, f) if f in source_keys else FieldMapping(f, type="const")
            for f in required
        ]
    )
    if profile is None:
        missing = [f for f in required if f not in source_keys]
        if missing:
            print(f"[경고] 데이터에 없는 필드(빈 값 생성): {', '.join(missing)}",
                  file=sys.stderr)
    # 명시적 비움(빈 고정값)은 빈 값 게이트의 대상이 아니다 — 사람이 이미 「이 필드는
    # 비운다」고 답한 자리라, 표식도 붙이지 않고 확인도 다시 묻지 않는다.
    checked = [f for f in required if f not in set(mapping.declared_empty_fields())]
    report = validate(checked, records)
    if report.missing_columns:
        print(f"[경고] 데이터에 없는 필드(빈 값 생성): {', '.join(report.missing_columns)}",
              file=sys.stderr)
    if report.empty_valued:
        # ADR-E 빈값 게이트의 CLI 이식(RC-03) — 기본 차단, --ack-empty 옵트인 시 GUI 와
        # 같은 미입력 표식으로 진행(표식은 managed 레코드 검증이 GUI 와 같은 규칙으로 넣는다).
        from .domain.job import MISSING_MARKER

        if not args.ack_empty:
            print("[오류] 값이 비어 있는 필드가 있습니다 — 표식 없이 조용히 생성하지 "
                  f"않습니다: {', '.join(report.empty_valued)}", file=sys.stderr)
            print("확인했으면 --ack-empty 를 지정하세요(빈 필드에 "
                  f"'{MISSING_MARKER.format(field='필드명')}' 표식을 넣고 진행).",
                  file=sys.stderr)
            return 1
        print(f"[안내] 미입력 표식 주입: {', '.join(report.empty_valued)}", file=sys.stderr)

    # 파일명 계약 사전검증(RC-20) — 미치환 {{토큰}}이 조용히 실파일명이 되는 경로 차단.
    # 토큰은 연결된 템플릿 필드의 값으로 푼다(GUI 와 같은 배달 계획) — 필드가 아닌 원천 열
    # 이름은 배달 계획이 OUTPUT_NAME_TOKEN_UNRESOLVED 로 거절한다.
    name_tokens = pattern_field_tokens(args.pattern)
    if records and name_tokens:
        unresolved = [t for t in name_tokens if not any(t in rec for rec in records)]
        if unresolved:
            ap.error(
                "파일명 패턴의 토큰이 데이터에 없어 그대로 파일명이 됩니다: "
                + ", ".join("{{" + t + "}}" for t in unresolved)
                + " — --pattern 을 데이터 키에 맞게 지정하세요"
            )

    # 생성 척추는 GUI 와 같은 managed 파이프라인이다(#1081 PR3) — 임시 작업공간에 이 실행만의
    # Work 를 세워 초기 등록 → 연결 판본 → 봉인 → 레코드 검증 → 배달 계획 → 물질화 → 배달·되읽기.
    # CLI 의 게이트 부재(검토 게이트·완주 스탬프·취소 없음)는 의도된 제품 계약이다.
    import tempfile

    from .external.headless_generation import run_headless_generation

    with tempfile.TemporaryDirectory(prefix="hwpxfiller-cli-", ignore_cleanup_errors=True) as ws:
        result = run_headless_generation(
            workspace=Path(ws),
            template_path=args.template,
            mapping=mapping,
            filename_pattern=args.pattern,
            records=source_records,
            source_schema_keys=source_keys,
            output_directory=args.out,
            overwrite=args.overwrite,
            clock=datetime.now,
        )
    return _report_generation(args, result)


def _source_schema_keys(records: "list[dict[str, str]]") -> "tuple[str, ...]":
    """원천 레코드의 열 이름 — 첫 등장 순서, 레코드마다 빠진 열도 합친다."""
    keys: dict[str, None] = {}
    for record in records:
        for key in record:
            keys.setdefault(key, None)
    return tuple(keys)


def _report_generation(args, result) -> int:
    """managed 결과를 CLI 문장·종료 코드로 번역한다(RC-16 — 게이트 1 · 환경 2).

    판정은 이미 났다 — 여기서는 사실을 말하고, 파일을 만들었으면 원장(--ledger)을 남긴다.
    """
    from .external.delivery_coordinator import DeliveryAborted, DeliveryCompleted
    from .external.headless_generation import (
        TEMPLATE_INITIALIZATION,
        HeadlessExecuted,
        HeadlessNeedsOverwrite,
        HeadlessRefused,
    )
    from .external.managed_generation import ManagedReadBackFailed

    if isinstance(result, HeadlessNeedsOverwrite):
        # 기본은 차단(RC-02) — 기존 산출물(수기 보정본일 수 있음)의 무경고 파괴 금지.
        print("[오류] 같은 이름의 파일이 이미 있어 덮어쓰게 됩니다: "
              + ", ".join(result.conflict_names), file=sys.stderr)
        print("덮어쓰려면 --overwrite 를 지정하세요.", file=sys.stderr)
        return 1
    if isinstance(result, HeadlessRefused):
        if result.code == "PATH_OCCUPANCY_OBSERVATION_FAILED":
            # --out 자리가 폴더가 아니거나 읽을 수 없다 — 환경성 실패(exit 2, RC-16).
            print(f"[오류] 파일을 읽거나 쓸 수 없습니다: {args.out} — "
                  + "; ".join(result.details), file=sys.stderr)
            return 2
        if result.stage == TEMPLATE_INITIALIZATION:
            print("[오류] 이 템플릿을 문서 작업으로 초기화할 수 없어 생성할 수 없습니다"
                  f"({result.code}). 템플릿 파일을 확인하세요.", file=sys.stderr)
            return 1
        print(f"[오류] 문서를 만들지 않았습니다({result.code}).", file=sys.stderr)
        for line in result.details:
            print(f"  {line}", file=sys.stderr)
        return 1
    assert isinstance(result, HeadlessExecuted)
    outcome = result.outcome
    if not isinstance(outcome, (DeliveryCompleted, DeliveryAborted, ManagedReadBackFailed)):
        # 배달 전 거절(구간 표기·무결성·레코드 재검증) — write 0.
        code = getattr(outcome, "code", type(outcome).__name__)
        print(f"[오류] 문서를 만들지 않았습니다({code}): {getattr(outcome, 'detail', '')}",
              file=sys.stderr)
        return 1
    total = len(result.resolved_delivery.ordered_items)
    delivered = outcome.delivered
    succeeded = len(delivered) - (1 if isinstance(outcome, ManagedReadBackFailed) else 0)
    print(f"완료: {succeeded}/{total} 성공 -> {args.out}")
    if isinstance(outcome, DeliveryAborted):
        failed = result.resolved_delivery.ordered_items[outcome.failed_item_ordinal]
        print(f"  [실패] {failed.resolved_output_relative_path}: {outcome.detail}",
              file=sys.stderr)
        unstarted = total - len(delivered) - 1
        if unstarted:
            print(f"  [미착수] {unstarted}건 — 앞서 쓴 문서는 그대로 유지됩니다.",
                  file=sys.stderr)
    if isinstance(outcome, ManagedReadBackFailed):
        doc = delivered[outcome.failed_item_ordinal]
        print(f"  [실패] {doc.relative_path}: 만든 뒤 다시 읽어 확인하지 못했습니다"
              f"({outcome.detail})", file=sys.stderr)
    seen_notes = set()
    for doc in delivered:
        for note in doc.execution_notes:
            # 완화 처리(경고 후 진행, #154)도 무음이면 조용한 데이터 손실 — RC-03 동형.
            # 노트는 템플릿 구조 속성이라 배치 전체에서 한 번만 알린다.
            if note in seen_notes:
                continue
            seen_notes.add(note)
            print(f"  [주의] {describe_fill_note(note)}", file=sys.stderr)

    if args.ledger:
        try:
            _export_ledger(args, result)
        except Exception as exc:  # noqa: BLE001 - 증거 저장 실패는 조용히 넘기지 않는다
            # 원장은 사이드카 — 실패해도 '생성 실패'로 위장하지 않는다(RC-16, GUI 와 동형).
            print(f"[원장 실패] 사이드카를 저장하지 못했습니다: {exc} — "
                  f"생성물({succeeded}건)은 저장돼 있습니다.", file=sys.stderr)
    return 0 if isinstance(outcome, DeliveryCompleted) else 1


def _export_ledger(args, result) -> None:
    """``--ledger`` opt-in — managed 배달 원장 사이드카를 out 폴더에 저장한다.

    GUI 「문서 만들기」가 배달마다 남기는 것과 **같은 원장**(``managed-delivery/v1``:
    봉인 basis·plan digest, 문서별 처분·output digest·완화 노트, 중단 사실)이다(#1081 PR3).
    ``work_authority_id`` 는 이 실행의 임시 Work 라 실행을 가리킬 뿐 재사용되지 않는다.
    소스 표기는 포인터-온리(경로·기간·뷰) — 나라 쿼리 URL·ServiceKey 는 박제하지 않는다.
    파일명은 실행별 타임스탬프(RC-02) — 재실행이 이전 실행의 증거를 덮지 않는다.
    """
    from .application.execution_contract_set import plan_semantic_digest
    from .external.ledger_export import write_managed_delivery_ledger

    if args.source == "nara":
        source = f"nara:표준입찰공고 {args.bgn}~{args.end}"
    elif args.source == "pclm":
        from .data.pclm import PclmDataSource

        # 포인터는 소스가 만든다 — 문자열을 여기서 재조립하면 표기가 둘로 갈린다.
        # 값을 읽지 않는 순수 구성이라 원장 저장이 DB 를 다시 열지 않는다.
        source = PclmDataSource(db=args.db, view=args.view).source_pointer()
    else:
        source = f"file:{args.data}"
    sidecar = write_managed_delivery_ledger(
        result.resolved_delivery.output_directory,
        generated_at=result.validated_at,
        work_authority_id=result.work_authority_id,
        execution_basis_digest=result.execution_basis_digest,
        plan_semantic_digest=plan_semantic_digest(result.plan_payload),
        result=result.outcome,
        source=source,
    )
    print(f"[원장] {sidecar} 저장", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
