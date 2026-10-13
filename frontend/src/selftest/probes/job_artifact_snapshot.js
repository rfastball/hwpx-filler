/** Distinct backend artifact states for the existing job-result selftest. */
export function jobArtifactSnapshot(base, status, detail = "") {
  return {
    ...JSON.parse(JSON.stringify(base)),
    artifact_view: { open: true, ordinal: 0, filename: "공고서-001.hwpx", status, detail },
  };
}
