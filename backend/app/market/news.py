"""Notícias por ativo via RSS do Google Notícias (pt-BR), com cache diário."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import httpx
from defusedxml import ElementTree as ET  # XML externo: bloqueia entidades maliciosas (XXE/billion laughs)
from sqlalchemy.orm import Session

from app.db import KV
from app.security import url_http_segura

UA = {"User-Agent": "Mozilla/5.0 (wealth-balancer; leitor RSS)"}
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
MAX_ITENS = 12
JANELA_DIAS = 45


def _query(ticker: str, nome: str | None) -> str:
    if ticker.lower().startswith("tesouro"):
        return '"Tesouro Direto" OR "juros futuros" OR "Copom"'
    termos = [f'"{ticker}"']
    if nome and nome.upper() != ticker.upper():
        termos.append(f'"{nome}"')
    return " OR ".join(termos)


def _clean(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", html or "")).strip()


def parse_rss(xml_bytes: bytes, hoje: datetime | None = None) -> list[dict]:
    hoje = hoje or datetime.now(timezone.utc)
    root = ET.fromstring(xml_bytes)
    itens = []
    for it in root.iter("item"):
        titulo = _clean(it.findtext("title", ""))
        fonte_el = it.find("source")
        fonte = fonte_el.text if fonte_el is not None and fonte_el.text else ""
        if fonte and titulo.endswith(f" - {fonte}"):
            titulo = titulo[: -len(fonte) - 3]
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate", ""))
        except (TypeError, ValueError):
            pub = None
        if pub and hoje - pub > timedelta(days=JANELA_DIAS):
            continue
        itens.append({
            "titulo": titulo,
            "fonte": fonte,
            "link": url_http_segura(it.findtext("link", "")),  # só http(s) chega ao navegador
            "data": pub.date().isoformat() if pub else None,
        })
    itens.sort(key=lambda i: i["data"] or "", reverse=True)
    # remove títulos duplicados (mesma notícia em vários veículos)
    vistos, out = set(), []
    for i in itens:
        k = i["titulo"].lower()[:80]
        if k not in vistos:
            vistos.add(k)
            out.append(i)
    return out[:MAX_ITENS]


def get_news(session: Session, ticker: str, nome: str | None = None, refresh: bool = False) -> dict:
    key = f"news:{ticker.upper()}"
    kv = session.get(KV, key)
    if kv and kv.valor and not refresh:
        d = json.loads(kv.valor)
        if d.get("dia") == date.today().isoformat():
            return d
    r = httpx.get(
        GOOGLE_NEWS_RSS,
        params={"q": _query(ticker, nome), "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"},
        headers=UA, timeout=20, follow_redirects=True,
    )
    r.raise_for_status()
    d = {"dia": date.today().isoformat(), "ticker": ticker, "consulta": _query(ticker, nome),
         "itens": parse_rss(r.content)}
    kv = kv or KV(chave=key)
    kv.valor = json.dumps(d, ensure_ascii=False)
    session.merge(kv)
    session.commit()
    return d
