//! Installation-scoped HMAC token for one observed slot configuration.

use crate::atomic_file::write_bytes_atomic_exclusive;
use base64::Engine;
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use hwpx_filler::execution_structure::content_digest;
use hwpx_filler::text_render::python_repr;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs;
use std::io;
use std::path::Path;

const SCHEME: &str = "hfslot1";
const SCHEMA: &str = "slot-configuration-token/v1";
const PURPOSE: &str = "SLOT_CONFIGURATION";
const SECRET_SCHEMA: &str = "slot-token-secret/v1";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenError {
    pub code: &'static str,
    pub detail: String,
}
impl From<String> for TokenError {
    fn from(detail: String) -> Self {
        Self {
            code: "INVALID_CONFIGURATION_TOKEN",
            detail,
        }
    }
}
impl From<&str> for TokenError {
    fn from(detail: &str) -> Self {
        Self::from(detail.to_owned())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Claims {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub template_application_id: String,
    pub selection_semantic_contract_id: String,
    pub configuration_presence: bool,
    pub configuration_version: Option<u32>,
    pub actor_binding_digest: String,
    pub issued_at: String,
}

fn text(out: &mut Vec<u8>, value: &str) -> Result<(), String> {
    let len = u32::try_from(value.len()).map_err(|_| "token text 가 u32 범위 초과")?;
    out.extend_from_slice(&len.to_be_bytes());
    out.extend_from_slice(value.as_bytes());
    Ok(())
}

pub fn actor_binding_digest(subject: &str, workspace: &str) -> Result<String, String> {
    let mut material = Vec::new();
    text(&mut material, "slot-actor-binding/v1")?;
    text(&mut material, subject)?;
    text(&mut material, workspace)?;
    let digest = Sha256::digest(&material);
    Ok(format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    ))
}

fn canonical(claims: &Claims) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    for value in [
        SCHEMA,
        PURPOSE,
        &claims.workspace_instance_id,
        &claims.work_authority_id,
        &claims.template_application_id,
        &claims.selection_semantic_contract_id,
    ] {
        text(&mut out, value)?;
    }
    out.push(u8::from(claims.configuration_presence));
    match claims.configuration_version {
        Some(value) => {
            out.push(1);
            out.extend_from_slice(&value.to_be_bytes());
        }
        None => out.push(0),
    }
    text(&mut out, &claims.actor_binding_digest)?;
    text(&mut out, &claims.issued_at)?;
    Ok(out)
}

fn hmac(secret: &[u8; 32], payload: &[u8]) -> [u8; 32] {
    let mut key = [0u8; 64];
    key[..32].copy_from_slice(secret);
    let mut inner = key.map(|byte| byte ^ 0x36);
    let mut outer = key.map(|byte| byte ^ 0x5c);
    let mut hash = Sha256::new();
    hash.update(inner);
    hash.update(payload);
    inner.fill(0);
    let inner_hash = hash.finalize();
    let mut hash = Sha256::new();
    hash.update(outer);
    hash.update(inner_hash);
    outer.fill(0);
    hash.finalize().into()
}

pub fn sign(claims: &Claims, secret: &[u8; 32]) -> Result<String, String> {
    let prefix = format!("{SCHEME}.{}", URL_SAFE_NO_PAD.encode(canonical(claims)?));
    let signature = hmac(secret, prefix.as_bytes());
    Ok(format!("{prefix}.{}", URL_SAFE_NO_PAD.encode(signature)))
}

struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], String> {
        let end = self.offset.checked_add(count).ok_or("token claims 절단")?;
        let result = self
            .bytes
            .get(self.offset..end)
            .ok_or("token claims 절단")?;
        self.offset = end;
        Ok(result)
    }
    fn text(&mut self) -> Result<String, String> {
        let count = u32::from_be_bytes(self.take(4)?.try_into().expect("four bytes"));
        let count = usize::try_from(count).map_err(|_| "token claims 절단")?;
        String::from_utf8(self.take(count)?.to_vec()).map_err(|_| "token claims 파싱 실패".into())
    }
}
pub fn open(token: &str, secret: &[u8; 32]) -> Result<Claims, TokenError> {
    let parts: Vec<_> = token.split('.').collect();
    if parts.len() != 3 || parts[0] != SCHEME {
        return Err("token 형식 불일치".into());
    }
    let payload = URL_SAFE_NO_PAD
        .decode(parts[1])
        .map_err(|_| "token base64 손상")?;
    let signature = URL_SAFE_NO_PAD
        .decode(parts[2])
        .map_err(|_| "token base64 손상")?;
    let expected = hmac(secret, format!("{}.{}", parts[0], parts[1]).as_bytes());
    if signature.len() != 32
        || signature
            .iter()
            .zip(expected)
            .fold(0u8, |diff, (left, right)| diff | (left ^ right))
            != 0
    {
        return Err("token 서명 불일치(tamper·secret)".into());
    }
    decode_claims(&payload)
}

fn decode_claims(payload: &[u8]) -> Result<Claims, TokenError> {
    let mut reader = Reader {
        bytes: payload,
        offset: 0,
    };
    let schema = reader.text()?;
    let purpose = reader.text()?;
    let workspace_instance_id = reader.text()?;
    let work_authority_id = reader.text()?;
    let template_application_id = reader.text()?;
    let selection_semantic_contract_id = reader.text()?;
    let configuration_presence = match reader.take(1)?[0] {
        0 => false,
        1 => true,
        _ => return Err("token bool tag 손상".into()),
    };
    let configuration_version = match reader.take(1)?[0] {
        0 => None,
        1 => Some(u32::from_be_bytes(
            reader.take(4)?.try_into().expect("four bytes"),
        )),
        _ => return Err("token opt tag 손상".into()),
    };
    let actor_binding_digest = reader.text()?;
    let issued_at = reader.text()?;
    if reader.offset != payload.len() {
        return Err("token claims 잉여 바이트".into());
    }
    if purpose != PURPOSE {
        return Err(TokenError {
            code: "TOKEN_PURPOSE_MISMATCH",
            detail: format!("token purpose {}", python_repr(&Value::String(purpose))),
        });
    }
    if schema != SCHEMA {
        return Err(format!("token schema {}", python_repr(&Value::String(schema))).into());
    }
    Ok(Claims {
        workspace_instance_id,
        work_authority_id,
        template_application_id,
        selection_semantic_contract_id,
        configuration_presence,
        configuration_version,
        actor_binding_digest,
        issued_at,
    })
}

pub fn load_or_create_secret(root: &Path) -> Result<[u8; 32], String> {
    let path = root.join("slot_token_secret.json");
    match fs::read(&path) {
        Ok(bytes) => {
            let envelope: Value =
                serde_json::from_slice(&bytes).map_err(|_| "secret 파일 손상(JSON·형식)")?;
            let content = envelope
                .get("content")
                .ok_or("secret 파일 손상(JSON·형식)")?;
            if envelope.get("digest").and_then(Value::as_str)
                != Some(content_digest(content).as_str())
            {
                return Err("secret digest 손상".into());
            }
            if content.get("schema_version").and_then(Value::as_str) != Some(SECRET_SCHEMA) {
                return Err("secret schema 미상".into());
            }
            let encoded = content
                .get("secret_b64")
                .and_then(Value::as_str)
                .ok_or("secret base64 손상")?;
            let secret = STANDARD.decode(encoded).map_err(|_| "secret base64 손상")?;
            return secret.try_into().map_err(|_| "secret 길이 손상".into());
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.to_string()),
    }
    let mut secret = [0u8; 32];
    secret[..16].copy_from_slice(uuid::Uuid::new_v4().as_bytes());
    secret[16..].copy_from_slice(uuid::Uuid::new_v4().as_bytes());
    let content = json!({"schema_version":SECRET_SCHEMA,"secret_b64":STANDARD.encode(secret)});
    let envelope = json!({"digest":content_digest(&content),"content":content});
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let bytes = serde_json::to_vec_pretty(&envelope).map_err(|e| e.to_string())?;
    match write_bytes_atomic_exclusive(&path, &bytes) {
        Ok(()) => Ok(secret),
        Err(_) if path.exists() => {
            secret.fill(0);
            load_or_create_secret(root)
        }
        Err(error) => Err(error.to_string()),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    fn claims() -> Claims {
        Claims {
            workspace_instance_id: "ws-1".into(),
            work_authority_id: "W-1".into(),
            template_application_id: "A18".into(),
            selection_semantic_contract_id: "slot-selection/v1".into(),
            configuration_presence: true,
            configuration_version: Some(7),
            actor_binding_digest: "sha256:actor".into(),
            issued_at: "2026-08-16T00:00:00".into(),
        }
    }

    #[test]
    fn signed_context_round_trips_and_rejects_tampering() {
        let claims = claims();
        let secret = [17u8; 32];
        let token = sign(&claims, &secret).unwrap();
        // Independent Python codec output, including its HMAC and canonical byte encoding.
        assert_eq!(
            token,
            "hfslot1.AAAAG3Nsb3QtY29uZmlndXJhdGlvbi10b2tlbi92MQAAABJTTE9UX0NPTkZJR1VSQVRJT04AAAAEd3MtMQAAAANXLTEAAAADQTE4AAAAEXNsb3Qtc2VsZWN0aW9uL3YxAQEAAAAHAAAADHNoYTI1NjphY3RvcgAAABMyMDI2LTA4LTE2VDAwOjAwOjAw.QxlciAPUOYP511hnEA1iUZST2Lgfo5PoIh7jQzYtwJY"
        );
        assert_eq!(open(&token, &secret).unwrap(), claims);
        assert!(open(&token, &[14u8; 32]).is_err());
        let tampered = token.replacen("hfslot1.", "hfslot1.A", 1);
        assert!(open(&tampered, &secret).is_err());
        let absent = Claims {
            configuration_presence: false,
            configuration_version: None,
            ..claims.clone()
        };
        assert_eq!(
            open(&sign(&absent, &secret).unwrap(), &secret).unwrap(),
            absent
        );
        let max = Claims {
            configuration_version: Some(u32::MAX),
            ..claims.clone()
        };
        assert_eq!(open(&sign(&max, &secret).unwrap(), &secret).unwrap(), max);
        for malformed in [
            "",
            "nope",
            "a.b",
            "hfslot1.@@@.@@@",
            "wrong.x.y",
            "hfslot1..AA",
            "hfslot1.AA.@@",
        ] {
            assert_eq!(
                open(malformed, &secret).unwrap_err().code,
                "INVALID_CONFIGURATION_TOKEN"
            );
        }
        let sign_bytes = |bytes: &[u8]| {
            let prefix = format!("{SCHEME}.{}", URL_SAFE_NO_PAD.encode(bytes));
            format!(
                "{prefix}.{}",
                URL_SAFE_NO_PAD.encode(hmac(&secret, prefix.as_bytes()))
            )
        };
        let bytes = canonical(&claims).unwrap();
        for length in 0..bytes.len() {
            assert_eq!(
                open(&sign_bytes(&bytes[..length]), &secret)
                    .unwrap_err()
                    .code,
                "INVALID_CONFIGURATION_TOKEN",
                "truncated at {length}"
            );
        }
        let tags = [SCHEMA, PURPOSE, "ws-1", "W-1", "A18", "slot-selection/v1"]
            .iter()
            .map(|text| 4 + text.len())
            .sum::<usize>();
        for (offset, replacement, code) in [
            (4 + SCHEMA.len() - 1, b'2', "INVALID_CONFIGURATION_TOKEN"),
            (4 + SCHEMA.len() + 4, b'X', "TOKEN_PURPOSE_MISMATCH"),
            (4, 0xff, "INVALID_CONFIGURATION_TOKEN"),
            (tags, 2, "INVALID_CONFIGURATION_TOKEN"),
            (tags + 1, 2, "INVALID_CONFIGURATION_TOKEN"),
        ] {
            let mut invalid = bytes.clone();
            invalid[offset] = replacement;
            assert_eq!(open(&sign_bytes(&invalid), &secret).unwrap_err().code, code);
        }
        let mut trailing = bytes.clone();
        trailing.push(0x99);
        assert!(
            open(&sign_bytes(&trailing), &secret)
                .unwrap_err()
                .detail
                .contains("잉여")
        );
        assert_eq!(
            actor_binding_digest("local-user", "ws-1").unwrap(),
            "sha256:1da349ee9a2dcea73f44eedfa340fe0f665ff44b9527904991780b44c2ac1d3f"
        );
        assert_ne!(
            actor_binding_digest("local-user", "ws-1"),
            actor_binding_digest("local-user", "ws-2")
        );
        assert_ne!(
            actor_binding_digest("local-user", "ws-1"),
            actor_binding_digest("other", "ws-1")
        );
    }

    #[test]
    fn durable_secret_converges_across_creators_and_never_replaces_corrupt_or_unreadable_bytes() {
        let cache = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .canonicalize()
            .unwrap();
        let root = cache.join(format!("slot-token-secret-{}", uuid::Uuid::new_v4()));
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let handles = (0..2)
            .map(|_| {
                let root = root.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    load_or_create_secret(&root).unwrap()
                })
            })
            .collect::<Vec<_>>();
        let secrets = handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(secrets[0], secrets[1]);
        let secret = secrets[0];
        let signed = sign(&claims(), &secret).unwrap();
        assert_eq!(
            open(&signed, &load_or_create_secret(&root).unwrap()).unwrap(),
            claims()
        );
        let path = root.join("slot_token_secret.json");
        let original = fs::read(&path).unwrap();
        let envelope: Value = serde_json::from_slice(&original).unwrap();
        let mut tampered = envelope.clone();
        tampered["content"]["secret_b64"] = json!(STANDARD.encode([0u8; 32]));
        for corrupt in [
            b"{broken".to_vec(),
            b"{}".to_vec(),
            serde_json::to_vec(&tampered).unwrap(),
        ] {
            fs::write(&path, &corrupt).unwrap();
            assert!(load_or_create_secret(&root).is_err());
            assert_eq!(fs::read(&path).unwrap(), corrupt);
        }
        for content in [
            json!({"schema_version":"other", "secret_b64":STANDARD.encode(secret)}),
            json!({"schema_version":SECRET_SCHEMA, "secret_b64":"!!!"}),
            json!({"schema_version":SECRET_SCHEMA, "secret_b64":STANDARD.encode([0u8;31])}),
            json!({"schema_version":SECRET_SCHEMA}),
        ] {
            let invalid =
                serde_json::to_vec(&json!({"digest":content_digest(&content),"content":content}))
                    .unwrap();
            fs::write(&path, &invalid).unwrap();
            assert!(load_or_create_secret(&root).is_err());
            assert_eq!(fs::read(&path).unwrap(), invalid);
        }
        fs::write(&path, &original).unwrap();
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(0)
                .open(&path)
                .unwrap();
            assert!(load_or_create_secret(&root).is_err());
            drop(held);
            assert_eq!(fs::read(&path).unwrap(), original);
        }
        assert_eq!(load_or_create_secret(&root).unwrap(), secret);
        let root = root.canonicalize().unwrap();
        assert!(root.starts_with(cache));
        assert!(
            root.file_name()
                .unwrap()
                .to_str()
                .unwrap()
                .starts_with("slot-token-secret-")
        );
        fs::remove_dir_all(root).unwrap();
    }
}
