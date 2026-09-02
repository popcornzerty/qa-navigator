import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { analysisApi, projectsApi, storiesApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { formatConfidence, formatDate, percent } from "../lib/format";

export const Route = createFileRoute("/projects/$projectId/")({
  head: () => ({
    meta: [
      { title: "Project overview — AI QA Agent" },
      {
        name: "description",
        content: "Repository, branch, last analysis and QA volumes for a single project.",
      },
      { property: "og:title", content: "Project overview — AI QA Agent" },
      {
        property: "og:description",
        content: "Features, user stories, Gherkin and Playwright volumes for one repository.",
      },
    ],
  }),
  component: ProjectDetail,
});

function ProjectDetail() {
  const { projectId } = Route.useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId),
  });
  const stats = useQuery({
    queryKey: ["project-stats", projectId],
    queryFn: () => projectsApi.stats(projectId),
  });
  const features = useQuery({
    queryKey: ["features", projectId],
    queryFn: () => analysisApi.features(projectId),
  });
  const stories = useQuery({
    queryKey: ["stories", projectId],
    queryFn: () => storiesApi.list({ projectId }),
  });

  const analyze = useMutation({
    mutationFn: () => analysisApi.start(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analysis", projectId] });
      navigate({ to: "/projects/$projectId/analysis", params: { projectId } });
    },
  });

  return (
    <>
      <PageHeader
        title={project.data?.name ?? "Project"}
        subtitle={
          project.data
            ? `${project.data.repository} · ${project.data.branch} · last analysis ${formatDate(project.data.lastAnalysis)}`
            : "Loading…"
        }
        actions={
          <>
            {project.data ? <StatusBadge status={project.data.status} /> : null}
            <Button variant="primary" disabled={analyze.isPending} onClick={() => analyze.mutate()}>
              Analyze Repository
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricCard label="Features" value={String(stats.data?.features ?? "—")} />
        <MetricCard label="User stories" value={String(stats.data?.userStories ?? "—")} />
        <MetricCard label="Gherkin" value={String(stats.data?.gherkinScenarios ?? "—")} />
        <MetricCard label="Playwright" value={String(stats.data?.playwrightTests ?? "—")} />
        <MetricCard
          label="Coverage"
          value={stats.data ? percent(stats.data.coverage) : "—"}
          progress={stats.data?.coverage ?? 0}
          tone="pass"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            title="Detected features"
            meta={`${features.data?.length ?? 0} features`}
            actions={
              <Link to="/projects/$projectId/analysis" params={{ projectId }}>
                <Button variant="outline" size="sm">
                  Analysis workflow
                </Button>
              </Link>
            }
          />
          <ul className="divide-y divide-line">
            {(features.data ?? []).map((feature) => (
              <li key={feature.id} className="px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">{feature.name}</p>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {formatConfidence(feature.confidence)}
                    </span>
                    <StatusBadge status={feature.status} />
                  </div>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{feature.description}</p>
                <details className="mt-1.5">
                  <summary className="cursor-pointer font-mono text-[10px] tracking-wider text-dim uppercase">
                    source files
                  </summary>
                  <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-dim">
                    {feature.sourceFiles.map((file) => (
                      <li key={file}>{file}</li>
                    ))}
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel>
          <PanelHeader
            title="Latest user stories"
            meta={`${stories.data?.length ?? 0} stories`}
            actions={
              <Link to="/backlog">
                <Button variant="outline" size="sm">
                  Backlog
                </Button>
              </Link>
            }
          />
          <PanelBody className="p-0">
            <ul className="divide-y divide-line">
              {(stories.data ?? []).slice(0, 6).map((story) => (
                <li key={story.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <Link
                      to="/backlog/$storyId"
                      params={{ storyId: story.id }}
                      className="font-mono text-[11px] text-primary hover:underline"
                    >
                      {story.id}
                    </Link>
                    <p className="truncate text-sm">{story.title}</p>
                  </div>
                  <StatusBadge status={story.status} />
                </li>
              ))}
            </ul>
          </PanelBody>
        </Panel>
      </div>
    </>
  );
}
