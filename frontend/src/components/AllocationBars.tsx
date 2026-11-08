import { useState } from "react";
import type { Alocacao } from "../api";
import { CLASS_COLOR, fmtBRL, fmtPct } from "../format";

const SCALE = 50; // eixo de 0 a 50%

const STATUS = {
  abaixo: { icon: "▼", label: "Abaixo da faixa", color: "var(--warning)" },
  acima: { icon: "▲", label: "Acima da faixa", color: "var(--critical)" },
  ok: { icon: "✓", label: "Na faixa", color: "var(--good)" },
  fora: { icon: "•", label: "Fora do balanceamento", color: "var(--muted)" },
} as const;

/** Alocação atual por classe vs. alvo (traço) e faixa permitida (banda). */
export default function AllocationBars({ data }: { data: Alocacao[] }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = data.filter((a) => a.pct != null);
  const x = (p: number) => `${(Math.min(p, SCALE) / SCALE) * 100}%`;

  return (
    <div className="card p-5">
      <div className="mb-1 font-semibold">Alocação por classe</div>
      <div className="mb-4 text-sm text-2">Barra = % atual · faixa cinza = intervalo permitido · traço = alvo</div>
      <div className="space-y-4">
        {rows.map((a) => {
          const st = STATUS[a.status];
          const falta = a.falta_para_alvo ?? 0;
          return (
            <div
              key={a.classe}
              className="relative grid grid-cols-[130px_1fr_220px] items-center gap-4"
              onMouseEnter={() => setHover(a.classe)}
              onMouseLeave={() => setHover(null)}
            >
              <div>
                <div className="flex items-center gap-2 font-medium">
                  <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[a.classe] }} />
                  {a.label}
                </div>
                <div className="num text-sm text-2">{fmtBRL(a.valor)}</div>
              </div>
              <div className="relative h-7">
                <div
                  className="absolute top-0 h-full rounded"
                  style={{ left: x(a.min!), width: `calc(${x(a.max!)} - ${x(a.min!)})`, background: "var(--band)" }}
                />
                <div
                  className="absolute top-1.5 h-4"
                  style={{ left: 0, width: x(a.pct!), background: CLASS_COLOR[a.classe], borderRadius: "0 4px 4px 0" }}
                />
                <div className="absolute top-0 h-full w-0.5" style={{ left: x(a.alvo!), background: "var(--ink)" }} />
                <span className="num absolute top-1 pl-1.5 text-sm font-semibold" style={{ left: x(a.pct!) }}>
                  {fmtPct(a.pct)}
                </span>
              </div>
              <div className="text-sm">
                <div className="flex items-center gap-1.5">
                  <span style={{ color: st.color }}>{st.icon}</span>
                  <span>{st.label}</span>
                </div>
                <div className="num text-2">
                  {falta > 0 ? `Faltam ${fmtBRL(falta)} p/ o alvo` : `${fmtBRL(-falta)} acima do alvo`}
                </div>
              </div>
              {hover === a.classe && (
                <div
                  className="card num pointer-events-none absolute z-10 px-3 py-2 text-sm shadow-lg"
                  style={{ left: 150, top: -44 }}
                >
                  <b>{a.label}</b>: {fmtPct(a.pct)} ({fmtBRL(a.valor)}) · alvo {a.alvo}% · faixa {a.min}–{a.max}%
                </div>
              )}
            </div>
          );
        })}
        <div className="grid grid-cols-[130px_1fr_220px] gap-4">
          <div />
          <div className="num relative h-4 text-xs text-muted">
            {[0, 10, 20, 30, 40, 50].map((t) => (
              <span key={t} className="absolute -translate-x-1/2" style={{ left: x(t) }}>
                {t}%
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
