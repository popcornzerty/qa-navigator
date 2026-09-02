import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { projectsApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { useCurrentProject } from "../lib/current-project";
import type { CreateProjectInput, JiraConnection, RepositorySource } from "../types/models";

export const Route = createFileRoute("/projects/new")({
  head: () => ({
    meta: [
      { title: "Create a project — AI QA Agent" },
      {
        name: "description",
        content: "Register a repository, choose a branch, link Jira and pick the local AI engine.",
      },
      { property: "og:title", content: "Create a project — AI QA Agent" },
      {
        property: "og:description",
        content: "Register a repository and prepare it for functional QA analysis.",
      },
    ],
  }),
  component: NewProjectPage,
});

const fieldClass =
  "w-full rounded-md bg-panel2 px-3 py-2 text-sm ring-1 ring-line outline-none focus:ring-primary/50";
const labelClass = "font-mono text-[10px] tracking-wider text-dim uppercase";

function NewProjectPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setProjectId } = useCurrentProject();

  const [name, setName] = useState("");
  const [repositorySource, setRepositorySource] = useState<RepositorySource>("github");
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("main");
  const [jiraConnection, setJiraConnection] = useState<JiraConnection>("not_connected");
  const [jiraProject, setJiraProject] = useState("");

  const create = useMutation({
    mutationFn: (input: CreateProjectInput) => projectsApi.create(input),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setProjectId(project.id);
      toast.success(`${project.name} created`);
      navigate({ to: "/projects/$projectId", params: { projectId: project.id } });
    },
    onError: () => toast.error("Could not create the project"),
  });

  return (
    <>
      <PageHeader title="New project" subtitle="Mocked in Phase 1 — no external service is contacted" />

      <Panel className="max-w-3xl">
        <PanelHeader title="Project configuration" meta="step 1 of 1" />
        <PanelBody>
          <form
            className="space-y-5"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate({
                name: name.trim(),
                repositorySource,
                repository: repository.trim(),
                branch: branch.trim() || "main",
                jiraConnection,
                jiraProject: jiraConnection === "connected" ? jiraProject.trim() || null : null,
                aiProvider: "ollama",
              });
            }}
          >
            <div className="space-y-1.5">
              <label className={labelClass} htmlFor="name">
                Project name
              </label>
              <input
                id="name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Atlas Commerce Storefront"
                className={fieldClass}
              />
            </div>

            <fieldset className="space-y-2">
              <legend className={labelClass}>Repository source</legend>
              <div className="flex gap-2">
                {(["github", "local"] as RepositorySource[]).map((source) => (
                  <button
                    key={source}
                    type="button"
                    onClick={() => setRepositorySource(source)}
                    className={`rounded-md px-3 py-1.5 text-xs ring-1 ${
                      repositorySource === source
                        ? "bg-primary/10 text-primary ring-primary/30"
                        : "text-muted-foreground ring-line hover:text-foreground"
                    }`}
                  >
                    {source === "github" ? "GitHub" : "Local repository"}
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className={labelClass} htmlFor="repository">
                  {repositorySource === "github" ? "GitHub repository URL" : "Local path"}
                </label>
                <input
                  id="repository"
                  required
                  value={repository}
                  onChange={(e) => setRepository(e.target.value)}
                  placeholder={
                    repositorySource === "github"
                      ? "github.com/atlas-demo/atlas-storefront"
                      : "local://workspaces/atlas-admin"
                  }
                  className={`${fieldClass} font-mono text-[12px]`}
                />
              </div>
              <div className="space-y-1.5">
                <label className={labelClass} htmlFor="branch">
                  Branch
                </label>
                <input
                  id="branch"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className={`${fieldClass} font-mono text-[12px]`}
                />
              </div>
            </div>

            <fieldset className="space-y-2">
              <legend className={labelClass}>Jira integration</legend>
              <div className="flex flex-wrap items-center gap-2">
                {(["not_connected", "connected"] as JiraConnection[]).map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setJiraConnection(value)}
                    className={`rounded-md px-3 py-1.5 text-xs ring-1 ${
                      jiraConnection === value
                        ? "bg-primary/10 text-primary ring-primary/30"
                        : "text-muted-foreground ring-line hover:text-foreground"
                    }`}
                  >
                    {value === "connected" ? "Connected" : "Not connected"}
                  </button>
                ))}
                {jiraConnection === "connected" ? (
                  <input
                    aria-label="Jira project key"
                    value={jiraProject}
                    onChange={(e) => setJiraProject(e.target.value)}
                    placeholder="ATL"
                    className="w-28 rounded-md bg-panel2 px-3 py-1.5 font-mono text-xs ring-1 ring-line outline-none focus:ring-primary/50"
                  />
                ) : null}
              </div>
            </fieldset>

            <fieldset className="space-y-2">
              <legend className={labelClass}>AI engine</legend>
              <div className="flex gap-2">
                <span className="rounded-md bg-primary/10 px-3 py-1.5 text-xs text-primary ring-1 ring-primary/30">
                  Ollama / Local
                </span>
                <span className="rounded-md px-3 py-1.5 text-xs text-dim ring-1 ring-line">
                  Other provider (coming later)
                </span>
              </div>
            </fieldset>

            <div className="flex items-center gap-2 border-t border-line pt-4">
              <Button type="submit" variant="primary" disabled={create.isPending}>
                {create.isPending ? "Creating…" : "Create project"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => navigate({ to: "/projects" })}>
                Cancel
              </Button>
            </div>
          </form>
        </PanelBody>
      </Panel>
    </>
  );
}
