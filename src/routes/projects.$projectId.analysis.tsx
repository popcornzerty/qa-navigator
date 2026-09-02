import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";
import { analysisApi, projectsApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { AnalysisPipeline, AnalysisStepList } from "../components/qa/analysis-pipeline";
import { Button } from "../components/ui/button";
import { Panel, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";

export const Route = createFileRoute("/projects/$projectId/analysis")({
  head: () => ({
    meta: [
      { title: "Repository analysis — AI QA Agent" },
      {
        name: "description",
        content:
          "Follow the analysis pipeline from repository retrieval to generated Gherkin scenarios.",
      },
      { property: "og:title", content: "Repository analysis — AI QA Agent" },
      {
        property: "og:description",
        content: "Pipeline states: repository, architecture, routes, components, APIs, features, stories, Gherkin.",
      },
    ],
  }),
  component: AnalysisPage,
});

function AnalysisPage() {
  const { projectId } = Route.useParams();
  const queryClient = useQueryClient();

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId),
  });
  const job = useQuery({
    queryKey: ["analysis", projectId],
    queryFn: () => analysisApi.current(projectId),
  });

  const restart = useMutation({
    mutationFn: () => analysisApi.start(projectId),
    onSuccess: (next) => queryClient.setQueryData(["analysis", projectId], next),
  });

  const running = job.data?.status === "running";

  /* Async job states: the UI polls the job until it settles. */
  useEffect(() => {
    if (!job.data || !running) return;
    const timer = setTimeout(async () => {
      const next = await analysisApi.poll(projectId, job.data!.jobId);
      queryClient.setQueryData(["analysis", projectId], next);
    }, 1600);
    return () => clearTimeout(timer);
  }, [job.data, running, projectId, queryClient]);

  return (
    <>
      <PageHeader
        title="Repository analysis"
        subtitle={project.data ? `${project.data.repository} · ${project.data.branch}` : "Loading…"}
        actions={
          <>
            {job.data ? <StatusBadge status={job.data.status} /> : null}
            <Button variant="primary" disabled={restart.isPending} onClick={() => restart.mutate()}>
              {running ? "Restart analysis" : "Analyze Repository"}
            </Button>
          </>
        }
      />

      <Panel>
        <PanelHeader title="Pipeline" meta={job.data?.jobId} />
        {job.data ? (
          <AnalysisPipeline job={job.data} />
        ) : (
          <p className="p-4 text-sm text-muted-foreground">Loading pipeline…</p>
        )}
      </Panel>

      <Panel className="max-w-2xl">
        <PanelHeader title="Steps" meta="live status" />
        {job.data ? <AnalysisStepList job={job.data} /> : null}
      </Panel>
    </>
  );
}
