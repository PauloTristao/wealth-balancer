"""API do app de carteira.

Rodar:  cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Docs:   http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from collections import defaultdict
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ImportLog, ManualPosition, get_session, init_db
from app.importers.b3 import UnknownReportError
from app.importers.service import import_file, load_rows
from app.market import tesouro
from app.market.service import refresh_quotes
from app.portfolio.ledger import run_ledger, summarize
from app.portfolio.evolution import build_evolution
from app.portfolio.valuation import build_dashboard
from app.recommend.opportunities import build as build_opportunities
from app.recommend.opportunities import clear_cache as clear_opportunities_cache
from app.recommend.opportunities import scores_by_ticker
from app.recommend.rebalance import simulate
from app.market.news import get_news
from app.recommend import insights
from app.settings import estrategia_config
from app import security as sec

log = logging.getLogger("wealth_balancer")

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Wealth Balancer", version="0.1.0", lifespan=_lifespan)

# App local: outros sites abertos no navegador não podem disparar POST/PUT/DELETE (CSRF) e nomes de
# host estranhos são recusados (DNS rebinding). Regras e allowlists em app/security.py.
@app.middleware("http")
async def _bloqueia_origem_externa(request: Request, call_next):
    if not sec.origem_permitida(request.method, request.headers.get("origin")):
        return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
    return await call_next(request)


@app.exception_handler(sec.InvalidInput)
async def _entrada_invalida(_request: Request, exc: sec.InvalidInput):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(RequestValidationError)
async def _validacao(_request: Request, exc: RequestValidationError):
    # Não ecoa o valor recebido: evita refletir entrada maliciosa e o erro 500 com NaN/Infinity.
    erros = [{"campo": ".".join(str(p) for p in e.get("loc", ()) if p != "body"), "erro": e.get("msg", "inválido")}
             for e in exc.errors()]
    return JSONResponse({"detail": erros}, status_code=422)


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(sec.ALLOWED_ORIGINS),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(sec.ALLOWED_HOSTS))



def _ledger(session: Session, until: date | None = None):
    return run_ledger(load_rows(session), until=until)


# ---------------------------------------------------------------- importação
@app.post("/api/imports")
async def upload(files: list[UploadFile] = File(...), session: Session = Depends(get_session)):
    results = []
    for f in files:
        if not sec.upload_permitido(f.filename):
            results.append({"arquivo": f.filename, "erro": "Formato não suportado: envie o .xlsx (ou .csv) exportado da B3."})
            continue
        nome = sec.nome_arquivo_seguro(f.filename or "")
        content = await f.read(sec.MAX_UPLOAD_BYTES + 1)
        if not content:
            results.append({"arquivo": nome, "erro": "Arquivo vazio."})
            continue
        if len(content) > sec.MAX_UPLOAD_BYTES:
            results.append({"arquivo": nome, "erro": "Arquivo grande demais (máx. 20 MB)."})
            continue
        try:
            results.append(import_file(session, nome, content))
        except UnknownReportError as exc:
            session.rollback()
            results.append({"arquivo": nome, "erro": str(exc)})
        except Exception as exc:  # planilha corrompida/ilegível: registra o tipo e responde sem detalhes internos
            session.rollback()
            log.warning("Falha ao ler upload %s: %s", nome, type(exc).__name__)
            results.append({"arquivo": nome, "erro": "Não foi possível ler o arquivo. Confira se é o export da B3."})
    return {"resultados": results}


@app.get("/api/imports")
def list_imports(session: Session = Depends(get_session)):
    logs = session.scalars(select(ImportLog).order_by(ImportLog.imported_at.desc())).all()
    return [
        {
            "id": l.id, "arquivo": l.filename, "tipo": l.kind, "importado_em": l.imported_at.isoformat(),
            "linhas": l.rows_total, "novas": l.rows_new,
            "periodo": [l.date_min.isoformat() if l.date_min else None, l.date_max.isoformat() if l.date_max else None],
        }
        for l in logs
    ]


# ---------------------------------------------------------------- carteira
@app.get("/api/portfolio")
def portfolio(ate: date | None = None, session: Session = Depends(get_session)):
    res = _ledger(session, ate)
    out = summarize(res)
    manual = [m.public() for m in session.scalars(select(ManualPosition)).all()]
    out["manuais"] = manual

    por_classe: dict[str, float] = defaultdict(float)
    for p in out["posicoes"]:
        por_classe[p["classe"]] += p["custo_total"]
    for m in manual:
        if not m["reserva_emergencia"]:
            por_classe[m["classe"]] += m["valor_atual"]
    total = sum(por_classe.values()) or 1.0
    out["por_classe_custo"] = {k: {"valor": round(v, 2), "pct": round(100 * v / total, 2)} for k, v in por_classe.items()}
    out["proventos_total"] = round(sum(i["valor"] for i in res.income), 2)
    out["lucro_realizado_total"] = round(sum(p.lucro_realizado for p in res.positions.values()), 2)
    return out


@app.get("/api/dashboard")
def dashboard(atualizar: bool = True, session: Session = Depends(get_session)):
    return build_dashboard(session, refresh=atualizar)


@app.get("/api/evolution")
def evolution(atualizar: bool = True, session: Session = Depends(get_session)):
    return build_evolution(session, refresh=atualizar)


@app.get("/api/rebalance")
def rebalance(aporte: float = 0.0, vendas: bool = False, novos: bool = True,
              session: Session = Depends(get_session)):
    """Simulação de aporte — não grava nada."""
    if aporte < 0:
        raise HTTPException(422, "aporte deve ser >= 0")
    dash = build_dashboard(session, refresh=True)
    scores = scores_by_ticker(session)
    return simulate(dash, aporte, estrategia_config().get("alocacao", {}), permitir_vendas=vendas,
                    scores=scores, novos=novos)


@app.get("/api/opportunities/{classe}")
def opportunities(classe: str, session: Session = Depends(get_session)):
    return build_opportunities(session, sec.classe_oportunidade(classe))


def _find_opportunity(session: Session, classe: str, ticker: str) -> dict:
    classe, ticker = sec.classe_oportunidade(classe), sec.ticker(ticker)
    for it in build_opportunities(session, classe)["itens"]:
        if it["ticker"].upper() == ticker.upper():
            return it
    raise HTTPException(404, f"{ticker} não encontrado em {classe}")


@app.get("/api/news/{ticker}")
def news(ticker: str, nome: str | None = None, session: Session = Depends(get_session)):
    ticker, nome = sec.ticker(ticker), sec.nome_busca(nome)
    try:
        return get_news(session, ticker, nome)
    except Exception as exc:  # falha de rede/feed: registra o tipo, não expõe detalhes internos
        log.warning("Falha ao buscar notícias de %s: %s", ticker, type(exc).__name__)
        raise HTTPException(502, "Falha ao buscar notícias. Tente de novo mais tarde.")


@app.get("/api/insight/status")
def insight_status():
    return {"configurado": insights.configured(), "modelo": insights.MODEL}


@app.get("/api/insight/{classe}/{ticker}")
def insight_get(classe: str, ticker: str, session: Session = Depends(get_session)):
    sec.classe_oportunidade(classe)
    return {"configurado": insights.configured(), "analise": insights.cached(session, sec.ticker(ticker))}


@app.post("/api/insight/{classe}/{ticker}")
def insight_generate(classe: str, ticker: str, session: Session = Depends(get_session)):
    op = _find_opportunity(session, classe, ticker)
    try:
        noticias = get_news(session, op["ticker"], op.get("nome"))["itens"]
    except Exception as exc:  # sem notícias a análise segue só com os indicadores
        log.warning("Notícias indisponíveis para %s: %s", op["ticker"], type(exc).__name__)
        noticias = []
    dash = build_dashboard(session, refresh=False)
    contexto = {
        "alocacao_por_classe": [{k: a[k] for k in ("label", "pct", "alvo", "min", "max", "status")}
                                for a in dash["alocacao"]],
        "patrimonio": dash["resumo"]["patrimonio"],
    }
    try:
        return insights.generate(session, op, noticias, contexto)
    except insights.InsightError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/opportunities/refresh")
def opportunities_refresh(session: Session = Depends(get_session)):
    from app.market import fundamentals as f

    clear_opportunities_cache()
    n = {c: f.refresh(session, c, force=True) for c in ("ACAO", "FII")}
    return {"atualizados": n}


@app.post("/api/quotes/refresh")
def quotes_refresh(session: Session = Depends(get_session)):
    res = _ledger(session)
    tickers = [p.ticker for p in res.open_positions() if not p.ticker.lower().startswith("tesouro")]
    q = refresh_quotes(session, tickers, force=True)
    n = tesouro.refresh(session, force=True)
    return {"cotacoes": len(q), "tesouro_linhas": n}


@app.get("/api/trades")
def trades(ticker: str | None = None, session: Session = Depends(get_session)):
    t = _ledger(session).trades
    if ticker:
        alvo = sec.ticker(ticker).upper()
        t = [x for x in t if x["ticker"].upper() == alvo]
    return sorted(t, key=lambda x: x["data"], reverse=True)


@app.get("/api/income")
def income(session: Session = Depends(get_session)):
    inc = _ledger(session).income
    por_mes: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    por_ativo: dict[str, float] = defaultdict(float)
    for i in inc:
        mes = i["data"][:7]
        por_mes[mes][i["classe"]] += i["valor"]
        por_mes[mes]["total"] += i["valor"]
        por_ativo[i["ticker"]] += i["valor"]
    return {
        "lancamentos": sorted(inc, key=lambda x: x["data"], reverse=True),
        "por_mes": [{"mes": m, **{k: round(v, 2) for k, v in d.items()}} for m, d in sorted(por_mes.items())],
        "por_ativo": sorted(({"ticker": k, "valor": round(v, 2)} for k, v in por_ativo.items()),
                            key=lambda x: -x["valor"]),
    }


# ---------------------------------------------------------------- posições manuais
_VALOR = Field(default=0.0, ge=0, le=1e12, allow_inf_nan=False)


class ManualIn(BaseModel):
    """Posição fora da B3 (reserva, banco digital...). Tipos e limites validados pelo Pydantic."""
    # extra="ignore": campos desconhecidos (ex.: "id" que o site reenvia ao editar) são descartados;
    # só os campos declarados abaixo chegam ao banco.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    nome: str = Field(min_length=1, max_length=80)
    classe: Literal["ACAO", "FII", "RF", "INTL", "OUTROS"]
    subtipo: str = Field(default="", max_length=40)
    instituicao: str = Field(default="", max_length=80)
    valor_aplicado: float = _VALOR
    valor_atual: float = _VALOR
    data_ref: date | None = None
    reserva_emergencia: bool = False
    obs: str = Field(default="", max_length=500)


def _apply_manual(m: ManualPosition, body: ManualIn) -> None:
    for k, v in body.model_dump().items():
        if k == "data_ref":
            v = v or date.today()
        if k == "reserva_emergencia":
            v = int(v)
        setattr(m, k, v)


@app.get("/api/manual-positions")
def list_manual(session: Session = Depends(get_session)):
    return [m.public() for m in session.scalars(select(ManualPosition)).all()]


@app.post("/api/manual-positions")
def create_manual(body: ManualIn, session: Session = Depends(get_session)):
    m = ManualPosition()
    _apply_manual(m, body)
    session.add(m)
    session.commit()
    return m.public()


@app.put("/api/manual-positions/{mid}")
def update_manual(mid: int, body: ManualIn, session: Session = Depends(get_session)):
    m = session.get(ManualPosition, mid)
    if not m:
        raise HTTPException(404)
    _apply_manual(m, body)
    session.commit()
    return m.public()


@app.delete("/api/manual-positions/{mid}")
def delete_manual(mid: int, session: Session = Depends(get_session)):
    m = session.get(ManualPosition, mid)
    if not m:
        raise HTTPException(404)
    session.delete(m)
    session.commit()
    return {"ok": True}
