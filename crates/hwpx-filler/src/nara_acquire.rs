//! Keyless Nara acquisition state. Secrets, transport and clock are injected effects.

use crate::data_source::{DataSource, DataSourceError, Record};
use crate::nara::{NARA_SERVICE_KEY_NAME, OK_RESULT_CODE, default_field_labels, validate_range};
use crate::structure_scan::python_trim;
use chrono::{Duration, NaiveDateTime};
use indexmap::{IndexMap, IndexSet};

pub const GATEWAY_FAILURE: &str =
    "나라장터 서비스 응답을 가져오지 못했습니다. 잠시 후 다시 시도하세요.";

pub trait SecretStorePort {
    fn get(&self, name: &str) -> Result<Option<String>, String>;
    fn set(&self, name: &str, value: &str) -> Result<(), String>;
    fn delete(&self, name: &str) -> Result<(), String>;
    fn has(&self, name: &str) -> Result<bool, String> {
        Ok(self.get(name)?.is_some())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NaraGatewayResponse {
    pub records: Vec<Record>,
    pub result_code: String,
    pub result_msg: String,
    pub field_labels: IndexMap<String, String>,
}
pub trait NaraGatewayPort {
    fn fetch(
        &self,
        key: &str,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<NaraGatewayResponse, String>;
    fn probe(
        &self,
        key: &str,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<NaraGatewayResponse, String>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AcquiredNaraData {
    pub records: Vec<Record>,
    pub fields: Vec<String>,
    pub labels: IndexMap<String, String>,
}
impl DataSource for AcquiredNaraData {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
        Ok(self.records.clone())
    }
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
        Ok(self.fields.clone())
    }
    fn field_labels(&self) -> IndexMap<String, String> {
        self.labels.clone()
    }
    fn source_pointer(&self) -> Option<String> {
        Some("nara:취득 스냅샷(키 미포함)".into())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AcquireResult {
    pub ok: bool,
    pub records: Vec<Record>,
    pub fields: Vec<String>,
    pub result_code: String,
    pub result_msg: String,
    pub error: String,
    pub bgn_dt: String,
    pub end_dt: String,
    pub num_rows: u64,
    pub page_no: u64,
    pub field_labels: Option<IndexMap<String, String>>,
}
impl AcquireResult {
    fn empty(ok: bool, error: impl Into<String>) -> Self {
        Self {
            ok,
            records: Vec::new(),
            fields: Vec::new(),
            result_code: String::new(),
            result_msg: String::new(),
            error: error.into(),
            bgn_dt: String::new(),
            end_dt: String::new(),
            num_rows: 0,
            page_no: 0,
            field_labels: None,
        }
    }
    pub fn count(&self) -> usize {
        self.records.len()
    }
    pub fn acceptable(&self) -> bool {
        self.ok && !self.records.is_empty()
    }
    pub fn source_label(&self) -> String {
        format!(
            "나라장터 · {}~{} · {}건",
            self.bgn_dt,
            self.end_dt,
            self.count()
        )
    }
    pub fn as_datasource(&self) -> AcquiredNaraData {
        AcquiredNaraData {
            records: self.records.clone(),
            fields: self.fields.clone(),
            labels: self
                .field_labels
                .clone()
                .unwrap_or_else(default_field_labels),
        }
    }
    pub fn summary(&self) -> String {
        if !self.ok {
            format!("취득 실패: {}", self.error)
        } else if self.records.is_empty() {
            "취득 0건 — 기간·페이지를 확인하세요(응답은 정상).".into()
        } else {
            format!("{}건 취득.", self.count())
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConnResult {
    pub ok: bool,
    pub message: String,
}

pub struct NaraAcquireViewModel<S, G, C> {
    pub store: S,
    pub gateway: G,
    pub clock: C,
    pub secret_name: String,
    pub last_result: Option<AcquireResult>,
}
impl<S, G, C> NaraAcquireViewModel<S, G, C>
where
    S: SecretStorePort,
    G: NaraGatewayPort,
    C: Fn() -> NaiveDateTime,
{
    pub fn new(
        store: S,
        gateway: G,
        clock: C,
        secret_name: impl Into<String>,
    ) -> Result<Self, String> {
        let secret_name = secret_name.into();
        if secret_name.is_empty() {
            return Err("나라장터 비밀 이름이 비어 있습니다.".into());
        }
        Ok(Self {
            store,
            gateway,
            clock,
            secret_name,
            last_result: None,
        })
    }
    pub fn with_default_name(store: S, gateway: G, clock: C) -> Self {
        Self::new(store, gateway, clock, NARA_SERVICE_KEY_NAME).expect("fixed secret name")
    }
    pub fn is_registered(&self) -> Result<bool, String> {
        self.store.has(&self.secret_name)
    }
    pub fn status_label(&self) -> Result<&'static str, String> {
        Ok(if self.is_registered()? {
            "등록됨"
        } else {
            "미등록"
        })
    }
    pub fn save_key(&self, key: &str) -> Result<(), String> {
        let key = python_trim(key);
        if key.is_empty() {
            return Err("서비스키가 비어 있습니다. 값을 입력하세요.".into());
        }
        self.store.set(&self.secret_name, key)
    }
    pub fn delete_key(&self) -> Result<(), String> {
        self.store.delete(&self.secret_name)
    }
    pub fn acquire(
        &mut self,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<AcquireResult, String> {
        let result = self.acquire_result(bgn, end, num_rows, page_no)?;
        self.commit(result.clone());
        Ok(result)
    }
    pub fn acquire_result(
        &self,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<AcquireResult, String> {
        let mut result = self.acquire_inner(bgn, end, num_rows, page_no)?;
        result.bgn_dt = bgn.into();
        result.end_dt = end.into();
        result.num_rows = num_rows;
        result.page_no = page_no;
        Ok(result)
    }
    pub fn commit(&mut self, result: AcquireResult) {
        self.last_result = result.acceptable().then_some(result);
    }
    pub fn invalidate(&mut self) {
        self.last_result = None;
    }
    fn acquire_inner(
        &self,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<AcquireResult, String> {
        let Some(key) = self.store.get(&self.secret_name)? else {
            return Ok(AcquireResult::empty(
                false,
                "서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.",
            ));
        };
        if key.is_empty() {
            return Ok(AcquireResult::empty(
                false,
                "서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.",
            ));
        }
        if let Some(detail) = validate_range(bgn, end) {
            return Ok(AcquireResult::empty(false, detail));
        }
        let response = match self.gateway.fetch(&key, bgn, end, num_rows, page_no) {
            Ok(item) => item,
            Err(_) => return Ok(AcquireResult::empty(false, GATEWAY_FAILURE)),
        };
        if response.result_code != OK_RESULT_CODE {
            return Ok(AcquireResult {
                result_code: response.result_code.clone(),
                result_msg: response.result_msg.clone(),
                ..AcquireResult::empty(
                    false,
                    format!(
                        "API 오류 [{}] {}",
                        if response.result_code.is_empty() {
                            "코드 없음"
                        } else {
                            &response.result_code
                        },
                        if response.result_msg.is_empty() {
                            "메시지 없음"
                        } else {
                            &response.result_msg
                        }
                    ),
                )
            });
        }
        let mut seen = IndexSet::new();
        for record in &response.records {
            seen.extend(record.keys().cloned());
        }
        Ok(AcquireResult {
            ok: true,
            records: response.records,
            fields: seen.into_iter().collect(),
            result_code: response.result_code,
            result_msg: response.result_msg,
            field_labels: Some(response.field_labels),
            ..AcquireResult::empty(true, "")
        })
    }
    pub fn test_connection(&self) -> Result<ConnResult, String> {
        let Some(key) = self.store.get(&self.secret_name)? else {
            return Ok(ConnResult {
                ok: false,
                message: "서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.".into(),
            });
        };
        if key.is_empty() {
            return Ok(ConnResult {
                ok: false,
                message: "서비스키가 등록되어 있지 않습니다. 먼저 키를 등록하세요.".into(),
            });
        }
        let now = (self.clock)();
        let bgn = (now - Duration::days(1)).format("%Y%m%d%H%M").to_string();
        let end = now.format("%Y%m%d%H%M").to_string();
        let response = match self.gateway.probe(&key, &bgn, &end, 1, 1) {
            Ok(item) => item,
            Err(_) => {
                return Ok(ConnResult {
                    ok: false,
                    message: format!("연결 실패: {GATEWAY_FAILURE}"),
                });
            }
        };
        if response.result_code != OK_RESULT_CODE {
            return Ok(ConnResult {
                ok: false,
                message: format!(
                    "연결 실패 — API 오류 [{}] {}",
                    if response.result_code.is_empty() {
                        "코드 없음"
                    } else {
                        &response.result_code
                    },
                    if response.result_msg.is_empty() {
                        "메시지 없음"
                    } else {
                        &response.result_msg
                    }
                ),
            });
        }
        Ok(ConnResult {
            ok: true,
            message: "연결 성공 — 키가 유효합니다.".into(),
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[derive(Default)]
    struct MemorySecret(Mutex<Option<String>>);
    impl SecretStorePort for MemorySecret {
        fn get(&self, _: &str) -> Result<Option<String>, String> {
            Ok(self.0.lock().unwrap().clone())
        }
        fn set(&self, _: &str, value: &str) -> Result<(), String> {
            *self.0.lock().unwrap() = Some(value.into());
            Ok(())
        }
        fn delete(&self, _: &str) -> Result<(), String> {
            *self.0.lock().unwrap() = None;
            Ok(())
        }
    }
    type GatewayCall = (&'static str, String, String, String, u64, u64);
    struct ScriptedGateway {
        responses: Mutex<Vec<Result<NaraGatewayResponse, String>>>,
        calls: Mutex<Vec<GatewayCall>>,
    }
    impl ScriptedGateway {
        fn new(responses: Vec<Result<NaraGatewayResponse, String>>) -> Self {
            Self {
                responses: Mutex::new(responses),
                calls: Mutex::new(Vec::new()),
            }
        }
        fn take(
            &self,
            mode: &'static str,
            key: &str,
            bgn: &str,
            end: &str,
            num_rows: u64,
            page_no: u64,
        ) -> Result<NaraGatewayResponse, String> {
            self.calls.lock().unwrap().push((
                mode,
                key.into(),
                bgn.into(),
                end.into(),
                num_rows,
                page_no,
            ));
            self.responses.lock().unwrap().remove(0)
        }
    }
    impl NaraGatewayPort for ScriptedGateway {
        fn fetch(
            &self,
            key: &str,
            bgn: &str,
            end: &str,
            num_rows: u64,
            page_no: u64,
        ) -> Result<NaraGatewayResponse, String> {
            self.take("fetch", key, bgn, end, num_rows, page_no)
        }
        fn probe(
            &self,
            key: &str,
            bgn: &str,
            end: &str,
            num_rows: u64,
            page_no: u64,
        ) -> Result<NaraGatewayResponse, String> {
            self.take("probe", key, bgn, end, num_rows, page_no)
        }
    }
    #[test]
    fn keyless_acquisition_commit_and_failure_discard() {
        let record: Record = [
            ("bidNtceNo".into(), "N1".into()),
            ("bidNtceNm".into(), "사무용 복합기 구매".into()),
        ]
        .into();
        let response = NaraGatewayResponse {
            records: vec![record],
            result_code: "00".into(),
            result_msg: "정상".into(),
            field_labels: default_field_labels(),
        };
        let gateway = ScriptedGateway::new(vec![
            Ok(response.clone()),
            Ok(response.clone()),
            Ok(NaraGatewayResponse {
                records: Vec::new(),
                ..response.clone()
            }),
            Ok(NaraGatewayResponse {
                result_code: "07".into(),
                result_msg: "INVALID_REQUEST_PARAMETER_ERROR".into(),
                ..response.clone()
            }),
            Ok(NaraGatewayResponse {
                result_code: String::new(),
                result_msg: String::new(),
                ..response.clone()
            }),
            Err("HTTP 401 ServiceKey=secret-key".into()),
        ]);
        let clock =
            || NaiveDateTime::parse_from_str("2026-06-30 12:34:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let mut vm =
            NaraAcquireViewModel::with_default_name(MemorySecret::default(), gateway, clock);
        assert_eq!(vm.status_label().unwrap(), "미등록");
        assert!(vm.save_key("  ").is_err());
        vm.save_key("  secret-key  ").unwrap();
        assert_eq!(vm.status_label().unwrap(), "등록됨");
        assert_eq!(
            vm.store.get(NARA_SERVICE_KEY_NAME).unwrap().as_deref(),
            Some("secret-key")
        );
        let invalid = vm
            .acquire_result("202606010000", "202607150000", 50, 2)
            .unwrap();
        assert!(!invalid.ok && invalid.error.contains("1개월"));
        assert!(vm.gateway.calls.lock().unwrap().is_empty());
        let preview = vm
            .acquire_result("202606010000", "202606302359", 50, 2)
            .unwrap();
        assert!(vm.last_result.is_none());
        assert_eq!(preview.fields, ["bidNtceNo", "bidNtceNm"]);
        assert_eq!(preview.result_code, "00");
        assert!(preview.summary().contains("1건"));
        assert_eq!((preview.num_rows, preview.page_no), (50, 2));
        assert_eq!(
            preview.as_datasource().source_pointer().unwrap(),
            "nara:취득 스냅샷(키 미포함)"
        );
        let mut snapshot = preview.as_datasource();
        assert_eq!(snapshot.records().unwrap(), preview.records);
        assert_eq!(snapshot.fields().unwrap(), preview.fields);
        assert_eq!(snapshot.field_labels()["bidNtceNo"], "입찰공고번호");
        assert!(!format!("{preview:?}").contains("secret-key"));
        vm.commit(preview.clone());
        assert_eq!(vm.last_result.as_ref().unwrap().count(), 1);
        vm.invalidate();
        assert!(vm.last_result.is_none());
        let acquired = vm.acquire("202606010000", "202606302359", 50, 2).unwrap();
        assert!(acquired.acceptable());
        assert_eq!(
            acquired.source_label(),
            "나라장터 · 202606010000~202606302359 · 1건"
        );
        assert_eq!(vm.last_result.as_ref(), Some(&acquired));
        let zero = vm.acquire("202606010000", "202606302359", 100, 1).unwrap();
        assert!(zero.ok && !zero.acceptable());
        assert!(zero.summary().starts_with("취득 0건"));
        assert!(vm.last_result.is_none());
        let auth = vm.acquire("202606010000", "202606302359", 100, 1).unwrap();
        assert!(!auth.ok && auth.result_code == "07" && auth.error.contains("07"));
        let missing = vm.acquire("202606010000", "202606302359", 100, 1).unwrap();
        assert!(
            !missing.ok && missing.result_code.is_empty() && missing.error.contains("API 오류")
        );
        vm.commit(acquired);
        let failed = vm.acquire("202606010000", "202606302359", 100, 1).unwrap();
        assert_eq!(failed.error, GATEWAY_FAILURE);
        assert!(!failed.error.contains("secret-key"));
        assert!(vm.last_result.is_none());
        let calls = vm.gateway.calls.lock().unwrap();
        assert_eq!(calls.len(), 6);
        assert_eq!(
            calls[0],
            (
                "fetch",
                "secret-key".into(),
                "202606010000".into(),
                "202606302359".into(),
                50,
                2
            )
        );
        assert!(calls.iter().all(|call| call.0 == "fetch"));
        drop(calls);
        vm.save_key(" KEY2 ").unwrap();
        assert_eq!(
            vm.store.get(NARA_SERVICE_KEY_NAME).unwrap().as_deref(),
            Some("KEY2")
        );
        vm.delete_key().unwrap();
        assert_eq!(vm.status_label().unwrap(), "미등록");
        vm.delete_key().unwrap();
        assert!(!vm.test_connection().unwrap().ok);
        assert_eq!(vm.gateway.calls.lock().unwrap().len(), 6);

        let key = "aB3+xY/z9Q==pLm4Kn7";
        let encoded = "aB3%2BxY%2Fz9Q%3D%3DpLm4Kn7";
        let raw = serde_json::to_vec(&serde_json::json!({"response": {
            "header": {"resultCode":format!("07-{key}-{encoded}"),
                "resultMsg":format!("rejected ServiceKey={key}; encoded={encoded}")},
            "body":{}
        }}))
        .unwrap();
        let gateway = crate::nara::NaraStdGateway {
            fetcher: std::sync::Arc::new(move |_| Ok(raw.clone())),
        };
        let mut vm =
            NaraAcquireViewModel::with_default_name(MemorySecret::default(), gateway, clock);
        vm.save_key(key).unwrap();
        let rejected = vm.acquire("202606010000", "202606302359", 100, 1).unwrap();
        assert!(!rejected.ok && vm.last_result.is_none());
        let surface = format!("{rejected:?}");
        assert!(!surface.contains(key) && !surface.contains(encoded));
        assert!(surface.contains("ServiceKey=[REDACTED]"));
    }

    #[test]
    fn connection_probes_only_one_day_and_never_exposes_a_key() {
        let key = "aB3+xY/z9Q==pLm4Kn7";
        let success = NaraGatewayResponse {
            records: Vec::new(),
            result_code: "00".into(),
            result_msg: "정상".into(),
            field_labels: default_field_labels(),
        };
        let gateway = ScriptedGateway::new(vec![
            Ok(success.clone()),
            Ok(NaraGatewayResponse {
                result_code: "30".into(),
                result_msg: "SERVICE_KEY_IS_NOT_REGISTERED_ERROR".into(),
                ..success.clone()
            }),
            Ok(NaraGatewayResponse {
                result_code: String::new(),
                result_msg: String::new(),
                ..success
            }),
            Err(format!("HTTP 401 ServiceKey={key}")),
        ]);
        let clock =
            || NaiveDateTime::parse_from_str("2026-06-30 12:34:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let vm = NaraAcquireViewModel::with_default_name(MemorySecret::default(), gateway, clock);
        vm.save_key(key).unwrap();
        assert!(vm.test_connection().unwrap().ok);
        let auth = vm.test_connection().unwrap();
        assert!(!auth.ok && auth.message.contains("30") && !auth.message.contains(key));
        let missing = vm.test_connection().unwrap();
        assert!(!missing.ok && missing.message.contains("코드 없음"));
        let transport = vm.test_connection().unwrap();
        assert!(!transport.ok && transport.message.contains(GATEWAY_FAILURE));
        assert!(!transport.message.contains(key) && !transport.message.contains("ServiceKey="));
        assert!(vm.last_result.is_none());
        let calls = vm.gateway.calls.lock().unwrap();
        assert_eq!(calls.len(), 4);
        assert!(calls.iter().all(|call| call
            == &(
                "probe",
                key.into(),
                "202606291234".into(),
                "202606301234".into(),
                1,
                1,
            )));
    }
}
