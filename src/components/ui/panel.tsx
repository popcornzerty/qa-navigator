import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <section className={cn("rounded-xl bg-panel ring-1 ring-line overflow-hidden", className)}>
      {children}
    </section>
  );
}

export function PanelHeader({
  title,
  meta,
  actions,
}: {
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
      <div className="flex items-center gap-2">
        <h2 className="font-display text-sm font-semibold">{title}</h2>
        {meta ? <span className="font-mono text-[11px] text-dim">{meta}</span> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PanelBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("p-4", className)}>{children}</div>;
}
