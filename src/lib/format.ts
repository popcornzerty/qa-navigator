/** Presentation helpers — pure functions, no React, no business rules. */

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(value: string): string {
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function formatDuration(ms: number): string {
  if (!ms) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function formatConfidence(value: number): string {
  return value.toFixed(2);
}

export function percent(value: number): string {
  return `${value.toFixed(1)}%`;
}

const LABELS: Record<string, string> = {
  draft: "Draft",
  needs_review: "Needs Review",
  approved: "Approved",
  created: "Created",
  out_of_sync: "Out of Sync",
  valid: "Valid",
  invalid: "Invalid",
  automated: "Automated",
  passed: "Passed",
  failed: "Failed",
  skipped: "Skipped",
  not_run: "Not run",
  ready: "Ready",
  analyzing: "Analyzing",
  never_analyzed: "Never analyzed",
  error: "Error",
  detected: "Detected",
  confirmed: "Confirmed",
  ignored: "Ignored",
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  queued: "Queued",
  connected: "Connected",
  not_connected: "Not connected",
  disconnected: "Disconnected",
};

export function label(status: string): string {
  return LABELS[status] ?? status;
}
