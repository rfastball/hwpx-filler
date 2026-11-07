//! In-memory document and trial revisions for one authoring tab.

use hwpx_filler::field_proposal::FieldProposalState;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};

fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

type PendingProposal = (String, Map<String, Value>, Map<String, Value>);

#[derive(Clone, Debug)]
pub struct AuthoringSession {
    pub id: String,
    pub media: String,
    pub content: Vec<u8>,
    pub source_path: String,
    pub save_path: String,
    pub baseline: Option<String>,
    pub source_baseline: Option<String>,
    pub saved_content: Vec<u8>,
    pub revision: u64,
    pub analysis: Value,
    pub cached_problems: Option<(u64, Vec<Value>)>,
    pub saved_analysis: Value,
    pub identifier_changes: Vec<Value>,
    pub last_preview: Option<(Vec<u8>, Vec<Value>)>,
    pub eol: String,
    pub external_changed: bool,
    pub rhwp_editable: Option<bool>,
    pub rhwp_diagnostics: Vec<Value>,
    pub cases: Vec<Value>,
    pub cases_error: String,
    pub cases_dirty: bool,
    pub values: Map<String, Value>,
    pub selected: Map<String, Value>,
    pub trial_input_revision: u64,
    pub trial_result: Option<Value>,
    pub trial_generation: u64,
    pub trial_coverage_evidence: HashMap<(String, String), (u64, String)>,
    pub trial_error: String,
    pub trial_document_revision: i64,
    pub trial_values_revision: i64,
    pub proposal: Option<FieldProposalState>,
    pub proposal_cache: Option<(u64, Value)>,
    pub proposal_bindings: Map<String, Value>,
    pub proposal_pending: Option<PendingProposal>,
    pub proposal_retired: HashMap<String, (Value, Value)>,
    pub proposal_seeded: Map<String, Value>,
}

impl AuthoringSession {
    pub fn new(id: String, media: String, content: Vec<u8>, analysis: Value) -> Self {
        Self {
            id,
            media,
            saved_content: Vec::new(),
            content,
            source_path: String::new(),
            save_path: String::new(),
            baseline: None,
            source_baseline: None,
            revision: 0,
            saved_analysis: Value::Object(Map::new()),
            analysis,
            cached_problems: None,
            identifier_changes: Vec::new(),
            last_preview: None,
            eol: "\n".into(),
            external_changed: false,
            rhwp_editable: None,
            rhwp_diagnostics: Vec::new(),
            cases: Vec::new(),
            cases_error: String::new(),
            cases_dirty: false,
            values: Map::new(),
            selected: Map::new(),
            trial_input_revision: 0,
            trial_result: None,
            trial_generation: 0,
            trial_coverage_evidence: HashMap::new(),
            trial_error: String::new(),
            trial_document_revision: -1,
            trial_values_revision: -1,
            proposal: None,
            proposal_cache: None,
            proposal_bindings: Map::new(),
            proposal_pending: None,
            proposal_retired: HashMap::new(),
            proposal_seeded: Map::new(),
        }
    }

    pub fn dirty(&self) -> bool {
        self.content != self.saved_content
    }
    pub fn trial_stale(&self) -> bool {
        self.trial_result.is_none()
            || self.trial_document_revision != self.revision as i64
            || self.trial_values_revision != self.trial_input_revision as i64
    }
    pub fn trial_inputs_dirty(&self) -> bool {
        if self.values.is_empty() && self.selected.is_empty() {
            return false;
        }
        !self.cases.iter().any(|case| {
            case.get("values") == Some(&Value::Object(self.values.clone()))
                && case.get("selected") == Some(&Value::Object(self.selected.clone()))
        })
    }
    pub fn replace_trial_input(
        &mut self,
        values: Map<String, Value>,
        selected: Map<String, Value>,
    ) {
        if values == self.values && selected == self.selected {
            return;
        }
        self.values = values;
        self.selected = selected;
        self.trial_input_revision += 1;
    }
    pub fn replace_content(&mut self, content: Vec<u8>, analysis: Value) {
        if content == self.content {
            return;
        }
        self.content = content;
        self.analysis = analysis;
        self.cached_problems = None;
        self.revision += 1;
        self.settle_proposal_bindings();
    }
    fn settle_proposal_bindings(&mut self) {
        let fields: HashSet<String> = self
            .analysis
            .get("fields")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|field| field.get("name").and_then(Value::as_str).map(str::to_owned))
            .collect();
        let mut values = self.values.clone();
        if self
            .proposal_pending
            .as_ref()
            .is_some_and(|pending| pending.0 == digest(&self.content))
        {
            let (_, bindings, seeded) = self.proposal_pending.take().expect("pending");
            for (name, binding) in bindings {
                if fields.contains(&name) {
                    if let Some(value) = seeded.get(&name) {
                        values.insert(name.clone(), value.clone());
                        self.proposal_seeded.insert(name.clone(), value.clone());
                    }
                    self.proposal_bindings.insert(name.clone(), binding);
                    self.proposal_retired.remove(&name);
                }
            }
        }
        let missing: Vec<String> = self
            .proposal_bindings
            .keys()
            .filter(|name| !fields.contains(*name))
            .cloned()
            .collect();
        for name in missing {
            let seeded = self
                .proposal_seeded
                .remove(&name)
                .unwrap_or(Value::String(String::new()));
            if let Some(binding) = self.proposal_bindings.remove(&name) {
                self.proposal_retired
                    .insert(name.clone(), (binding, seeded.clone()));
            }
            if values.get(&name) == Some(&seeded) {
                values.remove(&name);
            }
        }
        let restored: Vec<String> = self
            .proposal_retired
            .keys()
            .filter(|name| fields.contains(*name))
            .cloned()
            .collect();
        for name in restored {
            if let Some((binding, seeded)) = self.proposal_retired.remove(&name) {
                self.proposal_bindings.insert(name.clone(), binding);
                self.proposal_seeded.insert(name.clone(), seeded.clone());
                values.entry(name).or_insert(seeded);
            }
        }
        self.replace_trial_input(values, self.selected.clone());
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn proposal_draft_waits_for_exact_preview_and_undo_preserves_manual_input() {
        let original = b"name: Plain".to_vec();
        let offered = b"name: {{Name}}".to_vec();
        let manual = b"name: {{Name}} extra".to_vec();
        let analysis = |fields: Vec<&str>| json!({"fields":fields.into_iter().map(|name| json!({"name":name})).collect::<Vec<_>>()});
        let mut session = AuthoringSession::new(
            "one".into(),
            "txt".into(),
            original.clone(),
            analysis(vec![]),
        );
        let binding = json!({"source":"Name","type":"text","fmt":""});
        session.proposal_pending = Some((
            digest(&offered),
            Map::from_iter([("Name".into(), binding.clone())]),
            Map::from_iter([("Name".into(), json!("Plain"))]),
        ));
        session.replace_content(manual, analysis(vec!["Name"]));
        assert!(session.proposal_bindings.is_empty());
        assert!(session.values.is_empty());
        assert!(session.proposal_pending.is_some());
        session.replace_content(offered.clone(), analysis(vec!["Name"]));
        assert_eq!(session.proposal_bindings["Name"], binding);
        assert_eq!(session.values["Name"], "Plain");
        assert!(session.proposal_pending.is_none());
        session.replace_trial_input(
            Map::from_iter([("Name".into(), json!("Hand edit"))]),
            Map::new(),
        );
        session.replace_content(original, analysis(vec![]));
        assert!(session.proposal_bindings.is_empty());
        assert_eq!(session.values["Name"], "Hand edit");
        session.replace_content(offered, analysis(vec!["Name"]));
        assert_eq!(session.proposal_bindings["Name"], binding);
        assert_eq!(session.values["Name"], "Hand edit");
    }
}
