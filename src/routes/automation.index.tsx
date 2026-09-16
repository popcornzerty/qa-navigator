import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
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
import {
  type FileGroup,
  type FolderGroup,
  type GroupCounts,
  groupTests,
  needsAttention,
} from "../lib/test-groups";
import { cn } from "../lib/utils";
import type { TestOrigin, TestStatus } from "../types/models";

export const Route = createFileRoute("/automation/")({
  head: () => ({
    meta: [
      { title: "Automation — AI QA Agent" },
      {
        name: "description",
        content:
          "Browser tests grouped by folder and spec file, with status, last execution and runs.",
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
  const navigate = useNavigate();
  const [status, setStatus] = useState<TestStatus | "all">("all");
  const [origin, setOrigin] = useState<TestOrigin | "all">("all");
  // Files a person opened or closed by hand. Anything else follows the rule: open when it
  // holds something other than green.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  // Browser tests only. The backend suite reaches the engine through JUnit reports and
  // cannot be run from here; listed in this page, a thousand pytest rows buried the
  // hundred and forty tests that can. It has its place in the inventory.
  const filters = useMemo<TestFilters>(() => {
    const value: TestFilters = { status, origin, kind: "e2e" };
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
    queryKey: ["tests", "all-e2e", projectId],
    queryFn: () => testsApi.list(projectId ? { projectId, kind: "e2e" } : { kind: "e2e" }),
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

  const folders = useMemo(() => groupTests(tests), [tests]);
  const running = allTests.filter((item) => item.status === "running").length;
  const filtering = status !== "all" || origin !== "all";

  const isOpen = (file: FileGroup) =>
    toggled[file.file] ?? (filtering || needsAttention(file.counts));
  const setAll = (open: boolean) =>
    setToggled(
      Object.fromEntries(folders.flatMap((folder) => folder.files.map((f) => [f.file, open]))),
    );

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["tests"] });
  const watch = (message: string) =>
    toast.success(message, {
      // Long enough to be clicked: this is a shortcut to another screen, not a
      // notification. A short test finishes before a four-second toast expires.
      duration: 10_000,
      action: { label: "Watch", onClick: () => void navigate({ to: "/runs" }) },
    });

  const run = useMutation({
    mutationFn: (testId: string) => testsApi.run(testId),
    onSuccess: () => {
      invalidate();
      watch("Execution started");
    },
    onError: () => toast.error("Could not start this execution"),
  });

  const runFile = useMutation({
    mutationFn: (file: string) => {
      if (!projectId) throw new Error("Select a project first.");
      return testsApi.runFile(projectId, file);
    },
    onSuccess: (_job, file) => {
      invalidate();
      setToggled((current) => ({ ...current, [file]: true }));
      watch(`Running every test of ${file.split("/").pop()}`);
    },
    onError: (error: Error) => toast.error(error.message || "Could not run this file"),
  });

  const regenerate = useMutation({
    mutationFn: (testId: string) => testsApi.regenerate(testId),
    onSuccess: (job) => {
      invalidate();
      toast.success(`Regeneration queued (${job.jobId})`);
    },
    onError: () => toast.error("Could not queue the regeneration"),
  });

  const fileCount = folders.reduce((total, folder) => total + folder.files.length, 0);

  return (
    <>
      <PageHeader
        title="Automation"
        subtitle="Browser tests, grouped by folder and spec file — the repository's own layout"
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          testId="metric-tests"
          label="Tests"
          value={`${stats.total}`}
          hint="browser tests in this project"
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
          meta={
            isPending || isPlaceholderData
              ? "loading…"
              : `${tests.length} tests · ${fileCount} files`
          }
          actions={
            <div className="flex flex-wrap items-center gap-1.5">
              <Link to="/runs">
                <Button variant="outline" size="sm" data-testid="watch-executions">
                  {running > 0 ? `Watch ${running} running` : "Executions"}
                </Button>
              </Link>
              <Button variant="ghost" size="sm" onClick={() => setAll(true)}>
                Expand all
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setAll(false)}>
                Collapse all
              </Button>
              <span aria-hidden className="mx-1 h-4 w-px bg-line" />
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
            <span className="text-foreground">A passing run proves:</span> {ORIGIN_PROVES[origin]}
          </p>
        )}

        <div
          data-testid="automation-groups"
          className={cn(
            "transition-opacity",
            isPlaceholderData && "pointer-events-none opacity-50",
          )}
          aria-busy={isPlaceholderData}
        >
          {folders.length === 0 ? (
            <PanelBody className="text-center text-sm text-muted-foreground">
              {/* On the very first load nothing is known yet, so saying that nothing
                  matches would be an answer the app does not have. */}
              {isPending ? "Loading tests…" : "No Playwright test matches this filter."}
            </PanelBody>
          ) : (
            folders.map((folder) => (
              <Folder
                key={folder.folder}
                folder={folder}
                isOpen={isOpen}
                onToggle={(file, open) => setToggled((current) => ({ ...current, [file]: open }))}
                onRunFile={(file) => runFile.mutate(file)}
                runFilePending={runFile.isPending}
                onRun={(testId) => run.mutate(testId)}
                runPending={run.isPending}
                onRegenerate={(testId) => regenerate.mutate(testId)}
                regeneratePending={regenerate.isPending}
              />
            ))
          )}
        </div>
      </Panel>
    </>
  );
}

function Folder({
  folder,
  isOpen,
  onToggle,
  onRunFile,
  runFilePending,
  onRun,
  runPending,
  onRegenerate,
  regeneratePending,
}: {
  folder: FolderGroup;
  isOpen: (file: FileGroup) => boolean;
  onToggle: (file: string, open: boolean) => void;
  onRunFile: (file: string) => void;
  runFilePending: boolean;
  onRun: (testId: string) => void;
  runPending: boolean;
  onRegenerate: (testId: string) => void;
  regeneratePending: boolean;
}) {
  return (
    <section data-testid="test-folder" className="border-b border-line last:border-0">
      <div className="flex flex-wrap items-center justify-between gap-2 bg-panel2/60 px-4 py-2">
        <h3 className="font-mono text-[12px] text-foreground">{folder.label}/</h3>
        <Counts counts={folder.counts} suffix={`· ${folder.files.length} files`} />
      </div>

      {folder.files.map((file) => {
        const open = isOpen(file);
        const running = file.counts.running > 0;
        return (
          <div key={file.file} data-testid="test-file" className="border-t border-line/60">
            <div
              className={cn(
                "flex flex-wrap items-center justify-between gap-2 px-4 py-2.5",
                file.counts.failed > 0 && "bg-fail/5",
              )}
            >
              <button
                type="button"
                aria-expanded={open}
                data-testid="test-file-toggle"
                onClick={() => onToggle(file.file, !open)}
                className="flex min-w-0 items-center gap-2 text-left"
              >
                <span
                  aria-hidden
                  className={cn(
                    "inline-block w-3 text-[10px] text-dim transition-transform",
                    open && "rotate-90",
                  )}
                >
                  ▶
                </span>
                <span className="text-sm font-medium text-foreground">{file.label}</span>
                <span className="truncate font-mono text-[11px] text-dim">
                  {file.file.split("/").pop()}
                </span>
              </button>
              <div className="flex items-center gap-3">
                <Counts counts={file.counts} />
                <Button
                  variant="subtle"
                  size="sm"
                  data-testid="test-file-run"
                  disabled={runFilePending || running}
                  onClick={() => onRunFile(file.file)}
                  title={`Run the ${file.counts.total} tests of this file in one Playwright process`}
                >
                  {running ? "Running…" : `Run file (${file.counts.total})`}
                </Button>
              </div>
            </div>

            {open ? (
              <div className="overflow-x-auto">
                <table data-testid="automation-table" className="w-full text-sm">
                  <thead>
                    <tr className="border-y border-line/60 text-left text-[11px] tracking-wider text-dim uppercase">
                      <th className="py-2 pr-3 pl-10 font-medium">Scenario</th>
                      <th className="px-3 py-2 font-medium">Origin</th>
                      <th className="px-3 py-2 font-medium">User Story</th>
                      <th className="px-3 py-2 font-medium">Last execution</th>
                      <th className="px-3 py-2 font-medium">Duration</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-4 py-2 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {file.tests.map((test) => (
                      <tr
                        key={test.id}
                        data-testid="test-row"
                        className="transition-colors hover:bg-panel2"
                      >
                        <td className="max-w-md py-2.5 pr-3 pl-10 text-muted-foreground">
                          <span className="line-clamp-2">{test.scenario}</span>
                        </td>
                        <td className="px-3 py-2.5">
                          <OriginBadge origin={test.origin} />
                        </td>
                        <td className="px-3 py-2.5">
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
                        <td className="px-3 py-2.5 whitespace-nowrap text-muted-foreground">
                          {formatDateTime(test.lastRun)}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[11px] text-muted-foreground">
                          {formatDuration(test.durationMs)}
                        </td>
                        <td className="px-3 py-2.5">
                          <StatusBadge status={test.status} />
                        </td>
                        <td className="px-4 py-2.5">
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
                              disabled={runPending || test.status === "running"}
                              onClick={() => onRun(test.id)}
                            >
                              {test.status === "running" ? "Running…" : "Run"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              data-testid="test-regenerate"
                              disabled={regeneratePending || test.origin === "discovered"}
                              title={
                                test.origin === "discovered"
                                  ? "This test was written by hand — regenerating would overwrite it."
                                  : undefined
                              }
                              onClick={() => onRegenerate(test.id)}
                            >
                              Regenerate
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}

function Counts({ counts, suffix }: { counts: GroupCounts; suffix?: string }) {
  return (
    <span className="flex items-baseline gap-2.5 text-[11px]">
      <span className="font-mono text-pass">{counts.passed} passed</span>
      {counts.failed > 0 ? (
        <span className="font-mono font-semibold text-fail">{counts.failed} failed</span>
      ) : null}
      {counts.running > 0 ? (
        <span className="font-mono text-primary">{counts.running} running</span>
      ) : null}
      {counts.pending > 0 ? (
        <span className="font-mono text-skip">{counts.pending} no verdict</span>
      ) : null}
      {suffix ? <span className="text-dim">{suffix}</span> : null}
    </span>
  );
}
