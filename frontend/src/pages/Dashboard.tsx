import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import AllocationBars from "../components/AllocationBars";
import PositionsTable from "../components/PositionsTable";
import StatTile from "../components/StatTile";
import { fmtBRL, fmtDate, fmtPct, signClass } from "../format";

export default function DashboardPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const refresh = useMutation({
    mutationFn: api.refreshQuotes,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard"] }),
  });

  if (isLoading) return <p className="text-2">Carregando carteira e cotações…</p>;
  if (error) return <p className="neg">Erro ao carregar: {String(error)}</p>;
  if (!data) return null;
  if (!data.ativos.length)
    return (
      <p className="text-2">
        Nenhum ativo ainda. Vá em "Importar e ajustes" e envie o relatório de Movimentação da B3.
      </p>
    );

  const r = data.resumo;
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Consolidação</h1>
        <button onClick={() => refresh.mutate()} disabled={refresh.isPending} className="card px-3 py-1.5 text-sm">
          {refresh.isPending ? "Atualizando…" : "Atualizar cotações"}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Patrimônio investido"
          value={fmtBRL(r.patrimonio)}
          sub={<span className={signClass(r.variacao_dia)}>{fmtBRL(r.variacao_dia)} hoje</span>}
        />
        <StatTile
          label="Resultado (não realizado)"
          value={<span className={signClass(r.lucro_nao_realizado)}>{fmtBRL(r.lucro_nao_realizado)}</span>}
          sub={
            <>
              {fmtPct(r.rentabilidade_pct, true)} sobre {fmtBRL(r.custo)} investidos
            </>
          }
        />
        <StatTile
          label="Proventos 12 meses"
          value={fmtBRL(r.proventos_12m)}
          sub={
            <>
              YoC {fmtPct(r.yoc_12m_pct)} · total {fmtBRL(r.proventos_total)}
            </>
          }
        />
        <StatTile
          label="Lucro realizado (vendas)"
          value={<span className={signClass(r.lucro_realizado)}>{fmtBRL(r.lucro_realizado)}</span>}
          sub={r.reserva_emergencia ? <>Reserva de emergência: {fmtBRL(r.reserva_emergencia)}</> : "desde o início"}
        />
      </div>

      <AllocationBars data={data.alocacao} />

      <PositionsTable ativos={data.ativos} />

      {data.reserva.length > 0 && (
        <div className="card p-4 text-sm">
          <div className="mb-2 font-semibold">Reserva de emergência (fora do balanceamento)</div>
          {data.reserva.map((a) => (
            <div key={a.ticker} className="num flex justify-between">
              <span>{a.nome}</span>
              <span>{fmtBRL(a.valor_atual)}</span>
            </div>
          ))}
        </div>
      )}

      {(data.erros.length > 0 || data.avisos.length > 0) && (
        <details className="card p-4 text-sm">
          <summary className="cursor-pointer font-semibold">
            ⚠ Avisos de importação ({data.avisos.length + data.erros.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {data.erros.map((e) => (
              <li key={e} className="neg">
                {e}
              </li>
            ))}
            {data.avisos.map((w, i) => (
              <li key={i}>
                <span className="num text-muted">{fmtDate(w.data)}</span> <b>{w.ticker}</b> — {w.mensagem}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
