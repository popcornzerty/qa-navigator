import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { testsApi } from "../api";
import type { TestFilters } from "../api/tests";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { useCurrentProject } from "../lib/current-project";
import { formatDateTime, formatDuration } from "../lib/format";
import type { TestStatus } from "../types/models";

export const Route = createFileRoute("/automation/")({
  head: () => ({
    meta: [
      { title: "Automation — AI QA Agent" },
      {
        name: "description",
        content:
          "Playwright tests generated from Gherkin scenarios, with status and last execution.",
      },
      { property: "og:title", content: "Automation — AI QA Agent" },
      {
        property: "og:description",
        content: "Run, regenerate and inspect the Playwright suite covering your User Stories.",
      },
    ],
  }),
  component: AutomationPage,
});

const STATUS_FILTERS: (TestStatus | "all")[] = ["all", "passed", "failed", "skipped", "not_run"];
const chip = "rounded-md px-2.5 py-1 text-xs ring-1 transition-colors whitespace-nowrap capitalize";
const chipOn = "bg-primary/10 text-primary ring-primary/30";
const chipOff = "bg-panel2 text-muted-foreground ring-line hover:text-foreground";

function AutomationPage() {
  const { projectId } = useCurrentProject();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<TestStatus | "all">("all");

  const filters = useMemo<TestFilters>(() => {
    const value: TestFilters = { status };
    if (projectId) value.projectId = projectId;
    return value;
  }, [projectId, status]);

  const { data: tests = [] } = useQuery({
    queryKey: ["tests", filters],
    queryFn: () => testsApi.list(filters),
  });

  const { data: allTests = [] } = useQuery({
    queryKey: ["tests", "all", projectId],
    queryFn: () => testsApi.list(projectId ? { projectId } : {}),
  });

  const stats = useMemo(() => {
    const passed = allTests.filter((t) => t.status === "passed").length;
    return {
      total: allTests.length,
      passed,
      failed: allTests.filter((t) => t.status === "failed").length,
      skipped: allTests.filter((t) => t.status === "skipped").length,
      passRate: allTests.length === 0 ? 0 : (passed / allTests.length) * 100,
    };
  }, [allTests]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["tests"] });

  const run = useMutation({
    mutationFn: (testId: string) => testsApi.run(testId),
    onSuccess: (job) => {
      invalidate();
      toast.success(`Execution queued (${job.jobId})`);
    },
    onError: () => toast.error("Could not queue this execution"),
  });

  const regenerate = useMutation({
    mutationFn: (testId: string) => testsApi.regenerate(testId),
    onSuccess: (job) => {
      invalidate();
      toast.success(`Regeneration queued (${job.jobId})`);
    },
    onError: () => toast.error("Could not queue the regeneration"),
  });

  return (
    <>
      <PageHeader
        title="Automation"
        subtitle="Playwright suite generated from validated Gherkin scenarios"
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Tests" value={`${stats.total}`} hint="in this project" />
        <MetricCard
          label="Passed"
          value={`${stats.passed}`}
          tone="pass"
          hint={`${stats.passRate.toFixed(1)}% pass rate`}
          progress={stats.passRate}
        />
        <MetricCard
          label="Failed"
          value={`${stats.failed}`}
          tone={stats.failed > 0 ? "fail" : "default"}
          hint="need investigation"
        />
        <MetricCard label="Skipped" value={`${stats.skipped}`} hint="not executed" />
      </div>

      <Panel>
        <PanelHeader
          title="Playwright tests"
          meta={`${tests.length} shown`}
          actions={
            <div className="flex flex-wrap items-center gap-1.5">
              {STATUS_FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setStatus(value)}
                  className={`${chip} ${status === value ? chipOn : chipOff}`}
                >
                  {value.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          }
        />

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-3 py-2 font-medium">User Story</th>
                <th className="px-3 py-2 font-medium">Scenario</th>
                <th className="px-3 py-2 font-medium">Last execution</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {tests.map((test) => (
                <tr key={test.id} className="transition-colors hover:bg-panel2">
                  <td className="px-4 py-3 font-mono text-[12px]">{test.file}</td>
                  <td className="px-3 py-3">
                    <Link
                      to="/backlog/$storyId"
                      params={{ storyId: test.userStoryId }}
                      className="font-mono text-[11px] text-primary hover:underline"
                    >
                      {test.userStoryKey}
                    </Link>
                  </td>
                  <td className="max-w-72 truncate px-3 py-3 text-muted-foreground">
                    {test.scenario}
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                    {formatDateTime(test.lastRun)}
                  </td>
                  <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                    {formatDuration(test.durationMs)}
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={test.status} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Link to="/automation/$testId" params={{ testId: test.id }}>
                        <Button variant="outline" size="sm">
                          View
                        </Button>
                      </Link>
                      <Button
                        variant="subtle"
                        size="sm"
                        disabled={run.isPending}
                        onClick={() => run.mutate(test.id)}
                      >
                        Run
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={regenerate.isPending}
                        onClick={() => regenerate.mutate(test.id)}
                      >
                        Regenerate
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {tests.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <PanelBody className="text-center text-sm text-muted-foreground">
                      No Playwright test matches this filter.
                    </PanelBody>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
