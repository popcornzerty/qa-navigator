import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { analysisApi, projectsApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { Panel, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { formatDate } from "../lib/format";
import { useCurrentProject } from "../lib/current-project";

export const Route = createFileRoute("/projects/")({
  head: () => ({
    meta: [
      { title: "Projects — AI QA Agent" },
      {
        name: "description",
        content: "All connected repositories with branch, Jira status, last analysis and QA volumes.",
      },
      { property: "og:title", content: "Projects — AI QA Agent" },
      {
        property: "og:description",
        content: "Repositories under QA with branch, Jira status and last analysis.",
      },
    ],
  }),
  component: ProjectsPage,
});

function ProjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setProjectId } = useCurrentProject();
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });

  const analyze = useMutation({
    mutationFn: (projectId: string) => analysisApi.start(projectId),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["analysis"] });
      setProjectId(job.projectId);
      navigate({ to: "/projects/$projectId/analysis", params: { projectId: job.projectId } });
    },
    onError: () => toast.error("Could not start the analysis"),
  });

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Repositories under functional QA"
        actions={
          <Link to="/projects/new">
            <Button variant="primary">+ New Project</Button>
          </Link>
        }
      />

      <Panel>
        <PanelHeader title="All projects" meta={`${projects.length} total`} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                <th className="px-4 py-2 font-medium">Project</th>
                <th className="px-3 py-2 font-medium">Repository</th>
                <th className="px-3 py-2 font-medium">Branch</th>
                <th className="px-3 py-2 font-medium">Jira</th>
                <th className="px-3 py-2 font-medium">Last analysis</th>
                <th className="px-3 py-2 font-medium">Stories</th>
                <th className="px-3 py-2 font-medium">Tests</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {projects.map((project) => (
                <tr key={project.id} className="transition-colors hover:bg-panel2">
                  <td className="px-4 py-3 font-medium">{project.name}</td>
                  <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                    {project.repository}
                  </td>
                  <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                    {project.branch}
                  </td>
                  <td className="px-3 py-3">
                    {project.jiraProject ? (
                      <span className="font-mono text-[11px] text-primary">{project.jiraProject}</span>
                    ) : (
                      <StatusBadge status={project.jiraConnection} />
                    )}
                  </td>
                  <td className="px-3 py-3 text-muted-foreground">
                    {formatDate(project.lastAnalysis)}
                  </td>
                  <td className="px-3 py-3 font-mono text-muted-foreground">{project.storyCount}</td>
                  <td className="px-3 py-3 font-mono text-muted-foreground">
                    {project.automatedTestCount}
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={project.status} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Link
                        to="/projects/$projectId"
                        params={{ projectId: project.id }}
                        onClick={() => setProjectId(project.id)}
                      >
                        <Button variant="outline" size="sm">
                          Open
                        </Button>
                      </Link>
                      <Button
                        variant="subtle"
                        size="sm"
                        disabled={analyze.isPending}
                        onClick={() => analyze.mutate(project.id)}
                      >
                        Analyze
                      </Button>
                      <Link to="/settings" onClick={() => setProjectId(project.id)}>
                        <Button variant="ghost" size="sm">
                          Settings
                        </Button>
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
