import type { DashboardSummary } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

export const dashboardApi = {
  summary(projectId?: string): Promise<DashboardSummary> {
    return resolve(
      async () => {
        const stories = db.stories.filter((s) => !projectId || s.projectId === projectId);
        const scenarios = stories.flatMap((s) => s.gherkinScenarios);
        const tests = db.tests.filter((t) => !projectId || t.projectId === projectId);
        const criteria = stories.flatMap((s) => s.acceptanceCriteria);
        const covered = criteria.filter((c) => c.covered).length;

        return clone<DashboardSummary>({
          projects: db.projects.length,
          activeProjects: db.projects.filter((p) => p.status !== "never_analyzed").length,
          userStories: stories.length,
          approvedStories: stories.filter((s) => s.status === "approved" || s.status === "created")
            .length,
          gherkinScenarios: scenarios.length,
          validGherkin: scenarios.filter((s) => s.status === "valid" || s.status === "automated")
            .length,
          automatedTests: tests.length,
          failingTests: tests.filter((t) => t.status === "failed").length,
          coverage: criteria.length === 0 ? 0 : Math.round((covered / criteria.length) * 1000) / 10,
          activity: db.activity,
        });
      },
      () => http<DashboardSummary>(`/dashboard${projectId ? `?project_id=${projectId}` : ""}`),
    );
  },
};
