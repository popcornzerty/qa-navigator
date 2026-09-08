import { cn } from "../../lib/utils";

export function MetricCard({
  label,
  value,
  hint,
  progress,
  tone = "default",
  testId,
}: {
  label: string;
  value: string;
  hint?: string;
  progress?: number;
  tone?: "default" | "pass" | "fail";
  testId?: string;
}) {
  // Callers pass an explicit anchor: a value built from the label would be invisible to
  // static analysis, and the generator only accepts selectors it can actually find in the
  // source. The derived fallback keeps a card addressable when no anchor is given.
  const anchor =
    testId ??
    `metric-${label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")}`;

  return (
    <div data-testid={anchor} className="rounded-xl bg-panel p-4 ring-1 ring-line">
      <p className="font-mono text-[10px] tracking-wider text-dim uppercase">{label}</p>
      <p
        data-testid={`${anchor}-value`}
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
