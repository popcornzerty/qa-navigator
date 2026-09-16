import type { PlaywrightTest } from "../types/models";

/** Counts a group is read by: what is red, what is moving, what has no verdict. */
export interface GroupCounts {
  total: number;
  passed: number;
  failed: number;
  running: number;
  /** Skipped or never run: no verdict either way. */
  pending: number;
}

/** Every test of one spec file — the unit a QA engineer opens, fixes and reruns. */
export interface FileGroup {
  file: string;
  label: string;
  tests: PlaywrightTest[];
  counts: GroupCounts;
}

/** A directory of the repository holding spec files. */
export interface FolderGroup {
  folder: string;
  label: string;
  files: FileGroup[];
  counts: GroupCounts;
}

const SPEC_SUFFIX = /\.(spec|test|setup)\.[cm]?[jt]sx?$/;

/** `frontend/e2e/ajout-position.spec.ts` → `Ajout position`. */
export function fileLabel(path: string): string {
  const name = path.split("/").pop() ?? path;
  const bare = name
    .replace(SPEC_SUFFIX, "")
    .replace(/[-_.]+/g, " ")
    .trim();
  return bare ? bare.charAt(0).toUpperCase() + bare.slice(1) : name;
}

/** `frontend/e2e/ajout-position.spec.ts` → `frontend/e2e`. */
export function folderOf(path: string): string {
  const index = path.lastIndexOf("/");
  return index === -1 ? "." : path.slice(0, index);
}

function countsOf(tests: PlaywrightTest[]): GroupCounts {
  const counts: GroupCounts = { total: 0, passed: 0, failed: 0, running: 0, pending: 0 };
  for (const test of tests) {
    counts.total += 1;
    if (test.status === "passed") counts.passed += 1;
    else if (test.status === "failed") counts.failed += 1;
    else if (test.status === "running") counts.running += 1;
    else counts.pending += 1;
  }
  return counts;
}

function add(into: GroupCounts, from: GroupCounts): GroupCounts {
  return {
    total: into.total + from.total,
    passed: into.passed + from.passed,
    failed: into.failed + from.failed,
    running: into.running + from.running,
    pending: into.pending + from.pending,
  };
}

/** What needs looking at comes first: red, then running, then without a verdict. */
function urgency(counts: GroupCounts): number {
  if (counts.failed > 0) return 0;
  if (counts.running > 0) return 1;
  if (counts.pending > 0) return 2;
  return 3;
}

/** A group that holds anything other than green is opened; an all-green one is folded. */
export function needsAttention(counts: GroupCounts): boolean {
  return urgency(counts) < 3;
}

/**
 * Tests grouped the way the repository organises them: directory, then spec file.
 *
 * Nothing is named by hand. A folder a person maintains drifts the moment a spec is added
 * or renamed; the repository's own layout does not, and it is where the file to open is.
 */
export function groupTests(tests: PlaywrightTest[]): FolderGroup[] {
  const byFile = new Map<string, PlaywrightTest[]>();
  for (const test of tests) {
    const list = byFile.get(test.file) ?? [];
    list.push(test);
    byFile.set(test.file, list);
  }

  const byFolder = new Map<string, FileGroup[]>();
  for (const [file, list] of byFile) {
    const group: FileGroup = { file, label: fileLabel(file), tests: list, counts: countsOf(list) };
    const folder = folderOf(file);
    byFolder.set(folder, [...(byFolder.get(folder) ?? []), group]);
  }

  return [...byFolder.entries()]
    .map(([folder, files]) => {
      files.sort(
        (a, b) => urgency(a.counts) - urgency(b.counts) || a.label.localeCompare(b.label, "fr"),
      );
      const counts = files.reduce<GroupCounts>((total, file) => add(total, file.counts), {
        total: 0,
        passed: 0,
        failed: 0,
        running: 0,
        pending: 0,
      });
      return { folder, label: folder === "." ? "(racine)" : folder, files, counts };
    })
    .sort(
      (a, b) => urgency(a.counts) - urgency(b.counts) || a.folder.localeCompare(b.folder, "fr"),
    );
}
