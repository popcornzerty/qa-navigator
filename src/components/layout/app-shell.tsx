import { useEffect, useState, type ReactNode } from "react";
import { AppSidebar } from "./app-sidebar";
import { TopBar } from "./top-bar";

export function AppShell({ children }: { children: ReactNode }) {
  // The app is server-rendered, so buttons exist in the HTML before React attaches its
  // handlers. An automated click landing in that window does nothing and fails silently.
  // This marker appears only after hydration, giving tests something to wait on.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 space-y-5 p-4 sm:p-5">{children}</main>
      </div>
      {hydrated ? <span data-testid="app-ready" hidden /> : null}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {/* Every page exposes its title under one stable anchor, so a generated test can
            assert which screen it landed on without depending on wording or markup. */}
        <h1 data-testid="page-title" className="font-display text-2xl font-semibold tracking-tight">
          {title}
        </h1>
        {subtitle ? (
          <p data-testid="page-subtitle" className="mt-1 text-sm text-muted-foreground">
            {subtitle}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
