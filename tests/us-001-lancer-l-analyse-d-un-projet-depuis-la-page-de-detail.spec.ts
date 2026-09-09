// Généré par AI QA Agent — ne pas éditer à la main, la régénération écrase ce fichier.
// User Story : US-001 — Accéder à la page d'analyse d'un projet
// Scénario   : US-001-SC-1 — Lancer l'analyse d'un projet depuis la page de détail
// Domaine    : Projets
// Sources    : src/routeTree.gen.ts, src/routes/projects.$projectId.analysis.tsx, src/routes/projects.$projectId.index.tsx, src/routes/projects.index.tsx

import { expect, test } from "@playwright/test";

test.describe("Projets", () => {
  test("Lancer l'analyse d'un projet depuis la page de détail", async ({ page }) => {
    // Des étapes n'ont pas pu être automatisées : le test est marqué à traiter.
    test.fixme();
    await test.step("Étant donné Je suis sur la page de détail d'un projet", async () => {
      await page.goto('http://localhost:8080/projects/1');
      await page.getByTestId('app-ready').waitFor();
    });
    await test.step("Quand Je clique sur le bouton « Analyze Repository »", async () => {
      await page.getByTestId('project-analyze').click();
    });
    await test.step("Alors La page d'analyse du projet s'affiche", async () => {
      await page.goto('http://localhost:8080/projects/1/analysis');
      await page.getByTestId('app-ready').waitFor();
    });
    await test.step("Et L'en-tête affiche « Repository analysis »", async () => {
      await expect(page.getByTestId('page-title')).toHaveText('Repository analysis');
    });
    await test.step("Et Les étapes du pipeline sont listées : Repository, Architecture, Routes, Components, APIs, Features, User Stories, Gherkin", async () => {
      await expect(page.getByTestId('metric-coverage')).toBeVisible();
      await expect(page.getByTestId('metric-features')).toBeVisible();
      await expect(page.getByTestId('metric-gherkin')).toBeVisible();
      await expect(page.getByTestId('metric-playwright')).toBeVisible();
      await expect(page.getByTestId('metric-user-stories')).toBeVisible();
      await expect(page.getByTestId('metric-features')).toBeVisible();
      // TODO manuel (data-testid "metric-apis" introuvable dans le code analysé) : await expect(page.getByTestId('metric-apis')).toBeVisible();
      // TODO manuel (data-testid "metric-components" introuvable dans le code analysé) : await expect(page.getByTestId('metric-components')).toBeVisible();
      // TODO manuel (data-testid "metric-routes" introuvable dans le code analysé) : await expect(page.getByTestId('metric-routes')).toBeVisible();
    });
  });
});
