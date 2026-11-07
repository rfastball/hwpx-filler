//! Compare the declared set of sealed web artifact copies for a release.

use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq, Eq)]
struct Identity {
    artifact_id: String,
    tree_sha256: String,
}

#[derive(Debug, Serialize)]
pub struct Evidence {
    copies: Vec<String>,
    artifact_id: String,
    tree_sha256: String,
    same_artifact: bool,
}

#[derive(Debug, Serialize)]
pub struct SelfcheckEvidence {
    selfcheck_artifact_id: String,
    selfcheck_tree_sha256: String,
    selfcheck_matches_bundled: bool,
}

fn load(path: &Path, role: &str) -> Result<Value, String> {
    let bytes = fs::read(path).map_err(|error| {
        format!(
            "{role} 증거를 읽을 수 없습니다: {} ({error})",
            path.display()
        )
    })?;
    let bytes = bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes);
    let value: Value = serde_json::from_slice(bytes).map_err(|error| {
        format!(
            "{role} 증거를 읽을 수 없습니다: {} ({error})",
            path.display()
        )
    })?;
    if !value.is_object() {
        return Err(format!(
            "{role} 증거가 JSON object 가 아닙니다: {}",
            path.display()
        ));
    }
    Ok(value)
}

fn digest(value: &Value, field: &str, role: &str) -> Result<String, String> {
    let Some(raw) = value.get(field).and_then(Value::as_str) else {
        return Err(format!("{role} 증거에 identity 필드가 없습니다: {field}"));
    };
    if raw.len() != 64
        || !raw
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(format!(
            "{role} 증거의 identity 형태가 sha256 이 아닙니다: {field}={raw:?}"
        ));
    }
    Ok(raw.to_owned())
}

fn identity(value: &Value, role: &str) -> Result<Identity, String> {
    Ok(Identity {
        artifact_id: digest(value, "artifact_id", role)?,
        tree_sha256: digest(value, "tree_sha256", role)?,
    })
}

pub fn judge_selfcheck(selfcheck: &Path, expected: &Path) -> Result<SelfcheckEvidence, String> {
    if !selfcheck.is_file() {
        return Err(format!(
            "selfcheck 증거가 없습니다: {}",
            selfcheck.display()
        ));
    }
    if !expected.is_file() {
        return Err(format!("bundled 증거가 없습니다: {}", expected.display()));
    }
    let actual = identity(&load(selfcheck, "selfcheck")?, "selfcheck")?;
    let bundled = identity(&load(expected, "bundled")?, "bundled")?;
    let mut drift = Vec::new();
    if actual.artifact_id != bundled.artifact_id {
        drift.push(format!(
            "artifact_id: selfcheck={:?} bundled={:?}",
            actual.artifact_id, bundled.artifact_id
        ));
    }
    if actual.tree_sha256 != bundled.tree_sha256 {
        drift.push(format!(
            "tree_sha256: selfcheck={:?} bundled={:?}",
            actual.tree_sha256, bundled.tree_sha256
        ));
    }
    if !drift.is_empty() {
        return Err(format!(
            "selfcheck 가 해석한 web artifact 가 번들 사본과 다릅니다 — {}",
            drift.join(" · ")
        ));
    }
    Ok(SelfcheckEvidence {
        selfcheck_artifact_id: actual.artifact_id,
        selfcheck_tree_sha256: actual.tree_sha256,
        selfcheck_matches_bundled: true,
    })
}

pub fn reconcile(
    copies: &[(String, PathBuf)],
    build_metadata: Option<&Path>,
    expected: &[String],
) -> Result<Evidence, String> {
    let collected = collect_identities(copies, build_metadata)?;
    let actual = validate_names(&collected, expected)?;
    let reference = collected
        .values()
        .next()
        .ok_or_else(|| "대조할 사본이 없습니다".to_owned())?;
    for field in ["artifact_id", "tree_sha256"] {
        if !all_match(&collected, reference, field) {
            return Err(format!("출하 사본들의 {field} 가 다릅니다"));
        }
    }
    Ok(Evidence {
        copies: actual,
        artifact_id: reference.artifact_id.clone(),
        tree_sha256: reference.tree_sha256.clone(),
        same_artifact: true,
    })
}

fn collect_identities(
    copies: &[(String, PathBuf)],
    build_metadata: Option<&Path>,
) -> Result<BTreeMap<String, Identity>, String> {
    let mut collected = BTreeMap::new();
    if let Some(path) = build_metadata {
        let metadata = load(path, "build metadata")?;
        let web = metadata.get("web").filter(|value| {
            value.is_object() && value.get("present").is_some_and(|present| present == true)
        });
        let Some(web) = web else {
            return Err(format!(
                "build metadata 에 sealed web artifact identity 가 없습니다 ({})",
                path.display()
            ));
        };
        collected.insert("source".to_owned(), identity(web, "source")?);
    }
    for (name, path) in copies {
        if collected.contains_key(name) {
            return Err(format!("사본 이름이 중복됐습니다: {name}"));
        }
        collected.insert(name.clone(), identity(&load(path, name)?, name)?);
    }
    Ok(collected)
}

fn validate_names(
    collected: &BTreeMap<String, Identity>,
    expected: &[String],
) -> Result<Vec<String>, String> {
    let actual = collected.keys().cloned().collect::<Vec<_>>();
    let mut declared = expected.to_vec();
    declared.sort();
    if actual != declared {
        return Err(format!(
            "대조할 사본 집합이 선언과 다릅니다 — 선언={declared:?} 실제={actual:?}"
        ));
    }
    Ok(actual)
}

fn all_match(collected: &BTreeMap<String, Identity>, reference: &Identity, field: &str) -> bool {
    let reference_value = if field == "artifact_id" {
        &reference.artifact_id
    } else {
        &reference.tree_sha256
    };
    collected.values().all(|value| {
        let observed = if field == "artifact_id" {
            &value.artifact_id
        } else {
            &value.tree_sha256
        };
        observed == reference_value
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{judge_selfcheck, reconcile};
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn every_declared_copy_must_match_a_valid_digest() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("hwpx-reconcile-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let meta = root.join("metadata.json");
        let dist = root.join("dist.json");
        let portable = root.join("portable.json");
        let a = "a".repeat(64);
        let b = "b".repeat(64);
        fs::write(
            &meta,
            format!(r#"{{"web":{{"present":true,"artifact_id":"{a}","tree_sha256":"{b}"}}}}"#),
        )
        .unwrap();
        fs::write(
            &dist,
            format!(r#"{{"artifact_id":"{a}","tree_sha256":"{b}"}}"#),
        )
        .unwrap();
        fs::write(
            &portable,
            format!(r#"{{"artifact_id":"{a}","tree_sha256":"{b}"}}"#),
        )
        .unwrap();
        let copies = [
            ("dist".into(), dist.clone()),
            ("portable".into(), portable.clone()),
        ];
        let expected = ["source".into(), "dist".into(), "portable".into()];
        let evidence = reconcile(&copies, Some(&meta), &expected).unwrap();
        assert_eq!(
            serde_json::to_value(evidence).unwrap()["copies"],
            serde_json::json!(["dist", "portable", "source"])
        );
        assert!(
            reconcile(&copies[..1], Some(&meta), &expected)
                .unwrap_err()
                .contains("선언과 다릅니다")
        );
        assert!(
            reconcile(
                &[
                    ("dist".into(), dist.clone()),
                    ("dist".into(), portable.clone())
                ],
                Some(&meta),
                &expected
            )
            .unwrap_err()
            .contains("중복됐습니다")
        );
        fs::write(
            &portable,
            format!(
                r#"{{"artifact_id":"{}","tree_sha256":"{b}"}}"#,
                "c".repeat(64)
            ),
        )
        .unwrap();
        assert!(
            reconcile(&copies, Some(&meta), &expected)
                .unwrap_err()
                .contains("artifact_id 가 다릅니다")
        );
        fs::write(&portable, r#"{"artifact_id":"junk","tree_sha256":"bad"}"#).unwrap();
        assert!(
            reconcile(&copies, Some(&meta), &expected)
                .unwrap_err()
                .contains("sha256 이 아닙니다")
        );
        fs::write(&meta, r#"{"web":{"present":false}}"#).unwrap();
        assert!(
            reconcile(&copies, Some(&meta), &expected)
                .unwrap_err()
                .contains("identity 가 없습니다")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn selfcheck_file_must_exist_and_match_the_bundled_digest() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("hwpx-selfcheck-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let selfcheck = root.join("selfcheck.json");
        let bundled = root.join("bundle.json");
        let a = "a".repeat(64);
        let b = "b".repeat(64);
        assert!(
            judge_selfcheck(&selfcheck, &bundled)
                .unwrap_err()
                .contains("증거가 없습니다")
        );
        fs::write(&selfcheck, "").unwrap();
        fs::write(
            &bundled,
            format!(r#"{{"artifact_id":"{a}","tree_sha256":"{b}"}}"#),
        )
        .unwrap();
        assert!(
            judge_selfcheck(&selfcheck, &bundled)
                .unwrap_err()
                .contains("읽을 수 없습니다")
        );
        fs::write(
            &selfcheck,
            format!(r#"{{"artifact_id":"{a}","tree_sha256":"{b}"}}"#),
        )
        .unwrap();
        let evidence = judge_selfcheck(&selfcheck, &bundled).unwrap();
        assert_eq!(
            serde_json::to_value(evidence).unwrap()["selfcheck_matches_bundled"],
            true
        );
        fs::write(
            &selfcheck,
            format!(
                r#"{{"artifact_id":"{}","tree_sha256":"{b}"}}"#,
                "c".repeat(64)
            ),
        )
        .unwrap();
        assert!(
            judge_selfcheck(&selfcheck, &bundled)
                .unwrap_err()
                .contains("artifact_id: selfcheck=")
        );
        fs::remove_dir_all(root).unwrap();
    }
}
