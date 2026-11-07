//! Deterministic proposal/held grading and user-facing reason text.

use crate::field_induction::specificity;
use crate::field_induction_evidence::SpotEvidence;

pub const KIND_PROPOSAL: &str = "proposal";
pub const KIND_HELD: &str = "held";
pub const REASON_BAD_NAME: &str =
    "열 이름을 필드 이름으로 쓸 수 없습니다. 문구를 고르고 직접 필드로 만드세요.";
const REASON_TIE: &str = "값이 같은 열이 여럿입니다. 연결할 열을 고르세요.";
const REASON_PROSE_ONCE: &str =
    "문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다.";
const REASON_FIXED: &str = "고정 문구 안의 낱말로 보입니다.";
const REASON_GENERIC: &str = "규정·안내 문장 안의 낱말로 보입니다.";

pub fn note_same_value(column: &str) -> String {
    format!("‘{column}’ 열도 같은 값입니다.")
}
pub fn count_spots(count: usize) -> String {
    format!("{count}곳")
}

#[derive(Clone, Debug)]
pub struct Grade {
    pub kind: &'static str,
    pub column: String,
    pub others: Vec<String>,
    pub spots: Vec<SpotEvidence>,
    pub reason: String,
    pub note: String,
    pub count_text: String,
}
impl Grade {
    fn new(
        kind: &'static str,
        column: &str,
        others: Vec<String>,
        spots: Vec<SpotEvidence>,
    ) -> Self {
        Self {
            kind,
            column: column.into(),
            others,
            spots,
            reason: String::new(),
            note: String::new(),
            count_text: String::new(),
        }
    }
}
fn same_site(a: &SpotEvidence, b: &SpotEvidence) -> bool {
    (a.slot.paragraph, a.slot.start, a.slot.end) == (b.slot.paragraph, b.slot.start, b.slot.end)
}
fn is_foreign(spot: &SpotEvidence, column: &str, has_literal: bool) -> bool {
    has_literal
        && spot.matched.iter().any(|name| name == column)
        && !spot.literal.iter().any(|name| name == column)
}
fn keep_spot(
    spot: &SpotEvidence,
    column: &str,
    has_literal: bool,
    labelled: &[&SpotEvidence],
    short: bool,
) -> bool {
    if is_foreign(spot, column, has_literal) {
        return false;
    }
    if labelled.iter().any(|item| same_site(item, spot)) {
        return true;
    }
    if short {
        spot.standalone && spot.bounded && !spot.glued && !spot.fixed() && !spot.generic()
    } else {
        spot.anchored() && !spot.fixed() && !spot.generic()
    }
}
fn apply_left_out_note(result: &mut Grade, labelled: &[&SpotEvidence], left_out: usize) {
    if result
        .spots
        .iter()
        .all(|spot| labelled.iter().any(|item| same_site(item, spot)))
    {
        let label = labelled.first().map_or("", |spot| spot.label.as_str());
        result.note = format!(
            "라벨 ‘{label}’ 옆 {}곳만 골랐습니다. 다른 {left_out}곳은 라벨이 없어 고르지 않았습니다.",
            result.spots.len()
        );
        result.count_text = format!("라벨 옆 {}곳만", result.spots.len());
    } else {
        result.note = format!(
            "값만 있는 자리 {}곳을 골랐습니다. 문장 속 {left_out}곳은 고르지 않았습니다.",
            result.spots.len()
        );
    }
}
fn offer(
    column: &str,
    others: Vec<String>,
    labelled: &[SpotEvidence],
    spots: &[SpotEvidence],
    short: bool,
) -> Grade {
    let has_literal = labelled
        .iter()
        .any(|spot| spot.literal.iter().any(|name| name == column));
    let labelled: Vec<_> = labelled
        .iter()
        .filter(|spot| !is_foreign(spot, column, has_literal))
        .collect();
    let kept: Vec<_> = spots
        .iter()
        .filter(|spot| keep_spot(spot, column, has_literal, &labelled, short))
        .cloned()
        .collect();
    let left_out = spots.len() - kept.len();
    let mut result = Grade::new(KIND_PROPOSAL, column, others, kept);
    if left_out == 0 {
        return result;
    }
    apply_left_out_note(&mut result, &labelled, left_out);
    result
}
fn resolve_column(
    columns: &[String],
    pick: Option<&str>,
    labelled: Vec<SpotEvidence>,
) -> (Option<String>, Vec<SpotEvidence>) {
    let fixed = pick
        .filter(|pick| columns.iter().any(|column| column == *pick))
        .map(str::to_owned)
        .or_else(|| (columns.len() == 1).then(|| columns[0].clone()));
    if let Some(column) = fixed {
        (Some(column), labelled)
    } else {
        let named: std::collections::HashSet<_> = labelled
            .iter()
            .flat_map(|spot| spot.matched.iter())
            .collect();
        if named.len() != 1 {
            (None, Vec::new())
        } else {
            let column = (*named.into_iter().next().unwrap()).clone();
            let matching = labelled
                .into_iter()
                .filter(|spot| spot.matched.len() == 1 && spot.matched[0] == column)
                .collect();
            (Some(column), matching)
        }
    }
}
pub fn grade(columns: &[String], spots: &[SpotEvidence], pick: Option<&str>) -> Option<Grade> {
    let first = spots.first()?;
    let labelled: Vec<SpotEvidence> = spots
        .iter()
        .filter(|spot| spot.labelled())
        .cloned()
        .collect();
    let (column, labelled) = resolve_column(columns, pick, labelled);
    let short = specificity(&first.text) < 0.75;
    let Some(column) = column else {
        if short {
            return None;
        }
        let mut result = Grade::new(
            KIND_HELD,
            &columns[0],
            columns[1..].to_vec(),
            spots.to_vec(),
        );
        result.reason = REASON_TIE.into();
        return Some(result);
    };
    let others = columns
        .iter()
        .filter(|item| **item != column)
        .cloned()
        .collect();
    if short {
        return (!labelled.is_empty()).then(|| offer(&column, others, &labelled, spots, true));
    }
    if !labelled.is_empty() {
        return Some(offer(&column, others, &labelled, spots, false));
    }
    if spots.iter().any(SpotEvidence::generic) {
        let mut result = Grade::new(KIND_HELD, &column, others, spots.to_vec());
        result.reason = REASON_GENERIC.into();
        return Some(result);
    }
    if spots.iter().any(SpotEvidence::fixed) {
        let mut result = Grade::new(KIND_HELD, &column, others, spots.to_vec());
        result.reason = REASON_FIXED.into();
        return Some(result);
    }
    if spots.iter().any(SpotEvidence::anchored) {
        return Some(offer(&column, others, &[], spots, false));
    }
    let mut result = Grade::new(KIND_HELD, &column, others, spots.to_vec());
    result.reason = if spots.len() == 1 {
        REASON_PROSE_ONCE.into()
    } else {
        format!(
            "같은 값 {}곳이 모두 문장 속에 있어 일반 낱말로 보입니다.",
            spots.len()
        )
    };
    Some(result)
}
