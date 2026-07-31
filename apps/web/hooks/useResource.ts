"use client";

import { useEffect, useRef, useState } from "react";


export function useResource<T>(loader: () => Promise<T>, dependencies: ReadonlyArray<unknown> = []) {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    loaderRef.current()
      .then((value) => { if (active) setData(value); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Não foi possível carregar o recurso."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // The explicit dependency list is controlled by each resource owner.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, nonce]);

  return {
    data,
    error,
    loading,
    refresh: () => setNonce((value) => value + 1),
    setError,
  };
}
