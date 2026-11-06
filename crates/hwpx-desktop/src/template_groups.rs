//! Retained library grouping and workspace settings; not exposed by the web UI.

use crate::settings_store::{mutate, read_with_alert};
use crate::template_link::library_key_for;
use hwpx_filler::structure_scan::python_trim;
use hwpx_filler::text_render::python_repr;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}
fn check_media(media: &str) -> io::Result<()> {
    if !matches!(media, "hwpx" | "txt") {
        return Err(invalid(format!(
            "유효하지 않은 템플릿 형식: {} (허용: ('hwpx', 'txt'))",
            python_repr(&json!(media))
        )));
    }
    Ok(())
}
fn strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}
fn assignments(value: Option<&Value>) -> BTreeMap<String, String> {
    value
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .filter_map(|(key, value)| {
            value
                .as_str()
                .filter(|group| !group.is_empty())
                .map(|group| (key.clone(), group.into()))
        })
        .collect()
}
fn normalized_groups(value: &Value) -> io::Result<BTreeSet<String>> {
    let items = value
        .as_array()
        .filter(|items| items.iter().all(Value::is_string))
        .ok_or_else(|| invalid("접힌 그룹 목록은 문자열 리스트여야 합니다"))?;
    Ok(items
        .iter()
        .map(|item| item.as_str().unwrap().to_owned())
        .collect())
}
fn checked_assignments(value: &Value) -> io::Result<BTreeMap<String, String>> {
    if !value
        .as_object()
        .is_some_and(|items| items.values().all(Value::is_string))
    {
        return Err(invalid("템플릿 그룹 지정은 {문자열: 문자열} 이어야 합니다"));
    }
    Ok(assignments(Some(value)))
}
fn media_value<'a>(data: &'a Map<String, Value>, key: &str, media: &str) -> Option<&'a Value> {
    data.get(key)?.as_object()?.get(media)
}
fn put_media(data: &mut Map<String, Value>, key: &str, media: &str, value: Value) {
    let mut bucket = data
        .get(key)
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    bucket.insert(media.into(), value);
    data.insert(key.into(), Value::Object(bucket));
}

pub struct GroupSettings {
    path: PathBuf,
    alert: Arc<dyn Fn(&str) + Send + Sync>,
}
impl GroupSettings {
    pub fn new(path: PathBuf, alert: impl Fn(&str) + Send + Sync + 'static) -> Self {
        Self {
            path,
            alert: Arc::new(alert),
        }
    }
    fn read(&self) -> io::Result<Map<String, Value>> {
        read_with_alert(&self.path, |message| (self.alert)(message))
    }
    pub fn load_job_collapsed(&self) -> io::Result<Vec<String>> {
        Ok(strings(self.read()?.get("job_collapsed_groups")))
    }
    pub fn save_job_collapsed(&self, value: &Value) -> io::Result<()> {
        let groups = normalized_groups(value)?;
        mutate(&self.path, |data| {
            data.insert("job_collapsed_groups".into(), json!(groups));
        })
    }
    pub fn recollapse_job(&self, old: &str, new: &str) -> io::Result<()> {
        let mut groups = self
            .load_job_collapsed()?
            .into_iter()
            .collect::<BTreeSet<_>>();
        if !groups.remove(old) {
            return Ok(());
        }
        if !new.is_empty() {
            groups.insert(new.into());
        }
        self.save_job_collapsed(&json!(groups))
    }
    pub fn reconcile_templates(&self, media: &str, live_keys: &HashSet<String>) -> io::Result<()> {
        let assignments = self.load_template_groups(media)?;
        if assignments.keys().all(|key| live_keys.contains(key)) {
            return Ok(());
        }
        self.update_template_state(media, |current, _| {
            current.retain(|key, _| live_keys.contains(key));
        })?;
        Ok(())
    }
    pub fn load_template_groups(&self, media: &str) -> io::Result<BTreeMap<String, String>> {
        check_media(media)?;
        Ok(assignments(media_value(
            &self.read()?,
            "template_groups",
            media,
        )))
    }
    pub fn load_template_collapsed(&self, media: &str) -> io::Result<Vec<String>> {
        check_media(media)?;
        Ok(strings(media_value(
            &self.read()?,
            "template_collapsed_groups",
            media,
        )))
    }
    pub fn save_template_groups(&self, media: &str, value: &Value) -> io::Result<()> {
        check_media(media)?;
        let groups = checked_assignments(value)?;
        mutate(&self.path, |data| {
            put_media(data, "template_groups", media, json!(groups))
        })
    }
    pub fn save_template_collapsed(&self, media: &str, value: &Value) -> io::Result<()> {
        check_media(media)?;
        let groups = normalized_groups(value)?;
        mutate(&self.path, |data| {
            put_media(data, "template_collapsed_groups", media, json!(groups))
        })
    }
    /// One replacement commits assignments and collapse state while preserving other media.
    pub(crate) fn update_template_state(
        &self,
        media: &str,
        update: impl Fn(&mut BTreeMap<String, String>, &mut BTreeSet<String>),
    ) -> io::Result<()> {
        check_media(media)?;
        mutate(&self.path, |data| {
            let mut groups = assignments(media_value(data, "template_groups", media));
            let mut collapsed = strings(media_value(data, "template_collapsed_groups", media))
                .into_iter()
                .collect();
            update(&mut groups, &mut collapsed);
            put_media(data, "template_groups", media, json!(groups));
            put_media(data, "template_collapsed_groups", media, json!(collapsed));
        })
    }
}

pub struct TemplateGroupModel {
    settings: Arc<GroupSettings>,
    media: String,
    assign: BTreeMap<String, String>,
    collapsed: BTreeSet<String>,
}
impl TemplateGroupModel {
    pub fn new(settings: Arc<GroupSettings>, media: &str) -> io::Result<Self> {
        check_media(media)?;
        let data = settings.read()?;
        let assign = assignments(media_value(&data, "template_groups", media));
        let collapsed = strings(media_value(&data, "template_collapsed_groups", media))
            .into_iter()
            .collect();
        Ok(Self {
            settings,
            media: media.into(),
            assign,
            collapsed,
        })
    }
    pub fn group_of(&self, key: &str) -> &str {
        self.assign.get(key).map_or("", String::as_str)
    }
    pub fn set_group(&mut self, key: &str, group: &str) -> io::Result<()> {
        let mut assign = self.assign.clone();
        let group = python_trim(group);
        if group.is_empty() {
            assign.remove(key);
        } else {
            assign.insert(key.into(), group.into());
        }
        self.persist(assign, self.collapsed.clone())
    }
    pub fn existing_groups(&self, live: Option<&HashSet<String>>) -> Vec<String> {
        self.assign
            .iter()
            .filter(|(key, _)| live.is_none_or(|keys| keys.contains(*key)))
            .map(|(_, group)| group.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect()
    }
    pub fn rename_group(&mut self, old: &str, new: &str) -> io::Result<usize> {
        let old = python_trim(old);
        let new = python_trim(new);
        if old.is_empty() {
            return Err(invalid("대상 그룹 이름이 비어 있습니다"));
        }
        if new.is_empty() {
            return Err(invalid("그룹 이름이 비어 있습니다"));
        }
        let count = self.assign.values().filter(|group| *group == old).count();
        if old == new {
            return Ok(count);
        }
        let preexisting = self.assign.values().any(|group| group == new);
        let assign = self
            .assign
            .iter()
            .map(|(key, group)| {
                (
                    key.clone(),
                    if group == old {
                        new.into()
                    } else {
                        group.clone()
                    },
                )
            })
            .collect();
        let mut collapsed = self.collapsed.clone();
        if collapsed.remove(old) && !preexisting {
            collapsed.insert(new.into());
        }
        self.persist(assign, collapsed)?;
        Ok(count)
    }
    pub fn disband_group(&mut self, old: &str) -> io::Result<usize> {
        let old = python_trim(old);
        if old.is_empty() {
            return Err(invalid("대상 그룹 이름이 비어 있습니다"));
        }
        let assign: BTreeMap<_, _> = self
            .assign
            .iter()
            .filter(|(_, group)| *group != old)
            .map(|(key, group)| (key.clone(), group.clone()))
            .collect();
        let count = self.assign.len() - assign.len();
        let mut collapsed = self.collapsed.clone();
        collapsed.remove(old);
        self.persist(assign, collapsed)?;
        Ok(count)
    }
    pub fn reconcile(&mut self, live: &HashSet<String>) -> io::Result<()> {
        let assign: BTreeMap<_, _> = self
            .assign
            .iter()
            .filter(|(key, _)| live.contains(*key))
            .map(|(key, group)| (key.clone(), group.clone()))
            .collect();
        if assign.len() != self.assign.len() {
            self.persist(assign, self.collapsed.clone())?;
        }
        Ok(())
    }
    pub fn is_collapsed(&self, group: &str) -> bool {
        self.collapsed.contains(group)
    }
    pub fn toggle_collapse(&mut self, group: &str) -> io::Result<()> {
        let mut collapsed = self.collapsed.clone();
        if !collapsed.remove(group) {
            collapsed.insert(group.into());
        }
        self.persist(self.assign.clone(), collapsed)
    }
    pub fn build_sections(
        &self,
        items: &[Value],
        key_of: impl Fn(&Value) -> &str,
        grouped_view: bool,
    ) -> (Vec<Value>, bool) {
        let mut groups = BTreeMap::<String, Vec<Value>>::new();
        for item in items {
            let group = if grouped_view {
                self.group_of(key_of(item))
            } else {
                ""
            };
            groups.entry(group.into()).or_default().push(item.clone());
        }
        let ungrouped = groups.remove("");
        let flat = groups.is_empty();
        let mut ordered = groups.into_iter().collect::<Vec<_>>();
        if let Some(items) = ungrouped {
            ordered.push((String::new(), items));
        }
        (ordered.into_iter().map(|(group, items)| json!({"collapsed":!flat && self.is_collapsed(&group),"group":group,"count":items.len(),"items":items})).collect(), flat)
    }
    fn persist(
        &mut self,
        assign: BTreeMap<String, String>,
        collapsed: BTreeSet<String>,
    ) -> io::Result<()> {
        self.settings
            .update_template_state(&self.media, |groups, folds| {
                *groups = assign.clone();
                *folds = collapsed.clone();
            })?;
        self.assign = assign;
        self.collapsed = collapsed;
        Ok(())
    }
}

/// Group labels may use a basename fallback; durable Job links must never use it.
pub fn group_key(path: &Path, root: Option<&Path>) -> String {
    let key = root.map_or_else(String::new, |root| library_key_for(path, root));
    if key.is_empty() {
        path.file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned()
    } else {
        key
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::shell_settings::ShellSettings;
    use std::fs;

    fn fixture() -> (PathBuf, Arc<GroupSettings>) {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("library-groups-{}", uuid::Uuid::new_v4().simple()));
        fs::create_dir_all(&root).unwrap();
        let settings = Arc::new(GroupSettings::new(root.join("settings.json"), |_| {
            panic!("valid settings must not alarm")
        }));
        (root, settings)
    }

    #[test]
    fn group_settings_preserve_other_media_workspace_and_valid_parts_of_corrupt_values() {
        let (root, settings) = fixture();
        let shell = ShellSettings::new(settings.path.clone(), |_| panic!("unexpected alarm"));
        assert!(settings.load_job_collapsed().unwrap().is_empty());
        assert!(settings.load_template_groups("hwpx").unwrap().is_empty());
        assert!(settings.load_template_collapsed("txt").unwrap().is_empty());
        shell.save_theme("dark").unwrap();
        settings
            .save_job_collapsed(&json!(["나", "가", "가", ""]))
            .unwrap();
        assert_eq!(settings.load_job_collapsed().unwrap(), ["", "가", "나"]);
        settings.recollapse_job("없는 그룹", "다").unwrap();
        settings.recollapse_job("가", "다").unwrap();
        settings.recollapse_job("나", "").unwrap();
        assert_eq!(settings.load_job_collapsed().unwrap(), ["", "다"]);
        settings
            .save_template_groups("hwpx", &json!({"공고.hwpx":"입찰","빈.hwpx":""}))
            .unwrap();
        settings
            .save_template_groups("txt", &json!({"협조전.txt":"입찰"}))
            .unwrap();
        settings
            .save_template_collapsed("hwpx", &json!(["입찰"]))
            .unwrap();
        settings
            .save_template_collapsed("txt", &json!(["나", "가", "가", ""]))
            .unwrap();
        assert_eq!(
            settings.load_template_groups("hwpx").unwrap(),
            BTreeMap::from([("공고.hwpx".into(), "입찰".into())])
        );
        assert_eq!(
            settings.load_template_groups("txt").unwrap(),
            BTreeMap::from([("협조전.txt".into(), "입찰".into())])
        );
        assert_eq!(settings.load_template_collapsed("hwpx").unwrap(), ["입찰"]);
        assert_eq!(
            settings.load_template_collapsed("txt").unwrap(),
            ["", "가", "나"]
        );
        assert_eq!(shell.load_theme().unwrap(), "dark");
        shell.save_theme("light").unwrap();
        assert_eq!(settings.load_job_collapsed().unwrap(), ["", "다"]);
        let before = fs::read(&settings.path).unwrap();
        for media in ["pdf", ""] {
            assert!(settings.load_template_groups(media).is_err());
            assert!(settings.load_template_collapsed(media).is_err());
            assert!(settings.save_template_groups(media, &json!({})).is_err());
            assert!(settings.save_template_collapsed(media, &json!([])).is_err());
        }
        for value in [json!("입찰"), json!(["입찰", 3]), Value::Null] {
            assert!(settings.save_job_collapsed(&value).is_err());
            assert!(settings.save_template_collapsed("hwpx", &value).is_err());
        }
        for value in [json!(["a.hwpx"]), json!({"a.hwpx":3}), Value::Null] {
            assert!(settings.save_template_groups("hwpx", &value).is_err());
        }
        assert_eq!(
            fs::read(&settings.path).unwrap(),
            before,
            "invalid settings must not write"
        );
        let practice = GroupSettings::new(root.join("practice/settings.json"), |_| {
            panic!("unexpected alarm")
        });
        practice.save_job_collapsed(&json!(["연습"])).unwrap();
        practice
            .save_template_groups("hwpx", &json!({"공고.hwpx":"연습"}))
            .unwrap();
        assert_eq!(fs::read(&settings.path).unwrap(), before);
        assert_eq!(practice.load_job_collapsed().unwrap(), ["연습"]);
        assert_eq!(
            practice.load_template_groups("hwpx").unwrap()["공고.hwpx"],
            "연습"
        );
        for (value, jobs) in [
            (json!("손상"), vec![]),
            (json!(["입찰", 3, null]), vec!["입찰"]),
        ] {
            fs::write(&settings.path, serde_json::to_vec(&json!({"job_collapsed_groups":value,"template_groups":value,"template_collapsed_groups":value})).unwrap()).unwrap();
            assert_eq!(settings.load_job_collapsed().unwrap(), jobs);
            assert!(settings.load_template_groups("hwpx").unwrap().is_empty());
            assert!(settings.load_template_collapsed("hwpx").unwrap().is_empty());
        }
        fs::write(&settings.path, serde_json::to_vec(&json!({"template_groups":{"hwpx":{"a.hwpx":"입찰","b.hwpx":3,"c.hwpx":""},"txt":{"a.txt":"그룹"}},"template_collapsed_groups":{"hwpx":"깨진 값","txt":["그룹",3,null]}})).unwrap()).unwrap();
        assert_eq!(
            settings.load_template_groups("hwpx").unwrap(),
            BTreeMap::from([("a.hwpx".into(), "입찰".into())])
        );
        assert_eq!(
            settings.load_template_groups("txt").unwrap()["a.txt"],
            "그룹"
        );
        assert!(settings.load_template_collapsed("hwpx").unwrap().is_empty());
        assert_eq!(settings.load_template_collapsed("txt").unwrap(), ["그룹"]);
        mutate(&settings.path, |data| {
            put_media(data, "template_groups", "hwpx", json!(["깨진 값"]))
        })
        .unwrap();
        assert!(settings.load_template_groups("hwpx").unwrap().is_empty());
        assert_eq!(
            settings.load_template_groups("txt").unwrap()["a.txt"],
            "그룹"
        );
        settings
            .update_template_state("hwpx", |assign, _| {
                assign.clear();
            })
            .unwrap();
        assert_eq!(
            settings.load_template_groups("txt").unwrap()["a.txt"],
            "그룹"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn group_model_commits_before_publication_and_preserves_merge_and_flat_view_contracts() {
        let (root, settings) = fixture();
        assert!(TemplateGroupModel::new(settings.clone(), "pdf").is_err());
        let mut model = TemplateGroupModel::new(settings.clone(), "hwpx").unwrap();
        let rows = [
            json!({"key":"a.hwpx","name":"a"}),
            json!({"key":"b.hwpx","name":"b"}),
            json!({"key":"c.hwpx","name":"c"}),
        ];
        fn key(row: &Value) -> &str {
            row["key"].as_str().unwrap()
        }
        let (sections, flat) = model.build_sections(&rows, key, true);
        assert!(flat);
        assert_eq!(
            sections,
            [json!({"group":"","collapsed":false,"count":3,"items":rows})]
        );
        model.toggle_collapse("").unwrap();
        assert!(
            !model.build_sections(&rows, key, true).0[0]["collapsed"]
                .as_bool()
                .unwrap()
        );
        model.set_group("a.hwpx", " 입찰 ").unwrap();
        model.set_group("b.hwpx", "입찰").unwrap();
        assert_eq!(model.existing_groups(None), ["입찰"]);
        assert_eq!(
            TemplateGroupModel::new(settings.clone(), "hwpx")
                .unwrap()
                .group_of("a.hwpx"),
            "입찰"
        );
        model.toggle_collapse("입찰").unwrap();
        assert_eq!(model.rename_group("입찰", "2026 입찰").unwrap(), 2);
        let restored = TemplateGroupModel::new(settings.clone(), "hwpx").unwrap();
        assert_eq!(restored.group_of("a.hwpx"), "2026 입찰");
        assert_eq!(restored.group_of("b.hwpx"), "2026 입찰");
        assert!(restored.is_collapsed("2026 입찰"));
        assert!(!restored.is_collapsed("입찰"));
        let before = fs::read(&settings.path).unwrap();
        assert_eq!(model.rename_group("2026 입찰", "2026 입찰").unwrap(), 2);
        assert!(model.rename_group("2026 입찰", " ").is_err());
        assert!(model.rename_group("", "새이름").is_err());
        assert!(model.disband_group("").is_err());
        assert_eq!(fs::read(&settings.path).unwrap(), before);
        model.set_group("c.hwpx", "입찰").unwrap();
        assert_eq!(model.rename_group("2026 입찰", "입찰").unwrap(), 2);
        assert!(!model.is_collapsed("입찰") && !model.is_collapsed("2026 입찰"));
        model.toggle_collapse("입찰").unwrap();
        model.set_group("b.hwpx", "수의").unwrap();
        model.toggle_collapse("수의").unwrap();
        assert_eq!(model.rename_group("수의", "입찰").unwrap(), 1);
        assert!(model.is_collapsed("입찰") && !model.is_collapsed("수의"));
        assert_eq!(model.disband_group("입찰").unwrap(), 3);
        assert!(model.existing_groups(None).is_empty() && !model.is_collapsed("입찰"));
        model.set_group("b.hwpx", "나그룹").unwrap();
        model.set_group("a.hwpx", "가그룹").unwrap();
        model.toggle_collapse("가그룹").unwrap();
        let (sections, flat) = model.build_sections(&rows, key, true);
        assert!(!flat);
        assert_eq!(
            sections
                .iter()
                .map(|section| section["group"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["가그룹", "나그룹", ""]
        );
        assert_eq!(sections[0]["collapsed"], true);
        assert_eq!(sections[2]["count"], 1);
        assert_eq!(sections[2]["items"][0], rows[2]);
        let hidden = model.build_sections(&rows, key, false);
        assert!(hidden.1);
        assert_eq!(hidden.0[0]["items"], json!(rows));
        assert_eq!(hidden.0[0]["collapsed"], false);
        model.set_group("gone.hwpx", "고아").unwrap();
        let live = HashSet::from(["a.hwpx".into(), "b.hwpx".into()]);
        assert_eq!(model.existing_groups(Some(&live)), ["가그룹", "나그룹"]);
        assert!(
            model
                .build_sections(&[json!({"key":"현재.hwpx"})], key, true)
                .1
        );
        model.reconcile(&live).unwrap();
        model.reconcile(&live).unwrap();
        assert_eq!(
            TemplateGroupModel::new(settings.clone(), "hwpx")
                .unwrap()
                .group_of("gone.hwpx"),
            ""
        );
        let before = fs::read(&settings.path).unwrap();
        fs::write(&settings.path, [0xff]).unwrap();
        assert!(model.set_group("a.hwpx", "실패").is_err());
        assert!(model.rename_group("가그룹", "실패").is_err());
        assert_eq!(model.group_of("a.hwpx"), "가그룹");
        assert!(model.is_collapsed("가그룹") && !model.is_collapsed("실패"));
        assert_eq!(fs::read(&settings.path).unwrap(), [0xff]);
        fs::write(&settings.path, before).unwrap();
        model.set_group("b.hwpx", "계약").unwrap();
        let restored = TemplateGroupModel::new(settings.clone(), "hwpx").unwrap();
        assert_eq!(restored.group_of("a.hwpx"), "가그룹");
        assert_eq!(restored.group_of("b.hwpx"), "계약");
        model.set_group("a.hwpx", "").unwrap();
        assert_eq!(model.group_of("a.hwpx"), "");
        let mut txt = TemplateGroupModel::new(settings.clone(), "txt").unwrap();
        txt.toggle_collapse("입찰").unwrap();
        assert!(
            TemplateGroupModel::new(settings.clone(), "txt")
                .unwrap()
                .is_collapsed("입찰")
        );
        txt.toggle_collapse("입찰").unwrap();
        assert!(
            !TemplateGroupModel::new(settings.clone(), "txt")
                .unwrap()
                .is_collapsed("입찰")
        );
        let templates = root.join("templates");
        let inside = templates.join("조달/공고서.hwpx");
        let outside = root.join("바탕화면/공고서.hwpx");
        assert_eq!(group_key(&inside, Some(&templates)), "조달/공고서.hwpx");
        assert_eq!(
            group_key(&inside, Some(&templates)),
            library_key_for(&inside, &templates)
        );
        assert!(library_key_for(&outside, &templates).is_empty());
        assert_eq!(group_key(&outside, Some(&templates)), "공고서.hwpx");
        assert_eq!(group_key(&outside, None), "공고서.hwpx");
        fs::remove_dir_all(root).unwrap();
    }
}
