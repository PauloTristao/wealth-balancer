"""Normalização de tickers e classificação por classe de ativo."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.settings import ativos_config

TICKER_RE = re.compile(r"^([A-Z]{4})(\d{1,2})F?$")

CLASSES = ("ACAO", "FII", "RF", "INTL", "OUTROS")


@dataclass(frozen=True)
class TickerInfo:
    raw: str            # ticker como veio (ex.: XPML12)
    base: str           # ativo-base (ex.: XPML11)
    is_right: bool      # direito/recibo de subscrição
    classe: str
    subtipo: str


def split_produto(produto: str) -> tuple[str, str]:
    """'ITSA4 - ITAUSA S/A' -> ('ITSA4', 'ITAUSA S/A'); 'Tesouro Selic 2027' -> ('Tesouro Selic 2027', ...)."""
    produto = (produto or "").strip()
    if produto.lower().startswith("tesouro"):
        return produto, produto
    if " - " in produto:
        tk, nome = produto.split(" - ", 1)
        return tk.strip().upper(), nome.strip()
    return produto.upper(), produto


def strip_fracionario(ticker: str) -> str:
    """ITSA4F -> ITSA4."""
    m = TICKER_RE.match(ticker)
    if m and ticker.endswith("F"):
        return m.group(1) + m.group(2)
    return ticker


def base_ticker(ticker: str) -> tuple[str, bool]:
    """Mapeia direitos/recibos ao ativo-base.

    Ações: 1/9 -> 3 (ON), 2/10 -> 4 (PN). FIIs: 12..15 -> 11.
    """
    m = TICKER_RE.match(ticker)
    if not m:
        return ticker, False
    root, num = m.group(1), int(m.group(2))
    if num in (1, 9):
        return f"{root}3", True
    if num in (2, 10):
        return f"{root}4", True
    if 12 <= num <= 15:
        return f"{root}11", True
    return f"{root}{num}", False


def classify(ticker: str) -> tuple[str, str]:
    cfg = ativos_config()
    ov = (cfg.get("overrides") or {}).get(ticker)
    if ov:
        return ov.get("classe", "OUTROS"), ov.get("subtipo", "")
    if ticker.lower().startswith("tesouro"):
        low = ticker.lower()
        if "selic" in low:
            sub = "Tesouro Selic"
        elif "prefixado" in low:
            sub = "Tesouro Prefixado"
        elif "ipca" in low or "renda+" in low or "educa+" in low:
            sub = "Tesouro IPCA"
        else:
            sub = "Tesouro"
        return "RF", sub
    if ticker == "FUTURO":
        return "OUTROS", "Futuro"
    m = TICKER_RE.match(ticker)
    if not m:
        return "OUTROS", ""
    num = int(m.group(2))
    if num in (31, 32, 33, 34, 35, 39):
        return "INTL", "BDR"
    if num == 11:
        if ticker in (cfg.get("etfs_internacionais") or []):
            return "INTL", "ETF"
        if ticker in (cfg.get("etfs_nacionais") or []):
            return "ACAO", "ETF"
        if ticker in (cfg.get("units_acoes") or []):
            return "ACAO", "Unit"
        return "FII", "FII"
    if num in (3, 4, 5, 6, 7, 8):
        return "ACAO", "Ação"
    return "OUTROS", ""


def ticker_info(raw: str) -> TickerInfo:
    raw = strip_fracionario(raw.strip().upper()) if not raw.lower().startswith("tesouro") else raw.strip()
    if raw.upper().startswith("FUTURO"):
        return TickerInfo(raw, "FUTURO", False, "OUTROS", "Futuro")
    base, is_right = base_ticker(raw)
    classe, sub = classify(base)
    return TickerInfo(raw, base, is_right, classe, sub)


def root_of(ticker: str) -> str | None:
    m = TICKER_RE.match(ticker)
    return m.group(1) if m else None
