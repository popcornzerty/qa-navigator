import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { jiraApi, storiesApi, testsApi } from "../api";
import type { StoryFilters } from "../api/stories";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Panel, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { useCurrentProject } from "../lib/current-project";
import { formatConfidence } from "../lib/format";
import type { StoryStatus } from "../types/models";

export const Route = createFileRoute("/backlog/")({
  head: () => ({
    meta: [
      { title: "Backlog — AI QA Agent" },
      {
        name: "description",
        content:
          "Generated User Stories with confidence, acceptance criteria, Gherkin, Jira status and automation.",
      },
      { property: "og:title", content: "Backlog — AI QA Agent" },
      {
        property: "og:description",
        content: "Review generated User Stories before approving and synchronising them.",
      },
    ],
  }),
  component: BacklogPage,
});

const STATUS_FILTERS: (StoryStatus | "all")[] = [
  "all",
  "draft",
  "needs_review",
  "approved",
  "created",
  "out_of_sync",
];

const chip = "rounded-md px-2.5 py-1 text-xs ring-1 transition-colors whitespace-nowrap capitalize";
const chipOn = "bg-primary/10 text-primary ring-primary/30";
const chipOff = "bg-panel2 text-muted-foreground ring-line hover:text-foreground";
const labelClass = "font-mono text-[10px] tracking-wider text-dim uppercase";

function BacklogPage() {
  const { projectId } = useCurrentProject();
  const [status, setStatus] = useState<StoryStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [feature, setFeature] = useState("all");
  const [importOpen, setImportOpen] = useState(false);

  const filters = useMemo<StoryFilters>(() => {
    const value: StoryFilters = { status };
    if (projectId) value.projectId = projectId;
    if (search.trim()) value.search = search.trim();
    return value;
  }, [projectId, status, search]);

  const { data: stories = [], isLoading } = useQuery({
    queryKey: ["stories", filters],
    queryFn: () => storiesApi.list(filters),
  });

  const { data: tests = [] } = useQuery({
    queryKey: ["tests", projectId],
    queryFn: () => testsApi.list(projectId ? { projectId } : {}),
  });

  const testsByStory = useMemo(() => {
    const map = new Map<string, number>();
    // A discovered test belongs to no story, so it is counted against none.
    for (const test of tests) {
      if (!test.userStoryId) continue;
      map.set(test.userStoryId, (map.get(test.userStoryId) ?? 0) + 1);
    }
    return map;
  }, [tests]);

  const features = useMemo(
    () => ["all", ...Array.from(new Set(stories.map((story) => story.featureName))).sort()],
    [stories],
  );

  const visible = useMemo(
    () => (feature === "all" ? stories : stories.filter((s) => s.featureName === feature)),
    [stories, feature],
  );

  return (
    <>
      <PageHeader
        title="Backlog"
        subtitle="Generated User Stories awaiting review, approval and synchronisation"
        actions={
          <Button
            variant="outline"
            size="sm"
            data-testid="jira-import-open"
            onClick={() => setImportOpen(true)}
          >
            Import from Jira
          </Button>
        }
      />

      <JiraImportDialog open={importOpen} projectId={projectId} onOpenChange={setImportOpen} />

      <Panel>
        <PanelHeader
          title="User Stories"
          meta={`${visible.length} of ${stories.length}`}
          actions={
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search story or feature"
              aria-label="Search user stories"
              data-testid="backlog-search"
              className="w-48 rounded-md bg-panel2 px-3 py-1.5 text-xs ring-1 ring-line outline-none focus:ring-primary/50"
            />
          }
        />

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] tracking-wider text-dim uppercase">Status</span>
            {STATUS_FILTERS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setStatus(value)}
                className={`${chip} ${status === value ? chipOn : chipOff}`}
              >
                {value.replace(/_/g, " ")}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            <label
              htmlFor="feature-filter"
              className="font-mono text-[10px] tracking-wider text-dim uppercase"
            >
              Feature
            </label>
            <select
              id="feature-filter"
              value={feature}
              onChange={(event) => setFeature(event.target.value)}
              className="rounded-md bg-panel2 px-2.5 py-1 text-xs ring-1 ring-line outline-none focus:ring-primary/50"
            >
              {features.map((name) => (
                <option key={name} value={name} className="bg-panel2">
                  {name === "all" ? "All features" : name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table data-testid="backlog-table" className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                <th className="px-4 py-2 font-medium">Feature</th>
                <th className="px-3 py-2 font-medium">User Story</th>
                <th className="px-3 py-2 font-medium">Confidence</th>
                <th className="px-3 py-2 font-medium">AC</th>
                <th className="px-3 py-2 font-medium">Gherkin</th>
                <th className="px-3 py-2 font-medium">Jira</th>
                <th className="px-3 py-2 font-medium">Tests</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {visible.map((story) => {
                const covered = story.acceptanceCriteria.filter((c) => c.covered).length;
                const automated = testsByStory.get(story.id) ?? 0;
                return (
                  <tr
                    key={story.id}
                    data-testid="story-row"
                    className="transition-colors hover:bg-panel2"
                  >
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                      {story.featureName}
                    </td>
                    <td className="px-3 py-3">
                      <Link
                        to="/backlog/$storyId"
                        params={{ storyId: story.id }}
                        data-testid="story-link"
                        className="group block"
                      >
                        <span className="font-mono text-[11px] text-primary">{story.id}</span>
                        <span className="ml-2 group-hover:underline">{story.title}</span>
                      </Link>
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {formatConfidence(story.confidence)}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {covered}/{story.acceptanceCriteria.length}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {story.gherkinScenarios.length}
                    </td>
                    <td className="px-3 py-3">
                      {story.jiraKey ? (
                        <span className="font-mono text-[11px] text-primary">{story.jiraKey}</span>
                      ) : (
                        <span className="font-mono text-[11px] text-dim">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {automated || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={story.status} />
                    </td>
                  </tr>
                );
              })}
              {!isLoading && visible.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-sm text-muted-foreground">
                    No user story matches these filters.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

/**
 * Pulls User Stories from Jira.
 *
 * Read-only, and credentialless by design: the engine holds the Jira token in its own
 * environment, so the browser never sees or sends one.
 */
function JiraImportDialog({
  open,
  projectId,
  onOpenChange,
}: {
  open: boolean;
  projectId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [jql, setJql] = useState("");
  const [maxResults, setMaxResults] = useState(50);

  const importStories = useMutation({
    mutationFn: () =>
      jiraApi.importStories(projectId!, {
        ...(jql.trim() ? { jql: jql.trim() } : {}),
        maxResults,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["stories"] });
      queryClient.invalidateQueries({ queryKey: ["coverage"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onOpenChange(false);
      toast.success(
        result.imported === 0 && result.updated === 0
          ? "No issue matched this query"
          : `${result.imported} imported, ${result.updated} updated`,
      );
    },
    // The backend explains what to fix (missing project key, missing credentials,
    // rejected JQL): surface it verbatim and keep the dialog open.
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Import from Jira</DialogTitle>
          <DialogDescription>
            Issues are imported as User Stories. Nothing is written back to Jira.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="jira-jql">
              JQL query (optional)
            </label>
            <textarea
              id="jira-jql"
              rows={2}
              value={jql}
              onChange={(event) => setJql(event.target.value)}
              placeholder={'project = "ATL" AND issuetype = Story ORDER BY created DESC'}
              className="w-full resize-y rounded-md bg-panel2 px-3 py-2 font-mono text-[12px] ring-1 ring-line outline-none focus:ring-primary/50"
            />
            <p className="text-xs text-dim">Leave empty to use the project&apos;s Jira key.</p>
          </div>

          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="jira-max">
              Maximum issues
            </label>
            <input
              id="jira-max"
              type="number"
              min={1}
              max={100}
              value={maxResults}
              onChange={(event) => setMaxResults(Number(event.target.value) || 50)}
              className="w-28 rounded-md bg-panel2 px-3 py-2 text-sm ring-1 ring-line outline-none focus:ring-primary/50"
            />
          </div>

          <p className="rounded-md bg-panel2 px-3 py-2 text-xs text-muted-foreground ring-1 ring-line">
            Jira credentials are configured on the engine, never in this interface.
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            data-testid="jira-import-submit"
            disabled={!projectId || importStories.isPending}
            onClick={() => importStories.mutate()}
          >
            {importStories.isPending ? "Importing…" : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
