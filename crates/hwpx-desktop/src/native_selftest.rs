//! Real WebView selftest capability, present only in an explicit `--selftest` process.

use crate::atomic_file::write_bytes_atomic;
use crate::shell_settings::ShellSettings;
use crate::web_assets::WebAssets;
use serde_json::{Value, json};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use tauri::{WebviewWindow, Wry};
use uuid::Uuid;

const PROVIDES: &[&str] = &[
    "input_select",
    "window_resize",
    "window_geometry",
    "current_url",
    "artifact_identity",
    "settings_readback",
];

const GLOBAL_DELTA_JS: &str = r#"function delta() {
    const retired = ['AppCloseGuard','Bridge','Copy','DataPicker','DataZone','EditorEntry',
      'EditorScreen','GroupList','Guard','Intent','JobScreen','LibraryScreen','Modal','Nav',
      'PathTrack','Personalization','Popover','Preserve','Relink','SegView','SheetPicker',
      'SurfaceSheet','Theme','UndoToast','WorkbenchScreen','__push','escHtml'];
    const names = Object.getOwnPropertyNames(window).sort();
    const digest = list => {
      let h = 0x811c9dc5;
      for (const name of list) {
        for (let j=0;j<name.length;j++) {
          h ^= name.charCodeAt(j);
          h = (h + ((h<<1)+(h<<4)+(h<<7)+(h<<8)+(h<<24))) >>> 0;
        }
        h ^= 10;
        h = (h + ((h<<1)+(h<<4)+(h<<7)+(h<<8)+(h<<24))) >>> 0;
      }
      return h >>> 0;
    };
    return {total_own:names.length,
      hwpx_namespace:names.filter(name=>name.startsWith('__hwpx')),
      retired_present:names.filter(name=>retired.includes(name)),
      digest:digest(names),
      digest_without_test:digest(names.filter(name=>name!=='__hwpxTest')),
      has_document:names.includes('document'), has_location:names.includes('location')};
}"#;

pub struct NativeSelftest {
    claimed: AtomicBool,
    terminal: AtomicU8,
    pub mode: String,
    pub input: Value,
    pub probes: Option<Vec<String>>,
    pub output: PathBuf,
    pub artifact_id: String,
    pub tree_sha256: String,
}

impl NativeSelftest {
    fn parse_probes(raw: &str) -> Result<Vec<String>, String> {
        let names = raw.split(',').map(str::trim).collect::<Vec<_>>();
        if names.is_empty() || names.iter().any(|name| name.is_empty()) {
            return Err("selftest probes must be nonempty comma-separated names".into());
        }
        Ok(names.into_iter().map(str::to_owned).collect())
    }

    pub fn from_env(assets: &WebAssets) -> Result<Self, String> {
        let mode = if std::env::var_os("HWPX_SELFTEST_NO_CAPABILITY").is_some() {
            "no_capability"
        } else if std::env::var_os("HWPX_SELFTEST_GLOBAL_DELTA").is_some() {
            "global_delta"
        } else if std::env::var_os("HWPX_SELFTEST_GEOMETRY_ONLY").is_some() {
            "geometry_only"
        } else if std::env::var_os("HWPX_SELFTEST_SET_FONT_SCALE").is_some() {
            "font_scale_write"
        } else if std::env::var_os("HWPX_SELFTEST_SET_THEME").is_some() {
            "theme_write"
        } else {
            "full"
        };
        let input = match mode {
            "font_scale_write" => std::env::var("HWPX_SELFTEST_SET_FONT_SCALE")
                .map(Value::String)
                .map_err(|error| error.to_string())?,
            "theme_write" => std::env::var("HWPX_SELFTEST_SET_THEME")
                .map(Value::String)
                .map_err(|error| error.to_string())?,
            _ => Value::Null,
        };
        let probes = std::env::var("HWPX_SELFTEST_PROBES")
            .ok()
            .map(|raw| Self::parse_probes(&raw))
            .transpose()?;
        let output = std::env::var_os("HWPX_SELFTEST_OUT")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                std::env::current_exe()
                    .ok()
                    .and_then(|path| {
                        path.parent()
                            .map(|parent| parent.join("selftest_result.json"))
                    })
                    .unwrap_or_else(|| PathBuf::from("selftest_result.json"))
            });
        Ok(Self {
            claimed: AtomicBool::new(false),
            terminal: AtomicU8::new(0),
            mode: mode.into(),
            input,
            probes,
            output,
            artifact_id: assets.artifact_id.clone(),
            tree_sha256: assets.tree_sha256.clone(),
        })
    }

    pub fn claim(&self, version: &Value) -> Value {
        if version != 1 {
            return json!({"ok":false,"code":"version-unsupported"});
        }
        if self.claimed.swap(true, Ordering::SeqCst) {
            return json!({"ok":false,"code":"already_claimed"});
        }
        let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        json!({"ok":true,"version":1,"token":token,"provides":PROVIDES})
    }

    pub fn web_capability(&self) -> bool {
        self.mode != "no_capability"
    }

    fn resize_dimensions(payload: &Value) -> Option<(u32, u32)> {
        let width = payload["width"].as_u64()?;
        let height = payload["height"].as_u64()?;
        ((320..=4096).contains(&width) && (320..=4096).contains(&height))
            .then_some((width as u32, height as u32))
    }

    fn setting_refusal(op: &str, payload: &Value) -> Option<&'static str> {
        match payload["setting"].as_str() {
            Some("theme" | "font_scale") => None,
            Some(_) => Some(if op == "input_select" {
                "unknown_input"
            } else {
                "unknown_op"
            }),
            None => Some("malformed_payload"),
        }
    }

    fn payload_refusal(op: &str, payload: &Value) -> Option<&'static str> {
        match op {
            "input_select" | "settings_readback" => Self::setting_refusal(op, payload),
            "window_resize" if Self::resize_dimensions(payload).is_some() => None,
            "window_resize" => Some("malformed_payload"),
            _ if payload.is_null() || payload.as_object().is_some_and(|body| body.is_empty()) => {
                None
            }
            _ => Some("malformed_payload"),
        }
    }

    fn host_op_refusal(&self, op: &str, payload: &Value) -> Option<&'static str> {
        if !self.claimed.load(Ordering::SeqCst) {
            return Some("not-claimed");
        }
        if !PROVIDES.contains(&op) {
            return Some("unknown_op");
        }
        Self::payload_refusal(op, payload)
    }

    fn input_value(payload: &Value) -> Result<Value, &'static str> {
        match payload["setting"].as_str() {
            Some("theme") => Ok(Value::String(
                std::env::var("HWPX_SELFTEST_SET_THEME").unwrap_or_default(),
            )),
            Some("font_scale") => Ok(Value::String(
                std::env::var("HWPX_SELFTEST_SET_FONT_SCALE").unwrap_or_default(),
            )),
            _ => Err("unknown_input"),
        }
    }

    fn setting_value(settings: &ShellSettings, payload: &Value) -> Result<Value, &'static str> {
        match payload["setting"].as_str() {
            Some("theme") => settings
                .load_theme()
                .map(|value| json!(value))
                .map_err(|_| "internal"),
            Some("font_scale") => settings
                .load_font_scale()
                .map(|value| json!(value))
                .map_err(|_| "internal"),
            _ => Err("unknown_op"),
        }
    }

    fn execute_host_op(
        &self,
        op: &str,
        payload: &Value,
        window: &WebviewWindow<Wry>,
        settings: &ShellSettings,
    ) -> Result<Value, &'static str> {
        match op {
            "input_select" => Self::input_value(payload),
            "window_resize" => {
                let (width, height) = Self::resize_dimensions(payload).expect("validated payload");
                crate::tauri_host::set_outer_logical_size(window, width, height)
                    .map(|_| json!({"width":width,"height":height}))
                    .map_err(|_| "internal")
            }
            "window_geometry" => self.geometry(window).map_err(|_| "internal"),
            "current_url" => window
                .url()
                .map(|url| json!(url.to_string()))
                .map_err(|_| "internal"),
            "artifact_identity" => Ok(json!({
                "artifact_id":self.artifact_id,"tree_sha256":self.tree_sha256
            })),
            "settings_readback" => Self::setting_value(settings, payload),
            _ => Err("unknown_op"),
        }
    }

    pub fn host_op(
        &self,
        op: &str,
        payload: &Value,
        window: &WebviewWindow<Wry>,
        settings: &ShellSettings,
    ) -> Value {
        if let Some(code) = self.host_op_refusal(op, payload) {
            let detail = if code == "not-claimed" {
                "악수 전에는 호스트 연산을 받지 않는다".to_owned()
            } else {
                format!("호스트 연산 {op} 실패")
            };
            return json!({"ok":false,"op":op,"code":code,"detail":detail,"value":null});
        }
        let value = self.execute_host_op(op, payload, window, settings);
        match value {
            Ok(value) => json!({"ok":true,"op":op,"code":"ok","detail":"","value":value}),
            Err(code) => {
                json!({"ok":false,"op":op,"code":code,"detail":format!("호스트 연산 {op} 실패"),"value":null})
            }
        }
    }

    fn geometry(&self, window: &WebviewWindow<Wry>) -> Result<Value, String> {
        let position = window.outer_position().map_err(|error| error.to_string())?;
        let size = window.outer_size().map_err(|error| error.to_string())?;
        let scale = window.scale_factor().map_err(|error| error.to_string())?;
        let monitor = window
            .current_monitor()
            .map_err(|error| error.to_string())?
            .ok_or("창 모니터가 없습니다.")?;
        let available = monitor.work_area();
        let position = position.to_logical::<f64>(scale);
        let size = size.to_logical::<f64>(scale);
        let available_position = available.position.to_logical::<f64>(scale);
        let available_size = available.size.to_logical::<f64>(scale);
        let (x, y, width, height) = (
            position.x.round() as i64,
            position.y.round() as i64,
            size.width.round() as i64,
            size.height.round() as i64,
        );
        let (avail_x, avail_y, avail_width, avail_height) = (
            available_position.x.round() as i64,
            available_position.y.round() as i64,
            available_size.width.round() as i64,
            available_size.height.round() as i64,
        );
        let maximized_like = x <= avail_x + 8
            && y <= avail_y + 8
            && x + width >= avail_x + avail_width - 20
            && y + height >= avail_y + avail_height - 20;
        Ok(json!({"x":x,"y":y,"width":width,"height":height,
            "avail_x":avail_x,"avail_y":avail_y,"avail_width":avail_width,
            "avail_height":avail_height,"maximized_like":maximized_like}))
    }

    pub fn finish(&self, response: &Value) -> Result<(), String> {
        if self
            .terminal
            .compare_exchange(0, 3, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err("selftest already finished".into());
        }
        let evidence = response.get("evidence").filter(|value| value.is_object());
        let mut output = evidence.cloned().unwrap_or_else(|| json!({}));
        let succeeded = response["ok"] == true && response["state"] == "succeeded";
        if !succeeded {
            output["error"] = json!(format!("WebView2 selftest failed: {}", response));
        }
        let bytes = serde_json::to_vec_pretty(&output).map_err(|error| error.to_string())?;
        write_bytes_atomic(&self.output, &bytes).map_err(|error| error.to_string())?;
        self.terminal
            .store(if succeeded { 1 } else { 2 }, Ordering::SeqCst);
        Ok(())
    }

    pub fn timeout(&self) -> Result<bool, String> {
        if self
            .terminal
            .compare_exchange(0, 2, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Ok(false);
        }
        let output = json!({"error":"WebView2 selftest deadline exceeded"});
        write_bytes_atomic(&self.output, output.to_string().as_bytes())
            .map_err(|error| error.to_string())?;
        Ok(true)
    }

    pub fn succeeded(&self) -> bool {
        self.terminal.load(Ordering::SeqCst) == 1
    }

    pub fn driver_script(&self) -> Result<String, String> {
        if self.mode == "no_capability" {
            let sentinel = serde_json::to_string(
                &std::env::var("HWPX_SELFTEST_LEAK_SENTINEL").unwrap_or_default(),
            )
            .map_err(|error| error.to_string())?;
            return Ok(format!(
                r#"(async()=>{{
                    const invoke=window.__TAURI__.core.invoke;
                    const sentinel={sentinel};
                    if (sentinel) window[sentinel]=1;
                    const own=()=>Object.prototype.hasOwnProperty.call(window,'__hwpxTest');
                    const nonExposure={{selftest_own:own(),selftest_typeof:typeof window.__hwpxTest,
                        product_typeof:typeof window.__hwpx,
                        host_claim_typeof:typeof window.pywebview?.api?.selftest_claim}};
                    {GLOBAL_DELTA_JS}
                    const globalDelta=delta();
                    history.replaceState(null,'',location.pathname+'?selftest=1&hwpxTest=on#selftest');
                    nonExposure.url_after=location.href;
                    nonExposure.selftest_own_after_query_hash=own();
                    nonExposure.selftest_typeof_after_query_hash=typeof window.__hwpxTest;
                    const evidence={{mode:'no_capability',global_delta:globalDelta,non_exposure:nonExposure}};
                    if(sentinel) evidence.leak_sentinel=sentinel;
                    const ok=nonExposure.product_typeof==='object' && !nonExposure.selftest_own
                        && nonExposure.host_claim_typeof==='undefined';
                    await invoke('selftest_finish',{{response:{{ok,state:ok?'succeeded':'failed',evidence}}}});
                }})().catch(error=>window.__TAURI__.core.invoke('selftest_finish',
                    {{response:{{ok:false,state:'failed',error:String(error)}}}}));"#
            ));
        }
        if self.mode == "global_delta" {
            return Ok(format!(
                r#"(async()=>{{
                    const invoke=window.__TAURI__.core.invoke;
                    for(let i=0;i<300 && !window.__hwpxTest;i++)
                        await new Promise(resolve=>setTimeout(resolve,100));
                    {GLOBAL_DELTA_JS}
                    const evidence={{mode:'global_delta',global_delta:delta()}};
                    const ok=window.__hwpxTest?.version===1;
                    await invoke('selftest_finish',{{response:{{ok,state:ok?'succeeded':'failed',evidence}}}});
                }})().catch(error=>window.__TAURI__.core.invoke('selftest_finish',
                    {{response:{{ok:false,state:'failed',error:String(error)}}}}));"#
            ));
        }
        let mode = serde_json::to_string(&self.mode).map_err(|error| error.to_string())?;
        let input = serde_json::to_string(&self.input).map_err(|error| error.to_string())?;
        let probes = serde_json::to_string(&self.probes).map_err(|error| error.to_string())?;
        let offline = std::env::var_os("HWPX_SELFTEST_OFFLINE_PROBE").is_some();
        Ok(format!(
            r#"(async()=>{{
            const invoke = window.__TAURI__.core.invoke;
            let api;
            for (let i=0;i<300;i++) {{
                api=window.__hwpxTest;
                if (api?.version===1) break;
                await new Promise(resolve=>setTimeout(resolve,100));
            }}
            if (!api || api.version!==1) {{
                await invoke('selftest_finish',{{response:{{ok:false,state:'failed',error:'facade-absent'}}}});
                return;
            }}
            const started=api.run({{version:1,action:'start',mode:{mode},input:{input},probes:{probes},flags:{{offlineProbe:{offline}}}}});
            if (!started.ok) {{await invoke('selftest_finish',{{response:started}});return;}}
            let result;
            do {{
                await new Promise(resolve=>setTimeout(resolve,100));
                result=api.run({{version:1,action:'poll',runId:started.runId}});
            }} while (result.state==='running');
            await invoke('selftest_finish',{{response:result}});
        }})().catch(async error=>{{
            await window.__TAURI__.core.invoke('selftest_finish',{{response:{{ok:false,state:'failed',error:String(error)}}}});
        }});"#
        ))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::NativeSelftest;
    use serde_json::json;
    use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};

    #[test]
    fn claim_and_terminal_state_are_single_use() {
        assert_eq!(
            NativeSelftest::parse_probes("theme_persist, personalization_persist").unwrap(),
            ["theme_persist", "personalization_persist"]
        );
        assert!(NativeSelftest::parse_probes("theme_persist,").is_err());
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/native-selftest-owner")
            .join(uuid::Uuid::new_v4().to_string());
        std::fs::create_dir_all(&root).unwrap();
        let make = |name: &str| NativeSelftest {
            claimed: AtomicBool::new(false),
            terminal: AtomicU8::new(0),
            mode: "full".into(),
            input: serde_json::Value::Null,
            probes: None,
            output: root.join(name),
            artifact_id: "artifact".into(),
            tree_sha256: "tree".into(),
        };
        let success = make("success.json");
        assert_eq!(
            success.host_op_refusal("window_resize", &json!({"width":720,"height":500})),
            Some("not-claimed")
        );
        assert_eq!(success.claim(&json!(2))["code"], "version-unsupported");
        assert_eq!(success.claim(&json!(1))["ok"], true);
        assert_eq!(success.claim(&json!(1))["code"], "already_claimed");
        for (op, payload, expected) in [
            ("window_geometry", json!(null), None),
            ("window_geometry", json!({}), None),
            ("window_geometry", json!({"x":1}), Some("malformed_payload")),
            ("window_resize", json!({"width":720,"height":500}), None),
            (
                "window_resize",
                json!({"width":true,"height":500}),
                Some("malformed_payload"),
            ),
            (
                "window_resize",
                json!({"width":0,"height":500}),
                Some("malformed_payload"),
            ),
            ("input_select", json!({}), Some("malformed_payload")),
            (
                "input_select",
                json!({"setting":"unknown"}),
                Some("unknown_input"),
            ),
            (
                "settings_readback",
                json!({"setting":"unknown"}),
                Some("unknown_op"),
            ),
            ("stray_op", json!(null), Some("unknown_op")),
        ] {
            assert_eq!(
                success.host_op_refusal(op, &payload),
                expected,
                "{op}: {payload}"
            );
        }
        success
            .finish(&json!({"ok":true,"state":"succeeded","evidence":{"url":"app"}}))
            .unwrap();
        assert!(success.succeeded());
        assert!(!success.timeout().unwrap());
        assert!(success.succeeded());
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&std::fs::read(&success.output).unwrap())
                .unwrap()["url"],
            "app"
        );
        let failed = make("failed.json");
        failed
            .finish(&json!({"ok":false,"state":"failed","error":"probe failed"}))
            .unwrap();
        assert!(!failed.succeeded());
        assert!(
            std::fs::read_to_string(&failed.output)
                .unwrap()
                .contains("probe failed")
        );
        let blocked = make("blocked.json");
        std::fs::create_dir(&blocked.output).unwrap();
        assert!(
            blocked
                .finish(&json!({"ok":true,"state":"succeeded"}))
                .is_err()
        );
        assert!(!blocked.succeeded());
        assert_eq!(blocked.terminal.load(Ordering::SeqCst), 3);
        assert!(
            blocked
                .finish(&json!({"ok":true,"state":"succeeded"}))
                .is_err()
        );
        let deadline = make("deadline.json");
        assert!(deadline.timeout().unwrap());
        assert!(
            deadline
                .finish(&json!({"ok":true,"state":"succeeded"}))
                .is_err()
        );
        assert!(!deadline.succeeded());
        assert!(
            std::fs::read_to_string(&deadline.output)
                .unwrap()
                .contains("deadline exceeded")
        );
        assert_eq!(deadline.terminal.load(Ordering::SeqCst), 2);
        let blocked_deadline = make("blocked-deadline.json");
        std::fs::create_dir(&blocked_deadline.output).unwrap();
        assert!(blocked_deadline.timeout().is_err());
        assert!(!blocked_deadline.succeeded());
        assert_eq!(blocked_deadline.terminal.load(Ordering::SeqCst), 2);
        std::fs::remove_dir_all(root).unwrap();
    }
}
