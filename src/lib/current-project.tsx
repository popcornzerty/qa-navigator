import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface CurrentProjectValue {
  projectId: string | null;
  setProjectId: (id: string) => void;
}

const CurrentProjectContext = createContext<CurrentProjectValue>({
  projectId: null,
  setProjectId: () => {},
});

export function CurrentProjectProvider({
  children,
  initialProjectId = null,
}: {
  children: ReactNode;
  initialProjectId?: string | null;
}) {
  const [projectId, setState] = useState<string | null>(initialProjectId);
  const setProjectId = useCallback((id: string) => setState(id), []);
  const value = useMemo(() => ({ projectId, setProjectId }), [projectId, setProjectId]);

  return <CurrentProjectContext.Provider value={value}>{children}</CurrentProjectContext.Provider>;
}

export function useCurrentProject() {
  return useContext(CurrentProjectContext);
}
