import type { AnalysisJob, AnalysisStep, Feature } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

const ORDER: AnalysisStep[] = db.analysisSteps.map((step) => ({ ...step }));

function freshSteps(): AnalysisStep[] {
  return ORDER.map((step, index) => ({
    ...step,
    status: index === 0 ? "running" : "pending",
  }));
}

function advance(job: AnalysisJob): AnalysisJob {
  const runningIndex = job.steps.findIndex((s) => s.status === "running");
  if (runningIndex === -1) return job;

  job.steps[runningIndex] = { ...job.steps[runningIndex]!, status: "completed" };
  const next = job.steps[runningIndex + 1];
  if (next) {
    job.steps[runningIndex + 1] = { ...next, status: "running" };
  }

  const completed = job.steps.filter((s) => s.status === "completed").length;
  job.progress = Math.round((completed / job.steps.length) * 100);
  job.status = completed === job.steps.length ? "completed" : "running";
  return job;
}

export const analysisApi = {
  /** Current (or last known) analysis job for a project. */
  current(projectId: string): Promise<AnalysisJob> {
    return resolve(
      async () => {
        let job = db.jobs.get(projectId);
        if (!job) {
          job = {
            jobId: `job_${projectId.slice(-5)}`,
            projectId,
            status: "running",
            progress: 62,
            startedAt: new Date().toISOString(),
            steps: db.analysisSteps.map((step) => ({ ...step })),
          };
          db.jobs.set(projectId, job);
        }
        return clone(job);
      },
      () => http<AnalysisJob>(`/analyses/current?project_id=${projectId}`),
    );
  },

  start(projectId: string): Promise<AnalysisJob> {
    return resolve(
      async () => {
        const job: AnalysisJob = {
          jobId: `job_${Math.random().toString(36).slice(2, 8)}`,
          projectId,
          status: "running",
          progress: 0,
          startedAt: new Date().toISOString(),
          steps: freshSteps(),
        };
        db.jobs.set(projectId, job);
        return clone(job);
      },
      () =>
        http<AnalysisJob>("/analyses", {
          method: "POST",
          body: JSON.stringify({ project_id: projectId }),
        }),
    );
  },

  /** Poll a job. In mock mode each poll advances one pipeline step. */
  poll(projectId: string, jobId: string): Promise<AnalysisJob> {
    return resolve(
      async () => {
        const job = db.jobs.get(projectId);
        if (!job) throw new Error(`Job ${jobId} not found`);
        return clone(advance(job));
      },
      () => http<AnalysisJob>(`/jobs/${jobId}`),
    );
  },

  features(projectId: string): Promise<Feature[]> {
    return resolve(
      async () => clone(db.featureList.filter((f) => f.projectId === projectId)),
      () => http<Feature[]>(`/features?project_id=${projectId}`),
    );
  },
};
