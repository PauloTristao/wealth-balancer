import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type Classe, type Janela, type MesEvolucao } from "../api";
import StatTile from "../components/StatTile";
import { CLASSES, CLASS_COLOR, CLASS_LABEL, fmtBRL, fmtMes, fmtPct, signClass } from "../format";

const RANGES = [
  { id: 12, label: "12 meses" },
  { id: 36, label: "3 anos" },
  { id: 0, label: "Tudo" },
];

const tooltipStyle = {
  contentStyle: { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 },
  labelStyle: { color: "var(--ink)", fontWeight: 600 },
  itemStyle: { color: "var(--ink)" },
};
const axisTick = { fill: "var(--muted)", fontSize: 12 };
const kBRL = (v: number) => (Math.abs(v) >= 1000 ? `R$ ${Math.round(v / 1000)} mil` : `R$ ${v}`);

const BENCH = {
  carteira: { label: "Carteira", color: "var(--ink)" },
  cdi: { label: "CDI", color: "var(--c-cdi)" },
  ibov: { label: "Ibovespa", color: "var(--c-ibov)" },
} as const;

/** Rentabilidade acumulada rebaseada para o início do período escolhido. */
function rebase(meses: MesEvolucao[], all: MesEvolucao[]) {
  const i0 = all.indexOf(meses[0]);
  const prevIbov = i0 > 0 ? all[i0 - 1].ibov_acum_pct : 0;
  let c = 1;
  let d = 1;
  return meses.map((m) => {
    c *= 1 + m.rent_mes_pct / 100;
    d *= 1 + (m.cdi_mes_pct ?? 0) / 100;
    const ibov =
      m.ibov_acum_pct == null || prevIbov == null ? null : ((1 + m.ibov_acum_pct / 100) / (1 + prevIbov / 100) - 1) * 100;
    return {
      mes: m.mes,
      label: fmtMes(m.mes),
      carteira: +(100 * (c - 1)).toFixed(2),
      cdi: +(100 * (d - 1)).toFixed(2),
      ibov: ibov == null ? null : +ibov.toFixed(2),
    };
  });
}

function EndLabel(props: { x?: number; y?: number; index?: number; value?: number; total: number; name: string; color: string }) {
  const { x, y, index, value, total, name, color } = props;
  if (index !== total - 1 || x == null || y == null || value == null) return null;
  return (
    <text x={x + 8} y={y} dy={4} fontSize={12} fill="var(--ink)">
      <tspan fill={color} fontWeight={700}>● </tspan>
      {name} {fmtPct(value, true)}
    </text>
  );
}

function JanelaTile({ label, j }: { label: string; j?: Janela }) {
  if (!j) return null;
  return (
    <StatTile
      label={`Rentabilidade · ${label}`}
      value={<span className={signClass(j.carteira_pct)}>{fmtPct(j.carteira_pct, true)}</span>}
      sub={
        <>
          CDI {fmtPct(j.cdi_pct, true)} · Ibovespa {fmtPct(j.ibov_pct, true)}
        </>
      }
    />
  );
}

export default function EvolucaoPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["evolution"], queryFn: api.evolution });
  const [range, setRange] = useState(36);

  const meses = useMemo(() => (data ? (range ? data.meses.slice(-range) : data.meses) : []), [data, range]);
  const patrimonio = useMemo(
    () =>
      meses.map((m) => ({
        mes: m.mes,
        label: fmtMes(m.mes),
        aplicado: m.aplicado,
        total: m.patrimonio,
        ...Object.fromEntries(CLASSES.map((c) => [c, m.por_classe[c] ?? 0])),
      })),
    [meses],
  );
  const rent = useMemo(() => (data ? rebase(meses, data.meses) : []), [meses, data]);

  if (isLoading) return <p className="text-2">Calculando a evolução mês a mês (a primeira vez baixa os históricos)…</p>;
  if (error) return <p className="neg">Erro: {String(error)}</p>;
  if (!data?.resumo) return <p className="text-2">Importe seus relatórios da B3 para ver a evolução.</p>;

  const r = data.resumo;
  const presentes = CLASSES.filter((c) => meses.some((m) => (m.por_classe[c] ?? 0) > 0));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Evolução patrimonial</h1>
        <div className="flex gap-1">
          {RANGES.map((x) => (
            <button
              key={x.id}
              onClick={() => setRange(x.id)}
              className={`rounded-md px-2.5 py-1 text-sm ${range === x.id ? "font-semibold" : "text-2"}`}
              style={range === x.id ? { background: "var(--band)" } : undefined}
            >
              {x.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Patrimônio"
          value={fmtBRL(r.patrimonio)}
          sub={<>aplicado {fmtBRL(r.aplicado)}</>}
        />
        <JanelaTile label="no ano" j={r.no_ano} />
        <JanelaTile label="12 meses" j={r.ultimos_12m} />
        <JanelaTile label={`desde ${fmtMes(r.inicio)}`} j={r.desde_inicio} />
      </div>

      <div className="card p-5">
        <div className="mb-1 font-semibold">Patrimônio no fim de cada mês, por classe</div>
        <div className="mb-3 text-sm text-2">Áreas empilhadas = valor de mercado · linha tracejada = valor aplicado (custo)</div>
        <div className="mb-2 flex flex-wrap gap-4 text-sm text-2">
          {presentes.map((c) => (
            <span key={c} className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[c] }} />
              {CLASS_LABEL[c]}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <svg width="18" height="4"><line x1="0" y1="2" x2="18" y2="2" stroke="var(--ink)" strokeWidth="2" strokeDasharray="5 3" /></svg>
            Aplicado
          </span>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={patrimonio} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: "var(--axis)" }} tickLine={false} minTickGap={16} />
            <YAxis tick={axisTick} axisLine={false} tickLine={false} tickFormatter={kBRL} width={80} />
            <Tooltip
              {...tooltipStyle}
              cursor={{ stroke: "var(--axis)" }}
              formatter={(v, name) => [fmtBRL(Number(v)), name === "aplicado" ? "Aplicado" : CLASS_LABEL[name as Classe]]}
            />
            {presentes.map((c) => (
              <Area
                key={c}
                dataKey={c}
                stackId="v"
                type="monotone"
                fill={CLASS_COLOR[c]}
                fillOpacity={0.85}
                stroke="var(--surface)"
                strokeWidth={1}
                isAnimationActive={false}
              />
            ))}
            <Line
              dataKey="aplicado"
              type="monotone"
              stroke="var(--ink)"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="card p-5">
        <div className="mb-1 font-semibold">Rentabilidade acumulada no período</div>
        <div className="mb-3 text-sm text-2">
          Desconta aportes e resgates (método de Dietz) e inclui proventos. Base 0% no início do período escolhido.
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={rent} margin={{ top: 8, right: 150, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: "var(--axis)" }} tickLine={false} minTickGap={16} />
            <YAxis tick={axisTick} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} width={50} />
            <ReferenceLine y={0} stroke="var(--axis)" />
            <Tooltip
              {...tooltipStyle}
              cursor={{ stroke: "var(--axis)" }}
              formatter={(v, name) => [fmtPct(Number(v), true), BENCH[name as keyof typeof BENCH].label]}
            />
            <Legend formatter={(v) => <span style={{ color: "var(--ink-2)" }}>{BENCH[v as keyof typeof BENCH].label}</span>} />
            {(Object.keys(BENCH) as (keyof typeof BENCH)[]).map((k) => (
              <Line
                key={k}
                dataKey={k}
                type="monotone"
                stroke={BENCH[k].color}
                strokeWidth={k === "carteira" ? 3 : 2}
                dot={false}
                activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
                connectNulls
                isAnimationActive={false}
                label={<EndLabel total={rent.length} name={BENCH[k].label} color={BENCH[k].color} />}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-2" style={{ borderColor: "var(--grid)" }}>
              <th className="px-3 py-2 text-left font-medium">Mês</th>
              {presentes.map((c) => (
                <th key={c} className="px-3 py-2 text-right font-medium">{CLASS_LABEL[c]}</th>
              ))}
              <th className="px-3 py-2 text-right font-medium">Patrimônio</th>
              <th className="px-3 py-2 text-right font-medium">Aplicado</th>
              <th className="px-3 py-2 text-right font-medium">Aportes líquidos</th>
              <th className="px-3 py-2 text-right font-medium">Proventos</th>
              <th className="px-3 py-2 text-right font-medium">Rent. mês</th>
              <th className="px-3 py-2 text-right font-medium">CDI mês</th>
            </tr>
          </thead>
          <tbody>
            {[...meses].reverse().map((m) => (
              <tr key={m.mes} className="num border-b" style={{ borderColor: "var(--grid)" }}>
                <td className="px-3 py-1.5" title={m.estimados.length ? `Sem cotação histórica (valor = custo): ${m.estimados.join(", ")}` : undefined}>
                  {fmtMes(m.mes)}
                  {m.estimados.length > 0 && <span className="text-muted"> *</span>}
                </td>
                {presentes.map((c) => (
                  <td key={c} className="px-3 py-1.5 text-right">{fmtBRL(m.por_classe[c] ?? 0)}</td>
                ))}
                <td className="px-3 py-1.5 text-right font-semibold">{fmtBRL(m.patrimonio)}</td>
                <td className="px-3 py-1.5 text-right">{fmtBRL(m.aplicado)}</td>
                <td className="px-3 py-1.5 text-right">{fmtBRL(m.aportes)}</td>
                <td className="px-3 py-1.5 text-right">{fmtBRL(m.proventos)}</td>
                <td className={`px-3 py-1.5 text-right ${signClass(m.rent_mes_pct)}`}>{fmtPct(m.rent_mes_pct, true)}</td>
                <td className="px-3 py-1.5 text-right">{fmtPct(m.cdi_mes_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="px-3 py-2 text-xs text-muted">
          * mês com ativo sem cotação histórica disponível (deslistado); valor considerado pelo custo. Posições manuais
          (fora da B3) não entram no histórico.
        </p>
      </div>
    </div>
  );
}
