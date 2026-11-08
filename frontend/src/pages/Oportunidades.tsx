import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Classe, type Forca, type Oportunidade } from "../api";
import NewsInsight from "../components/NewsInsight";
import { CLASS_COLOR, CLASS_LABEL, fmtBRL, fmtNum, fmtPct } from "../format";

const TABS = ["ACAO", "FII", "INTL", "RF"] as const;
type Tab = (typeof TABS)[number];

const FORCA = {
  ALTA: { icon: "▲", label: "Força alta", color: "var(--good)" },
  MEDIA: { icon: "●", label: "Força média", color: "var(--warning)" },
  BAIXA: { icon: "▼", label: "Força baixa", color: "var(--critical)" },
  DESCARTADA: { icon: "✕", label: "Descartadas (filtro eliminatório)", color: "var(--muted)" },
} as const;

const PILAR_LABEL: Record<string, string> = {
  preco: "Preço", qualidade: "Qualidade", dividendos: "Dividendos", saude: "Saúde financeira", renda: "Renda", taxa: "Taxa",
};

type Col = { label: string; title?: string; get: (o: Oportunidade) => string };
const ind = (o: Oportunidade, k: string) => o.indicadores[k] as number | null | undefined;
const x = (v: number | null | undefined, d = 2) => (v == null ? "—" : fmtNum(v, d));
const pct = (v: number | null | undefined) => (v == null ? "—" : fmtPct(v));
const mi = (v: number | null | undefined) =>
  v == null ? "—" : v >= 1e9 ? `${fmtNum(v / 1e9, 1)} bi` : `${fmtNum(v / 1e6, 0)} mi`;

const COLS: Record<Exclude<Classe, "OUTROS">, Col[]> = {
  ACAO: [
    { label: "Preço", get: (o) => fmtBRL(o.preco) },
    { label: "P/VP", get: (o) => x(ind(o, "p_vp")) },
    { label: "P/L", get: (o) => x(ind(o, "p_l"), 1) },
    { label: "DY", get: (o) => pct(ind(o, "dy")) },
    { label: "ROE", get: (o) => pct(ind(o, "roe")) },
    { label: "Dív.líq/EBIT", get: (o) => x(ind(o, "div_liq_ebit")) },
    { label: "Cresc. rec. 5a", get: (o) => pct(ind(o, "cagr_receita_5a")) },
    { label: "Margem seg.", title: "Menor entre preço teto Bazin e Graham vs. preço atual", get: (o) => fmtPct(o.margem_seguranca_pct, true) },
  ],
  FII: [
    { label: "Preço", get: (o) => fmtBRL(o.preco) },
    { label: "P/VP", get: (o) => x(ind(o, "p_vp")) },
    { label: "DY 12m", get: (o) => pct(ind(o, "dy")) },
    { label: "Vacância", get: (o) => pct(ind(o, "vacancia")) },
    { label: "Imóveis", get: (o) => x(ind(o, "qtd_imoveis"), 0) },
    { label: "FFO/DY", title: "Cobertura: FFO yield ÷ DY", get: (o) => x(ind(o, "cobertura_ffo")) },
    { label: "Patrimônio", get: (o) => mi(ind(o, "patrimonio")) },
    { label: "Liquidez/dia", get: (o) => mi(ind(o, "liquidez_diaria")) },
  ],
  INTL: [
    { label: "Preço", get: (o) => fmtBRL(o.preco) },
    { label: "Faixa 52s", title: "0% = mínima do ano · 100% = máxima", get: (o) => pct(ind(o, "posicao_52s_pct")) },
    { label: "Abaixo da máx.", get: (o) => pct(ind(o, "desconto_max_52s_pct")) },
    { label: "Taxa adm.", get: (o) => pct(ind(o, "taxa_adm")) },
  ],
  RF: [
    { label: "Taxa", get: (o) => (o.segmento.toLowerCase().includes("selic") ? `Selic + ${x(ind(o, "taxa"))}%` : pct(ind(o, "taxa"))) },
    { label: "Juro real", get: (o) => pct(ind(o, "juro_real")) },
    { label: "Prazo", get: (o) => `${x(ind(o, "anos"), 1)} anos` },
    { label: "Preço unit.", get: (o) => fmtBRL(o.preco) },
  ],
};

function ScoreBar({ v }: { v: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full" style={{ background: "var(--band)" }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(v, 100)}%`, background: "var(--ink-2)" }} />
      </div>
      <span className="num w-8 text-right">{fmtNum(v, 0)}</span>
    </div>
  );
}

function Detalhe({ o, onClose }: { o: Oportunidade; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-20 flex justify-end" style={{ background: "rgba(0,0,0,0.35)" }} onClick={onClose}>
      <aside
        className="h-full w-full max-w-lg overflow-y-auto p-6"
        style={{ background: "var(--surface)", borderLeft: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xl font-semibold">{o.ticker}</div>
            <div className="text-sm text-2">{[o.nome, o.setor, o.segmento].filter(Boolean).join(" · ")}</div>
          </div>
          <button onClick={onClose} className="text-2" aria-label="Fechar">✕</button>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <span style={{ color: FORCA[o.forca].color }}>{FORCA[o.forca].icon}</span>
          <span className="font-semibold">{FORCA[o.forca].label}</span>
          <span className="num text-2">score {fmtNum(o.score, 1)}</span>
          {o.possui && (
            <span className="rounded px-2 py-0.5 text-sm" style={{ background: "var(--band)" }}>
              na carteira · {o.recomendacao_posse}
            </span>
          )}
        </div>
        {o.motivo_descarte && <p className="mt-2 text-sm neg">Descartada: {o.motivo_descarte}</p>}

        {o.alertas.length > 0 && (
          <ul className="mt-4 space-y-1 text-sm">
            {o.alertas.map((a) => (
              <li key={a}>⚠ {a}</li>
            ))}
          </ul>
        )}

        <div className="mt-5 font-semibold">Pilares</div>
        <div className="mt-2 space-y-2">
          {Object.entries(o.pilares).map(([p, v]) => (
            <div key={p} className="grid grid-cols-[130px_1fr_40px] items-center gap-3 text-sm">
              <span>{PILAR_LABEL[p] ?? p}</span>
              <div className="h-2 rounded-full" style={{ background: "var(--band)" }}>
                <div className="h-full rounded-full" style={{ width: `${v}%`, background: CLASS_COLOR[o.classe] }} />
              </div>
              <span className="num text-right">{fmtNum(v, 0)}</span>
            </div>
          ))}
        </div>

        <div className="mt-5 font-semibold">Critérios</div>
        <table className="mt-2 w-full text-sm">
          <tbody>
            {o.criterios.map((c) => (
              <tr key={c.nome} className="border-b align-top" style={{ borderColor: "var(--grid)" }}>
                <td className="py-1.5 pr-2">
                  <div>{c.nome}</div>
                  <div className="text-xs text-muted">{c.explicacao}</div>
                </td>
                <td className="num py-1.5 pr-2 text-right whitespace-nowrap">
                  {c.valor == null ? "—" : typeof c.valor === "number" ? `${fmtNum(c.valor, 2)}${c.fmt === "%" ? "%" : c.fmt === "x" ? "" : ""}` : c.valor}
                </td>
                <td className="num py-1.5 text-right whitespace-nowrap text-2">
                  {c.pontos == null ? "n/a" : `${fmtNum(c.pontos * 100, 0)} pts`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {(o.preco_teto_bazin || o.preco_graham) && (
          <div className="mt-5 text-sm">
            <div className="font-semibold">Preço justo de referência</div>
            <div className="num mt-1 text-2">
              Preço atual {fmtBRL(o.preco)} · Teto Bazin (DY 6%) {fmtBRL(o.preco_teto_bazin)} · Graham {fmtBRL(o.preco_graham)}
            </div>
          </div>
        )}
        {o.posicao && (
          <div className="num mt-3 text-sm text-2">
            Sua posição: {fmtNum(o.posicao.qtd, 2)} · preço médio {fmtBRL(o.posicao.preco_medio)}
          </div>
        )}
        <NewsInsight o={o} />
        <p className="mt-6 text-xs text-muted">
          Análise automática a partir de indicadores públicos; não é recomendação de investimento.
        </p>
      </aside>
    </div>
  );
}

export default function OportunidadesPage() {
  const qc = useQueryClient();
  const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const [tab, setTab] = useState<Tab>((TABS as readonly string[]).includes(params.get("classe") ?? "") ? (params.get("classe") as Tab) : "ACAO");
  const [ativoInicial, setAtivoInicial] = useState<string | null>(params.get("ativo"));
  const [busca, setBusca] = useState("");
  const [soMeus, setSoMeus] = useState(false);
  const [verDescartadas, setVerDescartadas] = useState(false);
  const [limite, setLimite] = useState<Record<string, number>>({});
  const [sel, setSel] = useState<Oportunidade | null>(null);

  const { data, isLoading, error } = useQuery({ queryKey: ["opp", tab], queryFn: () => api.opportunities(tab) });
  useEffect(() => {
    if (!ativoInicial || !data) return;
    const it = data.itens.find((i) => i.ticker.toUpperCase() === ativoInicial.toUpperCase());
    if (it) setSel(it);
    setAtivoInicial(null);
  }, [data, ativoInicial]);
  const refresh = useMutation({
    mutationFn: api.refreshOpportunities,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["opp"] }),
  });

  const grupos = useMemo(() => {
    const itens = (data?.itens ?? []).filter(
      (o) =>
        (!soMeus || o.possui) &&
        (!busca || `${o.ticker} ${o.nome} ${o.segmento}`.toLowerCase().includes(busca.toLowerCase())),
    );
    const fs: Forca[] = verDescartadas ? ["ALTA", "MEDIA", "BAIXA", "DESCARTADA"] : ["ALTA", "MEDIA", "BAIXA"];
    return fs.map((f) => ({ forca: f, itens: itens.filter((o) => o.forca === f) }));
  }, [data, busca, soMeus, verDescartadas]);

  const cols = COLS[tab];
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Oportunidades</h1>
        <button className="card px-3 py-1.5 text-sm" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          {refresh.isPending ? "Atualizando…" : "Atualizar indicadores"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${tab === t ? "font-semibold" : "text-2"}`}
            style={tab === t ? { background: "var(--band)" } : undefined}
          >
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[t] }} />
            {CLASS_LABEL[t]}
          </button>
        ))}
        <input
          className="card ml-auto w-56 px-3 py-1.5 text-sm"
          placeholder="Buscar ticker, nome ou segmento"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
        />
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={soMeus} onChange={(e) => setSoMeus(e.target.checked)} /> só os que tenho
        </label>
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={verDescartadas} onChange={(e) => setVerDescartadas(e.target.checked)} /> descartadas
        </label>
      </div>

      {data && (
        <div className="text-xs text-muted">
          Fontes: {Object.entries(data.fontes).map(([k, v]) => `${k}: ${v ?? "—"}`).join(" · ")}
          {data.erros.map((e) => (
            <div key={e} className="neg">{e}</div>
          ))}
          {data.sem_dados.length > 0 && <div>Sem dados na fonte: {data.sem_dados.join(", ")}</div>}
        </div>
      )}
      {isLoading && <p className="text-2">Buscando indicadores…</p>}
      {error && <p className="neg">Erro: {String(error)}</p>}

      {grupos.map((g) => {
        const lim = limite[g.forca] ?? (g.forca === "ALTA" ? 999 : 25);
        return (
          <div key={g.forca} className="card overflow-x-auto">
            <div className="flex items-center gap-2 px-4 pt-3 pb-2 font-semibold">
              <span style={{ color: FORCA[g.forca].color }}>{FORCA[g.forca].icon}</span>
              {FORCA[g.forca].label}
              <span className="text-sm font-normal text-2">({g.itens.length})</span>
            </div>
            {g.itens.length === 0 ? (
              <p className="px-4 pb-3 text-sm text-2">Nenhum ativo neste grupo com os filtros atuais.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-y text-2" style={{ borderColor: "var(--grid)" }}>
                    <th className="px-4 py-1.5 text-left font-medium">Ativo</th>
                    <th className="px-2 py-1.5 text-left font-medium">Score</th>
                    {cols.map((c) => (
                      <th key={c.label} className="px-2 py-1.5 text-right font-medium whitespace-nowrap" title={c.title}>
                        {c.label}
                      </th>
                    ))}
                    <th className="px-2 py-1.5 text-left font-medium">Observação</th>
                  </tr>
                </thead>
                <tbody>
                  {g.itens.slice(0, lim).map((o) => (
                    <tr
                      key={o.ticker}
                      className="cursor-pointer border-b hover:opacity-80"
                      style={{ borderColor: "var(--grid)" }}
                      onClick={() => setSel(o)}
                    >
                      <td className="px-4 py-1.5">
                        <div className="font-medium">
                          {o.ticker}
                          {o.possui && (
                            <span className="ml-2 rounded px-1.5 py-0.5 text-xs font-normal" style={{ background: "var(--band)" }}>
                              na carteira · {o.recomendacao_posse}
                            </span>
                          )}
                        </div>
                        <div className="max-w-[240px] truncate text-xs text-muted">{o.segmento || o.nome}</div>
                      </td>
                      <td className="px-2 py-1.5"><ScoreBar v={o.score} /></td>
                      {cols.map((c) => (
                        <td key={c.label} className="num px-2 py-1.5 text-right whitespace-nowrap">{c.get(o)}</td>
                      ))}
                      <td className="max-w-[260px] truncate px-2 py-1.5 text-xs text-2" title={o.alertas.join("\n")}>
                        {o.motivo_descarte ?? (o.alertas.length ? `⚠ ${o.alertas[0]}` : "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {g.itens.length > lim && (
              <button
                className="px-4 py-2 text-sm text-2 underline"
                onClick={() => setLimite({ ...limite, [g.forca]: lim + 50 })}
              >
                ver mais {Math.min(50, g.itens.length - lim)} de {g.itens.length - lim}
              </button>
            )}
          </div>
        );
      })}

      <p className="text-xs text-muted">
        Critérios e limites ajustáveis em backend/app/config/estrategia.yaml. Análise automática a partir de dados
        públicos (Fundamentus, Tesouro Transparente, Banco Central, Yahoo); não é recomendação de investimento.
      </p>
      {sel && <Detalhe o={sel} onClose={() => setSel(null)} />}
    </div>
  );
}
