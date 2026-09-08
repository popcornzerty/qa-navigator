import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { API_BASE_URL, API_MODE, projectsApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { StatusBadge } from "../components/ui/status-badge";
import { useCurrentProject } from "../lib/current-project";
import { label } from "../lib/format";
import type { ProjectSettings } from "../types/models";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — AI QA Agent" },
      {
        name: "description",
        content:
          "Project, GitHub, Jira, AI provider and Playwright configuration for the current project.",
      },
      { property: "og:title", content: "Settings — AI QA Agent" },
      {
        property: "og:description",
        content: "Configure repository, integrations, AI provider and Playwright execution.",
      },
    ],
  }),
  component: SettingsPage,
});

const fieldClass =
  "w-full rounded-md bg-panel2 px-3 py-2 text-sm ring-1 ring-line outline-none focus:ring-primary/50";
const labelClass = "font-mono text-[10px] tracking-wider text-dim uppercase";

function SettingsPage() {
  const { projectId } = useCurrentProject();

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings", projectId],
    queryFn: () => projectsApi.settings(projectId!),
    enabled: Boolean(projectId),
  });

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Configuration is read from and written back through the API layer"
        actions={
          <span className="font-mono text-[11px] text-dim">
            {API_MODE === "http" ? `API · ${API_BASE_URL}` : "API · mock (in-memory)"}
          </span>
        }
      />

      {!projectId ? (
        <Panel>
          <PanelBody className="text-sm text-muted-foreground">
            Select a project in the top bar to configure it.
          </PanelBody>
        </Panel>
      ) : isLoading || !settings ? (
        <Panel>
          <PanelBody className="text-sm text-muted-foreground">Loading settings…</PanelBody>
        </Panel>
      ) : (
        <SettingsForm key={settings.projectId} settings={settings} />
      )}
    </>
  );
}

function SettingsForm({ settings }: { settings: ProjectSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ProjectSettings>(settings);

  const save = useMutation({
    mutationFn: (patch: Partial<ProjectSettings>) =>
      projectsApi.updateSettings(settings.projectId, patch),
    onSuccess: (updated) => {
      setDraft(updated);
      queryClient.invalidateQueries({ queryKey: ["settings", settings.projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Settings saved");
    },
    onError: () => toast.error("Could not save these settings"),
  });

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel>
        <PanelHeader
          title="Project"
          actions={
            <Button
              variant="primary"
              size="sm"
              disabled={save.isPending}
              onClick={() =>
                save.mutate({
                  name: draft.name,
                  repository: draft.repository,
                  branch: draft.branch,
                })
              }
            >
              Save
            </Button>
          }
        />
        <PanelBody className="space-y-3">
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-name">
              Project name
            </label>
            <input
              id="settings-name"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              className={fieldClass}
            />
          </div>
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-repository">
              Repository
            </label>
            <input
              id="settings-repository"
              value={draft.repository}
              onChange={(event) => setDraft({ ...draft, repository: event.target.value })}
              className={`${fieldClass} font-mono text-[12px]`}
            />
          </div>
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-branch">
              Branch
            </label>
            <input
              id="settings-branch"
              value={draft.branch}
              onChange={(event) => setDraft({ ...draft, branch: event.target.value })}
              className={`${fieldClass} font-mono text-[12px]`}
            />
          </div>
        </PanelBody>
      </Panel>

      <Panel>
        <PanelHeader title="GitHub" actions={<StatusBadge status={draft.github.status} />} />
        <PanelBody className="space-y-3">
          <Readonly label="Connection status" value={label(draft.github.status)} />
          <Readonly label="Account" value={draft.github.account ?? "—"} />
          <p className="text-xs text-muted-foreground">
            Connecting a GitHub account is handled by the backend — no remote call is made from the
            browser.
          </p>
        </PanelBody>
      </Panel>

      <Panel>
        <PanelHeader
          title="Jira"
          actions={
            <Button
              variant="primary"
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate({ jira: draft.jira })}
            >
              Save
            </Button>
          }
        />
        <PanelBody className="space-y-3">
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-jira-status">
              Connection status
            </label>
            <select
              id="settings-jira-status"
              value={draft.jira.status}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  jira: {
                    ...draft.jira,
                    status: event.target.value as ProjectSettings["jira"]["status"],
                  },
                })
              }
              className={fieldClass}
            >
              <option value="not_connected" className="bg-panel2">
                Not connected
              </option>
              <option value="connected" className="bg-panel2">
                Connected
              </option>
            </select>
          </div>
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-jira-key">
              Project key
            </label>
            <input
              id="settings-jira-key"
              value={draft.jira.projectKey ?? ""}
              placeholder="ATL"
              onChange={(event) =>
                setDraft({
                  ...draft,
                  jira: { ...draft.jira, projectKey: event.target.value || null },
                })
              }
              className={`${fieldClass} font-mono text-[12px]`}
            />
          </div>
        </PanelBody>
      </Panel>

      <Panel>
        <PanelHeader title="AI" actions={<StatusBadge status={draft.ai.status} />} />
        <PanelBody className="space-y-3">
          <Readonly
            label="Current provider"
            value={draft.ai.provider === "ollama" ? "Ollama" : "Other"}
          />
          <Readonly label="Model" value={draft.ai.model} />
          <Readonly label="Status" value={label(draft.ai.status)} />
          <p className="text-xs text-muted-foreground">
            The AI engine runs server-side. The frontend never contacts a model provider directly.
          </p>
        </PanelBody>
      </Panel>

      <Panel className="lg:col-span-2">
        <PanelHeader
          title="Playwright"
          actions={
            <Button
              variant="primary"
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate({ playwright: draft.playwright })}
            >
              Save
            </Button>
          }
        />
        <PanelBody className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-test-dir">
              Test directory
            </label>
            <input
              id="settings-test-dir"
              value={draft.playwright.testDirectory}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  playwright: { ...draft.playwright, testDirectory: event.target.value },
                })
              }
              className={`${fieldClass} font-mono text-[12px]`}
            />
          </div>
          <div className="space-y-1.5">
            <label className={labelClass} htmlFor="settings-base-url">
              Base URL
            </label>
            <input
              id="settings-base-url"
              value={draft.playwright.baseUrl}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  playwright: { ...draft.playwright, baseUrl: event.target.value },
                })
              }
              className={`${fieldClass} font-mono text-[12px]`}
            />
          </div>
          <fieldset className="space-y-2">
            <legend className={labelClass}>Browsers</legend>
            <div className="flex flex-wrap gap-2">
              {(["chromium", "firefox", "webkit"] as const).map((browser) => {
                const active = draft.playwright.browsers.includes(browser);
                return (
                  <button
                    key={browser}
                    type="button"
                    onClick={() =>
                      setDraft({
                        ...draft,
                        playwright: {
                          ...draft.playwright,
                          browsers: active
                            ? draft.playwright.browsers.filter((item) => item !== browser)
                            : [...draft.playwright.browsers, browser],
                        },
                      })
                    }
                    className={`rounded-md px-2.5 py-1 text-xs ring-1 transition-colors ${
                      active
                        ? "bg-primary/10 text-primary ring-primary/30"
                        : "bg-panel2 text-muted-foreground ring-line hover:text-foreground"
                    }`}
                  >
                    {browser}
                  </button>
                );
              })}
            </div>
          </fieldset>
          <label className="flex items-center gap-2 self-end text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={draft.playwright.headless}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  playwright: { ...draft.playwright, headless: event.target.checked },
                })
              }
              className="size-3.5 accent-current"
            />
            Run headless
          </label>
        </PanelBody>
      </Panel>
    </div>
  );
}

function Readonly({ label: name, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className={labelClass}>{name}</span>
      <span className="truncate text-sm">{value}</span>
    </div>
  );
}
