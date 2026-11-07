//! One pure decision for the global output folder and template-adjacent fallback.

use std::path::Path;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputFolderResolution {
    pub directory: String,
    pub source: &'static str,
    pub notice: &'static str,
}
impl OutputFolderResolution {
    pub fn resolved(&self) -> bool {
        !self.directory.is_empty()
    }
    pub fn source_label(&self) -> &'static str {
        match self.source {
            "remembered" => "설정한 저장 폴더",
            "template_default" => "기본값",
            _ => "",
        }
    }
}

pub fn resolve_output_folder(
    remembered_directory: &str,
    remembered_exists: bool,
    template_path: &str,
) -> OutputFolderResolution {
    let fallback = if template_path.is_empty() {
        String::new()
    } else {
        let value = Path::new(template_path)
            .parent()
            .unwrap_or(Path::new("."))
            .join("Results");
        if value.is_absolute() {
            value.to_string_lossy().into_owned()
        } else {
            String::new()
        }
    };
    let fallback_source = if fallback.is_empty() {
        ""
    } else {
        "template_default"
    };
    if !remembered_directory.is_empty()
        && remembered_exists
        && Path::new(remembered_directory).is_absolute()
    {
        return OutputFolderResolution {
            directory: remembered_directory.into(),
            source: "remembered",
            notice: "",
        };
    }
    let notice = if remembered_directory.is_empty() {
        ""
    } else if fallback.is_empty() {
        "설정한 저장 폴더를 찾을 수 없습니다. 설정에서 저장 폴더를 선택하세요."
    } else {
        "설정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다."
    };
    OutputFolderResolution {
        directory: fallback,
        source: fallback_source,
        notice,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn missing_global_folder_discloses_template_fallback() {
        let template = "C:/서고/공고서.hwpx";
        let fallback = Path::new("C:/서고")
            .join("Results")
            .to_string_lossy()
            .into_owned();
        for (remembered, exists, expected, source, label, notice) in [
            (
                "C:/chosen",
                true,
                "C:/chosen",
                "remembered",
                "설정한 저장 폴더",
                "",
            ),
            (
                "",
                false,
                fallback.as_str(),
                "template_default",
                "기본값",
                "",
            ),
            (
                "C:/gone",
                false,
                fallback.as_str(),
                "template_default",
                "기본값",
                "설정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다.",
            ),
            (
                "Results",
                true,
                fallback.as_str(),
                "template_default",
                "기본값",
                "설정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다.",
            ),
        ] {
            let result = resolve_output_folder(remembered, exists, template);
            assert_eq!(result.directory, expected);
            assert_eq!(result.source, source);
            assert_eq!(result.source_label(), label);
            assert_eq!(result.notice, notice);
            assert!(result.resolved());
        }
        for template in ["", "managed.hwpx", "서고/공고서.hwpx", "./공고서.hwpx"] {
            for remembered in ["", "C:/gone"] {
                let result = resolve_output_folder(remembered, false, template);
                assert!(!result.resolved());
                assert_eq!(result.directory, "");
                assert_eq!(result.source, "");
                assert_eq!(result.source_label(), "");
                assert_eq!(
                    result.notice,
                    if remembered.is_empty() {
                        ""
                    } else {
                        "설정한 저장 폴더를 찾을 수 없습니다. 설정에서 저장 폴더를 선택하세요."
                    }
                );
            }
        }
    }
}
