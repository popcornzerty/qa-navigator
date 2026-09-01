import type { PlaywrightTest, TestStatus } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

export interface TestFilters {
  projectId?: string;
  userStoryId?: string;
  status?: TestStatus | "all";
}

export const testsApi = {
  list(filters: TestFilters = {}): Promise<PlaywrightTest[]> {
    return resolve(
      async () =>
        clone(
          db.tests.filter((test) => {
            if (filters.projectId && test.projectId !== filters.projectId) return false;
            if (filters.userStoryId && test.userStoryId !== filters.userStoryId) return false;
            if (filters.status && filters.status !== "all" && test.status !== filters.status)
              return false;
            return true;
          }),
        ),
      () => {
        const params = new URLSearchParams();
        if (filters.projectId) params.set("project_id", filters.projectId);
        if (filters.userStoryId) params.set("story_id", filters.userStoryId);
        if (filters.status && filters.status !== "all") params.set("status", filters.status);
        return http<PlaywrightTest[]>(`/tests?${params.toString()}`);
      },
    );
  },

  get(testId: string): Promise<PlaywrightTest> {
    return resolve(
      async () => {
        const test = db.tests.find((t) => t.id === testId);
        if (!test) throw new Error(`Test ${testId} not found`);
        return clone(test);
      },
      () => http<PlaywrightTest>(`/tests/${testId}`),
    );
  },

  /** Long-running execution: returns a job handle the UI can poll. */
  run(testId: string): Promise<{ jobId: string; status: string; progress: number }> {
    return resolve(
      async () => ({
        jobId: `job_${Math.random().toString(36).slice(2, 8)}`,
        status: "queued",
        progress: 0,
      }),
      () =>
        http<{ jobId: string; status: string; progress: number }>(`/tests/${testId}/run`, {
          method: "POST",
        }),
    );
  },

  regenerate(testId: string): Promise<{ jobId: string; status: string }> {
    return resolve(
      async () => ({ jobId: `job_${Math.random().toString(36).slice(2, 8)}`, status: "queued" }),
      () => http<{ jobId: string; status: string }>(`/tests/${testId}/regenerate`, { method: "POST" }),
    );
  },
};
