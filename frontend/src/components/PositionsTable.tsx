import { Fragment } from "react";
import type { Ativo, Classe } from "../api";
import { CLASSES, CLASS_COLOR, CLASS_LABEL, fmtBRL, fmtNum, fmtPct, signClass } from "../format";

const thBase = "px-2 py-2 font-medium text-2 whitespace-nowrap";
const th = `${thBase} text-right`;
const td = "px-2 py-1.5 text-right num whitespace-nowrap";

export default function PositionsTable({ ativos }: { ativos: Ativo[] }) {
  const grupos = [...CLASSES, "OUTROS" as Classe]
    .map((c) => ({ classe: c, itens: ativos.filter((a) => a.classe === c) }))
    .filter((g) => g.itens.length);

  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b" style={{ borderColor: "var(--grid)" }}>
            <th className={`${thBase} text-left`}>Ativo</th>
            <th className={th}>Qtd</th>
            <th className={th}>Preço médio</th>
            <th className={th}>Preço atual</th>
            <th className={th}>Dia</th>
            <th className={th}>Investido</th>
            <th className={th}>Valor atual</th>
            <th className={th}>Resultado</th>
            <th className={th}>Rent.</th>
            <th className={th} title="Rentabilidade somando os proventos recebidos">Rent. c/ prov.</th>
            <th className={th}>Prov. 12m</th>
            <th className={th} title="Proventos 12 meses / valor investido">YoC 12m</th>
            <th className={th}>% classe</th>
            <th className={th}>% carteira</th>
          </tr>
        </thead>
        <tbody>
          {grupos.map((g) => {
            const inv = g.itens.reduce((s, a) => s + a.custo_total, 0);
            const val = g.itens.reduce((s, a) => s + a.valor_atual, 0);
            const prov = g.itens.reduce((s, a) => s + a.proventos_12m, 0);
            const pct = g.itens.reduce((s, a) => s + a.pct_carteira, 0);
            return (
              <Fragment key={g.classe}>
                <tr style={{ background: "var(--band)" }}>
                  <td className="px-2 py-1.5 font-semibold" colSpan={5}>
                    <span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[g.classe] }} />
                    {CLASS_LABEL[g.classe]}
                  </td>
                  <td className={`${td} font-semibold`}>{fmtBRL(inv)}</td>
                  <td className={`${td} font-semibold`}>{fmtBRL(val)}</td>
                  <td className={`${td} font-semibold ${signClass(val - inv)}`}>{fmtBRL(val - inv)}</td>
                  <td className={`${td} font-semibold ${signClass(val - inv)}`}>
                    {fmtPct(inv ? (100 * (val - inv)) / inv : null, true)}
                  </td>
                  <td className={td} />
                  <td className={`${td} font-semibold`}>{fmtBRL(prov)}</td>
                  <td className={`${td} font-semibold`}>{fmtPct(inv ? (100 * prov) / inv : null)}</td>
                  <td className={td} />
                  <td className={`${td} font-semibold`}>{fmtPct(pct)}</td>
                </tr>
                {g.itens.map((a) => (
                  <tr key={a.ticker} className="border-b" style={{ borderColor: "var(--grid)" }}>
                    <td className="px-2 py-1.5">
                      <div className="font-medium">
                        {a.manual ? (
                          a.ticker
                        ) : (
                          <a
                            href={`#/oportunidades?classe=${a.classe}&ativo=${encodeURIComponent(a.ticker)}`}
                            className="hover:underline"
                            title="Ver análise, notícias e IA"
                          >
                            {a.ticker}
                          </a>
                        )}
                      </div>
                      <div className="max-w-[220px] truncate text-xs text-muted" title={a.nome}>
                        {a.manual ? `Manual · ${a.subtipo}` : a.subtipo}
                      </div>
                    </td>
                    <td className={td}>{fmtNum(a.qtd, 2)}</td>
                    <td className={td}>{fmtBRL(a.preco_medio)}</td>
                    <td className={td} title={a.cotacao_em ? `${a.cotacao_fonte} · ${a.cotacao_em}` : undefined}>
                      {fmtBRL(a.preco_atual)}
                    </td>
                    <td className={`${td} ${signClass(a.variacao_dia)}`}>{fmtPct(a.variacao_dia, true)}</td>
                    <td className={td}>{fmtBRL(a.custo_total)}</td>
                    <td className={td}>{fmtBRL(a.valor_atual)}</td>
                    <td className={`${td} ${signClass(a.lucro)}`}>{fmtBRL(a.lucro)}</td>
                    <td className={`${td} ${signClass(a.rentabilidade_pct)}`}>{fmtPct(a.rentabilidade_pct, true)}</td>
                    <td className={`${td} ${signClass(a.rent_com_proventos_pct)}`}>
                      {fmtPct(a.rent_com_proventos_pct, true)}
                    </td>
                    <td className={td}>{fmtBRL(a.proventos_12m)}</td>
                    <td className={td}>{fmtPct(a.yoc_12m_pct)}</td>
                    <td className={td}>{fmtPct(a.pct_classe)}</td>
                    <td className={td}>{fmtPct(a.pct_carteira)}</td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
