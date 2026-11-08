# CLAUDE.md — Wealth Balancer (consolidação + balanceamento de carteira)

App web **local** (roda só na máquina do usuário) para consolidar a carteira de investimentos a partir dos relatórios da B3,
acompanhar evolução/proventos e apoiar decisões de aporte. **Não executa ordens**: só gera a visão de decisão.
Interface e textos em **português do Brasil**.
Notas pessoais do dono da carteira (caminhos, arquivos reais, posições) ficam em `CLAUDE.local.md` (fora do git).
**Nunca versionar dados pessoais**: planilhas, `data/`, `.env`, `backend/tests/local/` (ver `.gitignore`).

## Filosofia do investidor (guia todas as regras de recomendação)
- Comprar **empresas boas a um bom preço — as duas coisas juntas**, boas pagadoras de dividendos, com saúde
  financeira equilibrada, foco no longo prazo, aproveitando oportunidades sem giro excessivo.
- 4 classes balanceadas em **25% cada** (faixa **15–35%**): Ações (`ACAO`), FIIs (`FII`), Renda Fixa (`RF`),
  Internacional (`INTL`, só ETFs/BDRs negociados na B3). Reserva de emergência e `OUTROS` (cripto etc.) ficam fora.
- Ações: P/VP < 1 (com piso de segurança), P/L ~8–20, ROE, DY, dívida líquida saudável, crescimento.
- FIIs: DY, P/VP, vacância, qualidade/diversificação. RF: toda boa oportunidade (Tesouro Selic/Pré/IPCA+).

## Comandos principais (para rodar manualmente)
Todos a partir da pasta do projeto, no PowerShell ou no Prompt de Comando.

**Primeira vez (instalar dependências)**
```powershell
cd backend
pip install -r requirements.txt
cd ..\frontend
npm install
cd ..
```

**Abrir o app (jeito fácil)** — dois cliques em `iniciar.bat`, ou:
```powershell
.\iniciar.bat
```
Abre duas janelas (API e site) e o navegador em http://localhost:5173. Para fechar, feche as duas janelas.

**Abrir o app (manual, em dois terminais)**
```powershell
# Terminal 1 — API (http://127.0.0.1:8000, documentação em /docs)
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — site (http://localhost:5173)
cd frontend
npx vite --port 5173
```
Para parar: `Ctrl + C` em cada terminal. Se a porta 8000 ficar presa:
```powershell
Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

**Rodar os testes**
```powershell
cd backend
python -m pytest -q
cd ..\frontend
npx tsc -b          # checagem de tipos do site
```

**Ver a carteira calculada direto de uma planilha (sem abrir o app)**
```powershell
python backend\scripts\ledger_report.py C:\caminho\movimentacao-AAAA-MM.xlsx
```

**Importar a planilha do mês pela linha de comando** (com a API rodando; alternativa à tela "Importar e ajustes")
```powershell
curl.exe -F "files=@C:\caminho\movimentacao-AAAA-MM.xlsx" http://127.0.0.1:8000/api/imports
```

**Forçar atualização de dados de mercado** (com a API rodando)
```powershell
curl.exe -X POST http://127.0.0.1:8000/api/quotes/refresh          # cotações + Tesouro
curl.exe -X POST http://127.0.0.1:8000/api/opportunities/refresh   # indicadores (Fundamentus)
```

**Ativar a análise com IA**
```powershell
copy backend\.env.example backend\.env
notepad backend\.env      # cole a chave depois de ANTHROPIC_API_KEY= e salve; depois reinicie a API
```

**Ajustar regras** — editar e reiniciar a API:
- `backend\app\config\estrategia.yaml` → alvos/faixas por classe, limites e pesos do score, regras da força Alta.
- `backend\app\config\ativos.yaml` → classificação de tickers, ETFs/BDRs acompanhados, custo de bonificações.

**Backup / recomeçar do zero**
```powershell
copy data\carteira.db data\carteira-backup.db    # backup
del data\carteira.db                              # apaga tudo; reimporte as planilhas depois
```

## Regras invioláveis
1. **Simulação de aporte é só simulação.** Nunca gravar compra/venda nem criar botão de "confirmar".
   A carteira só muda pela importação da planilha da B3 do mês seguinte.
2. **Não contornar bloqueios de sites.** O Status Invest bloqueia clientes automatizados — não usar nem tentar
   burlar (headers, curl via subprocess, etc.). Fonte de fundamentos = Fundamentus (tabelas públicas, 1x/dia).
3. **Filosofia "bom E barato"** no score: força **Alta** exige score ≥ `forca.alta` **e** pilares de preço e
   qualidade ≥ `pilar_minimo` **e** as regras duras de `alta_exige` (ações: P/L 8–20 e P/VP ≤ 1; FIIs: P/VP ≤ 1).
   Fora disso, no máximo Média — sempre com o motivo no alerta.
4. Toda mudança de regra de negócio deve ser **configurável** em `backend/app/config/*.yaml` quando fizer sentido.
5. Ledger é **função pura**: as linhas brutas da B3 (`raw_events`) são a fonte da verdade; posições são
   recalculadas a cada consulta. Mudar regra não exige reimportar.
6. Não incluir identificadores de modelo de IA em commits/código além da constante `MODEL` em `insights.py`.

## Stack e comandos
- Backend: Python 3.13, FastAPI, SQLAlchemy 2 + SQLite (`data/carteira.db`), pandas/openpyxl, httpx, bs4,
  `anthropic` (SDK), python-dotenv, defusedxml. Frontend: React 19 + **Vite 6** (Node ≥ 20; Vite 7+ exigiria 20.19),
  TypeScript, Tailwind 4, TanStack Query, Recharts.
- Rodar tudo: `iniciar.bat` (API :8000, web :5173, abre o navegador). Vite faz proxy de `/api` → :8000.
- API manual: `cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` (docs em `/docs`). Sem `--reload`:
  **reiniciar a API após mudar código do backend.**
- Testes: `cd backend && python -m pytest -q` (`test_api_import.py` gera planilhas sintéticas no formato B3;
  `test_arquivos_locais.py` roda sobre os extratos reais em `data/imports/` — ou `CARTEIRA_TESTE_ARQUIVOS` — e é
  pulado se não houver; posições esperadas opcionais em `backend/tests/local/posicoes_esperadas.json`). Type-check do front: `cd frontend && npx tsc -b`.
- Relatório rápido do ledger sem banco: `python backend/scripts/ledger_report.py <arquivo.xlsx>`.
- IA: `backend/.env` com `ANTHROPIC_API_KEY=...` (modelo em `backend/.env.example`; `.env` é gitignored).
- Screenshots para conferir UI: não há Playwright; usar Edge headless
  (`msedge --headless=new --screenshot=... --virtual-time-budget=15000 URL`). Deep link útil:
  `#/oportunidades?classe=ACAO&ativo=BBAS3` abre o painel do ativo.
- No Windows/Git Bash, heredocs longos com JSX/aspas quebram: para patches grandes, escrever um script `.py`
  temporário com a ferramenta Write e executá-lo (depois apagar).

## Estrutura
```
backend/app/
  main.py                 rotas FastAPI
  settings.py             caminhos (DATA_DIR, DB_URL via env CARTEIRA_DATA_DIR/CARTEIRA_DB_URL) e YAMLs
  db.py                   modelos: ImportLog, RawEvent, ManualPosition, Quote, TesouroPrice, PriceMonthly,
                          Fundamental, KV (cache genérico: notícias, insights, macro, datas de refresh)
  config/ativos.yaml      classificação (ETFs intl/nacionais, units, overrides), etf_info, bdrs_acompanhados,
                          proxy_historico, custo_bonificacao, janela_emprestimo_dias
  config/estrategia.yaml  alocação alvo/faixas, limites e pesos do score, alta_exige, renda_fixa
  importers/              b3.py (parsers Movimentação/Negociação), common.py (RawRow, hash), service.py (import)
  portfolio/              assets.py (ticker base/classe), ledger.py, valuation.py (dashboard),
                          evolution.py (foto mensal + Dietz)
  market/                 quotes.py (Yahoo/brapi + faixa 52s), service.py (cache de cotações), tesouro.py,
                          history.py (séries mensais, CDI, IBOV), fundamentals.py (Fundamentus + macro BCB),
                          news.py (Google Notícias RSS)
  security.py             allowlists de entrada, origem/host (CSRF/DNS rebinding)
  recommend/              scoring.py, opportunities.py, rebalance.py (simulador), insights.py (Claude)
backend/tests/            regras do ledger, API ponta a ponta (sintético), extratos locais (opcional), mercado,
                          rebalance, scoring, notícias/IA (cliente fake)
frontend/src/
  api.ts (tipos + chamadas), format.ts (BRL/%, cores e rótulos das classes), App.tsx (rotas por hash)
  pages/  Dashboard (Carteira), Oportunidades, Rebalancear (Simular aporte), Evolucao, Proventos, Importar
  components/  StatTile, AllocationBars, PositionsTable, NewsInsight
data/  carteira.db + imports/AAAA-MM/ (arquivos B3 originais arquivados) — gitignored
```

## Ingestão B3 (rotina mensal)
- Usuário baixa na Área do Investidor B3: **Movimentação** (obrigatório) e **Negociação** (recomendado —
  substitui as liquidações da Movimentação casando ativo/qtd em até `janela_liquidacao_dias`). Upload em "Importar e ajustes" ou `POST /api/imports`.
- Tipo detectado pelo cabeçalho. Dedupe por hash da linha (data, E/S, movimento, **ticker** — não o nome, que
  a B3 muda —, instituição sem ponto final, qtd, preço, valor) + nº da ocorrência no arquivo → reimportar não duplica.
- Nome do arquivo e pasta não importam (só o conteúdo). O app arquiva o original em `data/imports/AAAA-MM/`
  (mês da data mais recente do arquivo). Exports com períodos sobrepostos são seguros.

### Peculiaridades da Movimentação (tratadas em `ledger.py`)
- "Transferência - Liquidação" com preço = compra (Crédito) / venda (Débito).
- **Aluguel (BTC)**: liquidação casada com linha "Empréstimo" (mesmo ativo/qtd, janela de dias) → `LEND_OUT`/
  `LEND_RETURN`, não altera posição. "Empréstimo" com valor = renda de aluguel (`ALUGUEL`).
- Devolução de aluguel com **ticker novo** de mesma raiz converte a posição (ex.: CPLE6 → CPLE5 via
  "Atualização" → alugada → devolvida como **CPLE3**).
- "Atualização": checkpoint de posição (reconciliação), conversão de subscrição exercida, ou troca de ticker.
- Direitos/recibos mapeados ao ativo-base: final 1/9→3, 2/10→4, 12–15→11 (ex.: XPML12→XPML11, ITSA10→ITSA4).
- Desdobro/grupamento (qtd, custo igual), Bonificação (custo de `custo_bonificacao`, senão 0 + aviso),
  Fração em Ativos + Leilão de Fração, Subscrição exercida (custo pendente até converter), taxa de custódia
  do Tesouro (soma ao custo), Resgate/Venda do Tesouro (qtd com 2 casas na B3).
- Ignorados: Transferência entre corretoras, *- Transferido, direitos não exercidos/cessões, Futuros (WIN).
- Proventos: Rendimento, Dividendo, JCP, Reembolso (dividendo durante aluguel), Aluguel.

## Dados de mercado (todos com cache)
- Cotações: Yahoo chart API (`.SA`), cache 15 min; brapi se `BRAPI_TOKEN` existir.
- Tesouro: CSV do Tesouro Transparente (preço/taxa diários de todos os títulos), refresh 12h. Nome do ativo
  "Tesouro X AAAA" → tipo + ano de vencimento (Renda+ = ano+19, Educa+ = ano+4). Avaliação pelo PU de venda.
- Históricos mensais: Yahoo `interval=1mo` com **desfazer ajuste de desdobramento** (numerator/denominator dos
  eventos de split depois do mês). Sem histórico (deslistados) → vale pelo custo (marcado `*`);
  CPLE5/6 usam proxy CPLE3. CDI: BCB SGS 4391; Ibovespa: `^BVSP`.
- Fundamentos: Fundamentus `resultado.php` e `fii_resultado.php`. Dív.líq/EBIT derivada = EV/EBIT − P/EBIT
  (inválida se P/EBIT ≥ 60, ex.: holdings → usa dív.líq/patrimônio). Bancos: P/EBIT e EV/EBIT = 0 → sem
  critérios de dívida e margem. VPA/LPA derivados de preço/P/VP e preço/P/L (para Graham).
  Sem CAGR de lucro em fonte gratuita (usa crescimento de receita 5a + margem líquida).
- Faixa de 52 semanas (ETFs/BDRs): calculada dos fechamentos diários, corrigindo saltos > 40% (split não
  registrado no Yahoo, ex.: SPXI11).
- Macro: Selic meta (SGS 432) e IPCA esperado 12m (Focus/olinda). Notícias: Google Notícias RSS pt-BR, 45 dias.

## Recomendação
- `scoring.py`: critérios de 0–1 (linear entre "zero" e "cheio"), agrupados em pilares com pesos; pilar sem
  dado é ignorado e pesos renormalizados. Forças: ALTA / MEDIA / BAIXA / DESCARTADA (filtro eliminatório:
  liquidez mínima, prejuízo, sem P/VP...).
  - DY acima de `suspeito` vale no máximo meio ponto; P/VP abaixo do piso = 0 ponto + alerta.
  - FIIs: P/VP contínuo (mais desconto = mais pontos até o piso), DY, cobertura FFO/DY, vacância, imóveis, patrimônio.
  - BDRs: sem fundamentos gratuitos → só posição na faixa 52s, score × 0,6, no máximo Média.
  - ETFs: posição 52s + taxa + diversificação (`etf_info.foco`: core/protecao/tema).
  - Tesouro: juro real (IPCA+ direto; prefixado vs IPCA esperado); Selic sempre Média; títulos com vencimento
    < 1 ano só aparecem se possuídos ("Manter até o vencimento").
- Ativos possuídos: Alta → "Reforçar", Média → "Manter", Baixa/Descartada → "Reavaliar".
- `opportunities.build` tem cache em memória de 10 min (simulador chama a cada digitação).
- Simulador (`rebalance.py`): distribui o aporte por **nível de água** (classe mais longe do alvo primeiro);
  vendas opcionais só até voltar ao **máximo** da faixa (não ao alvo); dentro da classe até 3 ativos priorizando
  Alta e score (possuídos Alta/Média + até 2 novos Alta se "novos"); nunca para "Reavaliar" ou título vencendo;
  sem scores → mantém composição atual. Cotas inteiras (Tesouro em 0,01) e 2ª passada gastando a sobra.
- Evolução: rentabilidade mensal por Dietz modificado (aportes/resgates não contam; proventos contam).

## IA
- `insights.py`: SDK `anthropic`, modelo `claude-sonnet-5-5`, `client.beta.messages.create` com
  `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`, `output_config={"effort": "medium",
  "format": json_schema}`. Trata `stop_reason` refusal/max_tokens e erros tipados do SDK.
- Só sob demanda (botão), cache por ativo em KV até gerar de novo. Recebe apenas indicadores, critérios, alertas, posição,
  alocação e manchetes; o prompt proíbe inventar fatos. Sem chave → UI mostra instruções.
- Antes de mexer em código da API do Claude, consultar a skill `claude-api` (não confiar em memória).

## Segurança (app local)
- API só em `127.0.0.1`; `TrustedHostMiddleware` (localhost/127.0.0.1) contra DNS rebinding; POST/PUT/DELETE com
  `Origin` fora de `ALLOWED_ORIGINS` → 403 (CSRF de outros sites abertos no navegador). curl sem Origin funciona.
- Toda entrada externa passa por `app/security.py` (allowlists, funções puras, **100% de branches** em
  `tests/test_security.py`): classe, ticker (B3 ou "Tesouro ..."), nome de busca, nome/extensão/tamanho do
  upload (máx. 20 MB, arquivado com nome saneado), links do RSS (só http(s)) e origem das requisições.
  Posições manuais validadas por Pydantic (`Literal`, limites, sem NaN/inf). Erros: mensagem amigável ao
  cliente, só o tipo da exceção no log; o 422 não ecoa a entrada. RSS via `defusedxml`.
- Cobertura: `python -m coverage run --branch --include=app/security.py -m pytest && python -m coverage report -m`.
- Chave da IA só em `backend/.env` (gitignored; carregado em `settings.py`).

## UI / visualização
- Paleta validada (skill dataviz): classes ACAO azul `#2a78d6`, FII laranja `#eb6834`, RF verde-água `#1baf7a`,
  INTL amarelo `#eda100` (variantes no tema escuro em `index.css`). Benchmarks: Carteira = tinta neutra (linha
  mais grossa), CDI violeta, Ibovespa magenta. Cores com contraste < 3:1 exigem rótulo direto/tabela.
- Status sempre com ícone + texto (▲ ▼ ● ✓), nunca só cor. Sem eixo duplo. Recharts com `isAnimationActive={false}`.
- Dark/light via `prefers-color-scheme`. Números com `font-variant-numeric: tabular-nums` (classe `num`).

## Pendências conhecidas
- Posições manuais não entram no histórico da Evolução. Nome das empresas não vem do Fundamentus.
- Não rodar comandos git (commit, push etc.) sem o usuário pedir.
