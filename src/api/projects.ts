import type { CreateProjectInput, Project, ProjectSettings, ProjectStats } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

function computeStats(projectId: string): ProjectStats {
  const stories = db.stories.filter((s) => s.projectId === projectId);
  const scenarios = stories.flatMap((s) => s.gherkinScenarios);
  const tests = db.tests.filter((t) => t.projectId === projectId);
  const criteria = stories.flatMap((s) => s.acceptanceCriteria);
  const covered = criteria.filter((c) => c.covered).length;

  return {
    features: db.featureList.filter((f) => f.projectId === projectId).length,
    userStories: stories.length,
    gherkinScenarios: scenarios.length,
    playwrightTests: tests.length,
    coverage: criteria.length === 0 ? 0 : Math.round((covered / criteria.length) * 1000) / 10,
  };
}

export const projectsApi = {
  list(): Promise<Project[]> {
    return resolve(
      async () => clone(db.projects),
      () => http<Project[]>("/projects"),
    );
  },

  get(projectId: string): Promise<Project> {
    return resolve(
      async () => {
        const project = db.projects.find((p) => p.id === projectId);
        if (!project) throw new Error(`Project ${projectId} not found`);
        return clone(project);
      },
      () => http<Project>(`/projects/${projectId}`),
    );
  },

  stats(projectId: string): Promise<ProjectStats> {
    return resolve(
      async () => computeStats(projectId),
      () => http<ProjectStats>(`/projects/${projectId}/stats`),
    );
  },

  create(input: CreateProjectInput): Promise<Project> {
    return resolve(
      async () => {
        const project: Project = {
          id: `prj-${Date.now().toString(36)}`,
          name: input.name,
          repository: input.repository,
          repositorySource: input.repositorySource,
          branch: input.branch,
          jiraProject: input.jiraProject,
          jiraConnection: input.jiraConnection,
          aiProvider: input.aiProvider,
          status: "never_analyzed",
          lastAnalysis: null,
          storyCount: 0,
          automatedTestCount: 0,
        };
        db.projects.push(project);
        db.settings.set(project.id, {
          projectId: project.id,
          name: project.name,
          repository: project.repository,
          branch: project.branch,
          github: {
            status: project.repositorySource === "github" ? "connected" : "disconnected",
            account: project.repositorySource === "github" ? "atlas-demo" : null,
          },
          jira: { status: project.jiraConnection, projectKey: project.jiraProject },
          ai: { provider: project.aiProvider, model: "qwen2.5-coder:14b", status: "connected" },
          playwright: {
            testDirectory: "tests",
            baseUrl: "https://staging.atlas-demo.test",
            browsers: ["chromium"],
            headless: true,
          },
        });
        return clone(project);
      },
      () => http<Project>("/projects", { method: "POST", body: JSON.stringify(input) }),
    );
  },

  settings(projectId: string): Promise<ProjectSettings> {
    return resolve(
      async () => {
        const value = db.settings.get(projectId);
        if (!value) throw new Error(`Settings for ${projectId} not found`);
        return clone(value);
      },
      () => http<ProjectSettings>(`/projects/${projectId}/settings`),
    );
  },

  updateSettings(projectId: string, patch: Partial<ProjectSettings>): Promise<ProjectSettings> {
    return resolve(
      async () => {
        const current = db.settings.get(projectId);
        if (!current) throw new Error(`Settings for ${projectId} not found`);
        const next = { ...current, ...patch } as ProjectSettings;
        db.settings.set(projectId, next);
        return clone(next);
      },
      () =>
        http<ProjectSettings>(`/projects/${projectId}/settings`, {
          method: "PATCH",
          body: JSON.stringify(patch),
        }),
    );
  },
};
