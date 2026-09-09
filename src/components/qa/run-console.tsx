import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { runsApi } from "../../api";
import { Button } from "../ui/button";
import { Panel, PanelBody, PanelHeader } from "../ui/panel";

/** Playwright's output for one run, appended as it arrives.
 *
 *  The log is fetched from an offset rather than in full: a suite that starts its own dev
 *  server prints for minutes, and resending the whole thing every second would move the
 *  same kilobytes over and over.
 */
export function RunConsole({ runId, showLink = true }: { runId: string; showLink?: boolean }) {
  const [lines, setLines] = useState<string[]>([]);
  const [since, setSince] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  // A different run is a different log: start over rather than appending to the old one.
  useEffect(() => {
    setLines([]);
    setSince(0);
  }, [runId]);

  const { data: run } = useQuery({
    queryKey: ["run", runId, since],
    queryFn: () => runsApi.get(runId, since),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 700 : false),
  });

  useEffect(() => {
    if (!run || run.lineCount === since) return;
    const incoming = run.log ? run.log.split("\n") : [];
    setLines((current) => [...current, ...incoming]);
    setSince(run.lineCount);
  }, [run, since]);

  // Follow the tail while it grows, the way a terminal does.
  useEffect(() => {
    const element = box.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines.length]);

  if (!run) {
    return (
      <Panel>
        <PanelHeader title="Console" meta="—" />
        <PanelBody className="text-sm text-muted-foreground">Loading execution…</PanelBody>
      </Panel>
    );
  }

  return (
    <div className="space-y-5">
      <Panel>
        <PanelHeader
          title="Console"
          meta={run.status === "running" ? "live" : `${lines.length} lines`}
          actions={
            showLink ? (
              <Link to="/automation/$testId" params={{ testId: run.testId }}>
                <Button variant="outline" size="sm">
                  Open test
                </Button>
              </Link>
            ) : null
          }
        />
        <div
          ref={box}
          data-testid="run-console"
          className="max-h-[26rem] overflow-auto bg-panel2/40 px-4 py-3 font-mono text-[12px] leading-6"
        >
          {lines.length === 0 ? (
            <p className="text-muted-foreground">
              {run.status === "running"
                ? "Waiting for Playwright to print its first line…"
                : "This execution produced no output."}
            </p>
          ) : (
            lines.map((line, index) => (
              <div key={index} className="whitespace-pre-wrap text-muted-foreground">
                {line || " "}
              </div>
            ))
          )}
          {run.status === "running" ? (
            <div className="mt-1 flex items-center gap-2 text-primary">
              <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
              running
            </div>
          ) : null}
        </div>
      </Panel>

      {run.errorMessage ? (
        <Panel>
          <PanelHeader title="Failure" meta={`${run.failed} of ${run.total}`} />
          <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-6 text-fail">
            {run.errorMessage}
          </pre>
        </Panel>
      ) : null}
    </div>
  );
}
