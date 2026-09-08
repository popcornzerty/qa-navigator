import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { projectsApi } from "../api";

interface CurrentProjectValue {
  projectId: string | null;
  setProjectId: (id: string) => void;
}

const CurrentProjectContext = createContext<CurrentProjectValue>({
  projectId: null,
  setProjectId: () => {},
});

/**
 * Holds the project every screen is scoped to.
 *
 * Until the user picks one, the first project returned by the API wins. Hardcoding a
 * default id here would tie the shell to whichever backend happens to own that id.
 */
export function CurrentProjectProvider({
  children,
  initialProjectId = null,
}: {
  children: ReactNode;
  initialProjectId?: string | null;
}) {
  const [selected, setSelected] = useState<string | null>(initialProjectId);
  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });

  const setProjectId = useCallback((id: string) => setSelected(id), []);
  const projectId = selected ?? projects?.[0]?.id ?? null;
  const value = useMemo(() => ({ projectId, setProjectId }), [projectId, setProjectId]);

  return <CurrentProjectContext.Provider value={value}>{children}</CurrentProjectContext.Provider>;
}

export function useCurrentProject() {
  return useContext(CurrentProjectContext);
}
