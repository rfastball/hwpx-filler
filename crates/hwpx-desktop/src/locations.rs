//! App-home and volatile tutorial-workspace path selection.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

pub const HOME_ENV_VAR: &str = "HWPXFILLER_HOME";
pub const DEFAULT_HOME_NAME: &str = ".hwpxfiller";

#[derive(Clone, Debug)]
pub struct Locations {
    home: PathBuf,
    active_workspace: Option<PathBuf>,
}
impl Locations {
    pub fn new(user_home: &Path, override_home: Option<OsString>) -> Self {
        let home = override_home
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| user_home.join(DEFAULT_HOME_NAME));
        Self {
            home,
            active_workspace: None,
        }
    }
    pub fn from_env() -> Result<Self, &'static str> {
        Self::from_lookup(|name| std::env::var_os(name))
    }
    fn from_lookup(mut lookup: impl FnMut(&str) -> Option<OsString>) -> Result<Self, &'static str> {
        let override_home = lookup(HOME_ENV_VAR).filter(|value| !value.is_empty());
        if let Some(home) = override_home {
            return Ok(Self {
                home: PathBuf::from(home),
                active_workspace: None,
            });
        }
        let user_home = lookup("USERPROFILE")
            .map(PathBuf::from)
            .or_else(|| {
                let mut drive = lookup("HOMEDRIVE")?;
                drive.push(lookup("HOMEPATH")?);
                Some(PathBuf::from(drive))
            })
            .ok_or("user home unavailable")?;
        Ok(Self::new(&user_home, None))
    }
    pub fn home(&self) -> &Path {
        &self.home
    }
    pub fn activate_workspace(&mut self, home: Option<PathBuf>) {
        self.active_workspace = home;
    }
    pub fn workspace_home(&self) -> &Path {
        self.active_workspace.as_deref().unwrap_or(&self.home)
    }
    pub fn tutorial_workspace_root(&self) -> PathBuf {
        self.home.join("tutorial_workspace")
    }
    pub fn jobs(&self) -> PathBuf {
        self.workspace_home().join("jobs")
    }
    pub fn templates(&self) -> PathBuf {
        self.workspace_home().join("templates")
    }
    pub fn datasets(&self) -> PathBuf {
        self.workspace_home().join("datasets")
    }
    pub fn presets(&self) -> PathBuf {
        self.workspace_home().join("presets")
    }
    pub fn template_authority(&self) -> PathBuf {
        self.workspace_home().join("template_authority")
    }
    pub fn example_data(&self) -> PathBuf {
        self.workspace_home().join("example_data")
    }
    pub fn authoring(&self) -> PathBuf {
        self.workspace_home().join("authoring")
    }
    pub fn global_settings(&self) -> PathBuf {
        self.home.join("settings.json")
    }
    pub fn workspace_settings(&self) -> PathBuf {
        self.workspace_home().join("settings.json")
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::Locations;
    use std::ffi::OsString;
    use std::path::PathBuf;

    #[test]
    fn environment_root_precedence_and_missing_home_are_explicit() {
        let explicit = Locations::from_lookup(|name| {
            assert_eq!(name, super::HOME_ENV_VAR);
            Some("D:/지정한 홈".into())
        })
        .unwrap();
        assert_eq!(explicit.home(), PathBuf::from("D:/지정한 홈"));
        for override_home in [None, Some(OsString::new())] {
            let selected = Locations::from_lookup(|name| match name {
                super::HOME_ENV_VAR => override_home.clone(),
                "USERPROFILE" => Some("C:/Users/사용자".into()),
                _ => panic!("profile must win over drive/path"),
            })
            .unwrap();
            assert_eq!(
                selected.home(),
                PathBuf::from("C:/Users/사용자/.hwpxfiller")
            );
        }
        let selected = Locations::from_lookup(|name| match name {
            "HOMEDRIVE" => Some("D:".into()),
            "HOMEPATH" => Some("/Users/대체".into()),
            _ => None,
        })
        .unwrap();
        assert_eq!(selected.home(), PathBuf::from("D:/Users/대체/.hwpxfiller"));
        for available in [None, Some("HOMEDRIVE"), Some("HOMEPATH")] {
            assert_eq!(
                Locations::from_lookup(|name| (available == Some(name)).then(|| "unused".into()))
                    .unwrap_err(),
                "user home unavailable"
            );
        }
    }

    #[test]
    fn practice_workspace_does_not_redirect_global_shell_state() {
        let user = PathBuf::from("C:/Users/test");
        for override_home in [None, Some(OsString::new())] {
            assert_eq!(
                Locations::new(&user, override_home).jobs(),
                user.join(".hwpxfiller/jobs")
            );
            assert_eq!(
                Locations::new(&user, None).datasets(),
                user.join(".hwpxfiller/datasets")
            );
        }
        let mut locations = Locations::new(&user, Some(OsString::from("C:/isolated-app")));
        assert_workspace_paths(&locations, "C:/isolated-app");
        assert_eq!(locations.jobs(), PathBuf::from("C:/isolated-app/jobs"));
        assert_eq!(
            locations.templates(),
            PathBuf::from("C:/isolated-app/templates")
        );
        assert_eq!(
            locations.datasets(),
            PathBuf::from("C:/isolated-app/datasets")
        );
        assert_eq!(
            locations.global_settings(),
            PathBuf::from("C:/isolated-app/settings.json")
        );
        locations.activate_workspace(Some(PathBuf::from("C:/practice/lesson")));
        assert_workspace_paths(&locations, "C:/practice/lesson");
        assert_eq!(locations.jobs(), PathBuf::from("C:/practice/lesson/jobs"));
        assert_eq!(
            locations.datasets(),
            PathBuf::from("C:/practice/lesson/datasets")
        );
        assert_eq!(
            locations.workspace_settings(),
            PathBuf::from("C:/practice/lesson/settings.json")
        );
        assert_eq!(
            locations.templates(),
            PathBuf::from("C:/practice/lesson/templates")
        );
        assert_eq!(
            locations.tutorial_workspace_root(),
            PathBuf::from("C:/isolated-app/tutorial_workspace")
        );
        assert_eq!(
            locations.global_settings(),
            PathBuf::from("C:/isolated-app/settings.json")
        );
        locations.activate_workspace(None);
        assert_workspace_paths(&locations, "C:/isolated-app");
        assert_eq!(locations.workspace_settings(), locations.global_settings());
    }

    fn assert_workspace_paths(locations: &Locations, root: &str) {
        for (actual, suffix) in [
            (locations.jobs(), "jobs"),
            (locations.templates(), "templates"),
            (locations.datasets(), "datasets"),
            (locations.presets(), "presets"),
            (locations.template_authority(), "template_authority"),
            (locations.example_data(), "example_data"),
            (locations.authoring(), "authoring"),
            (locations.workspace_settings(), "settings.json"),
        ] {
            assert_eq!(actual, PathBuf::from(root).join(suffix));
        }
    }
}
