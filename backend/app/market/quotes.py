"""Cotações de ativos da B3 (ações, FIIs, ETFs, BDRs).

Fonte principal: Yahoo Finance (endpoint de chart, sem chave). Se houver BRAPI_TOKEN
no ambiente, usa brapi.dev primeiro e o Yahoo como reserva.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import httpx

UA = {"User-Agent": "Mozilla/5.0 (wealth-balancer)"}
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
BRAPI_QUOTE = "https://brapi.dev/api/quote/{tickers}"


@dataclass
class QuoteData:
    ticker: str
    preco: float
    variacao_dia: float | None = None
    nome: str = ""
    max_52s: float | None = None
    min_52s: float | None = None
    fonte: str = ""


def _yahoo_symbol(ticker: str) -> str:
    return f"{ticker}.SA"


async def _yahoo_one(client: httpx.AsyncClient, ticker: str) -> QuoteData | None:
    try:
        r = await client.get(YAHOO_CHART.format(symbol=_yahoo_symbol(ticker)), params={"range": "5d", "interval": "1d"})
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        preco = meta.get("regularMarketPrice")
        if preco is None:
            return None
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        var = meta.get("regularMarketChangePercent")
        if var is None and prev:
            var = (preco / prev - 1) * 100
        return QuoteData(ticker, float(preco), var, meta.get("longName") or meta.get("shortName") or "",
                         meta.get("fiftyTwoWeekHigh"), meta.get("fiftyTwoWeekLow"), "yahoo")
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None


async def _brapi(client: httpx.AsyncClient, tickers: list[str], token: str) -> dict[str, QuoteData]:
    out: dict[str, QuoteData] = {}
    for i in range(0, len(tickers), 10):
        chunk = tickers[i:i + 10]
        try:
            r = await client.get(BRAPI_QUOTE.format(tickers=",".join(chunk)), params={"token": token})
            r.raise_for_status()
            for it in r.json().get("results", []):
                if it.get("regularMarketPrice") is None:
                    continue
                out[it["symbol"]] = QuoteData(
                    it["symbol"], float(it["regularMarketPrice"]), it.get("regularMarketChangePercent"),
                    it.get("longName") or it.get("shortName") or "", it.get("fiftyTwoWeekHigh"),
                    it.get("fiftyTwoWeekLow"), "brapi",
                )
        except (httpx.HTTPError, ValueError, KeyError):
            continue
    return out


async def fetch_quotes(tickers: list[str]) -> dict[str, QuoteData]:
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    async with httpx.AsyncClient(headers=UA, timeout=15, follow_redirects=True) as client:
        out: dict[str, QuoteData] = {}
        token = os.environ.get("BRAPI_TOKEN")
        if token:
            out.update(await _brapi(client, tickers, token))
        missing = [t for t in tickers if t not in out]
        sem = asyncio.Semaphore(6)

        async def one(t: str):
            async with sem:
                return await _yahoo_one(client, t)

        for q in await asyncio.gather(*(one(t) for t in missing)):
            if q:
                out[q.ticker] = q
        return out


async def _range_one(client: httpx.AsyncClient, ticker: str) -> tuple[str, dict | None]:
    """Mínima/máxima de 52 semanas a partir dos fechamentos diários, corrigindo saltos de
    desdobramento que o Yahoo às vezes não registra (variação diária > 40% em ETF/BDR)."""
    try:
        r = await client.get(YAHOO_CHART.format(symbol=_yahoo_symbol(ticker)), params={"range": "1y", "interval": "1d"})
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0].get("close") or [] if c]
        preco = res["meta"].get("regularMarketPrice") or (closes[-1] if closes else None)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return ticker, None
    if not closes or not preco:
        return ticker, None
    ajust = closes[:] + [preco]
    for i in range(len(ajust) - 1, 0, -1):  # de trás para frente, reescala o trecho anterior ao salto
        ratio = ajust[i] / ajust[i - 1]
        if ratio > 1.6 or ratio < 0.6:
            for j in range(i):
                ajust[j] *= ratio
    return ticker, {"preco": float(preco), "min_52s": min(ajust), "max_52s": max(ajust)}


async def fetch_ranges(tickers: list[str]) -> dict[str, dict]:
    async with httpx.AsyncClient(headers=UA, timeout=20, follow_redirects=True) as client:
        sem = asyncio.Semaphore(6)

        async def one(t):
            async with sem:
                return await _range_one(client, t)

        return {t: d for t, d in await asyncio.gather(*(one(t) for t in tickers)) if d}
