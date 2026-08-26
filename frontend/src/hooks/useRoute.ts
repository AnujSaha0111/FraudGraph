import { useEffect, useState } from "react";

export type Route =
  | { name: "home" }
  | { name: "cases" }
  | { name: "tx"; id: string }
  | { name: "case"; id: string };

export function parseHash(hash: string): Route {
  const clean = hash.replace(/^#/, "");
  const parts = clean.split("/").filter(Boolean);
  if (parts[0] === "cases") return { name: "cases" };
  if (parts[0] === "tx" && parts[1] && /^\d+$/.test(parts[1])) {
    // ids stay STRINGS: backend int64 ids exceed Number.MAX_SAFE_INTEGER
    return { name: "tx", id: parts[1] };
  }
  if (parts[0] === "case" && parts[1] && /^\d+$/.test(parts[1])) {
    return { name: "case", id: parts[1] };
  }
  return { name: "home" };
}

export function useRoute(): [Route, (to: string) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = (to: string) => {
    window.location.hash = to;
  };
  return [route, navigate];
}
