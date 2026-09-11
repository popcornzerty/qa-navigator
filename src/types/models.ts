/**
 * Data models mirroring the future Python/FastAPI backend payloads.
 * These are the only shapes the UI is allowed to depend on.
 */

export type ProjectStatus = "ready" | "analyzing" | "never_analyzed" | "error";
export type RepositorySource = "github" | "local";
export type JiraConnection = "not_connected" | "connected";
export type AiProvider = "ollama" | "other";

export interface Project {
  id: string;
  name: string;
  repository: string;
  repositorySource: RepositorySource;
  branch: string;
  jiraProject: string | null;
  jiraConnection: JiraConnection;
  aiProvider: AiProvider;
  status: ProjectStatus;
  lastAnalysis: string | null;
  storyCount: number;
  automatedTestCount: number;
}

export interface ProjectStats {
  features: number;
  userStories: number;
  gherkinScenarios: number;
  playwrightTests: number;
  /** Null when no requirement has been claimed yet — never render that as 0%. */
  coverage: number | null;
}

export type FeatureStatus = "detected" | "confirmed" | "ignored";

export interface Feature {
  id: string;
  projectId: string;
  name: string;
  description: string;
  confidence: number;
  sourceFiles: string[];
  status: FeatureStatus;
}

export type StoryStatus = "draft" | "needs_review" | "approved" | "created" | "out_of_sync";

export interface AcceptanceCriterion {
  id: string;
  userStoryId: string;
  text: string;
  covered: boolean;
}

export type GherkinStatus = "draft" | "valid" | "invalid" | "automated";

export interface GherkinScenario {
  id: string;
  userStoryId: string;
  feature: string;
  scenario: string;
  given: string[];
  when: string[];
  then: string[];
  status: GherkinStatus;
}

export interface UserStory {
  id: string;
  projectId: string;
  featureId: string;
  featureName: string;
  epic: string;
  title: string;
  description: string;
  confidence: number;
  sourceFiles: string[];
  acceptanceCriteria: AcceptanceCriterion[];
  gherkinScenarios: GherkinScenario[];
  jiraKey: string | null;
  status: StoryStatus;
}

/** `running` is what lets the UI tell a run in flight from a stale result: without it a
 *  test keeps its previous verdict while executing and nothing on screen moves. */
export type TestStatus = "passed" | "failed" | "skipped" | "not_run" | "running";

export interface TestResult {
  status: TestStatus;
  executedAt: string | null;
  durationMs: number;
  errorMessage?: string;
  screenshot?: string;
  trace?: string;
  consoleOutput?: string[];
}

/** Where a test came from — which is what tells the reader how much it proves.
 *  `code` and `jira` both mean the engine wrote it, and differ by what it was written
 *  from; `discovered` means the repository already shipped with it. */
export type TestOrigin = "code" | "jira" | "manual" | "discovered";

/** What a test exercises. A repository's suite is wider than its browser tests — 1020
 *  pytest next to 155 Playwright in the project this was built against — and a list that
 *  cannot say which is which is not an inventory. */
export type TestKind = "e2e" | "backend";

export interface PlaywrightTest {
  id: string;
  projectId: string;
  /** Null for a discovered test: it was written against the product, not against a
   *  stated requirement, so it traces to no User Story. */
  userStoryId: string | null;
  userStoryKey: string | null;
  gherkinScenarioId: string | null;
  scenario: string;
  file: string;
  origin: TestOrigin;
  kind: TestKind;
  /** The runner that produced the verdict. For the reader's benefit only. */
  framework: string;
  status: TestStatus;
  lastRun: string | null;
  durationMs: number;
  result: TestResult;
}

/** One test plus the code that defines it. Kept separate from the list response: a suite
 *  of a hundred imported tests would otherwise ship every spec file on every poll. */
export interface PlaywrightTestDetail extends PlaywrightTest {
  source: string;
  /** Line the test is declared on, for pointing at it inside a large file. */
  line: number | null;
  /** Why the code could not be read — a file moved or deleted since the last analysis. */
  sourceError: string | null;
}

/** One execution of one test, kept after the next one replaces it.
 *
 *  `PlaywrightTest` carries only the latest verdict, which made a flaky test
 *  indistinguishable from a stable one and left no way to say when a test started
 *  failing. This is the history behind it. */
export interface TestRun {
  id: string;
  testId: string;
  projectId: string;
  scenario: string;
  file: string;
  origin: TestOrigin;
  status: TestStatus;
  startedAt: string;
  finishedAt: string | null;
  durationMs: number;
  errorMessage: string | null;
  screenshot: string | null;
  trace: string | null;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
}

/** One execution with its output, served from an offset so a client watching a run in
 *  progress asks only for what it has not seen. */
export interface TestRunDetail extends TestRun {
  log: string;
  /** Number of lines before the first one in `log`. */
  offset: number;
  /** Total lines produced so far; echo it back as `since` to continue. */
  lineCount: number;
}

/* Analysis / async jobs */

export type StepStatus = "pending" | "running" | "completed" | "failed";

export type AnalysisStepKey =
  | "repository"
  | "architecture"
  | "routes"
  | "components"
  | "apis"
  | "existing_tests"
  | "features"
  | "stories"
  | "gherkin";

export interface AnalysisStep {
  key: AnalysisStepKey;
  label: string;
  status: StepStatus;
  detail?: string;
}

export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface AnalysisJob {
  jobId: string;
  projectId: string;
  status: JobStatus;
  progress: number;
  startedAt: string;
  steps: AnalysisStep[];
}

/* Coverage */

export interface CoverageGap {
  id: string;
  reference: string;
  label: string;
  reason: string;
  severity: "warning" | "critical";
}

export interface CoverageReport {
  projectId: string;
  userStories: { total: number; withGherkin: number; automated: number };
  acceptanceCriteria: { total: number; covered: number };
  gherkin: { total: number; valid: number };
  automation: { total: number; passing: number };
  /** Criteria of requirements a person owns — imported from Jira, or generated then
   *  approved. Null when none has been claimed, which is not the same as nothing being
   *  tested and must never render as 0%. */
  coverage: number | null;
  /** What the unreviewed drafts would give. Kept apart: measured against them, the figure
   *  fell from 30.8% to 11.4% on an unchanged product because a run wrote more criteria. */
  draftCoverage: number | null;
  baseline: "owned" | "none";
  /** Passing tests written against the product directly, proving a behaviour that traces
   *  to no stated requirement. */
  verifiedBehaviours: number;
  gaps: CoverageGap[];
}

/* Dashboard */

export interface ActivityEvent {
  id: string;
  kind: "success" | "info" | "warning" | "error";
  message: string;
  at: string;
}

export interface DashboardSummary {
  projects: number;
  activeProjects: number;
  userStories: number;
  approvedStories: number;
  gherkinScenarios: number;
  validGherkin: number;
  automatedTests: number;
  failingTests: number;
  /** Null when no requirement has been claimed yet — never render that as 0%. */
  coverage: number | null;
  activity: ActivityEvent[];
}

/* Settings */

export interface ProjectSettings {
  projectId: string;
  name: string;
  repository: string;
  branch: string;
  github: { status: "connected" | "disconnected"; account: string | null };
  jira: { status: JiraConnection; projectKey: string | null };
  ai: { provider: AiProvider; model: string; status: "connected" | "disconnected" };
  playwright: { testDirectory: string; baseUrl: string; browsers: string[]; headless: boolean };
}

/* Jira */

export interface JiraImportInput {
  jql?: string;
  maxResults?: number;
}

export interface JiraImportResult {
  imported: number;
  updated: number;
  storyIds: string[];
  jql: string;
}

export interface CreateProjectInput {
  name: string;
  repositorySource: RepositorySource;
  repository: string;
  branch: string;
  jiraConnection: JiraConnection;
  jiraProject: string | null;
  aiProvider: AiProvider;
}

/** One file's worth of tests — the unit a standup reads a suite in. */
export interface TestSuiteSummary {
  kind: TestKind;
  framework: string;
  suite: string;
  tests: number;
  passed: number;
  failed: number;
  skipped: number;
  notRun: number;
  durationMs: number;
  lastRun: string | null;
  origins: string[];
}

export interface TestTotals {
  suites: number;
  tests: number;
  passed: number;
  failed: number;
  skipped: number;
  notRun: number;
  durationMs: number;
  /** Null until something has run. Of the tests that did run, how many hold — a suite
   *  nobody has executed is absent from this rather than counted as a failure. */
  passRate: number | null;
}

export interface TestInventory {
  projectId: string;
  totals: TestTotals;
  suites: TestSuiteSummary[];
}

export interface ReportIngestion {
  kind: TestKind;
  framework: string;
  matched: number;
  created: number;
  durationMs: number;
  passed: number;
  failed: number;
  skipped: number;
}
