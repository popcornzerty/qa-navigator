import type { TestInventory, ReportIngestion } from "../types/models";
import { http, resolve } from "./client";
import * as db from "./mock/data";

export const inventoryApi = {
  /** Every test the engine knows about, grouped by the file it lives in. */
  get(projectId?: string): Promise<TestInventory> {
    return resolve(
      async () => {
        const tests = db.tests.filter((t) => !projectId || t.projectId === projectId);
        const suites = new Map<string, TestInventory["suites"][number]>();
        for (const test of tests) {
          const key = `${test.kind ?? "e2e"}:${test.file}`;
          const entry = suites.get(key) ?? {
            kind: test.kind ?? "e2e",
            framework: test.framework ?? "playwright",
            suite: test.file,
            tests: 0,
            passed: 0,
            failed: 0,
            skipped: 0,
            notRun: 0,
            durationMs: 0,
            lastRun: null,
            origins: [],
          };
          entry.tests += 1;
          if (test.status === "passed") entry.passed += 1;
          else if (test.status === "failed") entry.failed += 1;
          else if (test.status === "skipped") entry.skipped += 1;
          else entry.notRun += 1;
          suites.set(key, entry);
        }
        const list = [...suites.values()];
        const sum = (field: keyof (typeof list)[number]) =>
          list.reduce((total, item) => total + (item[field] as number), 0);
        const executed = sum("passed") + sum("failed");
        return {
          projectId: projectId ?? "",
          totals: {
            suites: list.length,
            tests: sum("tests"),
            passed: sum("passed"),
            failed: sum("failed"),
            skipped: sum("skipped"),
            notRun: sum("notRun"),
            durationMs: 0,
            passRate: executed ? (sum("passed") / executed) * 100 : null,
          },
          suites: list,
        };
      },
      () => http<TestInventory>(`/inventory${projectId ? `?project_id=${projectId}` : ""}`),
    );
  },

  /** Hand the engine a JUnit XML report a runner produced. */
  ingest(projectId: string, xml: string): Promise<ReportIngestion> {
    return resolve(
      async () => ({
        kind: "backend" as const,
        framework: "pytest",
        matched: 0,
        created: 0,
        durationMs: 0,
        passed: 0,
        failed: 0,
        skipped: 0,
      }),
      () =>
        http<ReportIngestion>(`/projects/${projectId}/reports`, {
          method: "POST",
          headers: { "Content-Type": "application/xml" },
          body: xml,
        }),
    );
  },
};
