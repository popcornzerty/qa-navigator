import type { TestOrigin } from "../../types/models";

export const ORIGIN_LABELS: Record<TestOrigin, string> = {
  discovered: "Existing",
  code: "From code",
  jira: "From Jira",
  manual: "Manual",
};

/** What a passing run of this test actually establishes.
 *
 *  These are not decoration. A test derived from the code cannot fail on the code it was
 *  derived from: it pins current behaviour, bugs included, and only ever catches a later
 *  change. Reading it as evidence that the product is correct is the single most
 *  expensive mistake this tool could invite, so the claim is stated wherever the verdict
 *  is shown rather than left for the reader to infer from a colour.
 */
export const ORIGIN_PROVES: Record<TestOrigin, string> = {
  jira: "A stated requirement is met.",
  discovered: "A behaviour a person verified still holds.",
  code: "Current behaviour is unchanged — not that it is correct.",
  manual: "What its author set out to check still holds.",
};

/** The longer form, for a detail view that has room to explain rather than assert. */
export const ORIGIN_EXPLANATIONS: Record<TestOrigin, string> = {
  jira: "Generated from a User Story imported from Jira. The requirement was written by a person; a passing run means the product meets it.",
  discovered:
    "This test already existed in the repository. It was written against the product directly, so it traces to no User Story — a passing run means a behaviour someone verified still holds.",
  code: "Generated from the code as it is, so it cannot fail on the code that produced it. A passing run means behaviour has not changed since — it says nothing about whether that behaviour is correct. Review the User Story before treating it as coverage.",
  manual: "Written by hand in this project. A passing run means what its author set out to check still holds.",
};

const STYLES: Record<TestOrigin, string> = {
  discovered: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
  code: "bg-primary/10 text-primary ring-primary/30",
  jira: "bg-sky-500/10 text-sky-400 ring-sky-500/30",
  manual: "bg-panel2 text-muted-foreground ring-line",
};

export function OriginBadge({ origin }: { origin: TestOrigin }) {
  return (
    <span
      data-testid="test-origin"
      title={`Proves: ${ORIGIN_PROVES[origin]}`}
      className={`rounded-md px-2 py-0.5 text-[11px] whitespace-nowrap ring-1 ${STYLES[origin]}`}
    >
      {ORIGIN_LABELS[origin]}
    </span>
  );
}
