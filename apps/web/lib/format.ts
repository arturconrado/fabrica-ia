export function shortId(id?: string) {
  return id ? id.slice(0, 8) : "";
}

export function fmtDate(value?: string) {
  if (!value) return "—";
  return new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });
}
