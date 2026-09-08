// Généré par AI QA Agent — ne pas éditer à la main, la régénération écrase ce fichier.
// User Story : US-001 — Accéder à la page d'analyse d'un projet
// Scénario   : US-001-SC-1 — Accéder à la page d'analyse depuis la liste des projets
// Domaine    : Projets
// Sources    : src/routeTree.gen.ts, src/routes/projects.$projectId.analysis.tsx, src/routes/projects.$projectId.index.tsx, src/routes/projects.index.tsx

import { expect, test } from "@playwright/test";

test.describe("Projets", () => {
  test("Accéder à la page d'analyse depuis la liste des projets", async ({ page }) => {
    // Des étapes n'ont pas pu être automatisées : le test est marqué à traiter.
    test.fixme();
    await test.step("Étant donné L'utilisateur est sur la page de détail d'un projet existant.", async () => {
      // TODO manuel : étape non automatisable avec les éléments détectés
    });
    await test.step("Et Le bouton 'Analyser' est visible dans l'interface.", async () => {
      page.getByTestId('project-analyze').click();
    });
    await test.step("Quand L'utilisateur clique sur le bouton 'Analyser'.", async () => {
      expect(page).toHaveURL('/projects/$projectId/analysis');
    });
    await test.step("Alors La route '/projects/$projectId/analysis' s'affiche.", async () => {
      expect(page.getByText('Repository analysis — AI QA Agent')).toBeVisible();
    });
    await test.step("Et L'en-tête de la page affiche le titre 'Repository analysis — AI QA Agent'.", async () => {
      // TODO manuel : étape non automatisable avec les éléments détectés
    });
    await test.step("Et La liste des étapes du pipeline (repository, architecture, routes, etc.) est visible.", async () => {
      // TODO manuel : étape non automatisable avec les éléments détectés
    });
  });
});
