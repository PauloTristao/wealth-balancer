export type Classe = "ACAO" | "FII" | "RF" | "INTL" | "OUTROS";

export interface Ativo {
  ticker: string; nome: string; classe: Classe; subtipo: string;
  qtd: number | null; preco_medio: number | null; custo_total: number;
  preco_atual: number | null; variacao_dia: number | null;
  cotacao_fonte: string | null; cotacao_em: string | null;
  valor_atual: number; lucro: number; rentabilidade_pct: number | null;
  rent_com_proventos_pct: number | null; proventos: number; proventos_12m: number;
  yoc_12m_pct: number | null; lucro_realizado: number; pct_carteira: number; pct_classe: number;
  manual: boolean; id?: number;
}
export interface Alocacao {
  classe: Classe; label: string; valor: number; pct: number | null; alvo: number | null;
  min: number | null; max: number | null; status: "abaixo" | "ok" | "acima" | "fora"; falta_para_alvo: number | null;
}
export interface Aviso { data: string; ticker: string; codigo: string; mensagem: string }
export interface Dashboard {
  resumo: {
    patrimonio: number; reserva_emergencia: number; custo: number; lucro_nao_realizado: number;
    rentabilidade_pct: number | null; lucro_realizado: number; proventos_total: number;
    proventos_12m: number; proventos_mes: number; yoc_12m_pct: number | null; variacao_dia: number;
  };
  alocacao: Alocacao[]; ativos: Ativo[]; reserva: Ativo[]; avisos: Aviso[]; erros: string[];
}
export interface Income {
  lancamentos: { data: string; ticker: string; tipo: string; valor: number; classe: Classe }[];
  por_mes: ({ mes: string; total: number } & Partial<Record<Classe, number>>)[];
  por_ativo: { ticker: string; valor: number }[];
}
export interface ImportLog { id: number; arquivo: string; tipo: string; importado_em: string; linhas: number; novas: number; periodo: [string, string] }
export interface Manual {
  id?: number; nome: string; classe: Classe; subtipo: string; instituicao: string;
  valor_aplicado: number; valor_atual: number; data_ref?: string; reserva_emergencia: boolean; obs: string;
}

export interface MesEvolucao {
  mes: string; patrimonio: number; aplicado: number; por_classe: Partial<Record<Classe, number>>;
  aportes: number; proventos: number; rent_mes_pct: number; rent_acum_pct: number;
  cdi_mes_pct: number | null; cdi_acum_pct: number; ibov_acum_pct: number | null; estimados: string[];
}
export interface Janela { carteira_pct: number; cdi_pct: number; ibov_pct: number | null; aportes: number; proventos: number }
export interface Evolucao {
  meses: MesEvolucao[];
  resumo: { inicio: string; patrimonio: number; aplicado: number; desde_inicio: Janela; ultimos_12m: Janela; no_ano: Janela } | null;
  erros: string[];
}

export interface ClasseSim {
  classe: Classe; alvo: number; min: number; max: number; antes: number; antes_pct: number; sugerido: number;
  comprar: number; vender: number; depois: number; depois_pct: number;
}
export interface Operacao { ticker: string; nome: string; classe: Classe; acao: "COMPRAR" | "VENDER"; qtd: number; preco: number; valor: number; motivo: string; novo?: boolean }
export interface Simulacao {
  simulacao: true; aporte: number; vendas: number; total_antes: number; total_depois: number; sobra: number;
  classes: ClasseSim[]; operacoes: Operacao[]; avisos: string[];
}

export type Forca = "ALTA" | "MEDIA" | "BAIXA" | "DESCARTADA";
export interface Criterio { nome: string; pilar: string; valor: number | string | null; pontos: number | null; fmt: string; explicacao: string }
export interface Oportunidade {
  ticker: string; nome: string; classe: Classe; setor: string; segmento: string; preco: number | null;
  score: number; forca: Forca; pilares: Record<string, number>; criterios: Criterio[]; alertas: string[];
  indicadores: Record<string, number | string | null>; descartada: boolean; motivo_descarte: string | null;
  possui?: boolean; recomendacao_posse?: string; posicao?: { qtd: number; preco_medio: number };
  preco_teto_bazin?: number; preco_graham?: number; margem_seguranca_pct?: number; vence_em_breve?: boolean;
}
export interface Oportunidades {
  classe: Classe; itens: Oportunidade[]; contagem: Record<Forca, number>;
  fontes: Record<string, string | null>; erros: string[]; sem_dados: string[];
}

export interface Noticia { titulo: string; fonte: string; link: string; data: string | null }
export interface Insight {
  dia: string; ticker: string; modelo: string; noticias_usadas: number;
  analise: {
    resumo_noticias: string; pontos_positivos: string[]; riscos: string[]; leitura_filosofia: string;
    veredito: string; confianca: string; noticias_relevantes: { titulo: string; por_que_importa: string }[];
  };
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const api = {
  dashboard: () => req<Dashboard>("/api/dashboard"),
  evolution: () => req<Evolucao>("/api/evolution"),
  rebalance: (aporte: number, vendas: boolean, novos: boolean) =>
    req<Simulacao>(`/api/rebalance?aporte=${aporte}&vendas=${vendas}&novos=${novos}`),
  news: (ticker: string, nome?: string) =>
    req<{ itens: Noticia[]; dia: string }>(`/api/news/${encodeURIComponent(ticker)}${nome ? `?nome=${encodeURIComponent(nome)}` : ""}`),
  insight: (classe: Classe, ticker: string) =>
    req<{ configurado: boolean; analise: Insight | null }>(`/api/insight/${classe}/${encodeURIComponent(ticker)}`),
  generateInsight: (classe: Classe, ticker: string) =>
    req<Insight>(`/api/insight/${classe}/${encodeURIComponent(ticker)}`, { method: "POST" }),
  opportunities: (classe: Classe) => req<Oportunidades>(`/api/opportunities/${classe}`),
  refreshOpportunities: () => req<unknown>("/api/opportunities/refresh", { method: "POST" }),
  income: () => req<Income>("/api/income"),
  imports: () => req<ImportLog[]>("/api/imports"),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return req<{ resultados: Record<string, unknown>[] }>("/api/imports", { method: "POST", body: fd });
  },
  refreshQuotes: () => req<unknown>("/api/quotes/refresh", { method: "POST" }),
  manuals: () => req<Manual[]>("/api/manual-positions"),
  saveManual: (m: Manual) =>
    m.id ? req<Manual>(`/api/manual-positions/${m.id}`, json("PUT", m)) : req<Manual>("/api/manual-positions", json("POST", m)),
  deleteManual: (id: number) => req<unknown>(`/api/manual-positions/${id}`, { method: "DELETE" }),
};
