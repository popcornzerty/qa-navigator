import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { formatGherkin, gherkinApi, parseGherkin, storiesApi, testsApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { GherkinBlock } from "../components/ui/gherkin-block";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { formatConfidence, formatDuration } from "../lib/format";
import type { AcceptanceCriterion, GherkinScenario, PlaywrightTest } from "../types/models";

export const Route = createFileRoute("/backlog/$storyId")({
  head: () => ({
    meta: [
      { title: "User Story — AI QA Agent" },
      {
        name: "description",
        content:
          "User Story detail with editable acceptance criteria, Gherkin scenarios and traceability.",
      },
      { property: "og:title", content: "User Story — AI QA Agent" },
      {
        property: "og:description",
        content:
          "Review acceptance criteria, edit Gherkin and follow traceability to test results.",
      },
    ],
  }),
  component: StoryDetailPage,
});

function StoryDetailPage() {
  const { storyId } = Route.useParams();
  const queryClient = useQueryClient();

  const { data: story, isLoading } = useQuery({
    queryKey: ["story", storyId],
    queryFn: () => storiesApi.get(storyId),
  });

  const { data: tests = [] } = useQuery({
    queryKey: ["tests", "story", storyId],
    queryFn: () => testsApi.list({ userStoryId: storyId }),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["story", storyId] });
    queryClient.invalidateQueries({ queryKey: ["stories"] });
  };

  const approve = useMutation({
    mutationFn: () => storiesApi.updateStatus(storyId, "approved"),
    onSuccess: () => {
      invalidate();
      toast.success("User Story approved");
    },
    onError: () => toast.error("Could not approve this story"),
  });

  const syncJira = useMutation({
    mutationFn: () => storiesApi.syncToJira(storyId),
    onSuccess: (updated) => {
      invalidate();
      toast.success(`Synchronised with Jira ${updated.jiraKey ?? ""}`.trim());
    },
    onError: () => toast.error("Could not synchronise with Jira"),
  });

  if (isLoading || !story) {
    return (
      <>
        <PageHeader title="User Story" subtitle="Loading story detail" />
        <Panel>
          <PanelBody className="text-sm text-muted-foreground">Loading…</PanelBody>
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={story.title}
        subtitle={`${story.id} · ${story.featureName} · epic ${story.epic}`}
        actions={
          <>
            <Link to="/backlog">
              <Button variant="ghost" size="sm">
                Back to backlog
              </Button>
            </Link>
            <Button
              variant="outline"
              size="sm"
              disabled={syncJira.isPending}
              onClick={() => syncJira.mutate()}
            >
              {story.jiraKey ? "Re-sync Jira" : "Create in Jira"}
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={approve.isPending || story.status === "approved"}
              onClick={() => approve.mutate()}
            >
              Approve
            </Button>
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Panel>
            <PanelHeader
              title="User Story"
              meta={story.id}
              actions={<StatusBadge status={story.status} />}
            />
            <PanelBody className="space-y-4">
              <p className="text-sm leading-6 text-muted-foreground">{story.description}</p>
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Meta label="Epic" value={story.epic} />
                <Meta label="Feature" value={story.featureName} />
                <Meta label="Confidence" value={formatConfidence(story.confidence)} />
                <Meta label="Jira" value={story.jiraKey ?? "—"} />
              </dl>
              <SourceFiles files={story.sourceFiles} />
            </PanelBody>
          </Panel>

          <CriteriaPanel
            storyId={story.id}
            criteria={story.acceptanceCriteria}
            onSaved={invalidate}
          />

          <Panel>
            <PanelHeader title="Gherkin" meta={`${story.gherkinScenarios.length} scenarios`} />
            <div className="divide-y divide-line">
              {story.gherkinScenarios.map((scenario) => (
                <ScenarioEditor key={scenario.id} scenario={scenario} onSaved={invalidate} />
              ))}
              {story.gherkinScenarios.length === 0 ? (
                <PanelBody className="text-sm text-muted-foreground">
                  No Gherkin scenario generated for this story yet.
                </PanelBody>
              ) : null}
            </div>
          </Panel>
        </div>

        <div className="space-y-5">
          <TraceabilityPanel
            criteria={story.acceptanceCriteria}
            scenarios={story.gherkinScenarios}
            tests={tests}
          />

          <Panel>
            <PanelHeader title="Playwright tests" meta={`${tests.length}`} />
            <div className="divide-y divide-line">
              {tests.map((test) => (
                <Link
                  key={test.id}
                  to="/automation/$testId"
                  params={{ testId: test.id }}
                  className="flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-panel2"
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono text-[12px]">{test.file}</p>
                    <p className="truncate text-xs text-muted-foreground">{test.scenario}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="font-mono text-[11px] text-dim">
                      {formatDuration(test.durationMs)}
                    </span>
                    <StatusBadge status={test.status} />
                  </div>
                </Link>
              ))}
              {tests.length === 0 ? (
                <PanelBody className="text-sm text-muted-foreground">
                  No Playwright test generated from this story yet.
                </PanelBody>
              ) : null}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] tracking-wider text-dim uppercase">{label}</dt>
      <dd className="mt-0.5 truncate text-sm">{value}</dd>
    </div>
  );
}

/** Technical detail stays secondary — collapsed by default (progressive disclosure). */
function SourceFiles({ files }: { files: string[] }) {
  if (files.length === 0) return null;
  return (
    <details className="rounded-md bg-panel2 ring-1 ring-line">
      <summary className="cursor-pointer px-3 py-2 font-mono text-[10px] tracking-wider text-dim uppercase">
        Source files ({files.length})
      </summary>
      <ul className="space-y-1 px-3 pb-3">
        {files.map((file) => (
          <li key={file} className="font-mono text-[11px] text-muted-foreground">
            {file}
          </li>
        ))}
      </ul>
    </details>
  );
}

function CriteriaPanel({
  storyId,
  criteria,
  onSaved,
}: {
  storyId: string;
  criteria: AcceptanceCriterion[];
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: (input: { criterionId: string; text?: string; covered?: boolean }) => {
      const patch: { text?: string; covered?: boolean } = {};
      if (input.text !== undefined) patch.text = input.text;
      if (input.covered !== undefined) patch.covered = input.covered;
      return storiesApi.updateCriterion(storyId, input.criterionId, patch);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["coverage"] });
      onSaved();
    },
    onError: () => toast.error("Could not save this acceptance criterion"),
  });

  const covered = criteria.filter((c) => c.covered).length;

  return (
    <Panel>
      <PanelHeader title="Acceptance Criteria" meta={`${covered}/${criteria.length} covered`} />
      <div className="divide-y divide-line">
        {criteria.map((criterion) => {
          const value = drafts[criterion.id] ?? criterion.text;
          const dirty = value !== criterion.text;
          return (
            <div key={criterion.id} className="flex items-start gap-3 px-4 py-3">
              <span className="mt-2 shrink-0 font-mono text-[11px] text-primary">
                {criterion.id}
              </span>
              <textarea
                value={value}
                rows={1}
                aria-label={`Acceptance criterion ${criterion.id}`}
                onChange={(event) =>
                  setDrafts((current) => ({ ...current, [criterion.id]: event.target.value }))
                }
                onBlur={() => {
                  if (dirty) save.mutate({ criterionId: criterion.id, text: value });
                }}
                className="min-h-9 flex-1 resize-y rounded-md bg-panel2 px-3 py-2 text-sm ring-1 ring-line outline-none focus:ring-primary/50"
              />
              <label className="mt-1.5 flex shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={criterion.covered}
                  onChange={(event) =>
                    save.mutate({ criterionId: criterion.id, covered: event.target.checked })
                  }
                  className="size-3.5 accent-current"
                />
                covered
              </label>
            </div>
          );
        })}
        {criteria.length === 0 ? (
          <PanelBody className="text-sm text-muted-foreground">
            No acceptance criterion on this story yet.
          </PanelBody>
        ) : null}
      </div>
    </Panel>
  );
}

function ScenarioEditor({ scenario, onSaved }: { scenario: GherkinScenario; onSaved: () => void }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => formatGherkin(scenario));

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["gherkin"] });
    onSaved();
  };

  const save = useMutation({
    mutationFn: () => gherkinApi.update(scenario.id, parseGherkin(draft)),
    onSuccess: () => {
      setEditing(false);
      invalidate();
      toast.success("Gherkin saved");
    },
    onError: () => toast.error("Could not save this scenario"),
  });

  const validate = useMutation({
    mutationFn: () => gherkinApi.validate(scenario.id),
    onSuccess: () => {
      invalidate();
      toast.success("Scenario marked as valid");
    },
    onError: () => toast.error("Could not validate this scenario"),
  });

  const generate = useMutation({
    mutationFn: () => gherkinApi.generatePlaywright(scenario.id),
    onSuccess: (job) => {
      invalidate();
      toast.success(`Playwright generation queued (${job.jobId})`);
    },
    onError: () => toast.error("Could not queue Playwright generation"),
  });

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium">{scenario.scenario}</span>
          <StatusBadge status={scenario.status} />
        </div>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft(formatGherkin(scenario));
                  setEditing(false);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={save.isPending}
                onClick={() => save.mutate()}
              >
                Save
              </Button>
            </>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
                Edit
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={validate.isPending}
                onClick={() => validate.mutate()}
              >
                Validate
              </Button>
              <Button
                variant="subtle"
                size="sm"
                disabled={generate.isPending}
                onClick={() => generate.mutate()}
              >
                Generate Playwright
              </Button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <div className="px-4 pb-4">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={Math.max(8, draft.split("\n").length + 1)}
            aria-label={`Gherkin source for ${scenario.scenario}`}
            spellCheck={false}
            className="w-full resize-y rounded-md bg-panel2 px-4 py-3 font-mono text-[12.5px] leading-6 ring-1 ring-line outline-none focus:ring-primary/50"
          />
        </div>
      ) : (
        <GherkinBlock text={formatGherkin(scenario)} />
      )}
    </div>
  );
}

function TraceabilityPanel({
  criteria,
  scenarios,
  tests,
}: {
  criteria: AcceptanceCriterion[];
  scenarios: GherkinScenario[];
  tests: PlaywrightTest[];
}) {
  const results = tests.filter((test) => test.status !== "not_run");
  const chain = [
    { label: "User Story", value: "1", tone: "text-foreground" },
    { label: "Acceptance Criteria", value: `${criteria.length}`, tone: "text-foreground" },
    { label: "Gherkin", value: `${scenarios.length}`, tone: "text-foreground" },
    { label: "Playwright", value: `${tests.length}`, tone: "text-foreground" },
    {
      label: "Test Result",
      value: `${results.filter((t) => t.status === "passed").length}/${results.length} passed`,
      tone: results.some((t) => t.status === "failed") ? "text-fail" : "text-pass",
    },
  ];

  return (
    <Panel>
      <PanelHeader title="Traceability" meta="story to result" />
      <PanelBody>
        <ol className="space-y-1">
          {chain.map((step, index) => (
            <li key={step.label}>
              <div className="flex items-center justify-between rounded-md bg-panel2 px-3 py-2 ring-1 ring-line">
                <span className="font-mono text-[10px] tracking-wider text-dim uppercase">
                  {step.label}
                </span>
                <span className={`font-mono text-xs ${step.tone}`}>{step.value}</span>
              </div>
              {index < chain.length - 1 ? (
                <div className="flex h-3 justify-center">
                  <span className="w-px bg-line" />
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      </PanelBody>
    </Panel>
  );
}
