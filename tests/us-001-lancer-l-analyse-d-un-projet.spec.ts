// Généré par AI QA Agent — ne pas éditer à la main, la régénération écrase ce fichier.
// User Story : US-001 — Accéder à la page d'analyse d'un projet
// Scénario   : US-001-SC-1 — Lancer l'analyse d'un projet
// Domaine    : Projets
// Sources    : src/routeTree.gen.ts, src/routes/projects.$projectId.analysis.tsx, src/routes/projects.$projectId.index.tsx, src/routes/projects.index.tsx

import { expect, test } from "@playwright/test";

test.describe("Projets", () => {
  test("Lancer l'analyse d'un projet", async ({ page }) => {
    // Des étapes n'ont pas pu être automatisées : le test est marqué à traiter.
    test.fixme();
    await test.step("Étant donné Le testeur se trouve sur la page de détail d'un projet existant.", async () => {
      // TODO manuel : étape non automatisable avec les éléments détectés
    });
    await test.step("Et Le bouton 'Analyser' est visible dans l'interface.", async () => {
      // TODO manuel : étape non automatisable avec les éléments détectés
    });
    await test.step("Quand Le testeur clique sur le bouton 'Analyser'.", async () => {
      await page.getByTestId('project-open').click();
    });
    await test.step("Alors La vue change pour afficher la page d'analyse du projet.", async () => {
      await page.goto('/projects/$projectId/analysis');
      // TODO manuel (n'est pas une instruction Playwright) : if (await page.locator('app-ready').isVisible()) { await page.getByTestId('app-ready').waitFor(); }
    });
    await test.step("Et L'en-tête de la page affiche le titre 'Repository analysis — AI Agent'.", async () => {
      expect(page.getByText('Repository analysis — AI Agent')).toBeVisible();
    });
    await test.step("Et La liste des étapes du pipeline est visible.", async () => {
      // TODO manuel : étape non automatisable avec les éléments détectés
    });
  });
});
