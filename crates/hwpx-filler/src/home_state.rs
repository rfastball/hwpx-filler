//! Pure library row health, search, and view projections over host observations.

use crate::jamo::jamo_contains;
use crate::job::Job;
use crate::output_name::pattern_field_tokens;
use crate::structure_scan::python_trim;
use hwpx_core::package::HwpxPackage;
use std::collections::{BTreeMap, BTreeSet, HashSet};

pub const VIEW_ALL: &str = "all";
pub const VIEW_RECENT: &str = "recent";
pub const VIEW_FAVORITES: &str = "favorites";
pub const VIEW_NEEDS: &str = "needsAction";
pub const MODE_ALL: &str = "all";
pub const WORK_MODE_ORDER: [&str; 3] = ["hwpx_generate", "text_review_copy", "unsupported"];

pub fn work_mode_of_filter_value(value: &str) -> &'static str {
    match value {
        "hwpx" => WORK_MODE_ORDER[0],
        "txt" => WORK_MODE_ORDER[1],
        _ => WORK_MODE_ORDER[2],
    }
}

pub fn work_mode_label(mode: &str) -> &'static str {
    match mode {
        "hwpx" | "hwpx_generate" => "HWPX 문서 생성",
        "txt" | "text_review_copy" => "온나라 기안 검토·복사",
        _ => "지원 작업 방식 확인 필요",
    }
}

pub fn work_mode_short_label(mode: &str) -> &'static str {
    match mode {
        "hwpx" | "hwpx_generate" => "HWPX 생성",
        "txt" | "text_review_copy" => "온나라 기안",
        _ => "작업 방식 확인",
    }
}

pub fn example_entry_state(installed: bool) -> serde_json::Value {
    serde_json::json!({
        "installed": installed,
        "label": if installed { "예제 다시 설치…" } else { "예제로 시작하기…" },
        "hint": if installed {
            "동봉 예제 7건을 처음 상태로 되돌립니다."
        } else {
            "동봉 예제 7건을 라이브러리에 넣고 데이터를 고정합니다."
        },
        "removable": installed,
        "remove_label": "예제 걷어내기…",
        "remove_hint": "설치한 예제만 걷습니다. 되돌리려면 다시 설치하세요.",
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CompileState {
    Raw,
    Partial { remaining: usize },
    Compiled,
}
impl CompileState {
    pub fn badge_level(&self) -> &'static str {
        match self {
            Self::Raw => "muted",
            Self::Partial { .. } => "warn",
            Self::Compiled => "ok",
        }
    }
    pub fn badge_text(&self) -> String {
        match self {
            Self::Raw => "✏ 원문·누름틀 변환 필요".into(),
            Self::Partial { remaining } => format!("⚠ 미확인 토큰 {remaining}개"),
            Self::Compiled => "✅ 실행 준비".into(),
        }
    }
}

/// Recompute status from an opened package so an external HWPX edit cannot leave a stale badge.
pub fn compile_status(package: &HwpxPackage) -> Result<CompileState, String> {
    crate::template_library_state::TemplateStatus::inspect(package).map(|status| status.state)
}

/// Interpret bytes already read by the host; package parsing and field policy stay in Rust.
pub fn inspect_hwpx_bytes(
    bytes: &[u8],
) -> Result<(CompileState, Result<Vec<String>, String>), String> {
    let package = HwpxPackage::from_bytes(bytes, hwpx_core::package::PackageLimits::default())
        .map_err(|error| error.to_string())?;
    let status = compile_status(&package)?;
    let fields = crate::fields::required_fields(&package).map_err(|error| error.to_string());
    Ok((status, fields))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RowObservation {
    pub template_missing: bool,
    /// None means the HWPX compile status could not be read (or this is not HWPX).
    pub compile: Option<CompileState>,
    /// None means no structure observation; Err keeps an explicit read failure.
    pub template_fields: Option<Result<Vec<String>, String>>,
    pub txt_readable: bool,
}
impl Default for RowObservation {
    fn default() -> Self {
        Self {
            template_missing: false,
            compile: None,
            template_fields: None,
            txt_readable: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureDrift {
    pub readable: bool,
    pub template_fields: Vec<String>,
    pub template_only: Vec<String>,
    pub mapping_only: Vec<String>,
    pub conflicting: Vec<String>,
    pub read_error: String,
}
impl StructureDrift {
    pub fn from_fields(job: &Job, fields: Result<Vec<String>, String>) -> Self {
        match fields {
            Err(read_error) => Self {
                readable: false,
                template_fields: Vec::new(),
                template_only: Vec::new(),
                mapping_only: Vec::new(),
                conflicting: Vec::new(),
                read_error,
            },
            Ok(fields) => {
                let mut seen = HashSet::new();
                let template_fields = fields
                    .into_iter()
                    .filter(|field| seen.insert(field.clone()))
                    .collect::<Vec<_>>();
                let covered = job.mapping.cover_fields();
                let template_set = template_fields.iter().collect::<HashSet<_>>();
                let cover_set = covered.iter().collect::<HashSet<_>>();
                let template_only = template_fields
                    .iter()
                    .filter(|field| !cover_set.contains(field))
                    .cloned()
                    .collect();
                let mapping_only = covered
                    .iter()
                    .filter(|field| !template_set.contains(field))
                    .cloned()
                    .collect();
                Self {
                    readable: true,
                    template_fields,
                    template_only,
                    mapping_only,
                    conflicting: job.mapping.coverage_conflicts(),
                    read_error: String::new(),
                }
            }
        }
    }
    pub fn has_drift(&self) -> bool {
        !self.read_error.is_empty()
            || !self.template_only.is_empty()
            || !self.mapping_only.is_empty()
            || !self.conflicting.is_empty()
    }
    pub fn describe(&self, separator: &str) -> String {
        let mut parts = Vec::new();
        if !self.read_error.is_empty() {
            parts.push(format!("템플릿 구조를 읽을 수 없음: {}", self.read_error));
        }
        if !self.template_only.is_empty() {
            parts.push(format!(
                "새로 유입된 미매핑 필드: {}",
                self.template_only.join(", ")
            ));
        }
        if !self.mapping_only.is_empty() {
            parts.push(format!(
                "템플릿에서 소멸한 매핑 필드: {}",
                self.mapping_only.join(", ")
            ));
        }
        if !self.conflicting.is_empty() {
            parts.push(format!(
                "값 매핑과 비움 확정이 충돌하는 필드: {}",
                self.conflicting.join(", ")
            ));
        }
        parts.join(separator)
    }
}

fn template_name(path: &str) -> String {
    if path.is_empty() {
        "—".into()
    } else {
        path.rsplit(['/', '\\'])
            .next()
            .filter(|name| !name.is_empty())
            .unwrap_or("—")
            .into()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JobRow {
    pub name: String,
    pub template_name: String,
    pub template_missing: bool,
    pub field_count: usize,
    pub filename_pattern: String,
    pub last_run_at: String,
    pub compile_state: Option<CompileState>,
    pub compile_badge: String,
    pub tags: BTreeMap<String, String>,
    pub group: String,
    pub favorited_at: String,
    pub media: String,
    pub template_linked: bool,
    pub structure: Option<StructureDrift>,
    pub txt_readable: bool,
    pub unresolved_name_tokens: bool,
    pub mapping_empty: bool,
    pub data_bound: bool,
    pub data_label: String,
}
impl JobRow {
    pub fn from_job(job: &Job, observation: RowObservation) -> Self {
        let media = job.media();
        let compile_state = if media == "hwpx" && !observation.template_missing {
            observation.compile
        } else {
            None
        };
        let compile_badge = if media != "hwpx" || job.template_path.is_empty() {
            String::new()
        } else if observation.template_missing {
            "❌ 템플릿 없음".into()
        } else {
            compile_state
                .as_ref()
                .map_or_else(|| "⚠ 템플릿 오류".into(), CompileState::badge_text)
        };
        let structure = if media == "hwpx" && compile_state.is_none() {
            None
        } else {
            observation
                .template_fields
                .map(|fields| StructureDrift::from_fields(job, fields))
        };
        let covered = job
            .mapping
            .cover_fields()
            .into_iter()
            .collect::<HashSet<_>>();
        let declared = job
            .mapping
            .declared_empty_fields()
            .into_iter()
            .collect::<HashSet<_>>();
        let unresolved_name_tokens = media == "hwpx"
            && pattern_field_tokens(&job.filename_pattern)
                .iter()
                .any(|field| !covered.contains(field) || declared.contains(field));
        Self {
            name: job.name.clone(),
            template_name: template_name(&job.template_path),
            template_missing: observation.template_missing,
            field_count: job.mapping.mappings.len(),
            filename_pattern: job.filename_pattern.clone(),
            last_run_at: job.last_run_at.clone(),
            compile_state,
            compile_badge,
            tags: job
                .tags
                .iter()
                .filter_map(|(axis, value)| {
                    value.as_str().map(|value| (axis.clone(), value.into()))
                })
                .collect(),
            group: job.group.clone(),
            favorited_at: job.favorited_at.clone(),
            media: media.into(),
            template_linked: !job.template_path.is_empty(),
            structure,
            txt_readable: observation.txt_readable,
            unresolved_name_tokens,
            mapping_empty: job.mapping.mappings.is_empty(),
            data_bound: job.has_data_binding(),
            data_label: job.data_binding_label(),
        }
    }
    pub fn meta_line(&self) -> String {
        format!(
            "템플릿 {} · 필드 {}개 · 파일명 {}",
            self.template_name, self.field_count, self.filename_pattern
        )
    }
    pub fn badge_level(&self) -> &'static str {
        self.compile_state
            .as_ref()
            .map_or("danger", CompileState::badge_level)
    }
    pub fn is_runnable(&self) -> bool {
        self.badge_level() != "danger"
    }
    pub fn library_mode(&self) -> &str {
        if self.template_linked {
            &self.media
        } else {
            "hwpx"
        }
    }
    pub fn structure_drift(&self) -> bool {
        self.structure.as_ref().is_some_and(|structure| {
            (self.media == "hwpx" || structure.readable) && structure.has_drift()
        })
    }
    fn template_health_cause(&self) -> Option<(u8, String)> {
        if !self.template_linked {
            Some((3, "템플릿을 아직 연결하지 않았습니다.".into()))
        } else if self.template_missing {
            Some((3, "템플릿 파일을 찾을 수 없습니다.".into()))
        } else if !matches!(self.media.as_str(), "hwpx" | "txt") {
            Some((3, "지원하지 않는 작업 방식입니다.".into()))
        } else if (self.media == "hwpx" && self.compile_state.is_none()) || !self.txt_readable {
            Some((3, "템플릿을 읽을 수 없습니다.".into()))
        } else {
            None
        }
    }
    pub fn health_causes(&self) -> Vec<(u8, String)> {
        let mut causes = self.template_health_cause().into_iter().collect::<Vec<_>>();
        if self.unresolved_name_tokens {
            causes.push((3, "파일명 패턴의 토큰을 채우지 못합니다.".into()));
        }
        if self.structure_drift() && self.mapping_empty {
            causes.push((
                if self.media == "hwpx" { 3 } else { 2 },
                "매핑을 아직 확정하지 않았습니다.".into(),
            ));
        } else if self.structure_drift() {
            causes.push((2, "템플릿 구조가 확정 매핑과 달라졌습니다.".into()));
        } else if self.badge_level() == "warn" {
            causes.push((
                2,
                if self.compile_badge.is_empty() {
                    "템플릿에 확인할 항목이 남아 있습니다.".into()
                } else {
                    self.compile_badge.clone()
                },
            ));
        }
        causes.sort_by_key(|cause| std::cmp::Reverse(cause.0));
        causes
    }
    pub fn health(&self) -> (u8, String) {
        self.health_causes().into_iter().next().unwrap_or_default()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GroupSection {
    pub value: String,
    pub is_untagged: bool,
    pub rows: Vec<JobRow>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FacetValue {
    pub value: String,
    pub count: usize,
    pub active: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FacetAxis {
    pub axis: String,
    pub values: Vec<FacetValue>,
}

pub fn discover_tag_axes(jobs: &[Job]) -> BTreeMap<String, BTreeSet<String>> {
    let mut axes: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for job in jobs {
        for (axis, value) in &job.tags {
            if let Some(value) = value.as_str().filter(|value| !value.is_empty()) {
                axes.entry(axis.clone()).or_default().insert(value.into());
            }
        }
    }
    axes
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LibraryLens {
    pub view: String,
    pub mode: String,
    pub query: String,
    pub active_facets: BTreeMap<String, BTreeSet<String>>,
}
impl Default for LibraryLens {
    fn default() -> Self {
        Self {
            view: VIEW_ALL.into(),
            mode: MODE_ALL.into(),
            query: String::new(),
            active_facets: BTreeMap::new(),
        }
    }
}
impl LibraryLens {
    pub fn toggle_facet(&mut self, axis: &str, value: &str) {
        let selected = self.active_facets.entry(axis.into()).or_default();
        if !selected.remove(value) {
            selected.insert(value.into());
        }
        if selected.is_empty() {
            self.active_facets.remove(axis);
        }
    }
    pub fn set_facets(&mut self, mut facets: BTreeMap<String, BTreeSet<String>>) {
        facets.retain(|_, values| !values.is_empty());
        self.active_facets = facets;
    }
    pub fn clear_facets(&mut self) {
        self.active_facets.clear();
    }
    fn passes_facets(&self, row: &JobRow, exclude_axis: &str) -> bool {
        self.active_facets.iter().all(|(axis, selected)| {
            axis == exclude_axis
                || selected.is_empty()
                || row
                    .tags
                    .get(axis)
                    .is_some_and(|value| selected.contains(value))
        })
    }
    pub fn facets(&self, rows: &[JobRow]) -> Vec<FacetAxis> {
        let axes = rows
            .iter()
            .flat_map(|row| row.tags.keys())
            .chain(self.active_facets.keys())
            .collect::<BTreeSet<_>>();
        axes.into_iter()
            .map(|axis| FacetAxis {
                axis: axis.clone(),
                values: self.facet_values(rows, axis),
            })
            .collect()
    }
    fn facet_values(&self, rows: &[JobRow], axis: &str) -> Vec<FacetValue> {
        let mut counts: BTreeMap<String, usize> = BTreeMap::new();
        for row in rows {
            if let Some(value) = row.tags.get(axis).filter(|value| !value.is_empty()) {
                *counts.entry(value.clone()).or_default() +=
                    usize::from(self.passes_facets(row, axis));
            }
        }
        let selected = self.active_facets.get(axis);
        for value in selected.into_iter().flatten() {
            counts.entry(value.clone()).or_default();
        }
        counts
            .into_iter()
            .map(|(value, count)| FacetValue {
                active: selected.is_some_and(|selected| selected.contains(&value)),
                value,
                count,
            })
            .collect()
    }
    pub fn set_view(&mut self, view: &str) {
        self.view = if [VIEW_ALL, VIEW_RECENT, VIEW_FAVORITES, VIEW_NEEDS].contains(&view) {
            view
        } else {
            VIEW_ALL
        }
        .into();
    }
    pub fn set_mode(&mut self, mode: &str) {
        self.mode = if [MODE_ALL, "hwpx", "txt"].contains(&mode) {
            mode
        } else {
            MODE_ALL
        }
        .into();
    }
    fn mode_rows<'a>(&self, rows: &'a [JobRow]) -> Vec<&'a JobRow> {
        rows.iter()
            .filter(|row| self.passes_facets(row, ""))
            .filter(|row| self.mode == MODE_ALL || row.library_mode() == self.mode)
            .collect()
    }
    pub fn counts(&self, rows: &[JobRow]) -> [usize; 4] {
        let rows = self.mode_rows(rows);
        [
            rows.len(),
            rows.iter()
                .filter(|row| !row.last_run_at.is_empty())
                .count(),
            rows.iter()
                .filter(|row| !row.favorited_at.is_empty())
                .count(),
            rows.iter().filter(|row| row.health().0 > 0).count(),
        ]
    }
    fn picked_rows(&self, rows: &[JobRow]) -> Vec<JobRow> {
        let query = python_trim(&self.query);
        let mut picked = self
            .mode_rows(rows)
            .into_iter()
            .filter(|row| {
                query.is_empty()
                    || jamo_contains(&row.name, query)
                    || jamo_contains(&row.group, query)
                    || row.tags.values().any(|tag| jamo_contains(tag, query))
            })
            .filter(|row| match self.view.as_str() {
                VIEW_RECENT => !row.last_run_at.is_empty(),
                VIEW_FAVORITES => !row.favorited_at.is_empty(),
                VIEW_NEEDS => row.health().0 > 0,
                _ => true,
            })
            .cloned()
            .collect::<Vec<_>>();
        picked.sort_by(|left, right| left.name.cmp(&right.name));
        match self.view.as_str() {
            VIEW_RECENT => picked.sort_by(|left, right| right.last_run_at.cmp(&left.last_run_at)),
            VIEW_FAVORITES => {
                picked.sort_by(|left, right| right.favorited_at.cmp(&left.favorited_at))
            }
            VIEW_NEEDS => picked.sort_by_key(|row| std::cmp::Reverse(row.health().0)),
            _ => (),
        }
        picked
    }
    pub fn sections(&self, rows: &[JobRow], grouped: bool) -> Vec<GroupSection> {
        let picked = self.picked_rows(rows);
        if self.view != VIEW_ALL || !grouped {
            return vec![GroupSection {
                value: String::new(),
                is_untagged: false,
                rows: picked,
            }];
        }
        let names = picked
            .iter()
            .filter(|row| !row.group.is_empty())
            .map(|row| row.group.clone())
            .collect::<std::collections::BTreeSet<_>>();
        if names.is_empty() {
            return vec![GroupSection {
                value: String::new(),
                is_untagged: false,
                rows: picked,
            }];
        }
        let mut sections = names
            .into_iter()
            .map(|name| GroupSection {
                rows: picked
                    .iter()
                    .filter(|row| row.group == name)
                    .cloned()
                    .collect(),
                value: name,
                is_untagged: false,
            })
            .collect::<Vec<_>>();
        let untagged = picked
            .into_iter()
            .filter(|row| row.group.is_empty())
            .collect::<Vec<_>>();
        if !untagged.is_empty() {
            sections.push(GroupSection {
                value: String::new(),
                is_untagged: true,
                rows: untagged,
            });
        }
        sections
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        CompileState, JobRow, LibraryLens, RowObservation, VIEW_NEEDS, WORK_MODE_ORDER,
        compile_status, work_mode_label, work_mode_of_filter_value, work_mode_short_label,
    };
    use crate::job::Job;
    use serde_json::json;

    #[test]
    fn work_mode_labels_and_sections_preserve_library_attribution_and_rank() {
        let unlinked = Job::default();
        assert_eq!(unlinked.media(), "");
        assert_eq!(unlinked.work_mode(), "unsupported");
        assert_eq!(
            JobRow::from_job(&unlinked, RowObservation::default()).library_mode(),
            "hwpx"
        );
        assert_eq!(
            WORK_MODE_ORDER,
            ["hwpx_generate", "text_review_copy", "unsupported"]
        );
        for (mode, short, full) in [
            ("hwpx_generate", "HWPX 생성", "HWPX 문서 생성"),
            ("text_review_copy", "온나라 기안", "온나라 기안 검토·복사"),
            ("unsupported", "작업 방식 확인", "지원 작업 방식 확인 필요"),
        ] {
            assert_eq!(work_mode_short_label(mode), short);
            assert_eq!(work_mode_label(mode), full);
        }
        assert_eq!(work_mode_label("unknown"), work_mode_label("unsupported"));
        assert_eq!(
            work_mode_short_label(""),
            work_mode_short_label("unsupported")
        );
        assert_eq!(work_mode_of_filter_value("hwpx"), "hwpx_generate");
        assert_eq!(work_mode_of_filter_value("txt"), "text_review_copy");
        assert_eq!(work_mode_of_filter_value(""), "unsupported");
        // A library filter's hwpx attribution is translated, even for an unlinked Job.
        assert_eq!(work_mode_label("hwpx"), work_mode_label("hwpx_generate"));

        let ranked = [
            json!({"name":"기안A","mode":"text_review_copy"}),
            json!({"name":"문서A","mode":"hwpx_generate"}),
            json!({"name":"기안B","mode":"text_review_copy"}),
        ];
        assert_eq!(
            crate::job_presentation::mode_sections(&ranked),
            vec![
                json!({"mode":"text_review_copy","mode_label":"온나라 기안 검토·복사","names":["기안A","기안B"]}),
                json!({"mode":"hwpx_generate","mode_label":"HWPX 문서 생성","names":["문서A"]}),
            ]
        );
        assert_eq!(
            crate::job_presentation::mode_sections(&ranked[1..2]).len(),
            1
        );
        assert!(crate::job_presentation::mode_sections(&[]).is_empty());
    }

    #[test]
    fn missing_and_partial_rows_keep_health_order_and_search_counts() {
        assert_tag_facet_selection_and_counts();
        assert_library_views_and_row_metadata();
        let mut package = hwpx_core::package::HwpxPackage {
            entries: vec![hwpx_core::package::PackageEntry {
                name: "Contents/section0.xml".into(),
                data: format!("<hs:sec xmlns:hs='urn:section' xmlns:hp='{}'><hp:p><hp:run><hp:t>{{{{계약명}}}}</hp:t></hp:run></hp:p></hs:sec>", hwpx_core::text_model::HP_NS).into_bytes(),
                stored: false,
            }],
        };
        assert_eq!(compile_status(&package).unwrap(), CompileState::Raw);
        crate::authoring::compile_document(&mut package, None).unwrap();
        assert_eq!(compile_status(&package).unwrap(), CompileState::Compiled);
        let mut missing = Job {
            name: "행복도시".into(),
            template_path: "C:/lost.hwpx".into(),
            ..Job::default()
        };
        missing.last_run_at = "2026-11-05T12:00:00".into();
        let missing = JobRow::from_job(
            &missing,
            RowObservation {
                template_missing: true,
                txt_readable: true,
                ..RowObservation::default()
            },
        );
        assert_eq!(missing.health().0, 3);
        assert_eq!(missing.health().1, "템플릿 파일을 찾을 수 없습니다.");
        let partial = Job {
            name: "계약".into(),
            template_path: "C:/good.hwpx".into(),
            ..Job::default()
        };
        let partial = JobRow::from_job(
            &partial,
            RowObservation {
                compile: Some(CompileState::Partial { remaining: 2 }),
                template_fields: Some(Ok(vec!["공고명".into()])),
                txt_readable: true,
                ..RowObservation::default()
            },
        );
        assert_eq!(
            partial.health(),
            (3, "매핑을 아직 확정하지 않았습니다.".into())
        );
        assert_eq!(
            partial.structure.as_ref().unwrap().template_only,
            ["공고명"]
        );
        assert_eq!(
            partial.structure.as_ref().unwrap().describe("\n"),
            "새로 유입된 미매핑 필드: 공고명"
        );
        let rows = vec![missing, partial];
        let mut lens = LibraryLens::default();
        assert_eq!(lens.counts(&rows), [2, 1, 0, 2]);
        lens.set_view(VIEW_NEEDS);
        lens.query = "행복도ㅅ".into();
        assert_eq!(lens.sections(&rows, false)[0].rows.len(), 1);
        assert_eq!(lens.sections(&rows, false)[0].rows[0].name, "행복도시");
    }

    fn assert_library_views_and_row_metadata() {
        use super::{VIEW_ALL, VIEW_FAVORITES, VIEW_RECENT};
        use crate::mapping::FieldMapping;
        let plain = JobRow::from_job(
            &Job {
                name: "x".into(),
                filename_pattern: "p-{{ID}}".into(),
                ..Job::default()
            },
            RowObservation::default(),
        );
        assert_eq!(
            (
                plain.name.as_str(),
                plain.template_name.as_str(),
                plain.field_count
            ),
            ("x", "—", 0)
        );
        assert!(!plain.template_missing);
        assert_eq!(plain.last_run_at, "");
        let rows = [
            ("즐겨공고", "C:/lib.hwpx", "조달", "", "2026-07-20T09:00:00"),
            ("최근계약", "C:/lib.hwpx", "조달", "2026-07-25T09:00:00", ""),
            ("미사용문서", "C:/lib.hwpx", "", "", ""),
            ("깨진연결", "C:/none.hwpx", "", "", ""),
            ("기안문", "C:/none.txt", "", "", ""),
        ]
        .map(|(name, path, group, recent, favorite)| {
            let mut job = Job {
                name: name.into(),
                template_path: path.into(),
                group: group.into(),
                last_run_at: recent.into(),
                favorited_at: favorite.into(),
                ..Job::default()
            };
            job.mapping
                .mappings
                .push(FieldMapping::new("계약명", "bidNtceNm", "text", "", "", None).unwrap());
            if name == "미사용문서" {
                job.tags.insert("물품".into(), json!("의약품"));
            }
            JobRow::from_job(
                &job,
                RowObservation {
                    template_missing: path.contains("none"),
                    compile: Some(CompileState::Compiled),
                    template_fields: Some(Ok(vec!["계약명".into()])),
                    ..RowObservation::default()
                },
            )
        });
        assert_eq!(rows[1].last_run_at, "2026-07-25T09:00:00");
        assert_eq!(rows[0].field_count, 1);
        assert_eq!(rows[0].template_name, "lib.hwpx");
        assert_eq!(
            rows[0].meta_line(),
            "템플릿 lib.hwpx · 필드 1개 · 파일명 공고서-{{date}}-{{seq:001}}"
        );
        let names = |lens: &LibraryLens, grouped| {
            lens.sections(&rows, grouped)
                .iter()
                .flat_map(|section| section.rows.iter().map(|row| row.name.clone()))
                .collect::<Vec<_>>()
        };
        let mut lens = LibraryLens::default();
        assert_eq!(lens.counts(&rows), [5, 1, 1, 2]);
        for (view, expected) in [
            (VIEW_FAVORITES, vec!["즐겨공고"]),
            (VIEW_RECENT, vec!["최근계약"]),
            (VIEW_NEEDS, vec!["기안문", "깨진연결"]),
        ] {
            lens.set_view(view);
            assert_eq!(names(&lens, true), expected);
        }
        lens.set_view(VIEW_ALL);
        let groups = lens.sections(&rows, true);
        assert_eq!(
            groups
                .iter()
                .map(|group| (group.value.as_str(), group.is_untagged))
                .collect::<Vec<_>>(),
            [("조달", false), ("", true)]
        );
        assert_eq!(
            groups[0]
                .rows
                .iter()
                .map(|row| row.name.as_str())
                .collect::<Vec<_>>(),
            ["즐겨공고", "최근계약"]
        );
        let ungrouped = lens.sections(&rows, false);
        assert_eq!(ungrouped.len(), 1);
        assert!(!ungrouped[0].is_untagged && ungrouped[0].value.is_empty());
        assert_eq!(ungrouped[0].rows.len(), rows.len());
        let flat = lens.sections(&[plain], true);
        assert_eq!(flat.len(), 1);
        assert!(!flat[0].is_untagged && flat[0].value.is_empty());
        lens.set_mode("txt");
        assert_eq!(names(&lens, true), ["기안문"]);
        assert_eq!(lens.counts(&rows)[0], 1);
        lens.set_mode("hwpx");
        lens.query = "조달".into();
        assert_eq!(names(&lens, true), ["즐겨공고", "최근계약"]);
        lens.query = "의약품".into();
        assert_eq!(names(&lens, true), ["미사용문서"]);
        assert_eq!(lens.counts(&rows)[0], 4);
        lens.query = "bidNtceNm".into();
        assert!(names(&lens, true).is_empty());
        lens.set_view("엉뚱");
        lens.set_mode("엉뚱");
        assert_eq!((lens.view.as_str(), lens.mode.as_str()), (VIEW_ALL, "all"));
    }

    fn assert_tag_facet_selection_and_counts() {
        use super::{MODE_ALL, VIEW_ALL, VIEW_FAVORITES, VIEW_RECENT, discover_tag_axes};
        use std::collections::{BTreeMap, BTreeSet};
        let jobs = [
            (
                "적격-소액",
                "a.hwpx",
                json!({"금액구간":"1억미만","낙찰방법":"적격심사"}),
            ),
            (
                "적격-고시",
                "b.txt",
                json!({"금액구간":"고시이상","낙찰방법":"적격심사"}),
            ),
            (
                "협상-소액",
                "c.hwpx",
                json!({"금액구간":"1억미만","낙찰방법":"협상"}),
            ),
            ("무태그", "d.txt", json!({})),
        ]
        .map(|(name, path, tags)| Job {
            name: name.into(),
            template_path: path.into(),
            tags: tags.as_object().unwrap().clone(),
            last_run_at: if name == "무태그" {
                ""
            } else {
                "2026-07-09T15:42:00"
            }
            .into(),
            favorited_at: if name == "협상-소액" {
                "2026-07-10"
            } else {
                ""
            }
            .into(),
            ..Job::default()
        });
        let rows = jobs
            .iter()
            .map(|job| {
                JobRow::from_job(
                    job,
                    RowObservation {
                        template_missing: true,
                        ..RowObservation::default()
                    },
                )
            })
            .collect::<Vec<_>>();
        let expected: BTreeMap<String, BTreeSet<String>> = [
            (
                "금액구간".into(),
                ["1억미만".into(), "고시이상".into()].into(),
            ),
            ("낙찰방법".into(), ["적격심사".into(), "협상".into()].into()),
        ]
        .into();
        assert_eq!(discover_tag_axes(&jobs), expected);
        assert!(discover_tag_axes(&[]).is_empty());
        let mut empty_tag = Job::default();
        empty_tag.tags.insert("빈 축".into(), json!(""));
        assert!(discover_tag_axes(&[empty_tag]).is_empty());
        let shown = |lens: &LibraryLens| {
            lens.sections(&rows, true)
                .iter()
                .flat_map(|section| section.rows.iter().map(|row| row.name.clone()))
                .collect::<BTreeSet<_>>()
        };
        let names = |items: &[&str]| {
            items
                .iter()
                .map(|name| (*name).into())
                .collect::<BTreeSet<String>>()
        };
        let counts = |lens: &LibraryLens| {
            lens.facets(&rows)
                .into_iter()
                .map(|axis| {
                    (
                        axis.axis,
                        axis.values
                            .into_iter()
                            .map(|value| (value.value, (value.count, value.active)))
                            .collect::<BTreeMap<_, _>>(),
                    )
                })
                .collect::<BTreeMap<_, _>>()
        };
        let mut lens = LibraryLens::default();
        assert_eq!(counts(&lens)["금액구간"]["1억미만"], (2, false));
        assert_eq!(counts(&lens)["금액구간"]["고시이상"], (1, false));
        assert_eq!(counts(&lens)["낙찰방법"]["적격심사"], (2, false));
        assert_eq!(counts(&lens)["낙찰방법"]["협상"], (1, false));
        assert!(lens.facets(&rows[3..]).is_empty());
        let flat = lens.sections(&rows[3..], true);
        assert_eq!(flat.len(), 1);
        assert!(flat[0].value.is_empty() && !flat[0].is_untagged);

        lens.toggle_facet("낙찰방법", "적격심사");
        assert_eq!(shown(&lens), names(&["적격-고시", "적격-소액"]));
        assert_eq!(counts(&lens)["낙찰방법"]["적격심사"], (2, true));
        assert_eq!(counts(&lens)["낙찰방법"]["협상"], (1, false));
        assert_eq!(counts(&lens)["금액구간"]["1억미만"], (1, false));
        assert_eq!(counts(&lens)["금액구간"]["고시이상"], (1, false));
        lens.toggle_facet("낙찰방법", "협상");
        assert_eq!(
            shown(&lens),
            names(&["적격-고시", "적격-소액", "협상-소액"])
        );
        lens.toggle_facet("금액구간", "1억미만");
        assert_eq!(shown(&lens), names(&["적격-소액", "협상-소액"]));
        lens.toggle_facet("낙찰방법", "적격심사");
        assert_eq!(shown(&lens), names(&["협상-소액"]));
        assert_eq!(counts(&lens)["금액구간"]["고시이상"], (0, false));
        assert_eq!(counts(&lens)["낙찰방법"]["적격심사"], (1, false));
        for view in [VIEW_ALL, VIEW_RECENT, VIEW_FAVORITES, VIEW_NEEDS] {
            lens.set_view(view);
            assert_eq!(shown(&lens), names(&["협상-소액"]));
        }
        lens.query = "일치하지 않는 검색어".into();
        assert!(shown(&lens).is_empty());
        assert_eq!(lens.counts(&rows), [1, 1, 1, 1]);
        lens.query = "협상".into();
        lens.set_mode("txt");
        assert!(shown(&lens).is_empty());
        assert_eq!(lens.counts(&rows), [0; 4]);
        lens.set_mode("hwpx");
        assert_eq!(shown(&lens), names(&["협상-소액"]));
        lens.set_mode(MODE_ALL);
        lens.set_view(VIEW_ALL);
        lens.query.clear();
        lens.toggle_facet("낙찰방법", "협상");
        assert!(!lens.active_facets.contains_key("낙찰방법"));
        lens.clear_facets();
        assert!(lens.active_facets.is_empty());
        lens.clear_facets();
        lens.set_facets(
            [
                ("낙찰방법".into(), names(&["협상"])),
                ("빈축".into(), BTreeSet::new()),
            ]
            .into(),
        );
        assert_eq!(lens.active_facets.len(), 1);
        assert_eq!(shown(&lens), names(&["협상-소액"]));
        let orphaned = lens.facets(&rows[3..]);
        assert_eq!(orphaned[0].axis, "낙찰방법");
        assert_eq!(
            orphaned[0].values[0],
            super::FacetValue {
                value: "협상".into(),
                count: 0,
                active: true
            }
        );
        assert!(lens.sections(&rows[3..], true)[0].rows.is_empty());
        lens.clear_facets();
        lens.query = "고시이상".into();
        assert_eq!(shown(&lens), names(&["적격-고시"]));
    }
}
