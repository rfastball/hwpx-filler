//! Data-first Job compatibility, bound candidates, ranking and browse gates.

use crate::dataset_reference::excel_identity;
use crate::jamo::jamo_contains;
use crate::job::Job;
use crate::structure_scan::python_trim;
use std::collections::HashSet;

pub const MAIN_TOP_N: usize = 5;
pub const TAB_AVAILABLE: &str = "available";
pub const TAB_NEEDS_ACTION: &str = "needs_action";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkCompatibility {
    pub kind: &'static str,
    pub missing: Vec<String>,
    pub reason: &'static str,
    pub mode: &'static str,
}

pub fn compatibility_for(job: &Job, fields: &[String]) -> WorkCompatibility {
    let mode = job.work_mode();
    if mode == "unsupported" {
        return WorkCompatibility {
            kind: "excluded",
            missing: vec![],
            reason: "unsupported",
            mode,
        };
    }
    let present: HashSet<&str> = fields.iter().map(String::as_str).collect();
    let missing = job
        .source_keys()
        .into_iter()
        .filter(|key| !present.contains(key.as_str()))
        .collect::<Vec<_>>();
    WorkCompatibility {
        kind: if missing.is_empty() {
            TAB_AVAILABLE
        } else {
            TAB_NEEDS_ACTION
        },
        missing,
        reason: "",
        mode,
    }
}

pub fn data_binding_matches(
    job: &Job,
    path: &str,
    sheet: &str,
    header_row: u64,
    kind: &str,
) -> bool {
    job.has_data_binding()
        && job.data_kind == kind
        && excel_identity(&job.data_path, Some(&job.data_sheet))
            == excel_identity(path, Some(sheet))
        && job.data_header_row == header_row
}

pub fn bound_jobs<'a>(
    jobs: &'a [Job],
    path: &str,
    sheet: &str,
    header_row: u64,
    kind: &str,
) -> Vec<&'a Job> {
    if path.is_empty() {
        return vec![];
    }
    jobs.iter()
        .filter(|job| data_binding_matches(job, path, sheet, header_row, kind))
        .collect()
}

pub fn candidate_rows<'a>(jobs: &'a [Job], fields: &[String]) -> Vec<(&'a Job, WorkCompatibility)> {
    jobs.iter()
        .filter_map(|job| {
            let compat = compatibility_for(job, fields);
            (compat.kind != "excluded").then_some((job, compat))
        })
        .collect()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RankedWork {
    pub name: String,
    pub tier: &'static str,
    pub at: String,
    pub mode: &'static str,
}

pub fn rank_available(jobs: &[Job], fields: &[String]) -> Vec<RankedWork> {
    let mut ranked = candidate_rows(jobs, fields)
        .into_iter()
        .filter(|(_, compat)| compat.kind == TAB_AVAILABLE)
        .map(|(job, compat)| RankedWork {
            name: job.name.clone(),
            tier: if !job.favorited_at.is_empty() {
                "favorite"
            } else if !job.last_run_at.is_empty() {
                "recent"
            } else {
                "unused"
            },
            at: if !job.favorited_at.is_empty() {
                &job.favorited_at
            } else {
                &job.last_run_at
            }
            .clone(),
            mode: compat.mode,
        })
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        let tier = |value: &str| match value {
            "favorite" => 0,
            "recent" => 1,
            _ => 2,
        };
        tier(left.tier)
            .cmp(&tier(right.tier))
            .then_with(|| right.at.cmp(&left.at))
            .then_with(|| left.name.cmp(&right.name))
    });
    ranked
}

pub fn suggested_work(ranked: &[RankedWork], active: &str) -> String {
    if active.is_empty() && ranked.len() == 1 {
        ranked[0].name.clone()
    } else {
        String::new()
    }
}

pub fn preferred_promotion(ranked: &[RankedWork], active: &str, preferred: &str) -> String {
    if active.is_empty() && ranked.iter().any(|item| item.name == preferred) {
        preferred.into()
    } else {
        String::new()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrowseRow {
    pub name: String,
    pub missing: Vec<String>,
    pub mode: &'static str,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrowseResult {
    pub tab: &'static str,
    pub rows: Vec<BrowseRow>,
    pub available_count: usize,
    pub needs_count: usize,
    pub filtered_out: usize,
}

pub fn browse_candidates(jobs: &[Job], fields: &[String], tab: &str, query: &str) -> BrowseResult {
    let mut available = vec![];
    let mut needs = vec![];
    for (job, compat) in candidate_rows(jobs, fields) {
        let row = BrowseRow {
            name: job.name.clone(),
            missing: compat.missing,
            mode: compat.mode,
        };
        if compat.kind == TAB_AVAILABLE {
            available.push(row);
        } else {
            needs.push(row);
        }
    }
    available.sort_by(|left, right| left.name.cmp(&right.name));
    needs.sort_by(|left, right| left.name.cmp(&right.name));
    let normalized_tab = if tab == TAB_NEEDS_ACTION {
        TAB_NEEDS_ACTION
    } else {
        TAB_AVAILABLE
    };
    let pool = if normalized_tab == TAB_NEEDS_ACTION {
        &needs
    } else {
        &available
    };
    let trimmed = python_trim(query);
    let rows = if trimmed.is_empty() {
        pool.clone()
    } else {
        pool.iter()
            .filter(|row| jamo_contains(&row.name, trimmed))
            .cloned()
            .collect()
    };
    let filtered_out = pool.len() - rows.len();
    BrowseResult {
        tab: normalized_tab,
        rows,
        available_count: available.len(),
        needs_count: needs.len(),
        filtered_out,
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GateState {
    pub enabled: bool,
    pub level: &'static str,
    pub text: &'static str,
    pub reason: &'static str,
}
fn gate(enabled: bool, level: &'static str, text: &'static str, reason: &'static str) -> GateState {
    GateState {
        enabled,
        level,
        text,
        reason,
    }
}
pub fn prework_gate(has_data: bool, selected_count: usize, has_candidates: bool) -> GateState {
    if !has_data {
        gate(false, "warn", "데이터 파일을 먼저 선택하세요.", "no_data")
    } else if selected_count == 0 {
        gate(false, "warn", "처리할 항목을 선택하세요.", "no_rows")
    } else if !has_candidates {
        gate(
            false,
            "warn",
            "이 데이터에 연결된 문서 작업이 없습니다.",
            "no_candidates",
        )
    } else {
        gate(false, "warn", "문서 작업을 선택하세요.", "no_job")
    }
}
pub fn workbench_entry_gate(
    has_data: bool,
    selected_count: usize,
    template_ready: bool,
) -> GateState {
    if !has_data {
        gate(false, "warn", "데이터 파일을 먼저 선택하세요.", "no_data")
    } else if selected_count == 0 {
        gate(false, "warn", "처리할 항목을 선택하세요.", "no_rows")
    } else if !template_ready {
        gate(
            false,
            "danger",
            "템플릿 파일을 찾을 수 없습니다. 템플릿을 다시 연결한 뒤 진행하세요.",
            "template_missing",
        )
    } else {
        gate(
            true,
            "ok",
            "선택한 항목을 작업대에서 검토하고 복사합니다.",
            "",
        )
    }
}
pub fn unsupported_media_gate() -> GateState {
    gate(
        false,
        "danger",
        "이 작업의 템플릿은 HWPX 도 온나라 기안 TXT 도 아닙니다. 템플릿을 다시 연결한 뒤 진행하세요.",
        "template_missing",
    )
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::mapping::{FieldMapping, MappingProfile};
    use serde_json::Map;

    #[test]
    fn bound_candidates_preserve_identity_order_and_reasons() {
        let mut alpha = Job {
            name: "가나다".into(),
            template_path: "a.hwpx".into(),
            data_path: "sample.xlsx".into(),
            data_sheet: "One".into(),
            data_header_row: 2,
            ..Job::default()
        };
        for (path, sheet, header, kind, expected) in [
            ("sample.xlsx", "One", 2, "", true),
            ("./sample.xlsx", "One", 2, "", true),
            ("sample.xlsx", "Two", 2, "", false),
            ("sample.xlsx", "One", 1, "", false),
            ("other.xlsx", "One", 2, "", false),
            ("sample.xlsx", "One", 2, "pclm", false),
        ] {
            assert_eq!(
                data_binding_matches(&alpha, path, sheet, header, kind),
                expected
            );
        }
        alpha.data_kind = "pclm".into();
        assert!(data_binding_matches(
            &alpha,
            "sample.xlsx",
            "One",
            2,
            "pclm"
        ));
        assert!(!data_binding_matches(&alpha, "sample.xlsx", "One", 2, ""));
        assert!(!data_binding_matches(
            &Job::default(),
            "sample.xlsx",
            "One",
            2,
            ""
        ));
        alpha.data_kind.clear();
        alpha.mapping = MappingProfile::new(
            "",
            vec![FieldMapping::new("대상", "금액", "text", "", "", None).unwrap()],
            Map::new(),
        )
        .unwrap();
        let mut beta = alpha.clone();
        beta.name = "다른".into();
        beta.template_path = "b.txt".into();
        beta.mapping.mappings[0].source = "누락".into();
        beta.data_sheet = "Two".into();
        let mut excluded = alpha.clone();
        excluded.name = "미지원".into();
        excluded.template_path = "c.docx".into();
        let jobs = vec![beta, excluded, alpha];
        let fields = vec!["금액".into()];
        assert_eq!(bound_jobs(&jobs, "sample.xlsx", "One", 2, "").len(), 2);
        assert_eq!(candidate_rows(&jobs, &fields).len(), 2);
        assert_eq!(compatibility_for(&jobs[0], &fields).missing, vec!["누락"]);
        let ranked = rank_available(&jobs, &fields);
        assert_eq!(
            ranked
                .iter()
                .map(|row| row.name.as_str())
                .collect::<Vec<_>>(),
            vec!["가나다"]
        );
        assert_eq!(suggested_work(&ranked, ""), "가나다");
        assert_eq!(
            browse_candidates(&jobs, &fields, "needs_action", "다").rows[0].name,
            "다른"
        );
        assert_eq!(prework_gate(true, 1, false).reason, "no_candidates");
        assert!(workbench_entry_gate(true, 1, true).enabled);
    }

    #[test]
    fn compatibility_uses_declared_source_keys_in_mapping_order_for_both_media() {
        let mapping = MappingProfile::new(
            "",
            vec![
                FieldMapping::new("제목", "title", "text", "", "", None).unwrap(),
                FieldMapping::new("고정", "", "const", "", "", None).unwrap(),
                FieldMapping::new("잔존", "legacy", "const", "값", "", None).unwrap(),
                FieldMapping::new("날짜", "date", "date", "", "", None).unwrap(),
            ],
            Map::new(),
        )
        .unwrap();
        let mut job = Job {
            name: "기안".into(),
            template_path: "draft.txt".into(),
            mapping,
            ..Job::default()
        };
        let missing = compatibility_for(&job, &["date".into(), "extra".into()]);
        assert_eq!(missing.kind, TAB_NEEDS_ACTION);
        assert_eq!(missing.missing, ["title", "legacy"]);
        job.template_path = "notice.hwpx".into();
        assert_eq!(
            compatibility_for(&job, &["date".into()]).missing,
            missing.missing
        );
        job.template_path = "unsupported.docx".into();
        assert_eq!(compatibility_for(&job, &[]).kind, "excluded");
    }

    #[test]
    fn ranking_is_favorite_then_recent_then_name_without_truncation() {
        let job = |name: &str, favorite: &str, recent: &str| Job {
            name: name.into(),
            template_path: "notice.hwpx".into(),
            favorited_at: favorite.into(),
            last_run_at: recent.into(),
            ..Job::default()
        };
        let jobs = vec![
            job("unused", "", ""),
            job("recent", "", "2026-01-02"),
            job("favorite-old", "2026-01-01", "2026-12-31"),
            job("favorite-new", "2026-01-03", ""),
            job("recent-old", "", "2026-01-01"),
            job("a-unused", "", ""),
        ];
        let ranked = rank_available(&jobs, &[]);
        assert_eq!(ranked.len(), jobs.len());
        assert_eq!(
            ranked
                .iter()
                .map(|row| row.name.as_str())
                .collect::<Vec<_>>(),
            [
                "favorite-new",
                "favorite-old",
                "recent",
                "recent-old",
                "a-unused",
                "unused"
            ]
        );
        assert_eq!(suggested_work(&ranked, ""), "");
        assert_eq!(preferred_promotion(&ranked, "", "recent"), "recent");
        assert_eq!(preferred_promotion(&ranked, "active", "recent"), "");
        let lone = rank_available(&jobs[..1], &[]);
        assert_eq!(suggested_work(&lone, ""), "unused");
    }
}
