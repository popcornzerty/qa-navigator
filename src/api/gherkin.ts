import type { GherkinScenario, GherkinStatus } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

export interface GherkinFilters {
  projectId?: string;
  userStoryId?: string;
  feature?: string;
  status?: GherkinStatus | "all";
}

function allScenarios(): { scenario: GherkinScenario; projectId: string }[] {
  return db.stories.flatMap((story) =>
    story.gherkinScenarios.map((scenario) => ({ scenario, projectId: story.projectId })),
  );
}

export const gherkinApi = {
  list(filters: GherkinFilters = {}): Promise<GherkinScenario[]> {
    return resolve(
      async () =>
        clone(
          allScenarios()
            .filter(({ scenario, projectId }) => {
              if (filters.projectId && projectId !== filters.projectId) return false;
              if (filters.userStoryId && scenario.userStoryId !== filters.userStoryId) return false;
              if (filters.feature && scenario.feature !== filters.feature) return false;
              if (filters.status && filters.status !== "all" && scenario.status !== filters.status)
                return false;
              return true;
            })
            .map(({ scenario }) => scenario),
        ),
      () => {
        const params = new URLSearchParams();
        if (filters.projectId) params.set("project_id", filters.projectId);
        if (filters.userStoryId) params.set("story_id", filters.userStoryId);
        if (filters.feature) params.set("feature", filters.feature);
        if (filters.status && filters.status !== "all") params.set("status", filters.status);
        return http<GherkinScenario[]>(`/gherkin?${params.toString()}`);
      },
    );
  },

  update(scenarioId: string, patch: Partial<GherkinScenario>): Promise<GherkinScenario> {
    return resolve(
      async () => {
        const entry = allScenarios().find(({ scenario }) => scenario.id === scenarioId);
        if (!entry) throw new Error(`Scenario ${scenarioId} not found`);
        Object.assign(entry.scenario, patch);
        return clone(entry.scenario);
      },
      () =>
        http<GherkinScenario>(`/gherkin/${scenarioId}`, {
          method: "PATCH",
          body: JSON.stringify(patch),
        }),
    );
  },

  validate(scenarioId: string): Promise<GherkinScenario> {
    return resolve(
      async () => {
        const entry = allScenarios().find(({ scenario }) => scenario.id === scenarioId);
        if (!entry) throw new Error(`Scenario ${scenarioId} not found`);
        entry.scenario.status = "valid";
        return clone(entry.scenario);
      },
      () => http<GherkinScenario>(`/gherkin/${scenarioId}/validate`, { method: "POST" }),
    );
  },

  generatePlaywright(scenarioId: string): Promise<{ jobId: string; status: string }> {
    return resolve(
      async () => {
        const entry = allScenarios().find(({ scenario }) => scenario.id === scenarioId);
        if (entry) entry.scenario.status = "automated";
        return { jobId: `job_${Math.random().toString(36).slice(2, 8)}`, status: "queued" };
      },
      () =>
        http<{ jobId: string; status: string }>(`/gherkin/${scenarioId}/playwright`, {
          method: "POST",
        }),
    );
  },
};

/** Pure formatter — keeps Gherkin rendering logic out of components. */
export function formatGherkin(scenario: GherkinScenario): string {
  const lines: string[] = [`Feature: ${scenario.feature}`, "", `  Scenario: ${scenario.scenario}`];
  scenario.given.forEach((step, i) => lines.push(`    ${i === 0 ? "Given" : "And"} ${step}`));
  scenario.when.forEach((step, i) => lines.push(`    ${i === 0 ? "When" : "And"} ${step}`));
  scenario.then.forEach((step, i) => lines.push(`    ${i === 0 ? "Then" : "And"} ${step}`));
  return lines.join("\n");
}

/** Parses an edited Gherkin block back into structured steps. */
export function parseGherkin(text: string): Pick<GherkinScenario, "given" | "when" | "then"> {
  const given: string[] = [];
  const when: string[] = [];
  const then: string[] = [];
  let bucket: string[] | null = null;

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (/^Given /i.test(line)) {
      bucket = given;
      given.push(line.slice(6).trim());
    } else if (/^When /i.test(line)) {
      bucket = when;
      when.push(line.slice(5).trim());
    } else if (/^Then /i.test(line)) {
      bucket = then;
      then.push(line.slice(5).trim());
    } else if (/^And /i.test(line) && bucket) {
      bucket.push(line.slice(4).trim());
    }
  }

  return { given, when, then };
}
