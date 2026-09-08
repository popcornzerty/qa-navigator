import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { coverageApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { MetricCard } from "../components/ui/metric-card";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { useCurrentProject } from "../lib/current-project";
import { percent } from "../lib/format";
import { cn } from "../lib/utils";

export const Route = createFileRoute("/coverage")({
  head: () => ({
    meta: [
      { title: "Coverage — AI QA Agent" },
      {
        name: "description",
        content:
          "QA coverage dashboard: user stories, acceptance criteria, Gherkin and automation coverage.",
      },
      { property: "og:title", content: "Coverage — AI QA Agent" },
      {
        property: "og:description",
        content: "Measure functional QA coverage and surface what is still uncovered.",
      },
    ],
  }),
  component: CoveragePage,
});

function CoveragePage() {
  const { projectId } = useCurrentProject();
  const { data: report, isLoading } = useQuery({
    queryKey: ["coverage", projectId],
    queryFn: () => coverageApi.get(projectId ?? undefined),
  });

  if (isLoading || !report) {
    return (
      <>
        <PageHeader title="Coverage" subtitle="Loading coverage report" />
        <Panel>
          <PanelBody className="text-sm text-muted-foreground">Loading…</PanelBody>
        </Panel>
      </>
    );
  }

  const bars = [
    {
      label: "User Story coverage",
      hint: "stories with at least one Gherkin scenario",
      value: report.userStories.withGherkin,
      total: report.userStories.total,
    },
    {
      label: "Acceptance Criteria coverage",
      hint: "criteria covered by a scenario",
      value: report.acceptanceCriteria.covered,
      total: report.acceptanceCriteria.total,
    },
    {
      label: "Gherkin coverage",
      hint: "scenarios validated or automated",
      value: report.gherkin.valid,
      total: report.gherkin.total,
    },
    {
      label: "Automation coverage",
      hint: "stories with a Playwright test",
      value: report.userStories.automated,
      total: report.userStories.total,
    },
  ];

  return (
    <>
      <PageHeader
        title="Coverage"
        subtitle="How much of the functional scope is specified, automated and verified"
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="User Stories"
          value={`${report.userStories.total}`}
          hint={`${report.userStories.withGherkin} with Gherkin · ${report.userStories.automated} automated`}
        />
        <MetricCard
          label="Acceptance Criteria"
          value={`${report.acceptanceCriteria.total}`}
          hint={`${report.acceptanceCriteria.covered} covered`}
          progress={
            report.acceptanceCriteria.total === 0
              ? 0
              : (report.acceptanceCriteria.covered / report.acceptanceCriteria.total) * 100
          }
        />
        <MetricCard
          label="Automated tests"
          value={`${report.automation.total}`}
          hint={`${report.automation.passing} passing`}
          tone="pass"
        />
        <MetricCard
          label="Coverage"
          value={percent(report.coverage)}
          hint="acceptance criteria covered"
          progress={report.coverage}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Panel>
          <PanelHeader title="Overall coverage" meta="acceptance criteria" />
          <PanelBody className="grid place-items-center py-6">
            <Donut value={report.coverage} />
          </PanelBody>
        </Panel>

        <Panel className="lg:col-span-2">
          <PanelHeader title="Coverage breakdown" meta="4 dimensions" />
          <PanelBody className="space-y-4">
            {bars.map((bar) => (
              <Bar key={bar.label} {...bar} />
            ))}
          </PanelBody>
        </Panel>
      </div>

      <Panel>
        <PanelHeader title="Uncovered items" meta={`${report.gaps.length} gaps`} />
        <div className="divide-y divide-line">
          {report.gaps.map((gap) => (
            <div key={gap.id} className="flex items-start gap-3 px-4 py-3">
              <span
                className={cn(
                  "mt-0.5 shrink-0 font-mono text-[11px]",
                  gap.severity === "critical" ? "text-fail" : "text-skip",
                )}
                aria-hidden="true"
              >
                ⚠
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  <span className="font-mono text-[11px] text-primary">{gap.reference}</span>
                  <span className="ml-2">{gap.label}</span>
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">{gap.reason}</p>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded px-2 py-0.5 text-[11px] ring-1",
                  gap.severity === "critical"
                    ? "bg-fail/10 text-fail ring-fail/25"
                    : "bg-skip/10 text-skip ring-skip/25",
                )}
              >
                {gap.severity}
              </span>
            </div>
          ))}
          {report.gaps.length === 0 ? (
            <PanelBody className="text-center text-sm text-muted-foreground">
              Every acceptance criterion is covered.
            </PanelBody>
          ) : null}
        </div>
      </Panel>
    </>
  );
}

/** Pure SVG so the chart renders identically during SSR and hydration. */
function Donut({ value }: { value: number }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const filled = (Math.min(100, Math.max(0, value)) / 100) * circumference;

  return (
    <svg viewBox="0 0 140 140" className="size-40" role="img" aria-label={`Coverage ${value}%`}>
      <circle cx="70" cy="70" r={radius} fill="none" stroke="var(--line)" strokeWidth="12" />
      <circle
        cx="70"
        cy="70"
        r={radius}
        fill="none"
        stroke="var(--pass)"
        strokeWidth="12"
        strokeLinecap="round"
        strokeDasharray={`${filled} ${circumference - filled}`}
        transform="rotate(-90 70 70)"
      />
      <text
        x="70"
        y="70"
        textAnchor="middle"
        dominantBaseline="central"
        className="font-display fill-foreground text-[22px] font-semibold"
      >
        {value.toFixed(1)}%
      </text>
    </svg>
  );
}

function Bar({
  label,
  hint,
  value,
  total,
}: {
  label: string;
  hint: string;
  value: number;
  total: number;
}) {
  const ratio = total === 0 ? 0 : (value / total) * 100;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm">{label}</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {value}/{total} · {ratio.toFixed(1)}%
        </span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-line">
        <div
          className={cn(
            "h-full rounded-full",
            ratio >= 80 ? "bg-pass" : ratio >= 50 ? "bg-skip" : "bg-fail",
          )}
          style={{ width: `${ratio}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-dim">{hint}</p>
    </div>
  );
}
