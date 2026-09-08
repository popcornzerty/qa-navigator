# AI QA Agent — QA Engine

Independent FastAPI service backing the `qa-navigator` frontend
(<https://github.com/popcornzerty/qa-navigator>). It analyses JS/TS/React repositories —
a directory on this machine, or a public git repository it clones — and exposes the
whole `/api/v1` surface the UI consumes.

## Run locally

```bash
cd qa-engine
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -e ".[dev]"
copy .env.example .env
uvicorn qa_engine.main:app --app-dir src --reload
```

Interactive docs: <http://127.0.0.1:8000/docs>. OpenAPI JSON: `/openapi.json`.

> The service reads `.env` **at startup only**. After changing `CORS_ORIGINS`, restart it
> — a stale process is why the browser reports `Disallowed CORS origin`.

The frontend dev server runs on port 8080, so `.env` needs:

```
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
```

## Implementation status

| Area | State |
| --- | --- |
| Local repository scan, symbol extraction, feature grouping | ✅ implemented |
| Projects, settings, analyses, jobs, features | ✅ implemented |
| Stories, Gherkin, tests, coverage, dashboard (read + edit) | ✅ implemented, empty until generation runs |
| User Story / Gherkin generation via Ollama | ✅ implemented (see *Generation*) |
| Playwright `.spec.ts` generation | ✅ implemented (see *Playwright generation*) |
| Playwright execution | ✅ implemented (see *Execution*) |
| Jira import (read-only) | ✅ implemented (see *Jira import*) |
| Jira sync (writing back) | ⛔ not implemented — `POST /stories/{id}/jira-sync` returns `501` |
| Public git repository cloning | ✅ implemented (see *Repository sources*) |

Endpoints that cannot honour a request yet return **501 Not Implemented** with an explicit
message rather than pretending to succeed.

## API contract

Every route is prefixed with `/api/v1`, takes and returns JSON, and serialises in
**camelCase** to match the frontend's `src/types/models.ts`.

```
GET    /projects                                  POST /projects
GET    /projects/{id}                             GET  /projects/{id}/stats
GET    /projects/{id}/settings                    PATCH /projects/{id}/settings
POST   /projects/{id}/analyses                    GET  /projects/{id}/analyses
POST   /analyses                                  GET  /analyses/current?project_id=
GET    /analyses/{id}                             GET  /jobs/{id}
GET    /features?project_id=                      GET  /projects/{id}/features
GET    /stories                                   GET  /stories/{id}
PATCH  /stories/{id}                              PATCH /stories/{id}/acceptance-criteria/{cid}
POST   /stories/{id}/jira-sync            (501)   POST /projects/{id}/jira-import
GET    /gherkin                                   PATCH /gherkin/{id}
POST   /gherkin/{id}/validate                     POST /gherkin/{id}/playwright
GET    /tests                                     GET  /tests/{id}
POST   /tests/{id}/run                            POST /tests/{id}/regenerate
GET    /coverage?project_id=                      GET  /dashboard?project_id=
GET    /health
```

**Route ordering matters**: `/analyses/current` is declared before `/analyses/{analysis_id}`.
Reversing them makes Starlette match `current` as an id and return 404 on every poll.

## Analysis pipeline

An analysis is queued and processed by FastAPI's background-task runner. Its `steps` and
`progress` are persisted on the row, so polling `/analyses/current` returns real backend
state rather than a simulation:

```
repository → architecture → routes → components → apis → features → stories → gherkin
```

When generation is disabled or the runtime is unreachable, the last two steps report the
reason explicitly (`pending` or `failed`) and the analysis keeps the deterministic results
it produced, rather than claiming success.

Production deployments can replace the in-process runner with Celery/RQ without changing
the HTTP contract.

## Generation

Steps `stories` and `gherkin` call the local Ollama runtime. The split is deliberate:

| Deterministic (analyzer) | Generated (model) |
| --- | --- |
| files, routes, components, API calls, `data-testid` anchors | story title and description |
| which feature a story belongs to | acceptance criteria |
| confidence score | Gherkin steps |
| source files attached to the story | — |

A story therefore always traces back to real evidence: a hallucinated route cannot enter
the backlog, and confidence is never asked of the model.

Ids are human-readable and stable: `US-001`, `US-001-AC-01`, `US-001-SC-1`.

**Re-running an analysis** regenerates only stories that are still untouched
(`origin=generated` **and** `status=draft`). Anything approved, edited, synced to Jira or
imported survives.

### Throughput

Generation dominates the analysis time, and Ollama only accelerates on NVIDIA (CUDA) or
AMD (ROCm) hardware. Check where the model actually runs:

```bash
curl -s http://127.0.0.1:11434/api/ps
```

A `size_vram` of `0` means CPU inference. Measured on this workstation with
`qwen3.5:4b` on CPU: **~43 tok/s prompt, ~7.8 tok/s generation**, i.e. roughly
**6 minutes per functional domain** (3 stories + their scenarios). On a CUDA GPU the same
work runs one to two orders of magnitude faster.

`GENERATION_MAX_FEATURES` bounds how many domains one analysis generates for (highest
confidence first), so a run stays predictable. Results are committed per feature, so the
backlog fills progressively while the job is still running. `GENERATION_ENABLED=false`
turns generation off entirely and keeps the deterministic analysis — that is also what the
test suite uses, so `pytest` never reaches the model.

### Quality notes

Small models pad up to the requested number of scenarios by restating one scenario under a
new title; identical steps are therefore deduplicated server-side regardless of the title.
Prompts explicitly forbid URLs, route paths, selectors, component and file names in
user-facing text. A larger local model (for example `gemma-4-12B`, 6.9 GB) noticeably
improves wording at the cost of throughput — switch with `OLLAMA_MODEL`.

## Playwright generation

`POST /gherkin/{id}/playwright` queues generation of one `.spec.ts` (and
`POST /tests/{id}/regenerate` re-runs it). Both return `202` with a job handle; on CPU
inference one scenario takes roughly a minute.

The file skeleton is deterministic — traceability header, `test.describe`, one
`test.step` per Gherkin step. The model only fills each step body, and **every line it
returns is validated** before being written:

- it must look like a Playwright statement (`page.…`, `expect(…)`, `test.…`);
- it may not import, spawn a process, touch the filesystem or evaluate a string;
- it may only use `data-testid` values the analyzer actually found in the code.

A rejected line becomes a commented `// TODO manuel (<reason>)` and the test is marked
`test.fixme()`. **A test that cannot really drive the app is worth more as an explicit red
flag than as a green test asserting nothing.** `result.consoleOutput` lists the unresolved
steps.

### Where files are written

`<repository>/<testDirectory>/<file>.spec.ts`, **inside the analysed repository**, so the
project's own `playwright.config.ts` picks them up and a run behaves exactly like CI.
Generated files carry a header saying they are generated, and regeneration overwrites
them. The full source is also stored on the `playwright_tests` row.

### Getting runnable tests: instrument the app

Generation quality is capped by what the code exposes. An application with **no
`data-testid` attributes** gives the model nothing stable to target, and most steps come
back as `TODO`. Adding `data-testid` to the interactive elements under test is the single
highest-impact change — the analyzer already collects them and feeds them to the
generator as the allowed selector vocabulary.

## Execution

`POST /tests/{id}/run` shells out to the project's own runner:

```bash
npx playwright test <spec> --reporter=json
```

run from the repository root, with `PLAYWRIGHT_BASE_URL` taken from the project's
Playwright settings. The **JSON report is the source of truth** — a non-zero exit code is
normal when a test fails, so the report decides the outcome, not the exit status.

What the engine persists from a run:

| Field | Source |
| --- | --- |
| `status` | last result (`timedOut` and `interrupted` are folded into `failed`) |
| `durationMs`, `lastRun` | reporter duration, naive-UTC timestamp |
| `errorMessage` | assertion message, ANSI colour codes stripped |
| `screenshot`, `trace` | attachment paths, relative to the repository |
| `consoleOutput` | `stdout` / `stderr` captured by the reporter |

A passing run marks that story's acceptance criteria as covered, which feeds straight into
the coverage report.

`CI` is deliberately **not** forced in the child environment: it would switch the project
config to two retries and triple the duration of every failing run. Set it yourself to get
CI behaviour.

### Prerequisites in the analysed project

```bash
npm install -D @playwright/test
npx playwright install chromium
```

plus a `playwright.config.ts` whose `testDir` matches the project's configured test
directory. `qa-navigator` is set up this way: `baseURL` reads `PLAYWRIGHT_BASE_URL`,
`trace: "retain-on-failure"`, `screenshot: "only-on-failure"`, and a `webServer` block that
reuses an already-running dev server and starts one otherwise.

## Repository sources

A project is created with `repositorySource` set to `local` or `github`.

**`local`** — `repository` is a path on the machine running the engine.
`ALLOWED_REPOSITORY_ROOTS` restricts which paths are acceptable.

**`github`** — `repository` is a public git URL. Creation only *validates* the URL and
reserves a deterministic directory (`work/clones/<host>-<owner>-<repo>`); the clone itself
happens in the analysis pipeline's `repository` step, which already reports progress. That
step shows the checked-out revision, e.g. `84 fichiers analysés · main@4d1aa1a`.

Clones are `--depth 1 --single-branch`: the engine only reads the current state of one
branch. A later analysis fetches and hard-resets instead of re-cloning.

### URL vetting

Only `http` and `https` are accepted, and the scheme is checked **before** any convenience
rewriting. This matters: prepending `https://` to anything lacking `://` would smuggle
`ext::sh -c '…'` past the check, and git's transport-helper syntax turns that into command
execution. Also refused: URLs containing credentials (only public repositories are
supported, and the engine holds no secrets), whitespace, a leading `-` (which git would
read as an option), and hostnames that are not plausible.

`GIT_TERMINAL_PROMPT=0` is set for every git call, so a private repository fails fast
instead of hanging on a credential prompt.

## Jira import

`POST /projects/{id}/jira-import` pulls Jira issues in as User Stories. **Read-only**:
nothing is ever written back. Pushing a story to Jira writes to a system outside this
project, so it stays unimplemented until explicitly asked for.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/projects/<id>/jira-import      -H "Content-Type: application/json" -d '{"maxResults": 50}'
```

With no `jql`, the project's Jira key drives the default query:
`project = "ATL" AND issuetype = Story ORDER BY created DESC`. Pass your own `jql` to
narrow it.

### Credentials

Set them in the engine's `.env` — **never** in the frontend, a request payload, or a URL:

```
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=<token from id.atlassian.com/manage-profile/security/api-tokens>
```

They are read server-side, sent as HTTP Basic auth to Jira, and never returned in a
response or written to a log. Without them the endpoint answers `503` with an explanation;
if Jira rejects them it answers `502`.

### What is mapped

| Jira | Story |
| --- | --- |
| issue key | `jiraKey`, and the story status becomes `created` |
| summary | title |
| description (ADF) | description, flattened to text |
| parent summary | epic |
| acceptance criteria | see below |

Jira has **no standard acceptance-criteria field**. The importer looks in two places, in
order: the custom field named by `JIRA_ACCEPTANCE_CRITERIA_FIELD`, then a headed bullet
list in the description (`Critères d'acceptation`, `Acceptance Criteria`, `Conditions
d'acceptation`; `-`, `*`, `1.` and `AC-01` bullets are all recognised).

An imported story carries confidence `1.0` — it is a human-written fact, not an inference.

Re-importing is **non-destructive**: an existing story is refreshed by its Jira key, and
criteria are added rather than replaced, so local edits are never silently discarded.

## Detection rules

`analyzer.py` extracts **evidence**, never interpretation:

- `route` — `createFileRoute("/x")`, `<Route path="/x">`, `path: "/x"`
- `component` — a PascalCase declaration whose body actually contains JSX. Screaming-snake
  constants (`ORDER`, `API_MODE`) are excluded; they used to be reported as components.
- `hook`, `api_call`, `form`, and `testid` (`data-testid` values, collected so Playwright
  generation can later target real selectors instead of guessing them)

`features.py` then groups those symbols into **functional domains** — a repository with 300
components typically exposes under a dozen testable areas. Grouping is deterministic and
every feature traces back to the files that produced it. Detection is pattern-based, not an
AST, and never executes repository code.

The scanner honours the repository's root `.gitignore` (when `pathspec` is installed) and
always skips `.git`, `node_modules`, `dist`, `build`, caches and binaries.

## Database

SQLite by default (`DATABASE_URL`). `qa_engine/migrations.py` runs at startup and performs
minimal schema evolution: it adds columns that appeared on the models and recreates derived
tables whose shape changed. **Introduce Alembic before the first shared deployment** — this
helper is a development convenience, not a migration tool.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./qa_engine.db` | Persistence |
| `API_V1_PREFIX` | `/api/v1` | Route prefix |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allowed origins |
| `ALLOWED_REPOSITORY_ROOTS` | *(empty)* | Restricts which local paths may be analysed |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local generation runtime |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Model used for generation |
| `GENERATION_LANGUAGE` | `fr` | Language of generated stories and Gherkin |
| `GENERATION_ENABLED` | `true` | Turns the two generation steps on or off |
| `GENERATION_MAX_FEATURES` | `3` | Domains generated per analysis; `0` means all |
| `JIRA_BASE_URL` | *(empty)* | e.g. `https://acme.atlassian.net` |
| `JIRA_EMAIL` | *(empty)* | Atlassian account email |
| `JIRA_API_TOKEN` | *(empty)* | Atlassian API token |
| `JIRA_ACCEPTANCE_CRITERIA_FIELD` | *(empty)* | Custom field id holding criteria |
| `WORK_DIRECTORY` | `work` | Clones and generated artifacts |

## Tests

```bash
pytest
```
