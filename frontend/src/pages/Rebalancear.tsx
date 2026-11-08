import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type ClasseSim } from "../api";
import StatTile from "../components/StatTile";
import { CLASS_COLOR, CLASS_LABEL, fmtBRL, fmtNum, fmtPct } from "../format";

const SCALE = 50;
const x = (p: number) => `${(Math.min(Math.max(p, 0), SCALE) / SCALE) * 100}%`;
const PRESETS = [1000, 2000, 3000, 5000, 10000];

/** Antes (marcador vazado) → depois (barra) contra a faixa e o alvo. */
function ClasseRow({ c }: { c: ClasseSim }) {
  const [hover, setHover] = useState(false);
  const fora = c.depois_pct < c.min || c.depois_pct > c.max;
  const mov = c.comprar - c.vender;
  return (
    <div
      className="relative grid grid-cols-[130px_1fr_230px] items-center gap-4"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="flex items-center gap-2 font-medium">
        <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[c.classe] }} />
        {CLASS_LABEL[c.classe]}
      </div>
      <div className="relative h-7">
        <div
          className="absolute top-0 h-full rounded"
          style={{ left: x(c.min), width: `calc(${x(c.max)} - ${x(c.min)})`, background: "var(--band)" }}
        />
        <div
          className="absolute top-1.5 h-4"
          style={{ left: 0, width: x(c.depois_pct), background: CLASS_COLOR[c.classe], borderRadius: "0 4px 4px 0" }}
        />
        <div
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ left: x(c.antes_pct), border: "2px solid var(--ink)", background: "var(--surface)" }}
          title="antes"
        />
        <div className="absolute top-0 h-full w-0.5" style={{ left: x(c.alvo), background: "var(--ink)" }} />
      </div>
      <div className="num text-sm">
        <div>
          {fmtPct(c.antes_pct)} → <b>{fmtPct(c.depois_pct)}</b> {fora ? "⚠ fora da faixa" : ""}
        </div>
        <div className="text-2">
          {mov > 0 ? `comprar ${fmtBRL(c.comprar)}` : mov < 0 ? `vender ${fmtBRL(c.vender)}` : "sem movimento"}
        </div>
      </div>
      {hover && (
        <div className="card num pointer-events-none absolute z-10 px-3 py-2 text-sm shadow-lg" style={{ left: 150, top: -44 }}>
          <b>{CLASS_LABEL[c.classe]}</b>: {fmtBRL(c.antes)} → {fmtBRL(c.depois)} · alvo {c.alvo}% · faixa {c.min}–{c.max}%
        </div>
      )}
    </div>
  );
}

export default function RebalancearPage() {
  const [texto, setTexto] = useState("3000");
  const [vendas, setVendas] = useState(false);
  const [novos, setNovos] = useState(true);
  const [aporte, setAporte] = useState(3000);

  useEffect(() => {
    const t = setTimeout(() => {
      const v = Number(texto.replace(/\./g, "").replace(",", "."));
      if (Number.isFinite(v) && v >= 0) setAporte(v);
    }, 400);
    return () => clearTimeout(t);
  }, [texto]);

  const { data, isFetching, error } = useQuery({
    queryKey: ["rebalance", aporte, vendas, novos],
    queryFn: () => api.rebalance(aporte, vendas, novos),
    placeholderData: keepPreviousData,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Simular aporte</h1>

      <div className="card p-4 text-sm" style={{ borderLeft: "4px solid var(--c-cdi)" }}>
        <b>ⓘ Apenas simulação.</b> Nada é salvo nem registrado como compra. A carteira só muda quando você importar os
        relatórios da B3 do mês seguinte.
      </div>

      <div className="card flex flex-wrap items-end gap-4 p-5">
        <label className="text-sm">
          <div className="mb-1 text-2">Valor do aporte (R$)</div>
          <input
            className="card num w-44 px-3 py-2 text-lg"
            inputMode="decimal"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
          />
        </label>
        <div className="flex gap-1">
          {PRESETS.map((p) => (
            <button key={p} className="card px-2.5 py-1.5 text-sm" onClick={() => setTexto(String(p))}>
              {fmtBRL(p).replace(",00", "")}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={vendas} onChange={(e) => setVendas(e.target.checked)} />
          Considerar vendas para trazer classes acima de 35% de volta à faixa
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={novos} onChange={(e) => setNovos(e.target.checked)} />
          Incluir novas oportunidades (força Alta)
        </label>
        {isFetching && <span className="text-sm text-muted">calculando…</span>}
      </div>

      {error && <p className="neg">Erro: {String(error)}</p>}

      {data && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <StatTile label="Aporte" value={fmtBRL(data.aporte)} />
            <StatTile label="Vendas sugeridas" value={fmtBRL(data.vendas)} sub={vendas ? "classes acima da faixa" : "desativado"} />
            <StatTile label="Carteira depois" value={fmtBRL(data.total_depois)} sub={<>antes {fmtBRL(data.total_antes)}</>} />
            <StatTile label="Sobra (não alocado)" value={fmtBRL(data.sobra)} sub="arredondamento de cotas" />
          </div>

          <div className="card p-5">
            <div className="mb-1 font-semibold">Alocação antes → depois</div>
            <div className="mb-4 flex flex-wrap items-center gap-4 text-sm text-2">
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 rounded-full" style={{ border: "2px solid var(--ink)" }} /> antes
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-5 rounded-sm" style={{ background: "var(--ink-2)" }} /> depois
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-5 rounded-sm" style={{ background: "var(--band)" }} /> faixa permitida
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-0.5" style={{ background: "var(--ink)" }} /> alvo
              </span>
            </div>
            <div className="space-y-4">
              {data.classes.map((c) => (
                <ClasseRow key={c.classe} c={c} />
              ))}
            </div>
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-2" style={{ borderColor: "var(--grid)" }}>
                  <th className="px-3 py-2 text-left font-medium">Operação</th>
                  <th className="px-3 py-2 text-left font-medium">Ativo</th>
                  <th className="px-3 py-2 text-left font-medium">Classe</th>
                  <th className="px-3 py-2 text-right font-medium">Qtd</th>
                  <th className="px-3 py-2 text-right font-medium">Preço atual</th>
                  <th className="px-3 py-2 text-right font-medium">Valor</th>
                  <th className="px-3 py-2 text-left font-medium">Motivo</th>
                </tr>
              </thead>
              <tbody>
                {data.operacoes.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-3 py-3 text-2">
                      Nenhuma operação sugerida.
                    </td>
                  </tr>
                )}
                {data.operacoes.map((o) => (
                  <tr key={o.acao + o.ticker} className="num border-b" style={{ borderColor: "var(--grid)" }}>
                    <td className={`px-3 py-1.5 font-semibold ${o.acao === "VENDER" ? "neg" : "pos"}`}>
                      {o.acao === "VENDER" ? "▼ Vender" : "▲ Comprar"}
                    </td>
                    <td className="px-3 py-1.5 font-medium">
                      {o.ticker}
                      {o.novo && (
                        <span className="ml-2 rounded px-1.5 py-0.5 text-xs" style={{ background: "var(--band)" }}>
                          novo
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ background: CLASS_COLOR[o.classe] }} />
                      {CLASS_LABEL[o.classe]}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtNum(o.qtd, 2)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtBRL(o.preco)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtBRL(o.valor)}</td>
                    <td className="px-3 py-1.5 text-2">{o.motivo}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="space-y-1 text-sm text-2">
            {data.avisos.map((a) => (
              <li key={a}>• {a}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
