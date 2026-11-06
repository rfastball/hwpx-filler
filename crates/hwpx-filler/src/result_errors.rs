//! Existing result and fill-note wording shared by generated-document surfaces.

use crate::fields::{FillNote, FillNoteKind};

const ACCESS: &str = "파일 접근이 거부됐습니다. 같은 이름의 문서가 다른 프로그램(한글 등)에 열려 있지 않은지, 폴더 쓰기 권한이 있는지 확인하세요.";
const IN_USE: &str =
    "파일이 다른 프로그램(한글 등)에 열려 있습니다. 해당 문서를 닫은 뒤 다시 시도하세요.";
const DISK: &str = "디스크 공간이 부족합니다. 공간을 비우거나 다른 저장 폴더를 지정하세요.";
const MISSING: &str = "경로를 찾을 수 없습니다. 저장 폴더가 이동·삭제되지 않았는지 확인하세요.";
const HINTS: [(&str, &str); 9] = [
    ("Permission denied", ACCESS),
    ("No space left", DISK),
    ("No such file or directory", MISSING),
    ("[WinError 5]", ACCESS),
    ("액세스가 거부", ACCESS),
    ("[WinError 32]", IN_USE),
    ("다른 프로세스가 파일을 사용 중", IN_USE),
    ("[WinError 112]", DISK),
    ("디스크에 공간이 부족", DISK),
];

pub fn classify_result_error(reason: &str) -> (String, bool) {
    for (needle, hint) in HINTS {
        if reason.contains(needle) {
            return (format!("{hint} (원문: {reason})"), true);
        }
    }
    (reason.into(), false)
}

pub fn describe_fill_note(note: &FillNote) -> String {
    let field = &note.field;
    let kinds = note.detail.join(", ");
    match note.kind {
        FillNoteKind::InlineStripped => format!(
            "누름틀 '{field}' 값 안의 인라인 요소({kinds})를 값과 함께 제거하고 채웠습니다. 형광펜 등 표식이 사라졌을 수 있으니 산출물을 확인하세요."
        ),
        FillNoteKind::SlotSynthesized => format!(
            "빈 누름틀 '{field}' 에 값 자리를 새로 만들어 채웠습니다. 서식은 누름틀 주변 서식을 따릅니다."
        ),
        FillNoteKind::OccurrenceUnfillable => format!(
            "누름틀 '{field}' 자리 중 구조상 기입할 수 없는 곳이 있어 건너뛰었습니다. 산출물에서 해당 자리를 확인하세요."
        ),
    }
}
