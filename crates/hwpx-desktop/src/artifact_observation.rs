//! Read recorded output from disk, bind its digest, and reparse those exact bytes.

use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::candidate_revision::blob_digest;
use std::{fs, io, path::Path};

pub enum ArtifactObservation {
    Observed(Vec<u8>),
    Refused { code: &'static str, detail: String },
}

pub fn observe_delivered_artifact(
    path: &Path,
    recorded_digest: &str,
    is_txt: bool,
) -> io::Result<ArtifactObservation> {
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error)
            if matches!(
                error.kind(),
                io::ErrorKind::NotFound
                    | io::ErrorKind::NotADirectory
                    | io::ErrorKind::IsADirectory
            ) =>
        {
            return Ok(ArtifactObservation::Refused {
                code: "ARTIFACT_FILE_MISSING",
                detail: format!("안착 기록의 경로에 파일이 없다: {}", path.display()),
            });
        }
        Err(error) => return Err(error),
    };
    let observed = blob_digest(&bytes);
    if observed != recorded_digest {
        return Ok(ArtifactObservation::Refused {
            code: "ARTIFACT_DIGEST_MISMATCH",
            detail: format!(
                "{} 의 내용이 안착 기록과 다르다: 기대 {recorded_digest}, 실측 {observed}",
                path.display()
            ),
        });
    }
    let reparsed = if is_txt {
        std::str::from_utf8(&bytes)
            .map(|_| ())
            .map_err(|error| error.to_string())
    } else {
        HwpxPackage::from_bytes(&bytes, PackageLimits::default())
            .map(|_| ())
            .map_err(|error| format!("PackageError: {error}"))
    };
    if let Err(detail) = reparsed {
        return Ok(ArtifactObservation::Refused {
            code: "ARTIFACT_REPARSE_FAILED",
            detail: format!(
                "{} 를 {} 로 다시 열지 못했다: {detail}",
                path.display(),
                if is_txt { "TXT" } else { "HWPX" }
            ),
        });
    }
    Ok(ArtifactObservation::Observed(bytes))
}
