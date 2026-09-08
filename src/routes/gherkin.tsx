import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { formatGherkin, gherkinApi, storiesApi } from "../api";
import type { GherkinFilters } from "../api/gherkin";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { GherkinBlock } from "../components/ui/gherkin-block";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { useCurrentProject } from "../lib/current-project";
import { percent } from "../lib/format";
import type { GherkinStatus } from "../types/models";

export const Route = createFileRoute("/gherkin")({
  head: () => ({
    meta: [
      { title: "Gherkin — AI QA Agent" },
      {
        name: "description",
        content:
          "Gherkin workspace: features, scenarios, validation status and Playwright generation.",
      },
      { property: "og:title", content: "Gherkin — AI QA Agent" },
      {
        property: "og:description",
        content: "Filter, validate and automate Gherkin scenarios derived from User Stories.",
      },
    ],
  }),
  component: GherkinPage,
});

const STATUS_FILTERS: (GherkinStatus | "all")[] = ["all", "draft", "valid", "invalid", "automated"];
const COVERAGE_FILTERS = ["all", "covered", "uncovered"] as const;
type CoverageFilter = (typeof COVERAGE_FILTERS)[number];

const chip = "rounded-md px-2.5 py-1 text-xs ring-1 transition-colors whitespace-nowrap capitalize";
const chipOn = "bg-primary/10 text-primary ring-primary/30";
const chipOff = "bg-panel2 text-muted-foreground ring-line hover:text-foreground";
const fieldLabel = "font-mono text-[10px] tracking-wider text-dim uppercase";

function GherkinPage() {
  const { projectId } = useCurrentProject();
  const queryClient = useQueryClient();

  const [status, setStatus] = useState<GherkinStatus | "all">("all");
  const [feature, setFeature] = useState("all");
  const [storyId, setStoryId] = useState("all");
  const [coverage, setCoverage] = useState<CoverageFilter>("all");

  const filters = useMemo<GherkinFilters>(() => {
    const value: GherkinFilters = { status };
    if (projectId) value.projectId = projectId;
    if (feature !== "all") value.feature = feature;
    if (storyId !== "all") value.userStoryId = storyId;
    return value;
  }, [projectId, status, feature, storyId]);

  const { data: scenarios = [] } = useQuery({
    queryKey: ["gherkin", filters],
    queryFn: () => gherkinApi.list(filters),
  });

  const { data: allScenarios = [] } = useQuery({
    queryKey: ["gherkin", "all", projectId],
    queryFn: () => gherkinApi.list(projectId ? { projectId } : {}),
  });

  const { data: stories = [] } = useQuery({
    queryKey: ["stories", projectId],
    queryFn: () => storiesApi.list(projectId ? { projectId } : {}),
  });

  const storyTitles = useMemo(
    () => new Map(stories.map((story) => [story.id, story.title])),
    [stories],
  );

  const features = useMemo(
    () => ["all", ...Array.from(new Set(allScenarios.map((s) => s.feature))).sort()],
    [allScenarios],
  );

  const visible = useMemo(
    () =>
      scenarios.filter((scenario) => {
        if (coverage === "covered") return scenario.status === "automated";
        if (coverage === "uncovered") return scenario.status !== "automated";
        return true;
      }),
    [scenarios, coverage],
  );

  const stats = useMemo(() => {
    const total = allScenarios.length;
    const valid = allScenarios.filter(
      (s) => s.status === "valid" || s.status === "automated",
    ).length;
    const automated = allScenarios.filter((s) => s.status === "automated").length;
    return {
      features: new Set(allScenarios.map((s) => s.feature)).size,
      scenarios: total,
      valid,
      automated,
      coverage: total === 0 ? 0 : Math.round((automated / total) * 1000) / 10,
    };
  }, [allScenarios]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["gherkin"] });
    queryClient.invalidateQueries({ queryKey: ["stories"] });
    queryClient.invalidateQueries({ queryKey: ["coverage"] });
  };

  const validateAll = useMutation({
    mutationFn: async () => {
      const targets = visible.filter((s) => s.status !== "valid" && s.status !== "automated");
      await Promise.all(targets.map((s) => gherkinApi.validate(s.id)));
      return targets.length;
    },
    onSuccess: (count) => {
      invalidate();
      toast.success(
        count === 0 ? "Every scenario is already valid" : `${count} scenarios validated`,
      );
    },
    onError: () => toast.error("Could not validate these scenarios"),
  });

  const generateAll = useMutation({
    mutationFn: async () => {
      const targets = visible.filter((s) => s.status !== "automated");
      await Promise.all(targets.map((s) => gherkinApi.generatePlaywright(s.id)));
      return targets.length;
    },
    onSuccess: (count) => {
      invalidate();
      toast.success(
        count === 0
          ? "Every scenario is already automated"
          : `Playwright generation queued for ${count} scenarios`,
      );
    },
    onError: () => toast.error("Could not queue Playwright generation"),
  });

  return (
    <>
      <PageHeader
        title="Gherkin"
        subtitle="Executable specifications derived from approved User Stories"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              data-testid="gherkin-validate-all"
              disabled={validateAll.isPending || visible.length === 0}
              onClick={() => validateAll.mutate()}
            >
              Validate Gherkin
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-testid="gherkin-generate-all"
              disabled={generateAll.isPending || visible.length === 0}
              onClick={() => generateAll.mutate()}
            >
              Generate Playwright
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          testId="metric-features"
          label="Features"
          value={`${stats.features}`}
          hint="distinct Gherkin features"
        />
        <MetricCard
          testId="metric-scenarios"
          label="Scenarios"
          value={`${stats.scenarios}`}
          hint={`${stats.valid} valid`}
        />
        <MetricCard
          testId="metric-coverage"
          label="Coverage"
          value={percent(stats.coverage)}
          hint={`${stats.automated} automated`}
          progress={stats.coverage}
        />
        <MetricCard
          testId="metric-validation"
          label="Validation"
          value={`${stats.valid}/${stats.scenarios}`}
          hint="scenarios validated"
          progress={stats.scenarios === 0 ? 0 : (stats.valid / stats.scenarios) * 100}
        />
      </div>

      <Panel>
        <PanelHeader title="Scenarios" meta={`${visible.length} shown`} />

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={fieldLabel}>Status</span>
            {STATUS_FILTERS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setStatus(value)}
                className={`${chip} ${status === value ? chipOn : chipOff}`}
              >
                {value}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className={fieldLabel}>Coverage</span>
            {COVERAGE_FILTERS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setCoverage(value)}
                className={`${chip} ${coverage === value ? chipOn : chipOff}`}
              >
                {value}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            <label htmlFor="gherkin-feature" className={fieldLabel}>
              Feature
            </label>
            <select
              id="gherkin-feature"
              value={feature}
              onChange={(event) => setFeature(event.target.value)}
              className="rounded-md bg-panel2 px-2.5 py-1 text-xs ring-1 ring-line outline-none focus:ring-primary/50"
            >
              {features.map((name) => (
                <option key={name} value={name} className="bg-panel2">
                  {name === "all" ? "All features" : name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <label htmlFor="gherkin-story" className={fieldLabel}>
              User Story
            </label>
            <select
              id="gherkin-story"
              value={storyId}
              onChange={(event) => setStoryId(event.target.value)}
              className="max-w-56 rounded-md bg-panel2 px-2.5 py-1 text-xs ring-1 ring-line outline-none focus:ring-primary/50"
            >
              <option value="all" className="bg-panel2">
                All stories
              </option>
              {stories.map((story) => (
                <option key={story.id} value={story.id} className="bg-panel2">
                  {story.id} — {story.title}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="divide-y divide-line">
          {visible.map((scenario) => (
            <ScenarioRow
              key={scenario.id}
              scenarioId={scenario.id}
              title={scenario.scenario}
              feature={scenario.feature}
              status={scenario.status}
              storyId={scenario.userStoryId}
              storyTitle={storyTitles.get(scenario.userStoryId) ?? ""}
              text={formatGherkin(scenario)}
              onChanged={invalidate}
            />
          ))}
          {visible.length === 0 ? (
            <PanelBody className="text-center text-sm text-muted-foreground">
              No scenario matches these filters.
            </PanelBody>
          ) : null}
        </div>
      </Panel>
    </>
  );
}

function ScenarioRow({
  scenarioId,
  title,
  feature,
  status,
  storyId,
  storyTitle,
  text,
  onChanged,
}: {
  scenarioId: string;
  title: string;
  feature: string;
  status: GherkinStatus;
  storyId: string;
  storyTitle: string;
  text: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);

  const validate = useMutation({
    mutationFn: () => gherkinApi.validate(scenarioId),
    onSuccess: () => {
      onChanged();
      toast.success("Scenario marked as valid");
    },
    onError: () => toast.error("Could not validate this scenario"),
  });

  const generate = useMutation({
    mutationFn: () => gherkinApi.generatePlaywright(scenarioId),
    onSuccess: (job) => {
      onChanged();
      toast.success(`Playwright generation queued (${job.jobId})`);
    },
    onError: () => toast.error("Could not queue Playwright generation"),
  });

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
        >
          <span className="font-mono text-[11px] text-dim">{open ? "▾" : "▸"}</span>
          <span className="truncate text-sm font-medium">{title}</span>
          <span className="shrink-0 font-mono text-[11px] text-dim">{feature}</span>
          <StatusBadge status={status} />
        </button>
        <div className="flex items-center gap-1.5">
          <Link to="/backlog/$storyId" params={{ storyId }} title={storyTitle}>
            <Button variant="ghost" size="sm">
              {storyId}
            </Button>
          </Link>
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
        </div>
      </div>
      {open ? <GherkinBlock text={text} /> : null}
    </div>
  );
}
