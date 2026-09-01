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
  coverage: number;
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

export type TestStatus = "passed" | "failed" | "skipped" | "not_run";

export interface TestResult {
  status: TestStatus;
  executedAt: string | null;
  durationMs: number;
  errorMessage?: string;
  screenshot?: string;
  trace?: string;
  consoleOutput?: string[];
}

export interface PlaywrightTest {
  id: string;
  projectId: string;
  userStoryId: string;
  userStoryKey: string;
  gherkinScenarioId: string;
  scenario: string;
  file: string;
  status: TestStatus;
  lastRun: string | null;
  durationMs: number;
  result: TestResult;
}

/* Analysis / async jobs */

export type StepStatus = "pending" | "running" | "completed" | "failed";

export type AnalysisStepKey =
  | "repository"
  | "architecture"
  | "routes"
  | "components"
  | "apis"
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
  coverage: number;
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
  coverage: number;
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

export interface CreateProjectInput {
  name: string;
  repositorySource: RepositorySource;
  repository: string;
  branch: string;
  jiraConnection: JiraConnection;
  jiraProject: string | null;
  aiProvider: AiProvider;
}
