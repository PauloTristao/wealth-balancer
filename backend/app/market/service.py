"""Atualização de cotações com cache em banco."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Quote
from app.market.quotes import fetch_quotes

QUOTE_MAX_AGE = timedelta(minutes=15)


def cached_quotes(session: Session, tickers: list[str]) -> dict[str, Quote]:
    if not tickers:
        return {}
    return {q.ticker: q for q in session.scalars(select(Quote).where(Quote.ticker.in_(tickers))).all()}


def refresh_quotes(session: Session, tickers: list[str], force: bool = False) -> dict[str, Quote]:
    cache = cached_quotes(session, tickers)
    now = datetime.now()
    stale = [t for t in tickers if force or t not in cache or now - cache[t].atualizado_em > QUOTE_MAX_AGE]
    if stale:
        fresh = _run(fetch_quotes(stale))
        for t, q in fresh.items():
            obj = cache.get(t) or Quote(ticker=t)
            obj.preco, obj.variacao_dia, obj.nome = q.preco, q.variacao_dia, q.nome
            obj.max_52s, obj.min_52s, obj.fonte, obj.atualizado_em = q.max_52s, q.min_52s, q.fonte, now
            session.merge(obj)
        session.commit()
        cache = cached_quotes(session, tickers)
    return cache


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # chamado de dentro de um loop (não esperado nas rotas síncronas do FastAPI)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()
