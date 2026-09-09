import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { formatGherkin, storiesApi, testsApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { GherkinBlock } from "../components/ui/gherkin-block";
import {
  ORIGIN_EXPLANATIONS,
  ORIGIN_LABELS,
  ORIGIN_PROVES,
  OriginBadge,
} from "../components/qa/origin-badge";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { formatDateTime, formatDuration, label } from "../lib/format";
import { cn } from "../lib/utils";
import type { TestStatus } from "../types/models";

export const Route = createFileRoute("/automation/$testId")({
  head: () => ({
    meta: [
      { title: "Test result — AI QA Agent" },
      {
        name: "description",
        content: "Playwright test result with error message, trace, screenshot and console output.",
      },
      { property: "og:title", content: "Test result — AI QA Agent" },
      {
        property: "og:description",
        content: "Inspect a Playwright execution and trace it back to its User Story.",
      },
    ],
  }),
  component: TestDetailPage,
});

const BANNER: Record<TestStatus, string> = {
  passed: "bg-pass/10 text-pass ring-pass/30",
  failed: "bg-fail/10 text-fail ring-fail/30",
  skipped: "bg-skip/10 text-skip ring-skip/30",
  not_run: "bg-panel2 text-muted-foreground ring-line",
  running: "bg-primary/10 text-primary ring-primary/30",
};

function TestDetailPage() {
  const { testId } = Route.useParams();
  const queryClient = useQueryClient();

  const { data: test, isLoading } = useQuery({
    queryKey: ["test", testId],
    queryFn: () => testsApi.get(testId),
    // A run happens in a subprocess with no progress stream, so the row's status is the
    // only signal. Poll while it says `running`, and stop the moment it settles.
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1000 : false),
  });

  const { data: story } = useQuery({
    queryKey: ["story", test?.userStoryId],
    queryFn: () => storiesApi.get(test!.userStoryId!),
    enabled: Boolean(test?.userStoryId),
  });

  const run = useMutation({
    mutationFn: () => testsApi.run(testId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["test", testId] });
      toast.success("Execution started");
    },
    onError: () => toast.error("Could not start this execution"),
  });

  const regenerate = useMutation({
    mutationFn: () => testsApi.regenerate(testId),
    onSuccess: (job) => toast.success(`Regeneration queued (${job.jobId})`),
    onError: () => toast.error("Could not queue the regeneration"),
  });

  const running = test?.status === "running";

  if (isLoading || !test) {
    return (
      <>
        <PageHeader title="Test result" subtitle="Loading execution detail" />
        <Panel>
          <PanelBody className="text-sm text-muted-foreground">Loading…</PanelBody>
        </Panel>
      </>
    );
  }

  const scenario = story?.gherkinScenarios.find((s) => s.id === test.gherkinScenarioId);
  const result = test.result;

  return (
    <>
      <PageHeader
        title={test.file}
        subtitle={test.scenario}
        actions={
          <>
            <Link to="/automation">
              <Button variant="ghost" size="sm">
                Back to automation
              </Button>
            </Link>
            <Button
              variant="outline"
              size="sm"
              disabled={regenerate.isPending || test.origin === "discovered"}
              title={
                test.origin === "discovered"
                  ? "This test was written by hand — regenerating would overwrite it."
                  : undefined
              }
              onClick={() => regenerate.mutate()}
            >
              Regenerate
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-testid="test-run"
              disabled={run.isPending || running}
              onClick={() => run.mutate()}
            >
              {running ? "Running…" : "Run"}
            </Button>
          </>
        }
      />

      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3 ring-1",
          BANNER[test.status],
        )}
      >
        <div className="flex items-center gap-3">
          <span className="font-display text-lg font-semibold tracking-tight uppercase">
            {label(test.status)}
          </span>
          <span className="font-mono text-[11px] opacity-80">
            {formatDuration(test.durationMs)}
          </span>
        </div>
        <span className="font-mono text-[11px] opacity-80">
          {formatDateTime(result.executedAt)}
        </span>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          {test.status === "failed" ? (
            <>
              <Panel>
                <PanelHeader title="Error" meta="assertion or timeout" />
                <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-6 text-fail">
                  {result.errorMessage ?? "No error message captured."}
                </pre>
              </Panel>

              <Panel>
                <PanelHeader
                  title="Console output"
                  meta={`${result.consoleOutput?.length ?? 0} lines`}
                />
                <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-6 text-muted-foreground">
                  {(result.consoleOutput ?? ["No console output captured."]).join("\n")}
                </pre>
              </Panel>

              <div className="grid gap-5 sm:grid-cols-2">
                <Artifact title="Screenshot" path={result.screenshot} />
                <Artifact title="Trace" path={result.trace} />
              </div>
            </>
          ) : (
            <Panel>
              <PanelHeader title="Execution" meta={label(test.status)} />
              <PanelBody className="text-sm text-muted-foreground">
                {test.status === "passed"
                  ? "This execution passed. No error, screenshot or trace artifact was produced."
                  : test.status === "skipped"
                    ? "This test was skipped during the last run, so no result artifact is available."
                    : "This test has never been executed yet."}
              </PanelBody>
            </Panel>
          )}

          <Panel>
            <PanelHeader
              title="Test code"
              meta={test.line ? `${test.file}:${test.line}` : test.file}
            />
            {test.sourceError ? (
              <PanelBody className="text-sm text-muted-foreground">{test.sourceError}</PanelBody>
            ) : test.source ? (
              <div className="max-h-[32rem] overflow-auto">
                <pre className="px-4 py-3 text-[12px] leading-relaxed">
                  <code>
                    {test.source.split("\n").map((text, index) => {
                      const number = index + 1;
                      const highlighted = test.line !== null && number === test.line;
                      return (
                        <div
                          key={number}
                          className={`flex gap-3 ${highlighted ? "bg-primary/10" : ""}`}
                        >
                          <span className="w-10 shrink-0 text-right text-dim select-none">
                            {number}
                          </span>
                          <span className="whitespace-pre">{text}</span>
                        </div>
                      );
                    })}
                  </code>
                </pre>
              </div>
            ) : (
              <PanelBody className="text-sm text-muted-foreground">
                No source available for this test.
              </PanelBody>
            )}
          </Panel>

          <Panel>
            <PanelHeader title="Gherkin scenario" meta={scenario?.feature ?? "—"} />
            {scenario ? (
              <GherkinBlock text={formatGherkin(scenario)} />
            ) : (
              <PanelBody className="text-sm text-muted-foreground">
                The source scenario is not available for this test.
              </PanelBody>
            )}
          </Panel>
        </div>

        <div className="space-y-5">
          {running ? (
            <Panel>
              <PanelHeader title="Execution in progress" meta="live" />
              <PanelBody className="flex items-center gap-3 text-sm text-muted-foreground">
                <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
                Playwright is running this test. The result appears here as soon as it
                finishes.
              </PanelBody>
            </Panel>
          ) : null}

          <Panel>
            <PanelHeader title="Origin" meta={ORIGIN_LABELS[test.origin]} />
            <PanelBody className="space-y-3">
              <div className="flex items-center gap-2 text-sm">
                <OriginBadge origin={test.origin} />
                <span className="text-muted-foreground">
                  proves: {ORIGIN_PROVES[test.origin]}
                </span>
              </div>
              <p
                data-testid="origin-explanation"
                className="text-sm leading-relaxed text-muted-foreground"
              >
                {ORIGIN_EXPLANATIONS[test.origin]}
              </p>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Test" meta={test.id} />
            <PanelBody className="space-y-3">
              <Row label="File" value={test.file} mono />
              <Row label="Status" value={<StatusBadge status={test.status} />} />
              <Row label="Duration" value={formatDuration(test.durationMs)} mono />
              <Row label="Last execution" value={formatDateTime(test.lastRun)} />
              <Row label="Jira" value={test.userStoryKey} mono />
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="User Story" meta={test.userStoryId ?? "—"} />
            <PanelBody className="space-y-3">
              {test.userStoryId ? (
                <>
                  <p className="text-sm">{story?.title ?? "—"}</p>
                  <Link to="/backlog/$storyId" params={{ storyId: test.userStoryId }}>
                    <Button variant="outline" size="sm">
                      Open user story
                    </Button>
                  </Link>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  This test traces to no User Story. See Origin for what a passing run
                  establishes.
                </p>
              )}
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Row({
  label: name,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="font-mono text-[10px] tracking-wider text-dim uppercase">{name}</span>
      <span className={cn("truncate text-sm", mono && "font-mono text-[11px]")}>{value}</span>
    </div>
  );
}

/** Artifacts are produced by the runner; Phase 1 shows their reference, not their content. */
function Artifact({ title, path }: { title: string; path: string | undefined }) {
  return (
    <Panel>
      <PanelHeader title={title} />
      <PanelBody>
        {path ? (
          <div className="grid h-28 place-items-center rounded-md bg-panel2 ring-1 ring-line">
            <p className="px-3 text-center font-mono text-[11px] break-all text-muted-foreground">
              {path}
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Not captured.</p>
        )}
      </PanelBody>
    </Panel>
  );
}
