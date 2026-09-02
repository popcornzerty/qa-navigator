import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bell, Settings, User } from "lucide-react";
import { API_MODE, projectsApi } from "../../api";
import { useCurrentProject } from "../../lib/current-project";

export function TopBar() {
  const { projectId, setProjectId } = useCurrentProject();
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });
  const current = projects.find((p) => p.id === projectId) ?? projects[0];

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-panel/70 px-4 backdrop-blur-sm sm:px-5">
      <label className="sr-only" htmlFor="project-switcher">
        Current project
      </label>
      <div className="flex items-center gap-2.5 rounded-md bg-panel2 py-1.5 pr-2 pl-2.5 ring-1 ring-line focus-within:ring-primary/40">
        <span className="size-2 shrink-0 rounded-sm bg-primary" />
        <select
          id="project-switcher"
          className="max-w-[10rem] bg-transparent text-sm font-medium outline-none sm:max-w-none"
          value={current?.id ?? ""}
          onChange={(event) => setProjectId(event.target.value)}
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id} className="bg-panel2">
              {project.name}
            </option>
          ))}
        </select>
        <span className="font-mono text-[11px] text-dim">{current?.branch ?? "—"}</span>
      </div>

      <span className="hidden font-mono text-[11px] text-dim md:inline">
        workspace / atlas-qa
      </span>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          aria-label="Notifications"
          className="relative grid size-8 place-items-center rounded-md text-muted-foreground ring-1 ring-line hover:ring-primary/40"
        >
          <Bell className="size-4" />
          <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-skip" />
        </button>
        <Link
          to="/settings"
          aria-label="Settings"
          className="grid size-8 place-items-center rounded-md text-muted-foreground ring-1 ring-line hover:ring-primary/40"
        >
          <Settings className="size-4" />
        </Link>
        <span className="hidden px-1 font-mono text-[11px] text-dim sm:inline">
          API: {API_MODE.toUpperCase()}
        </span>
        <button
          type="button"
          aria-label="Profile"
          className="grid size-8 place-items-center rounded-full bg-panel2 text-primary ring-1 ring-line"
        >
          <User className="size-4" />
        </button>
      </div>
    </header>
  );
}
