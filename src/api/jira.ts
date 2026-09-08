import type { JiraImportInput, JiraImportResult, UserStory } from "../types/models";
import { clone, http, resolve } from "./client";
import * as db from "./mock/data";

/** Issues the mock backend pretends to find in Jira. */
const MOCK_ISSUES: { jiraKey: string; title: string; description: string; criteria: string[] }[] = [
  {
    jiraKey: "ATL-604",
    title: "Appliquer un code promotionnel au panier",
    description:
      "En tant que client, je veux saisir un code promotionnel afin de bénéficier d'une remise.",
    criteria: [
      "Le champ code promotionnel est visible dans le panier.",
      "Un code valide applique la remise au total.",
      "Un code expiré affiche un message d'erreur explicite.",
    ],
  },
  {
    jiraKey: "ATL-611",
    title: "Consulter l'historique des commandes",
    description:
      "En tant que client, je veux consulter mes commandes passées afin de suivre leur livraison.",
    criteria: [
      "Les commandes sont listées de la plus récente à la plus ancienne.",
      "Chaque commande affiche son statut de livraison.",
    ],
  },
];

function defaultJql(projectKey: string | null): string {
  return `project = "${projectKey ?? "ATL"}" AND issuetype = Story ORDER BY created DESC`;
}

export const jiraApi = {
  /**
   * Imports Jira issues as User Stories. Read-only: nothing is written back to Jira.
   *
   * Credentials live in the backend environment, never in the browser — which is why this
   * call carries no authentication of its own.
   */
  importStories(projectId: string, input: JiraImportInput = {}): Promise<JiraImportResult> {
    return resolve(
      async () => {
        const project = db.projects.find((p) => p.id === projectId);
        const jql = input.jql?.trim() || defaultJql(project?.jiraProject ?? null);
        const imported: string[] = [];
        const updated: string[] = [];

        for (const issue of MOCK_ISSUES.slice(0, input.maxResults ?? MOCK_ISSUES.length)) {
          const existing = db.stories.find(
            (story) => story.projectId === projectId && story.jiraKey === issue.jiraKey,
          );
          if (existing) {
            existing.title = issue.title;
            updated.push(existing.id);
            continue;
          }

          const id = `US-${String(200 + db.stories.length).padStart(3, "0")}`;
          const story: UserStory = {
            id,
            projectId,
            featureId: "",
            featureName: "Import Jira",
            epic: "Backlog Jira",
            title: issue.title,
            description: issue.description,
            // An imported story is a fact written by a human, not an inference.
            confidence: 1,
            sourceFiles: [],
            acceptanceCriteria: issue.criteria.map((text, index) => ({
              id: `${id}-AC-${String(index + 1).padStart(2, "0")}`,
              userStoryId: id,
              text,
              covered: false,
            })),
            gherkinScenarios: [],
            jiraKey: issue.jiraKey,
            status: "created",
          };
          db.stories.push(story);
          imported.push(id);
        }

        return clone({
          imported: imported.length,
          updated: updated.length,
          storyIds: [...imported, ...updated],
          jql,
        });
      },
      () =>
        http<JiraImportResult>(`/projects/${projectId}/jira-import`, {
          method: "POST",
          body: JSON.stringify({
            ...(input.jql ? { jql: input.jql } : {}),
            ...(input.maxResults ? { maxResults: input.maxResults } : {}),
          }),
        }),
    );
  },
};
