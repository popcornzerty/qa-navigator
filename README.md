# QA Navigator — AI QA Agent

A QA platform that tells you what your project's tests actually cover, and whether they
pass.

Point it at a repository and it will:

- **import the test suite the project already has** (Playwright), without rewriting it;
- **run any of those tests** from the interface, with the console streamed live and the
  history of every execution kept;
- **inventory every test, backend and browser**, from the JUnit XML reports your runners
  or your CI already produce (pytest, Playwright, Jest, Vitest, Go…);
- **measure coverage against requirements a person owns** — imported from Jira, or
  generated and then approved — and link an existing test to the requirement it verifies;
- optionally **propose** User Stories, Gherkin and Playwright specs from the code, with a
  local model (Ollama) or any OpenAI-compatible API. Proposals count for nothing until
  someone approves them.

The repository holds both halves:

| Path | What it is |
| --- | --- |
| `src/` | React + TypeScript interface (Vite, TanStack Start, Tailwind, shadcn/ui) |
| `backend/` | **QA engine** — an independent FastAPI service: analysis, import, execution, reports |
| `docs/` | Feeding the inventory from CI, and the original Phase 1 specification |

## Requirements

| Tool | Version | Needed for |
| --- | --- | --- |
| Node.js | 20.19+ or 22.12+ | the interface, and running Playwright suites |
| Python | 3.11+ | the engine |
| git | any recent | analysing a GitHub repository |
| [Ollama](https://ollama.com), or an OpenAI-compatible API | optional | proposing User Stories, Gherkin and specs |

## Getting started

**1. The engine** — first terminal:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # Windows: copy .env.example .env
uvicorn qa_engine.main:app --app-dir src --port 8000
```

On Windows, once installed, `start-backend.cmd` at the repository root does the same with
a double-click. Check it answers at <http://127.0.0.1:8000/health>.

**2. The interface** — second terminal, at the repository root:

```bash
npm install
cp .env.example .env.local        # Windows: copy .env.example .env.local
npm run dev
```

Open <http://localhost:8080>.

The engine reads `backend/.env` **at startup only**: restart it after any change.
Automatic generation is off by default (`GENERATION_ENABLED=false`): everything else works
without any model. See *Choosing the model* below to turn it on.

## Testing your project

### 1. Add it

*Projects → New project*, then either:

- **Local repository** — an absolute path on the machine running the engine;
- **GitHub** — a **public** repository URL. The engine clones it into `backend/work/`.
  Private repositories are not supported: the engine holds no git credentials. Analyse
  your local checkout instead.

Then *Analyze*. The analysis maps routes, components and API calls, groups them into
functional domains, and imports the Playwright tests the project already contains.

### 2. Make the project runnable

The engine runs your suite with your own configuration; it does not install anything in
your project. Before running tests from the interface:

```bash
# in the tested project
npm install
npx playwright install chromium
```

and start what the tests need. Playwright's `webServer` usually starts the frontend, but
**an API it proxies to must be running too** — otherwise every call is refused, and the
failure names the address that did not answer.

### 3. Give the suite its credentials

A suite that signs in reads its account from environment variables. Put them in
**`backend/.env`** of this engine, under the names your suite expects:

```bash
MY_APP_E2E_USER=...
MY_APP_E2E_PASSWORD=...
```

Every variable of that file is passed to the Playwright process the engine starts, except
the engine's own settings — its Jira token and generation key never reach the tested
project. None is returned by the API or written to a log; only their names are.
`backend/.env` is ignored by git.

If your application limits login attempts, reuse the session your setup saves
(`storageState`) instead of signing in on every run; each run from the interface replays
the setup project.

### 4. Get the whole picture

*État des lieux* lists every test the engine knows about — what passes, what fails, what
has never run — grouped by file, red first. Browser tests appear once imported; backend
tests appear once a JUnit report has been sent:

```bash
pytest --junitxml=report.xml
curl -X POST "http://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>/reports" \
  -H "Content-Type: application/xml" --data-binary @report.xml
```

The same call works from a CI pipeline, or through *Importer un rapport JUnit* in the
interface. See [docs/rapports-junit.md](docs/rapports-junit.md) for every runner and a
pipeline example.

## Choosing the model

Generation only drafts proposals — User Stories, Gherkin, Playwright specs — that a person
reviews. The inventory, runs and coverage use no model at all. Configure it in
`backend/.env`:

| | `GENERATION_PROVIDER=ollama` | `GENERATION_PROVIDER=openai` |
| --- | --- | --- |
| Where it runs | This machine ([Ollama](https://ollama.com)) | A remote service speaking the OpenAI API |
| Data sent elsewhere | **None** | **Source excerpts, screen copy, routes, requirements** |
| Speed on a CPU-only PC | Minutes per domain | Seconds |
| Settings | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `GENERATION_BASE_URL`, `GENERATION_MODEL`, `GENERATION_API_KEY` |

Example — Muse Spark 1.3 through [OpenCode Zen](https://opencode.ai/docs/zen/):

```bash
GENERATION_PROVIDER=openai
GENERATION_BASE_URL=https://opencode.ai/zen/v1
GENERATION_MODEL=muse-spark-1.3-contributor-free
GENERATION_API_KEY=<your OpenCode Zen key>
```

> ⚠️ **A remote provider receives parts of the analysed code.** Muse Spark is a proprietary
> Meta model, not open source. Its free and "contributor" offers are paid for with data:
> prompts and answers may be used to train Meta's models. Do not use them on a private
> repository unless that is acceptable. The engine warns at startup and on the *Settings*
> screen whenever prompts leave the machine.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| A screen says the engine is unreachable | The engine is not running — start it (step 1) |
| `Disallowed CORS origin` in the browser | `CORS_ORIGINS` in `backend/.env` lacks `http://localhost:8080`, or the engine was not restarted |
| A failure starts with *« L'application testée ne répond pas sur … »* | The tested application's backend is not running |
| A failure quotes *« Trop de tentatives… »* or another page message | The tested application refused the action; the quote is what its page displayed |
| A GitHub project fails at the *Repository* step | Private repository, or on Windows a path over 260 characters — keep the engine in a short folder |
| Projects seem to have vanished | Check `backend/qa_engine.db` is the database in use; the engine always resolves it from `backend/` |

`backend/README.md` documents the API, the analysis pipeline, generation, Jira and every
configuration variable.

## Working on the interface alone

Set `VITE_API_MODE=mock` in `.env.local`: every screen then runs on in-memory fixtures, with
no engine.

## Lovable

The interface was started with [Lovable](https://lovable.dev), and this repository stays in
sync with its [Lovable project](https://lovable.dev/projects/8b1b38fc-dc00-4836-a762-990bfb970ee6).
The original specification is kept in
[docs/phase-1-specification.md](docs/phase-1-specification.md).

## License

[MIT](LICENSE)
