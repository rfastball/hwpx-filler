//! ZIP names, local headers, and resource admission before any entry is decoded.

use super::{DirectoryEntry, PackageError, PackageLimits, budget, fmt_bytes, invalid, le16};
use std::io::{Read, Seek};
use zip::ZipArchive;

pub(super) fn check_metadata<R: Read + Seek>(
    blob: &[u8],
    original_directory_start: usize,
    zip: &mut ZipArchive<R>,
    names: &[DirectoryEntry],
    limits: PackageLimits,
) -> Result<(), PackageError> {
    let mut total = 0u64;
    let mut ranges = Vec::with_capacity(names.len());
    for (index, name) in names.iter().enumerate() {
        let file = zip
            .by_index_raw(index)
            .map_err(|e| invalid(e.to_string()))?;
        let header = usize::try_from(file.header_start())
            .map_err(|_| invalid("ZIP local offset overflow"))?;
        if blob.get(header..header.saturating_add(4)) != Some(b"PK\x03\x04".as_slice()) {
            return Err(invalid("missing ZIP local header"));
        }
        let local_name_len = le16(blob, header + 26)?;
        let local_extra_len = le16(blob, header + 28)?;
        let data_start = header
            .checked_add(30)
            .and_then(|n| n.checked_add(local_name_len))
            .and_then(|n| n.checked_add(local_extra_len))
            .ok_or_else(|| invalid("ZIP local offset overflow"))?;
        let local_raw = blob
            .get(header + 30..header + 30 + local_name_len)
            .ok_or_else(|| invalid("truncated ZIP local name"))?;
        let local_flags = le16(blob, header + 6)?;
        if decode_name(local_raw, local_flags & 0x0800 != 0)? != name.original_name {
            return Err(invalid("ZIP local and central names differ"));
        }
        let data_end = data_start
            .checked_add(
                usize::try_from(file.compressed_size())
                    .map_err(|_| invalid("ZIP compressed size overflow"))?,
            )
            .ok_or_else(|| invalid("ZIP compressed size overflow"))?;
        ranges.push((header, data_end));
        let size = file.size();
        budget("entry_bytes", size, limits.max_entry_bytes, || {
            format!(
                "엔트리 {} {} > {}",
                crate::structural_boundary::python_string_repr(&name.name),
                fmt_bytes(size),
                fmt_bytes(limits.max_entry_bytes)
            )
        })?;
        if size > limits.ratio_min_entry_bytes {
            let compressed = file.compressed_size().max(1);
            if (size as u128) > (compressed as u128) * (limits.max_compression_ratio as u128) {
                return Err(PackageError::Budget {
                    dimension: "compression_ratio",
                    observed: size.div_ceil(compressed),
                    limit: limits.max_compression_ratio,
                    detail: format!(
                        "엔트리 {} 압축률 {:.0}:1 > {}:1",
                        crate::structural_boundary::python_string_repr(&name.name),
                        size as f64 / compressed as f64,
                        limits.max_compression_ratio
                    ),
                });
            }
        }
        total = total
            .checked_add(size)
            .ok_or_else(|| invalid("ZIP size overflow"))?;
    }
    budget("total_bytes", total, limits.max_total_bytes, || {
        format!(
            "비압축 합계 {} > {}",
            fmt_bytes(total),
            fmt_bytes(limits.max_total_bytes)
        )
    })?;
    let central_start = original_directory_start;
    ranges.sort_unstable_by_key(|range| range.0);
    for (index, &(_, end)) in ranges.iter().enumerate() {
        let next = ranges.get(index + 1).map_or(central_start, |range| range.0);
        if end > next {
            return Err(invalid("overlapping ZIP entries"));
        }
    }
    Ok(())
}

const CP437_HIGH: &str = "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ";

pub(super) fn decode_name(raw: &[u8], utf8: bool) -> Result<String, PackageError> {
    if utf8 {
        return String::from_utf8(raw.to_vec()).map_err(|_| invalid("invalid UTF-8 ZIP name"));
    }
    let high: Vec<char> = CP437_HIGH.chars().collect();
    Ok(raw
        .iter()
        .map(|&byte| {
            if byte < 128 {
                char::from(byte)
            } else {
                high[usize::from(byte - 128)]
            }
        })
        .collect())
}

pub(super) fn validate_name(name: &str) -> Result<(), PackageError> {
    if name.is_empty()
        || name.contains('\0')
        || name.contains('\\')
        || name.starts_with('/')
        || name.chars().nth(1) == Some(':') && name.chars().next().is_some_and(char::is_alphabetic)
        || name.split('/').any(|part| part == "..")
    {
        return Err(invalid(format!("unsafe ZIP entry name {name:?}")));
    }
    Ok(())
}
