import type { AcceptanceCriterion, StoryStatus, UserStory } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

export interface StoryFilters {
  projectId?: string;
  featureId?: string;
  status?: StoryStatus | "all";
  search?: string;
}

export const storiesApi = {
  list(filters: StoryFilters = {}): Promise<UserStory[]> {
    return resolve(
      async () => {
        const search = filters.search?.toLowerCase().trim();
        return clone(
          db.stories.filter((story) => {
            if (filters.projectId && story.projectId !== filters.projectId) return false;
            if (filters.featureId && story.featureId !== filters.featureId) return false;
            if (filters.status && filters.status !== "all" && story.status !== filters.status)
              return false;
            if (search && !`${story.id} ${story.title} ${story.featureName}`.toLowerCase().includes(search))
              return false;
            return true;
          }),
        );
      },
      () => {
        const params = new URLSearchParams();
        if (filters.projectId) params.set("project_id", filters.projectId);
        if (filters.featureId) params.set("feature_id", filters.featureId);
        if (filters.status && filters.status !== "all") params.set("status", filters.status);
        if (filters.search) params.set("search", filters.search);
        return http<UserStory[]>(`/stories?${params.toString()}`);
      },
    );
  },

  get(storyId: string): Promise<UserStory> {
    return resolve(
      async () => {
        const story = db.stories.find((s) => s.id === storyId);
        if (!story) throw new Error(`Story ${storyId} not found`);
        return clone(story);
      },
      () => http<UserStory>(`/stories/${storyId}`),
    );
  },

  updateStatus(storyId: string, status: StoryStatus): Promise<UserStory> {
    return resolve(
      async () => {
        const story = db.stories.find((s) => s.id === storyId);
        if (!story) throw new Error(`Story ${storyId} not found`);
        story.status = status;
        return clone(story);
      },
      () =>
        http<UserStory>(`/stories/${storyId}`, {
          method: "PATCH",
          body: JSON.stringify({ status }),
        }),
    );
  },

  updateCriterion(
    storyId: string,
    criterionId: string,
    patch: Partial<Pick<AcceptanceCriterion, "text" | "covered">>,
  ): Promise<UserStory> {
    return resolve(
      async () => {
        const story = db.stories.find((s) => s.id === storyId);
        if (!story) throw new Error(`Story ${storyId} not found`);
        const criterion = story.acceptanceCriteria.find((c) => c.id === criterionId);
        if (!criterion) throw new Error(`Criterion ${criterionId} not found`);
        Object.assign(criterion, patch);
        return clone(story);
      },
      () =>
        http<UserStory>(`/stories/${storyId}/acceptance-criteria/${criterionId}`, {
          method: "PATCH",
          body: JSON.stringify(patch),
        }),
    );
  },

  syncToJira(storyId: string): Promise<UserStory> {
    return resolve(
      async () => {
        const story = db.stories.find((s) => s.id === storyId);
        if (!story) throw new Error(`Story ${storyId} not found`);
        story.jiraKey = story.jiraKey ?? `ATL-${Math.floor(600 + Math.random() * 99)}`;
        story.status = "created";
        return clone(story);
      },
      () => http<UserStory>(`/stories/${storyId}/jira-sync`, { method: "POST" }),
    );
  },
};
