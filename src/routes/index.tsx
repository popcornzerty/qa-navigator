import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { analysisApi, dashboardApi, storiesApi } from "../api";
import { AnalysisPipeline } from "../components/qa/analysis-pipeline";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { formatConfidence, percent, relativeTime } from "../lib/format";
import { useCurrentProject } from "../lib/current-project";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "QA Dashboard — AI QA Agent" },
      {
        name: "description",
        content:
          "Live QA metrics: projects, user stories, Gherkin scenarios, automated tests and automation coverage.",
      },
      { property: "og:title", content: "QA Dashboard — AI QA Agent" },
      {
        property: "og:description",
        content: "Projects, user stories, Gherkin scenarios and automation coverage at a glance.",
      },
    ],
  }),
  component: Dashboard,
});

const DOT: Record<string, string> = {
  success: "bg-pass",
  info: "bg-primary",
  warning: "bg-skip",
  error: "bg-fail",
};

function Dashboard() {
  const { projectId } = useCurrentProject();
  const summary = useQuery({
    queryKey: ["dashboard", projectId],
    queryFn: () => dashboardApi.summary(projectId ?? undefined),
  });
  const job = useQuery({
    queryKey: ["analysis", projectId],
    queryFn: () => analysisApi.current(projectId ?? "prj-atlas-store"),
  });
  const stories = useQuery({
    queryKey: ["stories", projectId],
    queryFn: () => storiesApi.list({ projectId: projectId ?? undefined }),
  });

  const data = summary.data;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Traceability wired end-to-end · repository to test result"
        actions={
          <Link to="/projects">
            <Button variant="primary">Analyze Repository</Button>
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricCard
          label="Projects"
          value={String(data?.projects ?? "—")}
          hint={`${data?.activeProjects ?? 0} active`}
        />
        <MetricCard
          label="User stories"
          value={String(data?.userStories ?? "—")}
          hint={`${data?.approvedStories ?? 0} approved`}
        />
        <MetricCard
          label="Gherkin"
          value={String(data?.gherkinScenarios ?? "—")}
          hint={`${data?.validGherkin ?? 0} valid`}
        />
        <MetricCard
          label="Tests"
          value={String(data?.automatedTests ?? "—")}
          hint={`${data?.failingTests ?? 0} failed`}
          tone={data && data.failingTests > 0 ? "fail" : "default"}
        />
        <MetricCard
          label="Coverage"
          value={data ? percent(data.coverage) : "—"}
          progress={data?.coverage ?? 0}
          tone="pass"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <PanelHeader
            title="Analysis Pipeline"
            meta={job.data ? `run ${job.data.jobId}` : "loading"}
            actions={
              <Link
                to="/projects/$projectId/analysis"
                params={{ projectId: projectId ?? "prj-atlas-store" }}
              >
                <Button variant="outline" size="sm">
                  Open workflow
                </Button>
              </Link>
            }
          />
          {job.data ? (
            <AnalysisPipeline job={job.data} />
          ) : (
            <p className="p-4 text-sm text-muted-foreground">Loading pipeline…</p>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Recent Activity" />
          <ul className="space-y-3 p-3 text-sm">
            {(data?.activity ?? []).map((event) => (
              <li key={event.id} className="flex gap-2.5">
                <span
                  className={`mt-1.5 size-1.5 shrink-0 rounded-full ${DOT[event.kind] ?? "bg-dim"}`}
                />
                <div>
                  <p className="text-foreground/90">{event.message}</p>
                  <p className="font-mono text-[11px] text-dim">{relativeTime(event.at)}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel>
        <PanelHeader
          title="Backlog"
          meta={`${stories.data?.length ?? 0} stories`}
          actions={
            <Link to="/backlog">
              <Button variant="outline" size="sm">
                Open backlog
              </Button>
            </Link>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                <th className="px-4 py-2 font-medium">Feature</th>
                <th className="px-3 py-2 font-medium">Story</th>
                <th className="px-3 py-2 font-medium">Conf</th>
                <th className="px-3 py-2 font-medium">Jira</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(stories.data ?? []).slice(0, 5).map((story) => (
                <tr key={story.id} className="transition-colors hover:bg-panel2">
                  <td className="px-4 py-3 font-medium">{story.featureName}</td>
                  <td className="px-3 py-3">
                    <Link
                      to="/backlog/$storyId"
                      params={{ storyId: story.id }}
                      className="font-mono text-[11px] text-primary hover:underline"
                    >
                      {story.id}
                    </Link>
                    <p className="text-foreground/80">{story.title}</p>
                  </td>
                  <td className="px-3 py-3 font-mono text-muted-foreground">
                    {formatConfidence(story.confidence)}
                  </td>
                  <td className="px-3 py-3 font-mono text-primary">{story.jiraKey ?? "—"}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={story.status} />
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
