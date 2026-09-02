import { Check, X } from "lucide-react";
import type { AnalysisJob } from "../../types/models";
import { cn } from "../../lib/utils";

function StepIcon({ status }: { status: AnalysisJob["steps"][number]["status"] }) {
  if (status === "completed")
    return (
      <div className="grid size-7 place-items-center rounded-full bg-pass/15 ring-1 ring-pass/40">
        <Check className="size-3.5 text-pass" />
      </div>
    );
  if (status === "failed")
    return (
      <div className="grid size-7 place-items-center rounded-full bg-fail/15 ring-1 ring-fail/40">
        <X className="size-3.5 text-fail" />
      </div>
    );
  if (status === "running")
    return (
      <div className="grid size-7 place-items-center rounded-full bg-primary/15 ring-1 ring-primary/50">
        <span className="size-2.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  return (
    <div className="grid size-7 place-items-center rounded-full ring-1 ring-line">
      <span className="size-2 rounded-full bg-dim" />
    </div>
  );
}

export function AnalysisPipeline({ job }: { job: AnalysisJob }) {
  return (
    <div>
      <div className="grid grid-cols-4 gap-2 p-4 sm:grid-cols-8">
        {job.steps.map((step) => (
          <div key={step.key} className="flex flex-col items-center gap-2">
            <StepIcon status={step.status} />
            <span
              className={cn(
                "text-center text-[11px]",
                step.status === "running"
                  ? "text-primary"
                  : step.status === "pending"
                    ? "text-dim"
                    : "text-muted-foreground",
              )}
            >
              {step.label}
            </span>
          </div>
        ))}
      </div>
      <div className="px-4 pb-4">
        <div className="flex items-center justify-between text-xs">
          <span className="font-mono text-[11px] text-muted-foreground">
            {job.jobId} · {job.status}
          </span>
          <span className="font-mono text-[11px] text-primary">{job.progress}%</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
          <div
            className="h-full bg-primary transition-[width] duration-500"
            style={{ width: `${job.progress}%` }}
          />
        </div>
      </div>
    </div>
  );
}

export function AnalysisStepList({ job }: { job: AnalysisJob }) {
  return (
    <ul className="divide-y divide-line">
      {job.steps.map((step) => (
        <li key={step.key} className="flex items-center gap-3 px-4 py-3">
          <StepIcon status={step.status} />
          <div className="min-w-0">
            <p className="text-sm">{step.label}</p>
            <p className="font-mono text-[11px] text-dim">{step.detail ?? step.status}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}
