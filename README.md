# Wealth Balancer

App **local** para consolidar sua carteira de investimentos a partir dos extratos da **B3** (Área do Investidor),
acompanhar evolução e proventos e apoiar a decisão de onde fazer o próximo aporte, com a carteira equilibrada em
4 classes: **Ações, FIIs, Renda Fixa e Internacional** (25% cada, faixa de 15% a 35%, configurável).

> O app **não executa ordens** e não se conecta à sua corretora. Ele só lê os extratos que você exporta e mostra
> a visão de decisão. Tudo roda na sua máquina, e seus dados ficam na pasta `data/`, que não vai para o git.
> Isto não é recomendação de investimento.

## Funcionalidades
- **Carteira:** posições, preço médio, valor atual, alocação por classe x alvo, lucro realizado.
- **Oportunidades:** score "empresa boa a bom preço" com indicadores públicos (Fundamentus), Tesouro Direto,
  ETFs e BDRs, além de notícias recentes e, opcionalmente, uma análise com IA (Claude).
- **Simular aporte:** distribui o valor entre as classes mais distantes do alvo. É só simulação e não grava nada.
- **Evolução:** patrimônio mês a mês x CDI e Ibovespa.
- **Proventos:** dividendos, JCP, rendimentos de FIIs e aluguel de ações.
- **Importar e ajustes:** envio dos extratos e posições manuais (reserva de emergência, contas fora da B3).

## Requisitos
- **Python 3.11+** (testado no 3.13)
- **Node.js 20+**

## Instalação
```bash
git clone https://github.com/PauloTristao/wealth-balancer.git
cd wealth-balancer
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
```

## Como rodar
**Windows:** dê dois cliques em `iniciar.bat`. Ele abre a API, o site e o navegador em http://localhost:5173.

**Manual (qualquer sistema), em dois terminais:**
```bash
# Terminal 1 — API em http://127.0.0.1:8000 (documentação em /docs)
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — site em http://localhost:5173
cd frontend
npx vite --port 5173
```

## Importando seus extratos da B3
1. Acesse a **Área do Investidor B3**, vá em **Extratos** e exporte em Excel:
   - **Movimentação** (obrigatório): compras, vendas, proventos, desdobramentos, aluguel, Tesouro etc.
   - **Negociação** (recomendado): preços exatos de cada pregão, que melhoram o preço médio.
2. No app, abra **Importar e ajustes** e envie os arquivos.
   Pela linha de comando: `curl -F "files=@movimentacao.xlsx" http://127.0.0.1:8000/api/imports`.

- O **nome do arquivo e a pasta não importam**. O tipo de relatório é detectado pelo conteúdo.
- **Reimportar não duplica**, e períodos sobrepostos são seguros. Você pode exportar sempre desde o início, ou só o mês novo.
- Na primeira vez, exporte **todo o histórico** para o preço médio e as posições ficarem corretos.

## Configuração (opcional)
| O quê | Onde |
|---|---|
| Alvos e faixas por classe, pesos do score, regras de "força Alta" | `backend/app/config/estrategia.yaml` |
| Classificação de tickers, ETFs/BDRs acompanhados, custo de bonificações | `backend/app/config/ativos.yaml` |
| Análise com IA (Claude): chave da API | `backend/.env` (copie de `backend/.env.example`) |
| Cotações pela brapi em vez do Yahoo | `BRAPI_TOKEN` em `backend/.env` |
| Pasta dos dados | variável `CARTEIRA_DATA_DIR` (padrão: `data/`) |

Reinicie a API depois de mudar a configuração.

**Análise com IA:** crie uma chave em [console.anthropic.com](https://console.anthropic.com), coloque em
`backend/.env` (`ANTHROPIC_API_KEY=...`) e reinicie a API. A análise só é gerada quando você clica em
"Solicitar análise da IA" e fica guardada até você gerar de novo. Cada análise custa poucos centavos de dólar.

## Fontes de dados (públicas, com cache)
Cotações: Yahoo Finance (ou brapi). Tesouro Direto: Tesouro Transparente. Indicadores: Fundamentus (1 consulta
por dia). Selic, IPCA esperado e CDI: Banco Central. Notícias: RSS do Google Notícias.

## Privacidade e segurança
- Seus extratos, o banco (`data/carteira.db`) e a chave da IA (`backend/.env`) ficam só na sua máquina e estão
  no `.gitignore`. O `.gitignore` também bloqueia qualquer `.xlsx`/`.csv`/imagem solta no projeto.
- A API escuta só em `127.0.0.1` e recusa requisições de outros sites abertos no navegador.
- Para a IA vão apenas os indicadores do ativo, sua alocação por classe e as manchetes. Os extratos não são enviados.

## Testes
```bash
cd backend && python -m pytest -q     # usa planilhas sintéticas geradas na hora
cd frontend && npx tsc -b             # checagem de tipos
```
Os testes de `test_arquivos_locais.py` também rodam sobre os **seus** extratos já importados (`data/imports/`),
se existirem. Para conferir posições exatas, crie `backend/tests/local/posicoes_esperadas.json`
(ex.: `{"ITSA4": 100, "Tesouro Selic 2029": 0.5}`). Essa pasta não vai para o git.

## Backup / recomeçar
Para fazer backup, copie `data/carteira.db`. Para recomeçar do zero, apague esse arquivo e reimporte os extratos.
