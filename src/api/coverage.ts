import type { CoverageGap, CoverageReport } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

function buildReport(projectId?: string): CoverageReport {
  const stories = db.stories.filter((s) => !projectId || s.projectId === projectId);
  const scenarios = stories.flatMap((s) => s.gherkinScenarios);
  const tests = db.tests.filter((t) => !projectId || t.projectId === projectId);
  const criteria = stories.flatMap((s) => s.acceptanceCriteria);
  const covered = criteria.filter((c) => c.covered).length;

  const automatedStoryIds = new Set(tests.map((t) => t.userStoryId));
  const gaps: CoverageGap[] = stories
    .flatMap((story) =>
      story.acceptanceCriteria
        .filter((criterion) => !criterion.covered)
        .map<CoverageGap>((criterion) => ({
          id: criterion.id,
          reference: criterion.id,
          label: criterion.text,
          reason: automatedStoryIds.has(story.id)
            ? `${story.id} is automated but this criterion has no covering scenario.`
            : `${story.id} has no Playwright automation yet.`,
          severity: story.status === "approved" || story.status === "created" ? "critical" : "warning",
        })),
    )
    .slice(0, 12);

  return {
    projectId: projectId ?? "all",
    userStories: {
      total: stories.length,
      withGherkin: stories.filter((s) => s.gherkinScenarios.length > 0).length,
      automated: stories.filter((s) => automatedStoryIds.has(s.id)).length,
    },
    acceptanceCriteria: { total: criteria.length, covered },
    gherkin: {
      total: scenarios.length,
      valid: scenarios.filter((s) => s.status === "valid" || s.status === "automated").length,
    },
    automation: { total: tests.length, passing: tests.filter((t) => t.status === "passed").length },
    coverage: criteria.length === 0 ? 0 : Math.round((covered / criteria.length) * 1000) / 10,
    gaps,
  };
}

export const coverageApi = {
  get(projectId?: string): Promise<CoverageReport> {
    return resolve(
      async () => clone(buildReport(projectId)),
      () => http<CoverageReport>(`/coverage${projectId ? `?project_id=${projectId}` : ""}`),
    );
  },
};
