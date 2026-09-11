# Alimenter l'état des lieux

L'écran **État des lieux** répond en lisant ce qui est enregistré : il n'exécute aucun
test. Les verdicts arrivent par un rapport JUnit XML, que ce soit depuis la pipeline ou
depuis un passage en local.

C'est ce qui rend l'inventaire indépendant du langage. JUnit XML est le format que tous
les runners produisent déjà — pytest, Playwright, Jest, Vitest, Go, Maven, PHPUnit — donc
l'outil n'a pas à piloter chacun d'eux pour savoir ce qui passe.

## Produire le rapport

| Runner     | Commande                                                        |
| ---------- | --------------------------------------------------------------- |
| pytest     | `pytest --junitxml=report.xml`                                    |
| Playwright | `PLAYWRIGHT_JUNIT_OUTPUT_NAME=report.xml playwright test --reporter=junit` |
| Vitest     | `vitest run --reporter=junit --outputFile=report.xml`             |
| Jest       | `jest --reporters=jest-junit`                                     |
| Go         | `go test ./... 2>&1 \| go-junit-report > report.xml`              |

## L'envoyer

Un seul appel, sans encodage ni dépendance :

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>/reports" \
  -H "Content-Type: application/xml" \
  --data-binary @report.xml
```

La réponse dit ce qui a été lu :

```json
{"kind":"backend","framework":"pytest","matched":5,"created":1020,
 "durationMs":49933,"passed":1025,"failed":0,"skipped":0}
```

`created` compte les tests que l'outil découvre par ce rapport — une suite backend n'est
pas quelque chose que l'analyse statique sait lire, donc elle apparaît à la première
ingestion. `matched` compte ceux qu'il connaissait déjà et dont il met le verdict à jour.

## Dans une pipeline

L'étape se place après les tests et ne doit jamais faire échouer le job : un inventaire
non mis à jour est un inconvénient, pas une régression.

```yaml
- name: Tests backend
  run: pytest --junitxml=backend.xml
- name: Tests navigateur
  run: npx playwright test --reporter=junit
  env:
    PLAYWRIGHT_JUNIT_OUTPUT_NAME: e2e.xml
- name: Publier l'état des lieux
  if: always()
  continue-on-error: true
  run: |
    for f in backend.xml e2e.xml; do
      curl -sS -X POST "$QA_NAVIGATOR_URL/api/v1/projects/$QA_PROJECT_ID/reports" \
        -H "Content-Type: application/xml" --data-binary "@$f" || true
    done
```

## Ce que l'outil déduit tout seul

- **La famille** (`backend` ou `e2e`) vient des fichiers nommés dans le rapport, pas d'un
  champ à remplir : personne ne devrait avoir à classer un artefact de CI.
- **Le runner** est déduit de la même façon, et ne sert qu'à l'affichage.
- **Le regroupement** se fait par fichier, parce que « quel fichier est au rouge » est la
  question qu'on pose en daily.

## Ce qu'il ne fait pas

Un test sans verdict n'est jamais compté comme un succès, et jamais comme un échec. Le
taux de réussite ne porte que sur ce qui a réellement tourné ; les tests jamais exécutés
sont affichés à côté, séparément. Compter « jamais lancé » comme un problème pousserait à
tout relancer avant chaque daily ; le compter comme un succès serait un mensonge.
