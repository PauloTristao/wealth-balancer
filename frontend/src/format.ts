import type { Classe } from "./api";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const num = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

export const fmtBRL = (v: number | null | undefined) => (v == null ? "—" : brl.format(v));
export const fmtNum = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: d }).format(v);
export const fmtPct = (v: number | null | undefined, sign = false) =>
  v == null ? "—" : `${sign && v > 0 ? "+" : ""}${num.format(v)}%`;
export const signClass = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "pos" : "neg");
export const fmtDate = (iso: string) => iso.slice(0, 10).split("-").reverse().join("/");
export const fmtMes = (ym: string) => {
  const [y, m] = ym.split("-");
  return `${["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"][+m - 1]}/${y.slice(2)}`;
};

export const CLASSES: Classe[] = ["ACAO", "FII", "RF", "INTL"];
export const CLASS_LABEL: Record<Classe, string> = {
  ACAO: "Ações", FII: "FIIs", RF: "Renda Fixa", INTL: "Internacional", OUTROS: "Outros",
};
export const CLASS_COLOR: Record<Classe, string> = {
  ACAO: "var(--c-acao)", FII: "var(--c-fii)", RF: "var(--c-rf)", INTL: "var(--c-intl)", OUTROS: "var(--c-outros)",
};
