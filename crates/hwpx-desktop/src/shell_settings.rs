//! App-global appearance and window geometry settings over the atomic JSON store.

use crate::settings_store::{mutate, read_with_alert};
use hwpx_filler::structure_scan::python_trim;
use hwpx_filler::text_render::python_repr;
use serde_json::{Value, json};
use std::io;
use std::path::PathBuf;
use std::sync::Arc;

const THEMES: [&str; 3] = ["system", "light", "dark"];
const FONT_SCALES: [&str; 3] = ["normal", "large", "larger"];

pub fn is_proportional_font(font: &str) -> bool {
    font == "malgun"
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WindowGeometry {
    pub x: i64,
    pub y: i64,
    pub width: i64,
    pub height: i64,
    pub maximized: bool,
}
impl WindowGeometry {
    fn from_value(value: &Value) -> Option<Self> {
        let object = value.as_object()?;
        let geometry = Self {
            x: object.get("x")?.as_i64()?,
            y: object.get("y")?.as_i64()?,
            width: object.get("width")?.as_i64()?,
            height: object.get("height")?.as_i64()?,
            maximized: object.get("maximized")?.as_bool()?,
        };
        (geometry.width >= 760 && geometry.height >= 600).then_some(geometry)
    }

    pub fn visible_in(&self, bounds: (i64, i64, i64, i64)) -> bool {
        let (vx, vy, vw, vh) = bounds;
        if vw <= 0 || vh <= 0 {
            return false;
        }
        let overlap = self
            .x
            .saturating_add(self.width)
            .min(vx.saturating_add(vw))
            .saturating_sub(self.x.max(vx));
        overlap >= self.width.min(64)
            && self.y.saturating_add(32) > vy
            && self.y < vy.saturating_add(vh)
    }
}

pub struct ShellSettings {
    path: PathBuf,
    alert: Arc<dyn Fn(&str) + Send + Sync>,
}
impl ShellSettings {
    pub fn new(path: PathBuf, alert: impl Fn(&str) + Send + Sync + 'static) -> Self {
        Self {
            path,
            alert: Arc::new(alert),
        }
    }
    fn read(&self) -> io::Result<serde_json::Map<String, Value>> {
        read_with_alert(&self.path, |message| (self.alert)(message))
    }
    fn save(&self, key: &str, value: Value) -> io::Result<()> {
        mutate(&self.path, |data| {
            data.insert(key.into(), value.clone());
        })
    }
    pub fn load_boot_completed(&self) -> io::Result<String> {
        Ok(self
            .read()?
            .get("boot_completed_runtime")
            .and_then(Value::as_str)
            .unwrap_or("")
            .into())
    }
    pub fn save_boot_completed(&self, version: &str) -> io::Result<()> {
        let version = python_trim(version);
        self.save(
            "boot_completed_runtime",
            json!(if version.is_empty() {
                "unknown"
            } else {
                version
            }),
        )
    }
    pub fn load_templates_root(&self) -> io::Result<String> {
        Ok(self
            .read()?
            .get("templates_root")
            .and_then(Value::as_str)
            .unwrap_or("")
            .into())
    }
    pub fn save_templates_root(&self, path: &str) -> io::Result<()> {
        if python_trim(path).is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "유효하지 않은 서식 폴더 경로: {}",
                    python_repr(&json!(path))
                ),
            ));
        }
        self.save("templates_root", json!(path))
    }
    pub fn load_draft_target_font(&self) -> io::Result<String> {
        Ok(self
            .read()?
            .get("draft_target_font")
            .and_then(Value::as_str)
            .filter(|font| matches!(*font, "gulimche" | "dotumche" | "malgun"))
            .unwrap_or("gulimche")
            .into())
    }
    pub fn save_draft_target_font(&self, font: &str) -> io::Result<()> {
        if !matches!(font, "gulimche" | "dotumche" | "malgun") {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "유효하지 않은 대상 글꼴: {} (허용: ('gulimche', 'dotumche', 'malgun'))",
                    python_repr(&json!(font))
                ),
            ));
        }
        self.save("draft_target_font", json!(font))
    }
    pub fn load_theme(&self) -> io::Result<String> {
        Ok(self
            .read()?
            .get("theme")
            .and_then(Value::as_str)
            .filter(|mode| THEMES.contains(mode))
            .unwrap_or("system")
            .into())
    }
    pub fn save_theme(&self, mode: &str) -> io::Result<()> {
        if !THEMES.contains(&mode) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "유효하지 않은 테마: {} (허용: ('system', 'light', 'dark'))",
                    python_repr(&json!(mode))
                ),
            ));
        }
        self.save("theme", json!(mode))
    }
    pub fn load_font_scale(&self) -> io::Result<String> {
        Ok(self
            .read()?
            .get("font_scale")
            .and_then(Value::as_str)
            .filter(|scale| FONT_SCALES.contains(scale))
            .unwrap_or("normal")
            .into())
    }
    pub fn save_font_scale(&self, scale: &str) -> io::Result<()> {
        if !FONT_SCALES.contains(&scale) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "유효하지 않은 글자 크기: {} (허용: ('normal', 'large', 'larger'))",
                    python_repr(&json!(scale))
                ),
            ));
        }
        self.save("font_scale", json!(scale))
    }
    pub fn load_master_width(&self) -> io::Result<i64> {
        Ok(self
            .read()?
            .get("master_width")
            .and_then(Value::as_i64)
            .filter(|width| (180..=420).contains(width))
            .unwrap_or(240))
    }
    pub fn save_master_width(&self, width: i64) -> io::Result<()> {
        if !(180..=420).contains(&width) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "목록 폭은 180~420px 정수여야 합니다",
            ));
        }
        self.save("master_width", json!(width))
    }
    pub fn load_authoring_widths(&self) -> io::Result<(Option<i64>, Option<i64>)> {
        let data = self.read()?;
        let widths = data.get("authoring_widths").and_then(Value::as_object);
        let valid = |panel: &str, low: i64, high: i64| {
            widths
                .and_then(|widths| widths.get(panel))
                .and_then(Value::as_i64)
                .filter(|width| (low..=high).contains(width))
        };
        Ok((valid("outline", 176, 384), valid("properties", 224, 448)))
    }
    pub fn save_authoring_width(&self, panel: &str, width: i64) -> io::Result<()> {
        let (low, high) = match panel {
            "outline" => (176, 384),
            "properties" => (224, 448),
            _ => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!(
                        "유효하지 않은 저작 패널: {} (허용: ('outline', 'properties'))",
                        python_repr(&json!(panel))
                    ),
                ));
            }
        };
        if !(low..=high).contains(&width) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("{panel} 패널 폭은 {low}~{high} 정수여야 합니다"),
            ));
        }
        mutate(&self.path, |data| {
            let mut widths = data
                .get("authoring_widths")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            widths.insert(panel.into(), json!(width));
            data.insert("authoring_widths".into(), Value::Object(widths));
        })
    }
    pub fn load_window_geometry(&self) -> io::Result<Option<WindowGeometry>> {
        Ok(self
            .read()?
            .get("window_geometry")
            .and_then(WindowGeometry::from_value))
    }
    pub fn save_window_geometry(&self, geometry: &WindowGeometry) -> io::Result<()> {
        if geometry.width < 760 || geometry.height < 600 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "창 기하는 정수 좌표·최소 760×600 크기·bool 최대화 상태여야 합니다",
            ));
        }
        self.save("window_geometry", json!({"x": geometry.x, "y": geometry.y, "width": geometry.width, "height": geometry.height, "maximized": geometry.maximized}))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{ShellSettings, WindowGeometry};
    use serde_json::{Value, json};
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn shell_settings_keep_unrelated_values_and_reject_invalid_dimensions() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-shell-settings-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("settings.json");
        let settings =
            ShellSettings::new(path.clone(), |_| panic!("valid settings must not alarm"));
        assert_eq!(settings.load_theme().unwrap(), "system");
        assert_eq!(settings.load_font_scale().unwrap(), "normal");
        assert_eq!(settings.load_master_width().unwrap(), 240);
        assert_eq!(settings.load_draft_target_font().unwrap(), "gulimche");
        assert_eq!(settings.load_authoring_widths().unwrap(), (None, None));
        assert_eq!(settings.load_window_geometry().unwrap(), None);
        fs::write(&path, r#"{"unknown":42,"theme":"broken","window_geometry":{"x":0,"y":0,"width":10,"height":900,"maximized":false}}"#).unwrap();
        let settings = ShellSettings::new(path.clone(), |_| {});
        assert_eq!(settings.load_theme().unwrap(), "system");
        assert_eq!(settings.load_boot_completed().unwrap(), "");
        settings.save_boot_completed("").unwrap();
        assert_eq!(settings.load_boot_completed().unwrap(), "unknown");
        settings.save_boot_completed(" 123.4 ").unwrap();
        assert_eq!(settings.load_boot_completed().unwrap(), "123.4");
        assert_eq!(settings.load_window_geometry().unwrap(), None);
        assert!(settings.save_master_width(421).is_err());
        settings.save_theme("dark").unwrap();
        settings.save_authoring_width("outline", 320).unwrap();
        settings.save_authoring_width("properties", 350).unwrap();
        assert_eq!(
            settings.load_authoring_widths().unwrap(),
            (Some(320), Some(350))
        );
        settings
            .save_window_geometry(&WindowGeometry {
                x: 1,
                y: 2,
                width: 900,
                height: 700,
                maximized: true,
            })
            .unwrap();
        assert_eq!(settings.load_window_geometry().unwrap().unwrap().x, 1);
        assert_geometry_visibility_contract();
        assert!(
            fs::read_to_string(&path)
                .unwrap()
                .contains("\"unknown\": 42")
        );
        assert_settings_values(&settings, &path);
        assert_corrupt_settings(&settings, &path);
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_geometry_visibility_contract() {
        let base = WindowGeometry {
            x: 20,
            y: 20,
            width: 1180,
            height: 900,
            maximized: false,
        };
        let screen = (0, 0, 1920, 1080);
        for (x, y, expected) in [
            (-100, 20, true),
            (-1200, 20, false),
            (1856, 20, true),
            (1860, 20, false),
            (1920, 20, false),
            (20, -32, false),
            (20, -31, true),
            (20, 1080, false),
        ] {
            assert_eq!(
                WindowGeometry { x, y, ..base }.visible_in(screen),
                expected,
                "x={x}, y={y}"
            );
        }
        assert!(!base.visible_in((0, 0, 0, 1080)));
        assert!(!base.visible_in((0, 0, 1920, -1)));
        assert!(WindowGeometry { x: -100, ..base }.visible_in((-1920, 0, 3840, 1080)));
    }

    fn assert_settings_values(settings: &ShellSettings, path: &Path) {
        for theme in ["system", "light", "dark"] {
            settings.save_theme(theme).unwrap();
            assert_eq!(settings.load_theme().unwrap(), theme);
        }
        for font in ["gulimche", "dotumche", "malgun"] {
            settings.save_draft_target_font(font).unwrap();
            assert_eq!(settings.load_draft_target_font().unwrap(), font);
        }
        for scale in ["normal", "large", "larger"] {
            settings.save_font_scale(scale).unwrap();
            assert_eq!(settings.load_font_scale().unwrap(), scale);
        }
        for width in [180, 333, 420] {
            settings.save_master_width(width).unwrap();
            assert_eq!(settings.load_master_width().unwrap(), width);
        }
        for (panel, bounds) in [("outline", [176, 384]), ("properties", [224, 448])] {
            for width in bounds {
                settings.save_authoring_width(panel, width).unwrap();
                let (outline, properties) = settings.load_authoring_widths().unwrap();
                assert_eq!(
                    if panel == "outline" {
                        outline
                    } else {
                        properties
                    },
                    Some(width)
                );
            }
        }
        assert_eq!(
            settings.load_authoring_widths().unwrap(),
            (Some(384), Some(448))
        );
        let before = fs::read(path).unwrap();
        for invalid in ["", "네온", "huge"] {
            assert!(settings.save_theme(invalid).is_err());
            assert!(settings.save_font_scale(invalid).is_err());
            assert!(settings.save_draft_target_font(invalid).is_err());
        }
        for width in [179, 421] {
            assert!(settings.save_master_width(width).is_err());
        }
        for (panel, width) in [
            ("outline", 175),
            ("outline", 385),
            ("properties", 223),
            ("properties", 449),
            ("dock", 240),
        ] {
            assert!(settings.save_authoring_width(panel, width).is_err());
        }
        for (method, args) in [
            ("set_font_scale", vec![Value::Null]),
            ("set_font_scale", vec![json!(150)]),
            ("set_master_width", vec![json!(true)]),
            ("set_master_width", vec![json!(240.5)]),
            ("set_authoring_width", vec![json!("outline"), json!(true)]),
            ("set_authoring_width", vec![json!("outline"), json!(240.5)]),
            ("set_authoring_width", vec![Value::Null, json!(240)]),
        ] {
            assert!(
                crate::native_methods::validate_host_call(method, &args).is_err(),
                "{method}: {args:?}"
            );
        }
        for (width, height) in [(759, 600), (760, 599)] {
            assert!(
                settings
                    .save_window_geometry(&WindowGeometry {
                        x: 0,
                        y: 0,
                        width,
                        height,
                        maximized: false
                    })
                    .is_err()
            );
        }
        assert_eq!(
            fs::read(path).unwrap(),
            before,
            "rejected settings must not write"
        );
        let saved: Value = serde_json::from_slice(&before).unwrap();
        assert_eq!(saved["unknown"], 42);
        assert_eq!(saved["theme"], "dark");
        assert_eq!(saved["draft_target_font"], "malgun");
        assert_eq!(saved["font_scale"], "larger");
        assert_eq!(saved["master_width"], 420);
    }

    fn assert_corrupt_settings(settings: &ShellSettings, path: &Path) {
        for value in [
            json!("invalid"),
            Value::Null,
            json!(true),
            json!(240.5),
            json!([]),
            json!({}),
        ] {
            fs::write(path, serde_json::to_vec(&json!({"theme":value,"draft_target_font":value,"font_scale":value,"master_width":value,"authoring_widths":value,"window_geometry":value})).unwrap()).unwrap();
            assert_eq!(settings.load_theme().unwrap(), "system");
            assert_eq!(settings.load_draft_target_font().unwrap(), "gulimche");
            assert_eq!(settings.load_font_scale().unwrap(), "normal");
            assert_eq!(settings.load_master_width().unwrap(), 240);
            assert_eq!(settings.load_authoring_widths().unwrap(), (None, None));
            assert_eq!(settings.load_window_geometry().unwrap(), None);
        }
        fs::write(
            path,
            br#"{"authoring_widths":{"outline":9999,"properties":true},"rail_collapsed":"yes"}"#,
        )
        .unwrap();
        assert_eq!(settings.load_authoring_widths().unwrap(), (None, None));
        for (key, value) in [
            ("x", json!(true)),
            ("y", json!("top")),
            ("width", json!(759)),
            ("height", json!(599)),
            ("maximized", json!(1)),
        ] {
            let mut geometry = json!({"x":-900,"y":40,"width":1180,"height":820,"maximized":true});
            geometry[key] = value;
            fs::write(
                path,
                serde_json::to_vec(&json!({"window_geometry":geometry})).unwrap(),
            )
            .unwrap();
            assert_eq!(settings.load_window_geometry().unwrap(), None, "{key}");
        }
        let geometry = WindowGeometry {
            x: -900,
            y: 40,
            width: 1180,
            height: 820,
            maximized: true,
        };
        settings.save_window_geometry(&geometry).unwrap();
        assert_eq!(settings.load_window_geometry().unwrap(), Some(geometry));
    }
}
