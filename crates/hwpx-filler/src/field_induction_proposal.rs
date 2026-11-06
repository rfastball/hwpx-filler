//! One document and one data row to grouped field proposals.

use crate::field_induction::{
    Candidate, ParagraphText, Slot, find_candidates, mask, occurrences, renderings, transform,
};
use crate::field_induction_evidence::{DocumentView, SpotEvidence, spot_evidence};
use crate::field_induction_grading::{
    Grade, KIND_HELD, KIND_PROPOSAL, REASON_BAD_NAME, count_spots, grade,
};
use crate::fields::{collapse_field_id, normalize_field_id};
use std::collections::HashSet;

const REASON_EMPTY: &str = "이 행에서 값이 비어 있습니다.";
const REASON_NOT_FOUND: &str = "문서에서 같은 값을 찾지 못했습니다.";
const REASON_CONTROL_BEFORE: &str =
    "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다.";

#[derive(Clone, Debug)]
pub struct Spot {
    pub id: String,
    pub paragraph: usize,
    pub start: usize,
    pub end: usize,
    pub text: String,
    pub where_label: String,
}
#[derive(Clone, Debug)]
pub struct Group {
    pub id: String,
    pub kind: &'static str,
    pub name: String,
    pub column: String,
    pub others: Vec<String>,
    pub value: String,
    pub raw: String,
    pub transform: &'static str,
    pub reason: String,
    pub note: String,
    pub only: Option<String>,
    pub links_existing: bool,
    pub count_text: String,
    pub spots: Vec<Spot>,
}
#[derive(Clone, Debug)]
pub struct Missing {
    pub column: String,
    pub reason: &'static str,
}
#[derive(Clone, Debug)]
pub struct Proposal {
    pub groups: Vec<Group>,
    pub missing: Vec<Missing>,
}
impl Proposal {
    pub fn count(&self, kind: &str) -> usize {
        self.groups.iter().filter(|item| item.kind == kind).count()
    }
}

pub fn field_name(column: &str) -> Option<String> {
    let clean: String = column
        .chars()
        .map(|ch| if "{}|".contains(ch) { ' ' } else { ch })
        .collect();
    let clean = clean.trim_start_matches(['#', '/', ' ']);
    let name = collapse_field_id(clean)?;
    let name = normalize_field_id(&name)?;
    (!name.contains("{{")
        && !name.contains("}}")
        && !name.contains('|')
        && !name.starts_with(['#', '/']))
    .then_some(name)
}
fn rank(group: &Group) -> (bool, std::cmp::Reverse<usize>, usize, usize) {
    let first = group.spots.first();
    (
        group.kind != KIND_PROPOSAL,
        std::cmp::Reverse(group.spots.len()),
        first.map_or(1 << 30, |spot| spot.paragraph),
        first.map_or(0, |spot| spot.start),
    )
}
fn slot_columns(slots: &[&Slot], columns: &[String]) -> (Vec<String>, Vec<(String, &'static str)>) {
    let mut best: Vec<(String, Candidate)> = Vec::new();
    for candidate in slots.iter().flat_map(|slot| slot.candidates.iter()) {
        let complexity =
            transform(candidate.transform).map_or(f64::INFINITY, |spec| spec.complexity);
        if let Some((_, kept)) = best
            .iter_mut()
            .find(|(column, _)| column == &candidate.column)
        {
            if complexity < transform(kept.transform).map_or(f64::INFINITY, |spec| spec.complexity)
            {
                *kept = candidate.clone();
            }
        } else {
            best.push((candidate.column.clone(), candidate.clone()));
        }
    }
    let ordered: Vec<_> = columns
        .iter()
        .filter(|column| best.iter().any(|(name, _)| name == *column))
        .cloned()
        .collect();
    let transforms = ordered
        .iter()
        .filter_map(|column| {
            best.iter()
                .find(|(name, _)| name == column)
                .map(|(_, candidate)| (column.clone(), candidate.transform))
        })
        .collect();
    (ordered, transforms)
}
fn display_value(
    rendered: &str,
    transform_id: &str,
    spots: &[SpotEvidence],
    view: &DocumentView,
) -> String {
    if transform(transform_id).is_none_or(|spec| spec.family != "number") {
        return rendered.into();
    }
    if spots.iter().all(|spot| {
        view.paragraphs[spot.slot.paragraph]
            .text
            .chars()
            .nth(spot.slot.end)
            == Some('원')
    }) {
        format!("{rendered}원")
    } else {
        rendered.into()
    }
}
fn to_spot(view: &DocumentView, evidence: &SpotEvidence) -> Spot {
    let slot = &evidence.slot;
    Spot {
        id: format!("s{}_{}", slot.paragraph, slot.start),
        paragraph: slot.paragraph,
        start: slot.start,
        end: slot.end,
        text: evidence.text.clone(),
        where_label: view.where_label(slot.paragraph).into(),
    }
}
fn group(
    view: &DocumentView,
    verdict: Grade,
    key: String,
    transform_id: &'static str,
    raw: &str,
    existing: &HashSet<String>,
) -> Group {
    let name = field_name(&verdict.column);
    let spots: Vec<_> = verdict
        .spots
        .iter()
        .filter(|item| item.creatable)
        .map(|item| to_spot(view, item))
        .collect();
    let value = verdict
        .spots
        .first()
        .map(|item| display_value(&item.text, transform_id, &verdict.spots, view))
        .unwrap_or_default();
    let count_text = if verdict.count_text.is_empty() {
        count_spots(if verdict.kind == KIND_PROPOSAL {
            spots.len()
        } else {
            verdict.spots.len()
        })
    } else {
        verdict.count_text.clone()
    };
    let mut result = Group {
        id: key,
        kind: verdict.kind,
        name: name.clone().unwrap_or_else(|| verdict.column.clone()),
        column: verdict.column,
        others: verdict.others,
        value,
        raw: raw.into(),
        transform: transform_id,
        reason: verdict.reason,
        note: verdict.note,
        only: None,
        links_existing: name.as_ref().is_some_and(|name| existing.contains(name)),
        count_text,
        spots,
    };
    if name.is_none() {
        result.kind = KIND_HELD;
        result.reason = REASON_BAD_NAME.into();
        result.note.clear();
    } else if result.kind == KIND_PROPOSAL && result.spots.is_empty() {
        result.kind = KIND_HELD;
        result.reason = REASON_CONTROL_BEFORE.into();
        result.note.clear();
    }
    result
}
fn grouped(
    view: &DocumentView,
    slots: &[Slot],
    row: &[(String, Option<String>)],
    columns: &[String],
    existing: &HashSet<String>,
    picks: &[(String, String)],
) -> Vec<Group> {
    let mut by_text: Vec<(String, Vec<&Slot>)> = Vec::new();
    for slot in slots {
        let text: String = view.paragraphs[slot.paragraph]
            .text
            .chars()
            .skip(slot.start)
            .take(slot.end - slot.start)
            .collect();
        if let Some((_, same)) = by_text.iter_mut().find(|(key, _)| *key == text) {
            same.push(slot)
        } else {
            by_text.push((text, vec![slot]));
        }
    }
    let mut out = Vec::new();
    for (_, same) in by_text {
        let (ordered, transforms) = slot_columns(&same, columns);
        let evidence: Vec<_> = same
            .iter()
            .map(|slot| spot_evidence(view, slot, &ordered))
            .collect();
        let key = format!("g_{}", ordered.join("|"));
        let pick = picks
            .iter()
            .find(|(id, _)| id == &key)
            .map(|(_, column)| column.as_str());
        if let Some(verdict) = grade(&ordered, &evidence, pick)
            && let Some((_, transform_id)) = transforms
                .iter()
                .find(|(column, _)| column == &verdict.column)
        {
            let raw = row
                .iter()
                .find(|(column, _)| column == &verdict.column)
                .and_then(|(_, value)| value.as_deref())
                .unwrap_or("");
            out.push(group(view, verdict, key, transform_id, raw, existing));
        }
    }
    out
}
fn one_per_column(groups: &[Group]) -> Vec<Group> {
    let mut ranked = groups.to_vec();
    ranked.sort_by_key(rank);
    let mut seen = HashSet::new();
    let mut kept: Vec<_> = ranked
        .into_iter()
        .filter(|group| seen.insert(group.column.clone()))
        .collect();
    kept.sort_by_key(|group| {
        group
            .spots
            .first()
            .map_or((1 << 30, 0), |spot| (spot.paragraph, spot.start))
    });
    kept
}
fn in_fields(paragraphs: &[ParagraphText], value: &str) -> bool {
    for (_, rendered) in renderings(value) {
        for paragraph in paragraphs {
            let mut unmasked = paragraph.clone();
            unmasked.field_spans.clear();
            unmasked.editable_end = 0;
            if occurrences(&unmasked, &rendered)
                .into_iter()
                .any(|(start, end)| {
                    paragraph
                        .field_spans
                        .iter()
                        .any(|(lo, hi)| start < *hi && *lo < end)
                })
            {
                return true;
            }
        }
    }
    false
}
pub fn propose(
    paragraphs: &[ParagraphText],
    row: &[(String, Option<String>)],
    columns: &[String],
    existing_fields: &[String],
    dismissed: &[(String, String)],
    picks: &[(String, String)],
) -> Proposal {
    let slots = mask(&find_candidates(paragraphs, row));
    let view = DocumentView::new(paragraphs, &slots);
    let existing: HashSet<_> = existing_fields.iter().cloned().collect();
    let groups = one_per_column(&grouped(&view, &slots, row, columns, &existing, picks));
    let covered: HashSet<_> = groups
        .iter()
        .flat_map(|group| std::iter::once(&group.column).chain(group.others.iter()))
        .cloned()
        .collect();
    let missing = columns
        .iter()
        .filter_map(|column| {
            let value = row
                .iter()
                .find(|(name, _)| name == column)
                .and_then(|(_, value)| value.as_deref());
            if value.is_none_or(str::is_empty) {
                Some(Missing {
                    column: column.clone(),
                    reason: REASON_EMPTY,
                })
            } else if !covered.contains(column) && !in_fields(paragraphs, value.unwrap()) {
                Some(Missing {
                    column: column.clone(),
                    reason: REASON_NOT_FOUND,
                })
            } else {
                None
            }
        })
        .collect();
    let groups = groups
        .into_iter()
        .filter(|group| {
            !(dismissed
                .iter()
                .any(|pair| pair.0 == group.column && pair.1 == group.raw)
                || group.kind == KIND_HELD && group.links_existing)
        })
        .collect();
    Proposal { groups, missing }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::field_induction::CellRef;

    fn doc(lines: &[&str]) -> Vec<ParagraphText> {
        lines
            .iter()
            .enumerate()
            .map(|(index, text)| ParagraphText {
                key: format!("p{index}"),
                text: (*text).into(),
                editable_end: text.chars().count() + 1,
                field_spans: Vec::new(),
                cell: None,
            })
            .collect()
    }
    fn row(items: &[(&str, Option<&str>)]) -> Vec<(String, Option<String>)> {
        items
            .iter()
            .map(|(name, value)| ((*name).into(), value.map(str::to_owned)))
            .collect()
    }
    fn propose_rows(paragraphs: &[ParagraphText], values: &[(&str, Option<&str>)]) -> Proposal {
        let row = row(values);
        let columns = row.iter().map(|(name, _)| name.clone()).collect::<Vec<_>>();
        propose(paragraphs, &row, &columns, &[], &[], &[])
    }
    fn group<'a>(result: &'a Proposal, column: &str) -> &'a Group {
        result
            .groups
            .iter()
            .find(|group| group.column == column)
            .unwrap()
    }

    #[test]
    fn mock_notice_keeps_ten_evidenced_groups_and_one_held() {
        let mut paragraphs = doc(&[
            "물품 구매 입찰 공고",
            "공고번호 R26BK01234567",
            "청사 보안 출입통제시스템 구매",
            "입찰을 다음과 같이 공고합니다.",
            "1. 입찰에 부치는 사항",
            "가. 공고명: 청사 보안 출입통제시스템 구매",
            "나. 추정가격: 170,309,180원 (부가가치세 포함)",
            "다. 수량: 12 식",
            "라. 납품장소: 정부대전청사 3동",
            "2. 입찰 일정",
            "가. 현장설명회: 2026. 9. 12. 14:00 (대전지방조달청 2층 회의실)",
            "나. 입찰서 제출 시작: 2026. 9. 12. 09:00",
            "다. 입찰마감일시: 2026. 9. 17. 18:00",
            "라. 개찰일시: 2026. 9. 18. 10:00",
            "3. 입찰 참가자격",
            "가. 이 입찰은 제한경쟁 입찰로서 아래 자격을 모두 갖춘 자가 참가할 수 있습니다.",
            "나. 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제42조에 따른 적격심사 대상자로서 결격 사유가 없는 자",
            "4. 입찰 방법",
            "가. 이 입찰은 전자입찰로 하며, 국가종합전자조달시스템에서 공고번호 R26BK01234567 을 조회하여 입찰서를 제출합니다.",
            "나. 전자입찰 이용 방법은 「국가종합전자조달시스템 이용약관」을 따릅니다.",
            "다. 낙찰자는 적격심사 결과 종합평점이 85점 이상인 자로 합니다.",
            "라. 적격심사 서류는 입찰마감일까지 제출합니다.",
            "담당: 김다온 주무관 (042-481-1234)",
            "2026. 9. 11.",
        ]);
        let cells = [
            ("계약방법", 0),
            ("제한경쟁", 1),
            ("낙찰자결정방법", 2),
            ("적격심사", 3),
        ]
        .into_iter()
        .map(|(text, col)| ParagraphText {
            key: format!("c{col}"),
            text: text.into(),
            editable_end: text.chars().count() + 1,
            field_spans: Vec::new(),
            cell: Some(CellRef {
                table: "t0".into(),
                row: 0,
                col,
                row_span: 1,
                col_span: 1,
            }),
        })
        .collect::<Vec<_>>();
        paragraphs.splice(14..14, cells);
        let values = row(&[
            ("입찰공고번호", Some("R26BK01234567")),
            ("현행공고", Some("R26BK01234567")),
            ("공고명", Some("청사 보안 출입통제시스템 구매")),
            ("추정가격", Some("170309180")),
            ("수량", Some("12")),
            ("납품장소", Some("정부대전청사 3동")),
            ("입찰마감일시", Some("2026-09-17 18:00")),
            ("개찰일시", Some("2026-09-18 10:00")),
            ("계약방법", Some("제한경쟁")),
            ("담당자", Some("김다온")),
            ("낙찰자결정방법", Some("적격심사")),
            ("입찰방식", Some("전자입찰")),
            ("품명", Some("")),
            ("비고", None),
        ]);
        let columns = values
            .iter()
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>();
        let result = propose(&paragraphs, &values, &columns, &[], &[], &[]);
        assert_eq!(
            (result.count(KIND_PROPOSAL), result.count(KIND_HELD)),
            (10, 1)
        );
        assert_eq!(group(&result, "추정가격").transform, "number_grouping");
        assert_eq!(group(&result, "추정가격").spots[0].text, "170,309,180");
        assert_eq!(group(&result, "수량").spots.len(), 1);
        assert_eq!(
            group(&result, "입찰마감일시").transform,
            "datetime_dot_spaced"
        );
        assert_eq!(
            group(&result, "계약방법")
                .spots
                .iter()
                .map(|spot| spot.where_label.as_str())
                .collect::<Vec<_>>(),
            vec!["표 칸, 2. 라"]
        );
        assert_eq!(group(&result, "낙찰자결정방법").count_text, "라벨 옆 1곳만");
        assert_eq!(
            group(&result, "낙찰자결정방법").note,
            "라벨 ‘낙찰자결정방법’ 옆 1곳만 골랐습니다. 다른 3곳은 라벨이 없어 고르지 않았습니다."
        );
        assert_eq!(group(&result, "입찰방식").kind, KIND_HELD);
        assert_eq!(
            result
                .missing
                .iter()
                .map(|item| item.column.as_str())
                .collect::<Vec<_>>(),
            vec!["품명", "비고"]
        );
    }

    #[test]
    fn ties_fixed_wording_and_prose_are_held_while_data_slots_are_offered() {
        let tied = propose_rows(
            &doc(&["한국상사"]),
            &[("상호", Some("한국상사")), ("거래처", Some("한국상사"))],
        );
        assert_eq!(tied.groups[0].kind, KIND_HELD);
        assert_eq!(tied.groups[0].others, vec!["거래처"]);
        assert_eq!(
            tied.groups[0].reason,
            "값이 같은 열이 여럿입니다. 연결할 열을 고르세요."
        );
        let fixed = propose_rows(
            &doc(&["근거: “조달청 군수품 구매 적격심사 세부기준” 제4조"]),
            &[("방법", Some("적격심사"))],
        );
        assert_eq!(fixed.groups[0].reason, "고정 문구 안의 낱말로 보입니다.");
        let prose = propose_rows(
            &doc(&["이번 사업은 정부대전청사 3동 이전을 위한 구매입니다"]),
            &[("장소", Some("정부대전청사 3동"))],
        );
        assert_eq!(
            prose.groups[0].reason,
            "문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다."
        );
        let mixed = propose_rows(
            &doc(&[
                "정부대전청사 3동",
                "이번 사업은 정부대전청사 3동 이전을 위한 구매입니다",
            ]),
            &[("장소", Some("정부대전청사 3동"))],
        );
        assert_eq!(mixed.groups[0].kind, KIND_PROPOSAL);
        assert_eq!(
            mixed.groups[0]
                .spots
                .iter()
                .map(|spot| spot.paragraph)
                .collect::<Vec<_>>(),
            vec![0]
        );
        assert_eq!(
            mixed.groups[0].note,
            "값만 있는 자리 1곳을 골랐습니다. 문장 속 1곳은 고르지 않았습니다."
        );
        let phone = propose_rows(
            &doc(&["문의는 담당 부서(042-481-1234)로 연락 바람"]),
            &[("전화", Some("042-481-1234"))],
        );
        assert_eq!(phone.groups[0].kind, KIND_PROPOSAL);
        let short = propose_rows(
            &doc(&["단위: 대", "대한민국 대표 대학"]),
            &[("단위", Some("대"))],
        );
        assert_eq!(
            short.groups[0].note,
            "라벨 ‘단위:’ 옆 1곳만 골랐습니다. 다른 3곳은 라벨이 없어 고르지 않았습니다."
        );
        let missing = propose_rows(&doc(&["총 12 건"]), &[("수량", Some("12"))]);
        assert!(missing.groups.is_empty());
        assert_eq!(
            missing.missing[0].reason,
            "문서에서 같은 값을 찾지 못했습니다."
        );
    }

    #[test]
    fn invalid_names_edit_barriers_and_existing_fields_do_not_create_false_missing() {
        assert_eq!(
            field_name(" 담당자   전화번호 "),
            Some("담당자 전화번호".into())
        );
        assert_eq!(field_name("#번호"), Some("번호".into()));
        assert_eq!(field_name("{a|b}"), Some("a b".into()));
        assert_eq!(field_name("{{}}"), None);
        let bad_name = propose_rows(&doc(&["공고명: 장비 구매"]), &[("{{}}", Some("장비 구매"))]);
        assert_eq!(bad_name.groups[0].kind, KIND_HELD);
        assert_eq!(
            bad_name.groups[0].reason,
            "열 이름을 필드 이름으로 쓸 수 없습니다. 문구를 고르고 직접 필드로 만드세요."
        );
        let mut blocked = doc(&["공고명: 장비 구매"]);
        blocked[0].editable_end = 2;
        let result = propose_rows(&blocked, &[("공고명", Some("장비 구매"))]);
        assert!(result.groups[0].spots.is_empty());
        assert_eq!(
            result.groups[0].reason,
            "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다."
        );
        let existing = vec!["공고명".into()];
        let values = row(&[("공고명", Some("장비 구매"))]);
        let columns = vec!["공고명".into()];
        let retained = propose(
            &doc(&["공고명: 장비 구매"]),
            &values,
            &columns,
            &existing,
            &[],
            &[],
        );
        assert!(retained.groups[0].links_existing);
        let dismissed = propose(
            &doc(&["공고명: 장비 구매"]),
            &values,
            &columns,
            &[],
            &[("공고명".into(), "장비 구매".into())],
            &[],
        );
        assert!(dismissed.groups.is_empty() && dismissed.missing.is_empty());
        let held_existing = propose(
            &doc(&["근거: “장비 구매 세부기준”"]),
            &values,
            &columns,
            &existing,
            &[],
            &[],
        );
        assert!(held_existing.groups.is_empty() && held_existing.missing.is_empty());
        let mut embedded = doc(&["수요기관: 조달청"]);
        embedded[0].field_spans = vec![(6, 9)];
        let protected = propose_rows(&embedded, &[("수요기관", Some("조달청"))]);
        assert!(protected.missing.is_empty());
    }

    #[test]
    fn numbered_cells_and_adjacent_values_keep_correct_owner_and_location() {
        let mut paragraphs = doc(&["1. 사항", "가. 공고명: 장비 구매", "(1) 세부: 첫째 장비"]);
        paragraphs.extend([
            ParagraphText {
                key: "c".into(),
                text: "둘째 장비".into(),
                editable_end: 9,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 0,
                    col: 1,
                    row_span: 1,
                    col_span: 1,
                }),
            },
            ParagraphText {
                key: "l".into(),
                text: "세부".into(),
                editable_end: 3,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 0,
                    col: 0,
                    row_span: 1,
                    col_span: 1,
                }),
            },
        ]);
        let result = propose_rows(
            &paragraphs,
            &[
                ("공고명", Some("장비 구매")),
                ("세부", Some("첫째 장비")),
                ("둘", Some("둘째 장비")),
            ],
        );
        assert_eq!(group(&result, "공고명").spots[0].where_label, "1. 가");
        assert_eq!(group(&result, "세부").spots[0].where_label, "1. 가. (1)");
        assert_eq!(
            group(&result, "둘").spots[0].where_label,
            "표 칸, 1. 가. (1)"
        );

        let cells = vec![
            ParagraphText {
                key: "h".into(),
                text: "납품장소".into(),
                editable_end: 5,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 0,
                    col: 0,
                    row_span: 1,
                    col_span: 2,
                }),
            },
            ParagraphText {
                key: "x".into(),
                text: "비고 없음".into(),
                editable_end: 6,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 1,
                    col: 0,
                    row_span: 1,
                    col_span: 1,
                }),
            },
            ParagraphText {
                key: "v".into(),
                text: "정부대전청사 3동".into(),
                editable_end: 10,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 1,
                    col: 1,
                    row_span: 1,
                    col_span: 1,
                }),
            },
        ];
        let result = propose_rows(&cells, &[("납품장소", Some("정부대전청사 3동"))]);
        assert_eq!(result.groups[0].kind, KIND_PROPOSAL);
        assert_eq!(result.groups[0].spots[0].where_label, "표 칸");

        let cells = vec![
            ParagraphText {
                key: "a".into(),
                text: "구분".into(),
                editable_end: 3,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 0,
                    col: 0,
                    row_span: 1,
                    col_span: 1,
                }),
            },
            ParagraphText {
                key: "b".into(),
                text: "품명".into(),
                editable_end: 3,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 0,
                    col: 1,
                    row_span: 1,
                    col_span: 1,
                }),
            },
            ParagraphText {
                key: "c".into(),
                text: "동등이상 물품".into(),
                editable_end: 8,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 1,
                    col: 0,
                    row_span: 1,
                    col_span: 1,
                }),
            },
            ParagraphText {
                key: "d".into(),
                text: "전동드릴".into(),
                editable_end: 5,
                field_spans: vec![],
                cell: Some(CellRef {
                    table: "t".into(),
                    row: 1,
                    col: 1,
                    row_span: 1,
                    col_span: 1,
                }),
            },
        ];
        let result = propose_rows(
            &cells,
            &[("세부품명", Some("전동드릴")), ("비고", Some("전동드릴"))],
        );
        assert_eq!(
            (
                result.groups[0].kind,
                result.groups[0].column.as_str(),
                result.groups[0].others.as_slice()
            ),
            (KIND_PROPOSAL, "세부품명", ["비고".to_owned()].as_slice())
        );
    }

    #[test]
    fn range_contact_and_short_values_exclude_prose_but_retain_real_slots() {
        let range = propose_rows(
            &doc(&["① 전자입찰서 접수일시: 2026. 9. 11. 10:00 ~ 2026. 9. 15. 10:00"]),
            &[
                ("개시", Some("2026-09-11 10:00")),
                ("마감", Some("2026-09-15 10:00")),
            ],
        );
        assert_eq!(
            range.groups.iter().map(|g| g.kind).collect::<Vec<_>>(),
            vec![KIND_PROPOSAL, KIND_PROPOSAL]
        );
        let contact = propose_rows(
            &doc(&[
                "   - 조달청 구매사업국 국방물자구매과 주무관 홍길동 (☎ 042-000-0000)",
                " ②  수요기관 연락처: 육군 한빛보급부대 물자관리과 홍길동 (☎ 042-000-1001) ",
            ]),
            &[
                ("수요기관", Some("육군 한빛보급부대")),
                ("담당부서", Some("물자관리과")),
                ("담당자", Some("홍길동")),
                ("전화", Some("042-000-1001")),
            ],
        );
        assert_eq!(
            contact
                .groups
                .iter()
                .filter(|g| g.kind == KIND_PROPOSAL)
                .count(),
            4
        );
        assert_eq!(
            group(&contact, "담당자")
                .spots
                .iter()
                .map(|spot| spot.paragraph)
                .collect::<Vec<_>>(),
            vec![1]
        );
        assert_eq!(
            group(&contact, "담당자").note,
            "값만 있는 자리 1곳을 골랐습니다. 문장 속 1곳은 고르지 않았습니다."
        );
        let numbering = propose_rows(
            &doc(&[
                "조달청 물품공고 제R26BK99000001-000호",
                "1) 시스템에 세부품명번호 10자리 9901000101(전동드릴)를 등록한 자",
                " 품          명:  전동드릴",
            ]),
            &[
                ("공고번호", Some("R26BK99000001-000")),
                ("세부품명", Some("전동드릴")),
                ("세부품명번호", Some("9901000101")),
            ],
        );
        assert_eq!(
            numbering
                .groups
                .iter()
                .filter(|g| g.kind == KIND_PROPOSAL)
                .count(),
            3
        );
        assert_eq!(
            group(&numbering, "세부품명")
                .spots
                .iter()
                .map(|spot| spot.paragraph)
                .collect::<Vec<_>>(),
            vec![1, 2]
        );
        let short = propose_rows(
            &doc(&[
                " 수 량 및 단 위:  40 대",
                " -전동드릴 / 40 대",
                "대한민국 대표 대학",
                "총 40 대를 구매",
            ]),
            &[
                ("수량", Some("40")),
                ("단위", Some("대")),
                ("품명", Some("전동드릴")),
            ],
        );
        assert_eq!(
            group(&short, "수량")
                .spots
                .iter()
                .map(|spot| spot.paragraph)
                .collect::<Vec<_>>(),
            vec![0, 1]
        );
        assert_eq!(
            group(&short, "수량").note,
            "값만 있는 자리 2곳을 골랐습니다. 문장 속 1곳은 고르지 않았습니다."
        );
        let long = propose_rows(
            &doc(&["수요기관: 조달청"]
                .into_iter()
                .chain(std::iter::repeat_n("조달청 안내 문장입니다", 6))
                .collect::<Vec<_>>()),
            &[("수요기관", Some("조달청"))],
        );
        assert_eq!(long.groups[0].spots.len(), 1);
        assert_eq!(
            long.groups[0].note,
            "라벨 ‘수요기관:’ 옆 1곳만 골랐습니다. 다른 6곳은 라벨이 없어 고르지 않았습니다."
        );
    }

    #[test]
    fn literal_labels_take_precedence_over_synonyms_and_fixed_date_frames() {
        let literal = propose_rows(
            &doc(&[
                " 입  찰  방  법:  전자입찰",
                " ① 입찰방식: 전자입찰(국내입찰)",
                "1) 전자입찰서",
            ]),
            &[("입찰방법", Some("전자입찰"))],
        );
        assert_eq!(
            literal.groups[0]
                .spots
                .iter()
                .map(|spot| spot.paragraph)
                .collect::<Vec<_>>(),
            vec![0]
        );
        assert_eq!(
            literal.groups[0].note,
            "라벨 ‘입 찰 방 법:’ 옆 1곳만 골랐습니다. 다른 2곳은 라벨이 없어 고르지 않았습니다."
        );
        let synonym = propose_rows(
            &doc(&[" ① 입찰방식: 전자입찰(국내입찰)"]),
            &[("입찰방법", Some("전자입찰"))],
        );
        assert_eq!(synonym.groups[0].kind, KIND_PROPOSAL);
        let unlabelled = propose_rows(&doc(&["1) 전자입찰서"]), &[("입찰방법", Some("전자입찰"))]);
        assert_eq!(
            unlabelled.groups[0].reason,
            "문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다."
        );
        let date_frame = propose_rows(
            &doc(&["수량: 20", "20  .   .   ."]),
            &[("수량", Some("20"))],
        );
        assert_eq!(
            date_frame.groups[0]
                .spots
                .iter()
                .map(|spot| spot.paragraph)
                .collect::<Vec<_>>(),
            vec![0]
        );
        let generic = propose_rows(
            &doc(&["계약상대자는 납품장소 하차도 조건을 지켜야 하며 위반한 경우에는 해지합니다."]),
            &[("인도조건", Some("납품장소 하차도"))],
        );
        assert_eq!(
            generic.groups[0].reason,
            "규정·안내 문장 안의 낱말로 보입니다."
        );
        let both = propose_rows(
            &doc(&["가. 개찰일: 2026-09-18", "2026년 9월 18일 개찰"]),
            &[("개찰일", Some("2026-09-18"))],
        );
        assert_eq!(both.groups[0].transform, "identity");
    }
}
