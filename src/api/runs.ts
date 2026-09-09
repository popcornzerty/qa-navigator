import type { TestRun, TestRunDetail, TestStatus } from "../types/models";
import { http, resolve } from "./client";

export interface RunFilters {
  projectId?: string;
  testId?: string;
  status?: TestStatus | "all";
  limit?: number;
}

export const runsApi = {
  /** Recent executions, newest first. */
  list(filters: RunFilters = {}): Promise<TestRun[]> {
    return resolve(
      // The mock dataset has no execution history: it is a snapshot, not a recording.
      async () => [],
      () => {
        const params = new URLSearchParams();
        if (filters.projectId) params.set("project_id", filters.projectId);
        if (filters.testId) params.set("test_id", filters.testId);
        if (filters.status && filters.status !== "all") params.set("status", filters.status);
        if (filters.limit) params.set("limit", String(filters.limit));
        return http<TestRun[]>(`/runs?${params.toString()}`);
      },
    );
  },

  /** One execution, with the output produced after line `since`.
   *
   *  Pass back the `lineCount` already held so a poll carries only what is new — the log
   *  of a run that starts its own dev server grows for minutes.
   */
  get(runId: string, since = 0): Promise<TestRunDetail> {
    return resolve(
      async () => {
        throw new Error("Execution history is not available in mock mode");
      },
      () => http<TestRunDetail>(`/runs/${runId}?since=${since}`),
    );
  },
};
