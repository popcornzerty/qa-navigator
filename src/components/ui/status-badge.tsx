import { cn } from "../../lib/utils";
import { label } from "../../lib/format";

type Tone = "pass" | "fail" | "skip" | "accent" | "neutral";

const TONE_MAP: Record<string, Tone> = {
  approved: "pass",
  created: "accent",
  valid: "pass",
  automated: "pass",
  passed: "pass",
  ready: "pass",
  connected: "pass",
  confirmed: "pass",
  completed: "pass",
  needs_review: "skip",
  analyzing: "accent",
  running: "accent",
  queued: "accent",
  detected: "skip",
  skipped: "skip",
  out_of_sync: "fail",
  failed: "fail",
  invalid: "fail",
  error: "fail",
  draft: "neutral",
  pending: "neutral",
  not_run: "neutral",
  never_analyzed: "neutral",
  not_connected: "neutral",
  disconnected: "neutral",
  ignored: "neutral",
};

const TONE_CLASS: Record<Tone, string> = {
  pass: "bg-pass/10 text-pass ring-pass/25",
  fail: "bg-fail/10 text-fail ring-fail/25",
  skip: "bg-skip/10 text-skip ring-skip/25",
  accent: "bg-primary/10 text-primary ring-primary/25",
  neutral: "bg-panel2 text-muted-foreground ring-line",
};

const DOT_CLASS: Record<Tone, string> = {
  pass: "bg-pass",
  fail: "bg-fail",
  skip: "bg-skip",
  accent: "bg-primary",
  neutral: "bg-dim",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = TONE_MAP[status] ?? "neutral";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium ring-1 whitespace-nowrap",
        TONE_CLASS[tone],
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", DOT_CLASS[tone])} />
      {label(status)}
    </span>
  );
}

export function statusTone(status: string): Tone {
  return TONE_MAP[status] ?? "neutral";
}
