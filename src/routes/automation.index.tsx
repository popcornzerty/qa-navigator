import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { testsApi } from "../api";
import type { TestFilters } from "../api/tests";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { ORIGIN_PROVES, OriginBadge } from "../components/qa/origin-badge";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { useCurrentProject } from "../lib/current-project";
import { formatDateTime, formatDuration } from "../lib/format";
import type { TestOrigin, TestStatus } from "../types/models";

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

const STATUS_FILTERS: (TestStatus | "all")[] = [
  "all",
  "running",
  "passed",
  "failed",
  "skipped",
  "not_run",
];

/** How a test came to exist. The label matters more than the value: "existing" is the
 *  honest word for a test the repository already had, and it is the one distinction that
 *  changes how much a green run is worth. */
const ORIGIN_FILTERS: { value: TestOrigin | "all"; label: string }[] = [
  { value: "all", label: "all origins" },
  { value: "discovered", label: "existing" },
  { value: "code", label: "from code" },
  { value: "jira", label: "from Jira" },
];

const chip = "rounded-md px-2.5 py-1 text-xs ring-1 transition-colors whitespace-nowrap capitalize";
const chipOn = "bg-primary/10 text-primary ring-primary/30";
const chipOff = "bg-panel2 text-muted-foreground ring-line hover:text-foreground";

function AutomationPage() {
  const { projectId } = useCurrentProject();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<TestStatus | "all">("all");
  const [origin, setOrigin] = useState<TestOrigin | "all">("all");

  const filters = useMemo<TestFilters>(() => {
    const value: TestFilters = { status, origin };
    if (projectId) value.projectId = projectId;
    return value;
  }, [projectId, status, origin]);

  const {
    data: tests = [],
    isPending,
    isPlaceholderData,
  } = useQuery({
    queryKey: ["tests", filters],
    queryFn: () => testsApi.list(filters),
    // Changing a filter changes the query key, so without this the list empties while the
    // new results are in flight and the table announces that nothing matches — a claim
    // that is not yet known to be true. The previous rows stay until the answer arrives.
    placeholderData: keepPreviousData,
    // Runs happen in a subprocess with no progress stream, so the rows are the only
    // signal. Poll while any of them is executing, and stop once they all settle.
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === "running") ? 1000 : false,
  });

  const { data: allTests = [] } = useQuery({
    queryKey: ["tests", "all", projectId],
    queryFn: () => testsApi.list(projectId ? { projectId } : {}),
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === "running") ? 1000 : false,
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
    onSuccess: () => {
      invalidate();
      toast.success("Execution started");
    },
    onError: () => toast.error("Could not start this execution"),
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
        subtitle="Playwright suite: what the engine generated, and what the repository already had"
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          testId="metric-tests"
          label="Tests"
          value={`${stats.total}`}
          hint="in this project"
        />
        <MetricCard
          testId="metric-passed"
          label="Passed"
          value={`${stats.passed}`}
          tone="pass"
          hint={`${stats.passRate.toFixed(1)}% pass rate`}
          progress={stats.passRate}
        />
        <MetricCard
          testId="metric-failed"
          label="Failed"
          value={`${stats.failed}`}
          tone={stats.failed > 0 ? "fail" : "default"}
          hint="need investigation"
        />
        <MetricCard
          testId="metric-skipped"
          label="Skipped"
          value={`${stats.skipped}`}
          hint="not executed"
        />
      </div>

      <Panel>
        <PanelHeader
          title="Playwright tests"
          meta={isPending || isPlaceholderData ? "loading…" : `${tests.length} shown`}
          actions={
            <div className="flex flex-wrap items-center gap-1.5">
              {ORIGIN_FILTERS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  data-testid={`filter-origin-${item.value}`}
                  onClick={() => setOrigin(item.value)}
                  className={`${chip} ${origin === item.value ? chipOn : chipOff}`}
                >
                  {item.label}
                </button>
              ))}
              <span aria-hidden className="mx-1 h-4 w-px bg-line" />
              {STATUS_FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  data-testid={`filter-status-${value}`}
                  onClick={() => setStatus(value)}
                  className={`${chip} ${status === value ? chipOn : chipOff}`}
                >
                  {value.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          }
        />

        {origin === "all" ? null : (
          <p
            data-testid="origin-claim"
            className="border-b border-line px-4 py-2.5 text-xs text-muted-foreground"
          >
            <span className="text-foreground">A passing run proves:</span>{" "}
            {ORIGIN_PROVES[origin]}
          </p>
        )}

        <div
          className={`overflow-x-auto transition-opacity ${
            isPlaceholderData ? "pointer-events-none opacity-50" : ""
          }`}
          aria-busy={isPlaceholderData}
        >
          <table data-testid="automation-table" className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-3 py-2 font-medium">Origin</th>
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
                <tr
                  key={test.id}
                  data-testid="test-row"
                  className="transition-colors hover:bg-panel2"
                >
                  <td className="px-4 py-3 font-mono text-[12px]">{test.file}</td>
                  <td className="px-3 py-3">
                    <OriginBadge origin={test.origin} />
                  </td>
                  <td className="px-3 py-3">
                    {test.userStoryId ? (
                      <Link
                        to="/backlog/$storyId"
                        params={{ storyId: test.userStoryId }}
                        className="font-mono text-[11px] text-primary hover:underline"
                      >
                        {test.userStoryKey}
                      </Link>
                    ) : (
                      <span className="text-[11px] text-dim">—</span>
                    )}
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
                        <Button variant="outline" size="sm" data-testid="test-view">
                          View
                        </Button>
                      </Link>
                      <Button
                        variant="subtle"
                        size="sm"
                        data-testid="test-run"
                        disabled={run.isPending || test.status === "running"}
                        onClick={() => run.mutate(test.id)}
                      >
                        {test.status === "running" ? "Running…" : "Run"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid="test-regenerate"
                        disabled={regenerate.isPending || test.origin === "discovered"}
                        title={
                          test.origin === "discovered"
                            ? "This test was written by hand — regenerating would overwrite it."
                            : undefined
                        }
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
                  <td colSpan={8}>
                    <PanelBody className="text-center text-sm text-muted-foreground">
                      {/* On the very first load nothing is known yet, so saying that
                          nothing matches would be an answer the app does not have. */}
                      {isPending ? "Loading tests…" : "No Playwright test matches this filter."}
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
