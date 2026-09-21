import { useEffect, useState } from "react";

// ponytail: two routes on the History API; adopt a router library when routes need params.
export type Path = "/" | "/analysis";

export function navigate(path: Path, state: unknown = null) {
  history.pushState(state, "", path);
  dispatchEvent(new PopStateEvent("popstate", { state }));
}

const read = () => ({
  path: (location.pathname === "/analysis" ? "/analysis" : "/") as Path,
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
