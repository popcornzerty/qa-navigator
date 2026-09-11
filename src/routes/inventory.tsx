import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { inventoryApi } from "../api";
import { PageHeader } from "../components/layout/app-shell";
import { Button } from "../components/ui/button";
import { Panel, PanelBody, PanelHeader } from "../components/ui/panel";
import { useCurrentProject } from "../lib/current-project";
import { formatDateTime, formatDuration, percent } from "../lib/format";
import { cn } from "../lib/utils";
import type { TestKind, TestSuiteSummary } from "../types/models";

export const Route = createFileRoute("/inventory")({
  head: () => ({
    meta: [
      { title: "État des lieux — AI QA Agent" },
      {
        name: "description",
        content:
          "Every test of the project, backend and browser, with what passes and what has never run.",
      },
    ],
  }),
  component: InventoryPage,
});

const FAMILY: Record<TestKind, { label: string; hint: string }> = {
  backend: { label: "Backend", hint: "Logique métier et API — exécutés sans navigateur" },
  e2e: { label: "Frontend (E2E)", hint: "Parcours dans un vrai navigateur" },
};

function InventoryPage() {
  const { projectId } = useCurrentProject();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [showPassing, setShowPassing] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["inventory", projectId],
    queryFn: () => inventoryApi.get(projectId ?? undefined),
    // The picture has to be current at a standup without anyone pressing anything, and
    // reading stored rows costs nothing — no test is executed to answer this.
    refetchInterval: 15_000,
  });

  const ingest = useMutation({
    mutationFn: async (file: File) => {
      if (!projectId) throw new Error("Sélectionnez d'abord un projet.");
      return inventoryApi.ingest(projectId, await file.text());
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
      queryClient.invalidateQueries({ queryKey: ["tests"] });
      queryClient.invalidateQueries({ queryKey: ["coverage"] });
      toast.success(
        `Rapport ${result.framework} lu : ${result.passed} OK, ${result.failed} KO, ` +
          `${result.skipped} ignorés · ${result.created} nouveaux tests`,
      );
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (isLoading || !data) {
    return (
      <>
        <PageHeader title="État des lieux" subtitle="Lecture de l'inventaire" />
        <Panel>
          <PanelBody className="text-sm text-muted-foreground">Chargement…</PanelBody>
        </Panel>
      </>
    );
  }

  const { totals, suites } = data;
  const failing = suites.filter((suite) => suite.failed > 0);
  const dormant = suites.filter((suite) => suite.failed === 0 && suite.notRun + suite.skipped > 0);

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept=".xml,application/xml,text/xml"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) ingest.mutate(file);
          event.target.value = "";
        }}
      />
      <PageHeader
        title="État des lieux"
        subtitle={`${totals.tests} tests · ${totals.suites} fichiers · ${formatDuration(
          totals.durationMs,
        )} d'exécution cumulée`}
        actions={
          <Button
            variant="outline"
            size="sm"
            data-testid="import-report"
            disabled={ingest.isPending || !projectId}
            onClick={() => fileInput.current?.click()}
          >
            {ingest.isPending ? "Lecture…" : "Importer un rapport JUnit"}
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="Taux de réussite"
          value={percent(totals.passRate)}
          hint={`sur ${totals.passed + totals.failed} tests exécutés`}
          tone={totals.failed > 0 ? "fail" : "pass"}
        />
        <Tile label="Au vert" value={String(totals.passed)} hint="dernier passage" tone="pass" />
        <Tile
          label="Au rouge"
          value={String(totals.failed)}
          hint={
            failing.length === 1 ? "1 fichier concerné" : `${failing.length} fichiers concernés`
          }
          tone={totals.failed > 0 ? "fail" : "muted"}
        />
        <Tile
          label="Jamais lancés"
          value={String(totals.notRun + totals.skipped)}
          hint={`${totals.notRun} jamais exécutés · ${totals.skipped} ignorés`}
          tone={totals.notRun + totals.skipped > 0 ? "skip" : "muted"}
        />
      </div>

      {/* A suite nobody has run is not a failing suite, and the two are never merged:
          calling "not run" a problem pushes a team to run everything before every
          standup, calling it a pass is a lie. */}
      <Panel>
        <PanelHeader
          title="Ce qu'il faut regarder"
          meta={failing.length === 0 ? "rien au rouge" : `${failing.length} à traiter`}
        />
        <PanelBody className="space-y-2 text-sm">
          {failing.length === 0 ? (
            <p className="text-muted-foreground">
              Aucun test au rouge.{" "}
              {totals.notRun + totals.skipped > 0
                ? `${totals.notRun + totals.skipped} tests n'ont pourtant jamais donné de verdict — ils ne prouvent rien tant qu'ils n'ont pas tourné.`
                : "Tout ce qui existe a un verdict."}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {failing.map((suite) => (
                <li key={`${suite.kind}:${suite.suite}`} className="flex items-start gap-2">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-fail" />
                  <span>
                    <span className="font-mono text-[12px]">{suite.suite}</span>{" "}
                    <span className="text-muted-foreground">
                      — {suite.failed} test{suite.failed > 1 ? "s" : ""} au rouge sur {suite.tests}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {dormant.length > 0 ? (
            <p className="border-t border-line pt-2 text-xs text-muted-foreground">
              {dormant.length} fichier{dormant.length > 1 ? "s" : ""} contien
              {dormant.length > 1 ? "nent" : "t"} des tests sans verdict.
            </p>
          ) : null}
        </PanelBody>
      </Panel>

      {(["backend", "e2e"] as TestKind[]).map((kind) => {
        const family = suites.filter((suite) => suite.kind === kind);
        if (family.length === 0) return null;
        return (
          <Family
            key={kind}
            kind={kind}
            suites={family}
            showPassing={showPassing}
            onToggle={() => setShowPassing((value) => !value)}
          />
        );
      })}

      <p className="text-xs leading-relaxed text-dim">
        L'inventaire lit ce qui est enregistré et n'exécute rien : il répond immédiatement, que les
        suites soient lançables ou non. Les verdicts viennent d'un rapport JUnit — celui de la
        pipeline ou d'un passage en local — ce qui couvre pytest, Playwright, Jest, Vitest, Go et le
        reste sans que l'outil ait à piloter chaque runner.
      </p>
    </>
  );
}

function Family({
  kind,
  suites,
  showPassing,
  onToggle,
}: {
  kind: TestKind;
  suites: TestSuiteSummary[];
  showPassing: boolean;
  onToggle: () => void;
}) {
  const totals = suites.reduce(
    (acc, suite) => ({
      tests: acc.tests + suite.tests,
      passed: acc.passed + suite.passed,
      failed: acc.failed + suite.failed,
      skipped: acc.skipped + suite.skipped,
      notRun: acc.notRun + suite.notRun,
    }),
    { tests: 0, passed: 0, failed: 0, skipped: 0, notRun: 0 },
  );
  const frameworks = [...new Set(suites.map((suite) => suite.framework))].sort();
  const visible = showPassing
    ? suites
    : suites.filter((suite) => suite.failed > 0 || suite.notRun > 0 || suite.skipped > 0);
  const hidden = suites.length - visible.length;

  return (
    <Panel>
      <PanelHeader
        title={`${FAMILY[kind].label} — ${totals.tests} tests`}
        meta={`${frameworks.join(", ")} · ${suites.length} fichiers`}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2">
        <div className="flex items-center gap-3 text-xs">
          <Count label="OK" value={totals.passed} className="text-pass" />
          <Count label="KO" value={totals.failed} className="text-fail" />
          <Count label="ignorés" value={totals.skipped} className="text-skip" />
          <Count label="jamais lancés" value={totals.notRun} className="text-muted-foreground" />
        </div>
        <span className="text-[11px] text-dim">{FAMILY[kind].hint}</span>
      </div>

      {visible.length === 0 ? (
        <PanelBody className="text-sm text-muted-foreground">
          Les {suites.length} fichiers sont entièrement au vert.
        </PanelBody>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-dim uppercase">
                <th className="px-4 py-2 font-medium">Fichier</th>
                <th className="px-3 py-2 text-right font-medium">Tests</th>
                <th className="px-3 py-2 text-right font-medium">OK</th>
                <th className="px-3 py-2 text-right font-medium">KO</th>
                <th className="px-3 py-2 text-right font-medium">Sans verdict</th>
                <th className="px-4 py-2 text-right font-medium">Dernier passage</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((suite) => {
                const pending = suite.notRun + suite.skipped;
                return (
                  <tr
                    key={suite.suite}
                    className={cn(
                      "border-b border-line/60 last:border-0",
                      suite.failed > 0 && "bg-fail/5",
                    )}
                  >
                    <td className="px-4 py-2">
                      <span className="font-mono text-[12px]">{suite.suite}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-muted-foreground">
                      {suite.tests}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-pass">
                      {suite.passed || "—"}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2 text-right font-mono text-[12px]",
                        suite.failed > 0 ? "font-semibold text-fail" : "text-dim",
                      )}
                    >
                      {suite.failed || "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-skip">
                      {pending || "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-xs text-muted-foreground">
                      {suite.lastRun ? formatDateTime(suite.lastRun) : "jamais"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {hidden > 0 || showPassing ? (
        <div className="border-t border-line px-4 py-2">
          <button
            type="button"
            onClick={onToggle}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {showPassing
              ? "Masquer les fichiers entièrement au vert"
              : `Afficher aussi les ${hidden} fichiers entièrement au vert`}
          </button>
        </div>
      ) : null}
    </Panel>
  );
}

function Count({ label, value, className }: { label: string; value: number; className: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className={cn("font-mono text-[13px] font-semibold", className)}>{value}</span>
      <span className="text-[11px] text-dim">{label}</span>
    </span>
  );
}

function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone: "pass" | "fail" | "skip" | "muted";
}) {
  const tones = {
    pass: "text-pass",
    fail: "text-fail",
    skip: "text-skip",
    muted: "text-muted-foreground",
  } as const;
  return (
    <div className="rounded-xl bg-panel p-4 ring-1 ring-line">
      <p className="font-mono text-[10px] tracking-wider text-dim uppercase">{label}</p>
      <p className={cn("mt-1 font-display text-2xl font-semibold tracking-tight", tones[tone])}>
        {value}
      </p>
      <p className="mt-0.5 text-[11px] text-dim">{hint}</p>
    </div>
  );
}
