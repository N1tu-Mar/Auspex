import { useEffect, useState } from "react";

// ponytail: History API routes; one optional `?id=` on /analysis. Adopt a router library if
// more params appear.
export type Path = "/" | "/analysis" | `/analysis?id=${string}`;

export function navigate(path: Path, state: unknown = null) {
  history.pushState(state, "", path);
  dispatchEvent(new PopStateEvent("popstate", { state }));
}

const read = () => ({
  path: (location.pathname === "/analysis" ? "/analysis" : "/") as "/" | "/analysis",
  analysisId: new URLSearchParams(location.search).get("id") ?? undefined,
  state: history.state as unknown,
});

export function useLocation() {
  const [current, setCurrent] = useState(read);
  useEffect(() => {
    const update = () => setCurrent(read());
    addEventListener("popstate", update);
    return () => removeEventListener("popstate", update);
  }, []);
  return current;
}
