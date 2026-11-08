"""Indicadores fundamentalistas (Fundamentus) e dados macro (BCB), com cache diário.

Fonte: tabelas públicas do Fundamentus (uma requisição por dia para ações e uma para FIIs).
- Ações: P/L, P/VP, DY, ROE, margem líquida, crescimento da receita 5a, liquidez, e
  dívida líquida/EBIT derivada de (EV/EBIT − P/EBIT). Bancos/financeiras vêm com EBIT = 0.
- FIIs: DY, P/VP, liquidez, valor de mercado (→ patrimônio), qtd. de imóveis, cap rate, vacância.
- Macro: Selic meta (SGS 432) e expectativa de IPCA 12 meses (Focus/BCB).
"""
from __future__ import annotations

import json
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import KV, Fundamental

UA = {"User-Agent": "Mozilla/5.0 (wealth-balancer; consulta diaria)"}
FUNDAMENTUS_ACOES = "https://www.fundamentus.com.br/resultado.php"
FUNDAMENTUS_FII = "https://www.fundamentus.com.br/fii_resultado.php"
SGS_SELIC_META = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
FOCUS_IPCA_12M = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoInflacao12Meses"
    "?%24top=1&%24filter=Indicador%20eq%20%27IPCA%27%20and%20Suavizada%20eq%20%27S%27"
    "&%24orderby=Data%20desc&%24format=json"
)


# ------------------------------------------------------------------ parsing
def _br_num(s: str) -> float | None:
    s = s.strip().replace("%", "").replace(".", "").replace(",", ".")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _table(url: str) -> tuple[list[str], list[list[str]]]:
    r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.content.decode("latin-1"), "html.parser")
    table = soup.find("table")
    heads = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if tds:
            rows.append(tds)
    return heads, rows


def parse_acoes(heads: list[str], rows: list[list[str]]) -> list[dict]:
    ix = {h: i for i, h in enumerate(heads)}

    def g(r, name):
        return _br_num(r[ix[name]]) if name in ix else None

    out = []
    for r in rows:
        p_ebit, ev_ebit = g(r, "P/EBIT"), g(r, "EV/EBIT")
        financeiro = (p_ebit in (None, 0.0)) and (ev_ebit in (None, 0.0))
        # EBIT pouco representativo (holdings: P/EBIT altíssimo) -> não usar dív./EBIT
        ebit_ok = p_ebit not in (None, 0.0) and ev_ebit is not None and 0 < p_ebit < 60
        div_ebit = round(ev_ebit - p_ebit, 2) if (ebit_ok and not financeiro) else None
        out.append({
            "ticker": r[0].upper(),
            "price": g(r, "Cotação"),
            "p_l": g(r, "P/L"),
            "p_vp": g(r, "P/VP"),
            "dy": g(r, "Div.Yield"),
            "roe": g(r, "ROE"),
            "roic": g(r, "ROIC"),
            "margem_liquida": g(r, "Mrg. Líq."),
            "dividaliquidaebit": div_ebit,
            "div_liq_patrimonio": g(r, "Dív.Líq/ Patrim."),
            "receitas_cagr5": g(r, "Cresc. Rec.5a"),
            "liquidezmediadiaria": g(r, "Liq.2meses"),
            "patrimonio": g(r, "Patrim. Líq"),
            "financeiro": financeiro,
        })
    return out


def parse_fiis(heads: list[str], rows: list[list[str]]) -> list[dict]:
    ix = {h: i for i, h in enumerate(heads)}

    def g(r, name):
        return _br_num(r[ix[name]]) if name in ix else None

    out = []
    for r in rows:
        pvp, vm = g(r, "P/VP"), g(r, "Valor de Mercado")
        seg = r[ix["Segmento"]] if "Segmento" in ix else ""
        imoveis = g(r, "Qtd de imóveis")
        papel = "títulos" in seg.lower() or "val. mob" in seg.lower()
        out.append({
            "ticker": r[0].upper(),
            "segment": seg,
            "sectorname": "Fundo de Papel" if papel else ("Fundo de Tijolo" if (imoveis or 0) > 0 else "Outros"),
            "price": g(r, "Cotação"),
            "ffo_yield": g(r, "FFO Yield"),
            "dy": g(r, "Dividend Yield"),
            "p_vp": pvp,
            "valor_mercado": vm,
            "patrimonio": vm / pvp if vm and pvp else None,
            "liquidezmediadiaria": g(r, "Liquidez"),
            "qtd_imoveis": imoveis,
            "cap_rate": g(r, "Cap Rate"),
            "vacancia": g(r, "Vacância Média"),
        })
    return out


# ------------------------------------------------------------------ cache
def _kv_key(cat: str) -> str:
    return f"fund:{cat}"


def is_fresh(session: Session, categoria: str) -> bool:
    kv = session.get(KV, _kv_key(categoria))
    return bool(kv and kv.valor == date.today().isoformat())


def refresh(session: Session, categoria: str, force: bool = False) -> int:
    if not force and is_fresh(session, categoria):
        return 0
    if categoria == "ACAO":
        rows = parse_acoes(*_table(FUNDAMENTUS_ACOES))
    elif categoria == "FII":
        rows = parse_fiis(*_table(FUNDAMENTUS_FII))
    else:
        raise ValueError(categoria)
    now = datetime.now()
    session.execute(delete(Fundamental).where(Fundamental.categoria == categoria))
    vistos = set()
    for d in rows:
        if d["ticker"] in vistos:
            continue
        vistos.add(d["ticker"])
        session.add(Fundamental(ticker=d["ticker"], categoria=categoria,
                                dados=json.dumps(d, ensure_ascii=False), atualizado_em=now))
    kv = session.get(KV, _kv_key(categoria)) or KV(chave=_kv_key(categoria))
    kv.valor = date.today().isoformat()
    session.merge(kv)
    session.commit()
    return len(vistos)


def load(session: Session, categoria: str) -> dict[str, dict]:
    rows = session.scalars(select(Fundamental).where(Fundamental.categoria == categoria)).all()
    return {r.ticker: json.loads(r.dados) for r in rows}


def updated_at(session: Session, categoria: str) -> str | None:
    kv = session.get(KV, _kv_key(categoria))
    return kv.valor if kv else None


# ------------------------------------------------------------------ macro
def macro(session: Session) -> dict:
    """Selic meta e IPCA esperado 12m (cache diário em KV)."""
    kv = session.get(KV, "macro")
    if kv and kv.valor:
        d = json.loads(kv.valor)
        if d.get("dia") == date.today().isoformat() and d.get("selic") is not None and d.get("ipca_12m") is not None:
            return d
    d = {"dia": date.today().isoformat(), "selic": None, "ipca_12m": None}
    try:
        d["selic"] = float(httpx.get(SGS_SELIC_META, timeout=20).json()[0]["valor"])
    except Exception:
        pass
    try:
        d["ipca_12m"] = float(httpx.get(FOCUS_IPCA_12M, timeout=20).json()["value"][0]["Mediana"])
    except Exception:
        pass
    if d["selic"] is not None:
        kv = kv or KV(chave="macro")
        kv.valor = json.dumps(d)
        session.merge(kv)
        session.commit()
    return d
