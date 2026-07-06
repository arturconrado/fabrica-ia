"use client";

import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";

export function AuthTokenControl() {
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const existing = window.localStorage.getItem("asf_bearer_token") || "";
    setToken(existing);
    setSaved(Boolean(existing));
  }, []);

  function saveToken() {
    if (token.trim()) {
      window.localStorage.setItem("asf_bearer_token", token.trim());
      setSaved(true);
    } else {
      window.localStorage.removeItem("asf_bearer_token");
      setSaved(false);
    }
  }

  return (
    <div className="hidden items-center gap-2 rounded-md border border-line bg-slate-50 px-2 py-1 lg:flex">
      <KeyRound className="h-3.5 w-3.5 text-slate-500" />
      <input
        aria-label="OIDC bearer token"
        className="h-7 w-40 bg-transparent text-xs outline-none placeholder:text-slate-400 xl:w-56"
        value={token}
        onChange={(event) => {
          setToken(event.target.value);
          setSaved(false);
        }}
        placeholder="OIDC bearer token"
        type="password"
      />
      <button className="rounded bg-slate-900 px-2 py-1 text-xs font-medium text-white" onClick={saveToken} type="button">
        {saved ? "Token set" : "Set token"}
      </button>
    </div>
  );
}
