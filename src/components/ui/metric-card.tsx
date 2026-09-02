import { cn } from "../../lib/utils";

export function MetricCard({
  label,
  value,
  hint,
  progress,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  progress?: number;
  tone?: "default" | "pass" | "fail";
}) {
  return (
    <div className="rounded-xl bg-panel p-4 ring-1 ring-line">
      <p className="font-mono text-[10px] tracking-wider text-dim uppercase">{label}</p>
      <p
        className={cn(
          "font-display mt-2 text-3xl font-semibold",
          tone === "pass" && "text-pass",
          tone === "fail" && "text-fail",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      {typeof progress === "number" ? (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
          <div
            className={cn("h-full rounded-full", tone === "fail" ? "bg-fail" : "bg-pass")}
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
