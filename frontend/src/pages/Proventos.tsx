import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Classe } from "../api";
import StatTile from "../components/StatTile";
import { CLASSES, CLASS_COLOR, CLASS_LABEL, fmtBRL, fmtDate, fmtMes } from "../format";

const RANGES = [
  { id: 12, label: "12 meses" },
  { id: 24, label: "24 meses" },
  { id: 0, label: "Tudo" },
];

/** Preenche meses sem proventos para o eixo do tempo ficar contínuo. */
function fillMonths(rows: { mes: string }[]): string[] {
  if (!rows.length) return [];
  const [y0, m0] = rows[0].mes.split("-").map(Number);
  const now = new Date();
  const out: string[] = [];
  for (let y = y0, m = m0; y < now.getFullYear() || (y === now.getFullYear() && m <= now.getMonth() + 1); ) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m++;
    if (m > 12) {
      m = 1;
      y++;
    }
  }
  return out;
}

export default function ProventosPage() {
  const { data, isLoading } = useQuery({ queryKey: ["income"], queryFn: api.income });
  const [range, setRange] = useState(24);

  const serie = useMemo(() => {
    if (!data) return [];
    const map = new Map(data.por_mes.map((r) => [r.mes, r]));
    const all = fillMonths(data.por_mes).map((mes) => {
      const r = map.get(mes);
      return {
        mes,
        label: fmtMes(mes),
        ...Object.fromEntries(CLASSES.map((c) => [c, r?.[c] ?? 0])),
        total: r?.total ?? 0,
      };
    });
    return range ? all.slice(-range) : all;
  }, [data, range]);

  if (isLoading || !data) return <p className="text-2">Carregando…</p>;

  const desde = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
  const total12 = data.lancamentos.filter((l) => l.data >= desde).reduce((s, l) => s + l.valor, 0);
  const presentes = CLASSES.filter((c) => serie.some((r) => ((r as unknown as Record<string, number>)[c] ?? 0) > 0));

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Proventos</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile label="Últimos 12 meses" value={fmtBRL(total12)} sub={`média ${fmtBRL(total12 / 12)}/mês`} />
        <StatTile
          label="Total recebido"
          value={fmtBRL(data.lancamentos.reduce((s, l) => s + l.valor, 0))}
          sub={`${data.lancamentos.length} lançamentos`}
        />
        <StatTile
          label="Maior pagador"
          value={data.por_ativo[0]?.ticker ?? "—"}
          sub={fmtBRL(data.por_ativo[0]?.valor)}
        />
      </div>

      <div className="card p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="font-semibold">Proventos por mês, por classe</div>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.id}
                onClick={() => setRange(r.id)}
                className={`rounded-md px-2.5 py-1 text-sm ${range === r.id ? "font-semibold" : "text-2"}`}
                style={range === r.id ? { background: "var(--band)" } : undefined}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={serie} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={{ stroke: "var(--axis)" }} tickLine={false} />
            <YAxis
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `R$ ${v}`}
              width={70}
            />
            <Tooltip
              cursor={{ fill: "var(--band)", opacity: 0.6 }}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }}
              labelStyle={{ color: "var(--ink)", fontWeight: 600 }}
              itemStyle={{ color: "var(--ink)" }}
              formatter={(v, name) => [fmtBRL(Number(v)), CLASS_LABEL[name as Classe] ?? name]}
            />
            <Legend formatter={(v) => <span style={{ color: "var(--ink-2)" }}>{CLASS_LABEL[v as Classe]}</span>} />
            {presentes.map((c, i) => (
              <Bar
                key={c}
                dataKey={c}
                stackId="p"
                fill={CLASS_COLOR[c]}
                stroke="var(--surface)"
                strokeWidth={1}
                radius={i === presentes.length - 1 ? [4, 4, 0, 0] : 0}
                maxBarSize={28}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="card p-5">
          <div className="mb-3 font-semibold">Total por ativo</div>
          <table className="w-full text-sm">
            <tbody>
              {data.por_ativo.map((a) => (
                <tr key={a.ticker} className="border-b" style={{ borderColor: "var(--grid)" }}>
                  <td className="py-1.5">{a.ticker}</td>
                  <td className="num py-1.5 text-right">{fmtBRL(a.valor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card p-5">
          <div className="mb-3 font-semibold">Últimos lançamentos</div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {data.lancamentos.slice(0, 200).map((l, i) => (
                  <tr key={i} className="border-b" style={{ borderColor: "var(--grid)" }}>
                    <td className="num py-1.5 text-muted">{fmtDate(l.data)}</td>
                    <td className="py-1.5">{l.ticker}</td>
                    <td className="py-1.5 text-2">{l.tipo}</td>
                    <td className="num py-1.5 text-right">{fmtBRL(l.valor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
