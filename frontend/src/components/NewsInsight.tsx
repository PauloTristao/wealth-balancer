import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Oportunidade } from "../api";
import { fmtDate } from "../format";

const VEREDITO_ICON: Record<string, string> = {
  "Comprar/Reforçar": "▲",
  Manter: "●",
  "Aguardar melhor preço": "◐",
  "Evitar/Reavaliar": "▼",
};

export default function NewsInsight({ o }: { o: Oportunidade }) {
  const qc = useQueryClient();
  const news = useQuery({ queryKey: ["news", o.ticker], queryFn: () => api.news(o.ticker, o.nome) });
  const ins = useQuery({ queryKey: ["insight", o.ticker], queryFn: () => api.insight(o.classe, o.ticker) });
  const gerar = useMutation({
    mutationFn: () => api.generateInsight(o.classe, o.ticker),
    onSuccess: (d) => qc.setQueryData(["insight", o.ticker], { configurado: true, analise: d }),
  });

  const a = ins.data?.analise;

  return (
    <>
      <div className="mt-6 font-semibold">Análise com IA</div>
      {ins.data && !ins.data.configurado && (
        <p className="mt-1 text-sm text-2">
          Para ativar: crie o arquivo <code>backend/.env</code> com <code>ANTHROPIC_API_KEY=sua-chave</code> (chave em
          console.anthropic.com) e reinicie o app. A análise só é gerada quando você clica, e fica guardada até você pedir para gerar de novo.
        </p>
      )}
      {ins.data?.configurado && (
        <div className="mt-2 flex items-center gap-3">
          <button className="card px-3 py-1.5 text-sm font-semibold" onClick={() => gerar.mutate()} disabled={gerar.isPending}>
            {gerar.isPending ? "Analisando (pode levar ~1 min)…" : a ? "Gerar de novo" : "Solicitar análise da IA"}
          </button>
          {a && <span className="text-xs text-muted">gerada em {fmtDate(a.dia)} · {a.noticias_usadas} manchetes</span>}
        </div>
      )}
      {gerar.error && <p className="neg mt-2 text-sm">{String(gerar.error).replace(/^Error: \d+ /, "")}</p>}
      {a && (
        <div className="mt-3 space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span>{VEREDITO_ICON[a.analise.veredito] ?? "●"}</span>
            <b>{a.analise.veredito}</b>
            <span className="text-2">· confiança {a.analise.confianca}</span>
          </div>
          <p>{a.analise.leitura_filosofia}</p>
          <p className="text-2">{a.analise.resumo_noticias}</p>
          {a.analise.pontos_positivos.length > 0 && (
            <div>
              <div className="font-medium">Pontos positivos</div>
              <ul className="ml-4 list-disc">
                {a.analise.pontos_positivos.map((p) => <li key={p}>{p}</li>)}
              </ul>
            </div>
          )}
          {a.analise.riscos.length > 0 && (
            <div>
              <div className="font-medium">Riscos</div>
              <ul className="ml-4 list-disc">
                {a.analise.riscos.map((p) => <li key={p}>{p}</li>)}
              </ul>
            </div>
          )}
          {a.analise.noticias_relevantes.length > 0 && (
            <div>
              <div className="font-medium">Notícias que pesam</div>
              <ul className="ml-4 list-disc">
                {a.analise.noticias_relevantes.map((n) => (
                  <li key={n.titulo}>
                    <i>{n.titulo}</i> — {n.por_que_importa}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-muted">Gerado por IA a partir dos indicadores e manchetes acima; pode errar. Não é recomendação de investimento.</p>
        </div>
      )}

      <div className="mt-6 font-semibold">Notícias recentes</div>
      {news.isLoading && <p className="text-sm text-2">Buscando…</p>}
      {news.error && <p className="neg text-sm">Não foi possível buscar notícias agora.</p>}
      {news.data && news.data.itens.length === 0 && <p className="text-sm text-2">Nenhuma notícia nos últimos 45 dias.</p>}
      <ul className="mt-2 space-y-2 text-sm">
        {news.data?.itens.map((n) => (
          <li key={n.link}>
            <a href={n.link} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
              {n.titulo}
            </a>
            <div className="text-xs text-muted">
              {n.data && fmtDate(n.data)} · {n.fonte}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
