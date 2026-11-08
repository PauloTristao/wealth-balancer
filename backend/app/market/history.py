"""Séries mensais com cache em banco: preços de ativos (Yahoo), Ibovespa e CDI (Banco Central).

Cada série é baixada no máximo uma vez por dia; os meses antigos não mudam.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import KV, PriceMonthly
from app.market.quotes import UA, YAHOO_CHART
from app.market.service import _run

IBOV = "^BVSP"
CDI = "CDI"
BCB_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
SGS_CDI_MENSAL = 4391   # CDI acumulado no mês (% a.m.)


def _kv_key(ticker: str) -> str:
    return f"hist:{ticker}"


def _fresh(session: Session, ticker: str) -> bool:
    kv = session.get(KV, _kv_key(ticker))
    return bool(kv and kv.valor == date.today().isoformat())


def _yahoo_symbol(ticker: str) -> str:
    return ticker if ticker.startswith("^") else f"{ticker}.SA"


async def _yahoo_monthly(client: httpx.AsyncClient, ticker: str, start: date) -> dict[str, float] | None:
    period1 = int(datetime(start.year, start.month, 1, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.now(timezone.utc).timestamp())
    try:
        r = await client.get(
            YAHOO_CHART.format(symbol=_yahoo_symbol(ticker)),
            params={"period1": period1, "period2": period2, "interval": "1mo", "events": "split"},
        )
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    splits = sorted(
        (datetime.fromtimestamp(int(k), timezone.utc).date(), v["numerator"] / v["denominator"])
        for k, v in ((res.get("events") or {}).get("splits") or {}).items()
    )
    out: dict[str, float] = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, timezone.utc).date()
        # o Yahoo ajusta preços passados por desdobramentos/grupamentos; desfazemos para casar com a qtd da época
        mes_fim = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        factor = 1.0
        for sd, ratio in splits:
            if sd >= mes_fim:
                factor *= ratio
        out[d.strftime("%Y-%m")] = float(c) * factor
    return out


def _bcb_monthly(serie: int, start: date) -> dict[str, float]:
    r = httpx.get(
        BCB_SGS.format(serie=serie),
        params={"formato": "json", "dataInicial": start.strftime("01/%m/%Y")},
        timeout=30,
    )
    r.raise_for_status()
    out = {}
    for it in r.json():
        d, m, y = it["data"].split("/")
        out[f"{y}-{m}"] = float(it["valor"])
    return out


def _store(session: Session, ticker: str, series: dict[str, float], fonte: str) -> None:
    session.execute(delete(PriceMonthly).where(PriceMonthly.ticker == ticker))
    session.add_all(PriceMonthly(ticker=ticker, mes=m, valor=v, fonte=fonte) for m, v in series.items())
    kv = session.get(KV, _kv_key(ticker)) or KV(chave=_kv_key(ticker))
    kv.valor = date.today().isoformat()
    session.merge(kv)


def load_series(session: Session, tickers: list[str]) -> dict[str, dict[str, float]]:
    rows = session.scalars(select(PriceMonthly).where(PriceMonthly.ticker.in_(tickers))).all()
    out: dict[str, dict[str, float]] = {t: {} for t in tickers}
    for r in rows:
        out[r.ticker][r.mes] = r.valor
    return out


def refresh_series(session: Session, tickers: list[str], start: date, include_cdi: bool = True) -> list[str]:
    """Atualiza (se necessário) as séries mensais. Retorna mensagens de erro, se houver."""
    errors: list[str] = []
    stale = [t for t in tickers if not _fresh(session, t)]
    if stale:
        async def go():
            async with httpx.AsyncClient(headers=UA, timeout=20, follow_redirects=True) as client:
                sem = asyncio.Semaphore(6)

                async def one(t):
                    async with sem:
                        return t, await _yahoo_monthly(client, t, start)

                return await asyncio.gather(*(one(t) for t in stale))

        for t, series in _run(go()):
            if series:
                _store(session, t, series, "yahoo")
            else:
                # sem histórico (ativo deslistado/convertido): marca como verificado hoje para não insistir
                kv = session.get(KV, _kv_key(t)) or KV(chave=_kv_key(t))
                kv.valor = date.today().isoformat()
                session.merge(kv)
    if include_cdi and not _fresh(session, CDI):
        try:
            _store(session, CDI, _bcb_monthly(SGS_CDI_MENSAL, start), "bcb")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            errors.append(f"CDI indisponível: {exc}")
    session.commit()
    return errors
