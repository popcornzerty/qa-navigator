import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { coverageApi } from "../../api";
import { useCurrentProject } from "../../lib/current-project";
import { percent } from "../../lib/format";

// Test anchors are written out in full rather than derived from the label: static
// analysis reads them literally, and a template-built value would be invisible to the
// generator that needs them to reach a screen.
const NAV = [
  { to: "/", label: "Dashboard", testId: "nav-dashboard" },
  { to: "/projects", label: "Projects", testId: "nav-projects" },
  { to: "/automation", label: "Automation", testId: "nav-automation" },
  { to: "/runs", label: "Executions", testId: "nav-runs" },
  { to: "/coverage", label: "Coverage", testId: "nav-coverage" },
] as const;

// Generation proposes; it does not establish anything. It sat at the top of the sidebar
// while being the weakest part of the tool, which read as a promise the output does not
// keep. It stays reachable, below what real executions prove.
const DRAFTS = [
  { to: "/backlog", label: "Backlog", testId: "nav-backlog" },
  { to: "/gherkin", label: "Gherkin", testId: "nav-gherkin" },
] as const;

const SETTINGS = { to: "/settings", label: "Settings", testId: "nav-settings" } as const;

export function AppSidebar() {
  const { projectId } = useCurrentProject();
  const { data } = useQuery({
    queryKey: ["coverage", projectId],
    queryFn: () => coverageApi.get(projectId ?? undefined),
  });
  const coverage = data?.coverage ?? null;

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-panel md:flex">
      <div className="flex items-center gap-2.5 px-4 py-4">
        <div className="grid size-7 place-items-center rounded-md bg-primary/15 ring-1 ring-primary/30">
          <span className="font-display text-sm font-bold text-primary">Q</span>
        </div>
        <div className="leading-tight">
          <p className="font-display text-sm font-semibold">AI QA Agent</p>
          <p className="font-mono text-[10px] tracking-wider text-dim">phase 1</p>
        </div>
      </div>

      <nav className="space-y-0.5 px-2 py-2 text-sm">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} label={item.label} testId={item.testId} />
        ))}

        <p className="px-3 pt-4 pb-1 font-mono text-[10px] tracking-wider text-dim uppercase">
          Proposals
        </p>
        {DRAFTS.map((item) => (
          <NavLink key={item.to} to={item.to} label={item.label} testId={item.testId} />
        ))}
        <p
          data-testid="drafts-caption"
          className="px-3 pt-1 pb-2 text-[11px] leading-snug text-dim"
        >
          Generated from the code. Nothing here counts until you approve it.
        </p>

        <NavLink to={SETTINGS.to} label={SETTINGS.label} testId={SETTINGS.testId} />
      </nav>

      <div className="mt-auto p-3">
        <div className="rounded-md bg-panel2 p-3 ring-1 ring-line">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10px] tracking-wider text-dim">COVERAGE</span>
            <span className="font-mono text-[11px] text-pass">{percent(coverage)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-pass" style={{ width: `${coverage ?? 0}%` }} />
          </div>
          {coverage === null ? (
            <p className="mt-2 text-[11px] leading-snug text-dim">
              No approved requirement to measure against.
            </p>
          ) : null}
        </div>
      </div>
    </aside>
  );
}

function NavLink({ to, label, testId }: { to: string; label: string; testId: string }) {
  return (
    <Link
      to={to}
      data-testid={testId}
      activeOptions={{ exact: to === "/" }}
      className="flex items-center gap-2.5 rounded-md px-3 py-2 text-muted-foreground hover:text-foreground"
      activeProps={{ className: "bg-panel2 text-foreground ring-1 ring-line" }}
    >
      {({ isActive }) => (
        <>
          <span
            className={`size-1.5 shrink-0 rounded-full ${isActive ? "bg-primary" : "bg-line"}`}
          />
          {label}
        </>
      )}
    </Link>
  );
}
