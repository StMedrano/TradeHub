export function scannerProgress(status) {
  const eligible = Number(status?.symbols_prefiltered || 0);
  const target = Number(
    status?.deep_scan_target === null || status?.deep_scan_target === undefined
      ? eligible
      : status.deep_scan_target
  );
  const scanned = Number(status?.symbols_deep_scanned || 0);
  if (target <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((scanned / target) * 100)));
}

export function scannerStatusTone(status) {
  if (status === "complete") return "green";
  if (status === "failed") return "red";
  if (status === "partial") return "amber";
  if (["queued", "discovering", "deep_scanning"].includes(status)) return "blue";
  return "gray";
}

export function opportunityAgeLabel(value, now = new Date()) {
  if (!value) return "—";
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime()) || Number.isNaN(now.getTime())) return "—";

  const seconds = Math.max(0, Math.floor((now.getTime() - timestamp.getTime()) / 1000));
  if (seconds < 60) return "<1m";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export function scannerIsActive(status) {
  return ["queued", "discovering", "deep_scanning"].includes(status);
}
