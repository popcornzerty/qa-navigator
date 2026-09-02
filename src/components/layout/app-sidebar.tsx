import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { coverageApi } from "../../api";
import { useCurrentProject } from "../../lib/current-project";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/projects", label: "Projects" },
  { to: "/backlog", label: "Backlog" },
  { to: "/gherkin", label: "Gherkin" },
  { to: "/automation", label: "Automation" },
  { to: "/coverage", label: "Coverage" },
  { to: "/settings", label: "Settings" },
] as const;

export function AppSidebar() {
  const { projectId } = useCurrentProject();
  const { data } = useQuery({
    queryKey: ["coverage", projectId],
    queryFn: () => coverageApi.get(projectId ?? undefined),
  });
  const coverage = data?.coverage ?? 0;

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
          <Link
            key={item.to}
            to={item.to}
            activeOptions={{ exact: item.to === "/" }}
            className="flex items-center gap-2.5 rounded-md px-3 py-2 text-muted-foreground hover:text-foreground"
            activeProps={{ className: "bg-panel2 text-foreground ring-1 ring-line" }}
          >
            {({ isActive }) => (
              <>
                <span
                  className={`size-1.5 shrink-0 rounded-full ${isActive ? "bg-primary" : "bg-line"}`}
                />
                {item.label}
              </>
            )}
          </Link>
        ))}
      </nav>

      <div className="mt-auto p-3">
        <div className="rounded-md bg-panel2 p-3 ring-1 ring-line">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10px] tracking-wider text-dim">AUTOMATION</span>
            <span className="font-mono text-[11px] text-pass">{coverage.toFixed(1)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-pass" style={{ width: `${coverage}%` }} />
          </div>
        </div>
      </div>
    </aside>
  );
}
