"""공문서 라벨·문맥 증거 — 자리 앞 라벨이 어느 열을 가리키는가, 자리가 고정 문구 안인가.

실험 엔진 ``decision/heuristic.py``·``decision/gongmun.py`` 의 이식이다.

* **kordoc** (github.com/chrisryugj/kordoc @ 878b700, MIT, (c) 2026 chrisryugj)에서 옮긴 것은 항목마다
  ``[kordoc: 파일]`` 로 적는다 — 라벨 정규화와 접두 일치 비율, 라벨 칸 판정, 목록 머리 기호(서수 음절 가드),
  직함 목록, 법령 문서 종류 낱말. 고지는 저장소 ``THIRD_PARTY_NOTICES`` 에 있다.
* **엔진 자체 규칙**(kordoc 에 없음): 조달 라벨 동의어 표, 머리말 복합어 규칙(「품명」→「세부품명」), 따옴표
  제목·인용 법령 발행처·이어지는 라벨 단서, 일반·당위 문장 단서(Krifka et al. 1995), 「한 값 한 자리」
  (Arasu & Garcia-Molina 2003 의 역할 구분을 한 문서로 줄인 것).

모든 함수는 문자열만 받는다 — 문맥 ``left`` 는 자리 앞 글자이며 줄 경계는 ``\\n`` 이다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# ------------------------------------------------------------------ kordoc ports
# [kordoc: src/hwpx/outline.ts] 목록 머리 기호(법령식 번호, 상자·글머리 기호)
LEGAL_RE = re.compile(r"^(\d{1,2}\.|[가-힣]\.|\d{1,2}\)|[가-힣]\)|\(\d{1,2}\)|\([가-힣]\)|[①-⑳]|[㉮-㉻])\s+")
BOX_RE = re.compile(r"^([□■❑❏ㅁ○ㅇ◦●❍◎\-–―—ㅡ‣▪▫ㆍ·•∙])\s+")
# [kordoc: src/shared/numbering.ts hangulOrdinal; gen-gongmun-fit.ts ORDINAL_SYLLABLES] 가나다… 거너더… (84)
ORDINAL_SYLLABLES = {chr(0xAC00 + i * 588 + v * 28) for v in (0, 4, 8, 13, 18, 20)
                     for i in (0, 2, 3, 5, 6, 7, 9, 11, 12, 14, 15, 16, 17, 18)}
# [kordoc: src/form/recognize.ts]
NUMERIC_VALUE_RE = re.compile(
    r"^제?\d+(?:[.,]\d+)*[십백천만억조]*(?:원|명|건|개|회|부|매|장|점|호|번|년|월|일|시|분|초|개월|주년|차례|퍼센트)?$")
SENTENCE_ENDING_RE = re.compile(r"(?:입니다|합니다|습니다|하세요|십시오|시오|바랍니다|바람|할 것|할것|하며|하고|한다|된다|됨|음|임)$")
# [kordoc: src/redact-name-address.ts TITLES] (사람 이름 뒤에 오는 직함만)
TITLES = ("회장", "사장", "이사장", "위원장", "대표", "대표이사", "장관", "차관", "청장", "처장", "실장", "국장", "과장",
          "팀장", "계장", "부장", "차장", "대리", "주임", "주무관", "사무관", "서기관", "연구관", "연구사", "연구원",
          "담당", "담당자", "교수", "원장", "소장", "센터장", "관장", "본부장", "지점장", "담당관")
# 공고의 연락처 줄에 쓰는 군 계급(kordoc TITLES 에 없음 — 엔진 자체 추가)
RANKS = ("상사", "중사", "하사", "원사", "준위", "소위", "중위", "대위", "소령", "중령", "대령", "군무원")
# [kordoc: src/hwpx/outline.ts LAW_CODE_RE] 문서 종류 낱말; 엔진 추가: 세부기준, 계약예규, 규칙
INSTRUMENTS = ("고시", "훈령", "예규", "지침", "규정", "세부기준", "계약예규", "규칙", "조례", "시행령", "시행규칙", "법률")
_MARKER_ONLY = re.compile(r"[\s□■❑❏ㅁ○ㅇ◦●❍◎\-–―—ㅡ‣▪▫ㆍ·•∙]*")


def normalize_label(text: str) -> str:
    """[kordoc: src/form/match.ts normalizeLabel] + 전각 쌍점·공백 접기."""
    return re.sub(r"[:：\s()（）·　]", "", text.strip())


def _marker(line: str) -> re.Match[str] | None:
    """줄 머리의 목록 기호 하나 — 「는.」처럼 서수 음절이 아닌 한글 한 글자는 기호가 아니다."""
    found = LEGAL_RE.match(line) or BOX_RE.match(line)
    if found is None:
        return None
    token = found.group(1)
    if re.fullmatch(r"[가-힣][.)]|\([가-힣]\)", token) and re.sub(r"[.()]", "", token) not in ORDINAL_SYLLABLES:
        return None  # [kordoc: gen-gongmun-fit.ts]
    return found


def strip_markers(line: str) -> str:
    """줄 머리의 목록 기호(1. 가. 1) 가) (1) ① ㉮ □ ○ - …)를 거듭 걷는다."""
    text = line.lstrip()
    for _ in range(4):
        found = _marker(text)
        if found is None:
            break
        text = text[found.end():]
    return text


def leading_marker(line: str) -> tuple[int, str] | None:
    """줄 머리의 법령식 번호 기호와 그 층위(0=「1.」 … 7=「㉮」) — 위치 표지(``where``)가 쓴다."""
    text = line.lstrip()
    found = LEGAL_RE.match(text)
    if found is None or _marker(text) is None:
        return None
    token = found.group(1)
    patterns = (r"\d{1,2}\.", r"[가-힣]\.", r"\d{1,2}\)", r"[가-힣]\)", r"\(\d{1,2}\)", r"\([가-힣]\)",
                r"[①-⑳]", r"[㉮-㉻]")
    level = next(index for index, pattern in enumerate(patterns) if re.fullmatch(pattern, token))
    return level, token


def raw_label(left: str, how: str) -> str:
    """사람에게 보일 라벨 원문 — 쌍점 라벨은 쌍점까지(「수량:」), 라벨 칸은 칸 글자, 앞 낱말은 그 낱말."""
    line = left.rsplit("\n", 1)[-1]
    if how == "colon":
        index = max(line.rfind(":"), line.rfind("："))
        return " ".join(strip_markers(line[:index]).split()) + line[index]
    if how == "cell":
        return " ".join(strip_markers(left.rsplit("\n", 2)[-2]).split())
    return label_before(strip_markers(line))


def is_label_cell(text: str) -> bool:
    """[kordoc: src/form/recognize.ts isLabelCell] — 열쇠말 목록 없이(우리 열쇠말은 열 이름이다)."""
    stripped = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰*※]+$", "", text.strip())
    if not stripped or len(stripped) > 30:
        return False
    compact = re.sub(r"\s", "", stripped)
    return bool(re.fullmatch(r"[가-힣0-9()（）·:：\-]+", compact) and 2 <= len(compact) <= 12
                and len(re.findall(r"[가-힣]", compact)) >= 2
                and (len(compact) <= 8 or len(stripped.split()) <= 2)
                and not NUMERIC_VALUE_RE.fullmatch(compact) and not SENTENCE_ENDING_RE.search(compact)
                and not re.match(r"^[(（]주[)）]|^주식회사", compact))


# ------------------------------------------------------------------ engine lexicon
# 조달·기안 라벨 동의어 — 같은 자료를 부르는 라벨 묶음(엔진 자체 사전, kordoc 에 없음).
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("공고명", "사업명", "건명", "입찰건명", "요청건명", "계약건명", "구매건명", "용역명"),
    ("계약방법", "입찰방법", "입찰방식", "계약방식"),
    ("계약상대자", "업체명", "상호", "계약업체", "대표계약업체", "계약자", "낙찰자"),
    ("수요기관", "발주기관", "요청기관", "수요처"),
    ("추정가격", "추정금액"),
    ("사업예산", "예산액", "배정예산", "사업비", "예산"),
    ("계약금액", "계약액", "계약금"),
    ("납품기한", "납기", "납품일자", "납품기일", "납품기간"),
    ("담당자", "담당", "담당공무원", "계약담당자", "담당자명"),
    ("담당자전화번호", "전화번호", "연락처", "전화", "문의처"),
    ("입찰공고번호", "공고번호"),
    ("개찰일시", "개찰일", "개찰시각"),
    ("입찰마감일시", "입찰서마감", "접수마감일시", "마감일시"),
    ("세부품명", "품명", "물품명"),
    ("수량", "구매수량"),
    ("시행일", "시행일자"),
    ("수신자", "수신"),
)


def _synonym_index() -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for group in SYNONYM_GROUPS:
        for a in group:
            index.setdefault(a, set()).update(b for b in group if b != a)
    return index


SYNONYMS = _synonym_index()
_LABEL = re.compile(r"([\w가-힣 ]{1,20})[:：]?\s*$")


def label_before(left: str) -> str:
    """자리 바로 앞 줄 끝의 낱말들(엔진 ``heuristic.label_before``)."""
    line = left.rsplit("\n", 1)[-1]
    found = _LABEL.search(line)
    return (found.group(1) if found else line).strip()


def _bigrams(text: str) -> set[str]:
    text = re.sub(r"[\s_\-.]", "", text.lower())
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def name_overlap(label: str, column: str) -> float:
    """열 이름 글자쌍 중 라벨에도 있는 비율(엔진 ``heuristic.name_overlap``)."""
    a, b = _bigrams(label), _bigrams(column.rsplit(".", 1)[-1])
    if not a or not b:
        return 0.0
    return len(a & b) / len(b)


# ------------------------------------------------------------------ label evidence
def _colon_label(line: str) -> tuple[str, str] | None:
    """줄에 쌍점 라벨이 있으면 (정규화 라벨, 방식). 쌍점과 자리 사이에 다른 값이 있으면 빈 라벨이다."""
    index = max(line.rfind(":"), line.rfind("："))
    if index < 0:
        return None
    gap = line[index + 1:]
    if len(gap.strip()) > 25 or ":" in gap:
        return None
    head = strip_markers(line[:index])
    if len(normalize_label(head)) > 16:
        head = re.split(r"[,;]|\s{2,}(?=\S{3,})", head)[-1]
    label = normalize_label(head)[-16:]
    if not label:
        return None
    # 쌍점과 자리 사이의 다른 값: 라벨은 그 첫 값의 것이다 — 복합 라벨(「수량 및 단위: 6 SET」)만 예외.
    if not gap.strip() or re.search(r"및|/|ㆍ|,", label):
        return label, "colon"
    return "", "colon-but-value-between"


def extract_label(left: str) -> tuple[str, str]:
    """(정규화 라벨, 방식) — 자리 줄의 ``라벨:``, 자리 바로 앞 낱말, 자리가 줄을 열면 앞 줄의 라벨 칸 순."""
    line = left.rsplit("\n", 1)[-1]
    colon = _colon_label(line)
    if colon is not None:
        return colon
    stripped = strip_markers(line)
    if _MARKER_ONLY.fullmatch(stripped):
        stripped = ""  # 값에 붙은 기호만 있는 줄(「-무정전 전원장치」): 위 칸을 본다
    if stripped.strip():
        return normalize_label(label_before(stripped)), "before"
    previous = strip_markers(left.rsplit("\n", 2)[-2] if "\n" in left else "")
    # 앞 줄이 「라벨: 값」이면 그 줄은 라벨 칸이 아니다(이식하며 더한 가드 — 짧은 값의 오인을 막는다).
    if is_label_cell(previous) and not re.search(r"[:：]\s*\S", previous):
        return normalize_label(previous), "cell"
    return "", "none"


def label_matches(label: str, column: str, *, fuzzy: bool) -> str | None:
    """정규화 ``label`` 이 정규화 ``column`` 을 어떻게 부르는가, 아니면 None.

    ``fuzzy`` 는 글자쌍 대체를 허용한다 — 진짜 라벨(``라벨:``·라벨 칸)에만, 산문의 앞 낱말에는 쓰지 않는다.
    """
    if not label or not column:
        return None
    parts = [part for part in re.split(r"및|/|,|、|ㆍ", label) if len(part) >= 2] or [label]
    for part in parts:
        how = _part_matches(part, column)
        if how is not None:
            return how
    if fuzzy and name_overlap(label, column) >= 0.5:
        return "bigram"
    return None


def _prefix_match(part: str, column: str) -> str | None:
    """[kordoc: src/form/match.ts findMatchingKey] 같음·접두(0.6)·역접두(0.75) 비율."""
    if part == column:
        return "exact"
    if part.startswith(column) and len(column) >= len(part) * 0.6:
        return "prefix"
    if column.startswith(part) and len(part) >= len(column) * 0.75:
        return "prefix-reverse"
    return None


def _part_matches(part: str, column: str) -> str | None:
    prefix = _prefix_match(part, column)
    if prefix is not None:
        return prefix
    if len(part) >= 2 and column.endswith(part):
        return "head-final"  # 품명 → 세부품명: 한국어 복합어는 머리가 뒤에 온다(엔진 규칙)
    if len(column) >= 2 and part.endswith(column):
        return "head-final-label"  # 담당자전화번호 → 전화번호
    synonyms = SYNONYMS.get(part, set())
    if column in synonyms or any(column.endswith(word) and len(word) >= 2 for word in synonyms):
        return "synonym"
    return None


# ------------------------------------------------------------------ static / data cues
#: 일반·당위 문장(Krifka et al. 1995) — 모든 문서에 같은 규칙을 말하는 문장. 필드는 이 사건의 사실을 싣는다.
GENERIC_PREDICATE = re.compile(
    r"(?:하여야|해야|되어야)\s?(?:한다|합니다|하며|하고|함)|(?:할|될|볼)\s?수\s?(?:있다|있습니다|있으며|있고|없다|없습니다|없으며)"
    r"|아니한다|아니합니다|아니하는|않는다|않습니다|(?:으로|로)\s?한다|에\s?따른다|에\s?따릅니다|준용한다|한한다|해당한다"
    r"|경우에는|경우에|때에는|바랍니다|하여서는")
#: 「한 값 한 자리」 — 문서의 진짜 반복 값(수신자·제목·품명)은 2~4번, 양식 낱말은 그보다 훨씬 많이 나온다.
SLOT_VOCAB_REPEATS = 5
CUE_GENERIC = "generic"
CUE_FIXED = "fixed"
_QUOTES = (("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’"), ("《", "》"), ("〈", "〉"))


def is_slot(prefix: str) -> bool:
    """「라벨: 값」 자리 — 값 바로 앞, 같은 줄에 낱말과 쌍점."""
    return bool(re.search(r"[가-힣A-Za-z)]\s*[:：]\s*$", prefix))


def span_sentence(left: str, span: str, right: str) -> str:
    """자리를 품은 문장(양쪽에서 「.」+공백·줄바꿈으로 자른다)."""
    before = re.split(r"[.。]\s|\n", left)[-1]
    after = re.split(r"[.。](?:\s|$)|\n", right)[0]
    return before + span + after


def _quoted(line_left: str, line_right: str) -> bool:
    """따옴표 제목 안 — 따옴표가 자리보다 더 많은 글자를 감쌀 때만(「사업명」처럼 값만 감싸면 값이다)."""
    for opening, closing in _QUOTES:
        if line_left.count(opening) > line_left.count(closing) and closing in line_right:
            inside_left = line_left[line_left.rfind(opening) + 1:]
            inside_right = line_right[:line_right.find(closing)]
            if inside_left.strip() or inside_right.strip():
                return True
    return False


def static_cue(left: str, span: str, right: str, *, repeats: int, prefixes: Sequence[str]) -> str | None:
    """자리가 고정 문구의 일부라는 단서 — ``CUE_GENERIC``(일반·당위 문장) 또는 ``CUE_FIXED``(그 밖).

    따옴표 제목 안, 이어지는 라벨 안(「변경 ⟦가능⟧ 여부:」), 인용 법령의 발행처(「(⟦조달청⟧ 고시)」),
    일반·당위 문장 안, 다른 곳에 라벨 자리가 있는 값의 산문 반복(「한 값 한 자리」).
    """
    line_left = left.rsplit("\n", 1)[-1]
    line_right = right.split("\n", 1)[0]
    if _quoted(line_left, line_right):
        return CUE_FIXED
    if re.match(r"\s?[가-힣]{1,6}\s*[:：]", line_right):
        return CUE_FIXED
    if re.match(r"\s?(" + "|".join(INSTRUMENTS) + r")(?:[)\s,.」』]|$)", line_right):
        return CUE_FIXED
    if not is_slot(line_left) and GENERIC_PREDICATE.search(span_sentence(left, span, right)):
        return CUE_GENERIC
    if slot_elsewhere(line_left, repeats=repeats, prefixes=prefixes):
        return CUE_FIXED
    return None


def slot_elsewhere(line_left: str, *, repeats: int, prefixes: Sequence[str]) -> bool:
    """문서가 이 값을 다른 곳의 ``라벨: 값`` 자리에 적고, 여기서는 자리 밖 산문으로 되풀이한다."""
    here = line_left[-32:]
    return (repeats >= SLOT_VOCAB_REPEATS and len(prefixes) >= 2 and not is_slot(here)
            and any(is_slot(prefix) for prefix in prefixes if prefix != here))


def data_cue(span: str, right: str) -> bool:
    """사건마다 바뀌는 값의 단서 — 전화번호, 직함·계급이 뒤따르는 사람 이름."""
    text = span.strip()
    titles = "|".join(TITLES + RANKS)
    if re.fullmatch(r"0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}", text):  # [kordoc: recognize.ts inferFieldType]
        return True
    if re.fullmatch(r"[가-힣]{2,4}", text) and re.match(r"\s?(" + titles + r")(?![가-힣])", right):
        return True
    return bool(re.fullmatch(r"[가-힣]{2,4}\s(" + titles + r")", text))


def glued_left(left: str, span: str) -> bool:
    """자리가 낱말 가운데서 시작한다 — 왼쪽에 글자·숫자가 붙어 있다."""
    return bool(left) and bool(span) and left[-1].isalnum() and span[0].isalnum()
