import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { runsApi } from "../api";
import type { RunFilters } from "../api/runs";
import { PageHeader } from "../components/layout/app-shell";
import { OriginBadge } from "../components/qa/origin-badge";
import { RunConsole } from "../components/qa/run-console";
import { Button } from "../components/ui/button";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { useCurrentProject } from "../lib/current-project";
import { formatDateTime, formatDuration } from "../lib/format";
import type { TestStatus } from "../types/models";

export const Route = createFileRoute("/runs")({
  head: () => ({
    meta: [
      { title: "Executions — AI QA Agent" },
      {
        name: "description",
        content:
          "Every Playwright execution, live while it runs and kept afterwards, with the output of whatever failed.",
      },
      { property: "og:title", content: "Executions — AI QA Agent" },
      {
        property: "og:description",
        content: "Watch a Playwright run as it happens and read back the history of failures.",
      },
    ],
  }),
  component: RunsPage,
});

const STATUS_FILTERS: (TestStatus | "all")[] = [
  "all",
  "running",
  "failed",
  "passed",
  "skipped",
  "not_run",
];

const chip = "rounded-md px-2.5 py-1 text-xs ring-1 transition-colors whitespace-nowrap capitalize";
const chipOn = "bg-primary/10 text-primary ring-primary/30";
const chipOff = "bg-panel2 text-muted-foreground ring-line hover:text-foreground";

function RunsPage() {
  const { projectId } = useCurrentProject();
  const [status, setStatus] = useState<TestStatus | "all">("all");
  const [selected, setSelected] = useState<string | null>(null);

  const filters = useMemo<RunFilters>(() => {
    const value: RunFilters = { status, limit: 100 };
    if (projectId) value.projectId = projectId;
    return value;
  }, [projectId, status]);

  const {
    data: runs = [],
    isPending,
    isPlaceholderData,
  } = useQuery({
    queryKey: ["runs", filters],
    queryFn: () => runsApi.list(filters),
    placeholderData: keepPreviousData,
    // A run in the list means a subprocess is alive right now; keep the list moving until
    // they have all settled.
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === "running") ? 1000 : 5000,
  });

  const stats = useMemo(
    () => ({
      total: runs.length,
      running: runs.filter((item) => item.status === "running").length,
      failed: runs.filter((item) => item.status === "failed").length,
      passed: runs.filter((item) => item.status === "passed").length,
    }),
    [runs],
  );

  // Follow whatever is executing unless the reader has picked something else to look at.
  const live = runs.find((item) => item.status === "running");
  const watched = selected ?? live?.id ?? runs[0]?.id ?? null;

  return (
    <>
      <PageHeader
        title="Executions"
        subtitle="Every Playwright run, live while it happens and kept afterwards"
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard testId="metric-runs" label="Executions" value={`${stats.total}`} hint="most recent first" />
        <MetricCard
          testId="metric-runs-running"
          label="Running"
          value={`${stats.running}`}
          hint="in progress now"
        />
        <MetricCard
          testId="metric-runs-failed"
          label="Failed"
          value={`${stats.failed}`}
          tone={stats.failed > 0 ? "fail" : "default"}
          hint="need investigation"
        />
        <MetricCard
          testId="metric-runs-passed"
          label="Passed"
          value={`${stats.passed}`}
          tone="pass"
          hint="in this window"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Panel className="lg:col-span-3">
          <PanelHeader
            title="History"
            meta={isPending || isPlaceholderData ? "loading…" : `${runs.length} shown`}
            actions={
              <div className="flex flex-wrap items-center gap-1.5">
                {STATUS_FILTERS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    data-testid={`filter-run-${value}`}
                    onClick={() => setStatus(value)}
                    className={`${chip} ${status === value ? chipOn : chipOff}`}
                  >
                    {value.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            }
          />

          <div
            className={`max-h-[36rem] overflow-auto transition-opacity ${
              isPlaceholderData ? "pointer-events-none opacity-50" : ""
            }`}
            aria-busy={isPlaceholderData}
          >
            <table data-testid="runs-table" className="w-full text-sm">
              <thead className="sticky top-0 bg-panel">
                <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                  <th className="px-4 py-2 font-medium">Started</th>
                  <th className="px-3 py-2 font-medium">Scenario</th>
                  <th className="px-3 py-2 font-medium">Origin</th>
                  <th className="px-3 py-2 font-medium">Tests</th>
                  <th className="px-3 py-2 font-medium">Duration</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    data-testid="run-row"
                    onClick={() => setSelected(run.id)}
                    className={`cursor-pointer transition-colors hover:bg-panel2 ${
                      run.id === watched ? "bg-panel2" : ""
                    }`}
                  >
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                      {formatDateTime(run.startedAt)}
                    </td>
                    <td className="max-w-64 truncate px-3 py-3">{run.scenario}</td>
                    <td className="px-3 py-3">
                      <OriginBadge origin={run.origin} />
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {run.total === 0 ? "—" : `${run.passed}/${run.total}`}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {formatDuration(run.durationMs)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                  </tr>
                ))}
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={6}>
                      <PanelBody className="text-center text-sm text-muted-foreground">
                        {isPending
                          ? "Loading executions…"
                          : "No execution yet. Run a test from Automation and it appears here."}
                      </PanelBody>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="lg:col-span-2">
          {watched ? <RunConsole runId={watched} /> : null}
        </div>
      </div>
    </>
  );
}
