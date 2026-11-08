"""Monta as listas de oportunidades por classe, marcando o que você já possui."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.importers.service import load_rows
from app.market import fundamentals, tesouro
from app.market.quotes import fetch_ranges
from app.market.service import _run
from app.portfolio.ledger import run_ledger
from app.recommend import scoring
from app.settings import ativos_config, estrategia_config

ORDEM_FORCA = {"ALTA": 0, "MEDIA": 1, "BAIXA": 2, "DESCARTADA": 3}
POSSE = {"ALTA": "Reforçar", "MEDIA": "Manter", "BAIXA": "Reavaliar", "DESCARTADA": "Reavaliar"}


def _owned(session: Session) -> dict[str, dict]:
    res = run_ledger(load_rows(session))
    return {p.ticker: {"qtd": p.qtd, "preco_medio": p.preco_medio, "custo": p.custo_total}
            for p in res.open_positions()}


def _mark(itens: list[dict], owned: dict[str, dict]) -> list[dict]:
    for it in itens:
        o = owned.get(it["ticker"])
        it["possui"] = bool(o)
        if o:
            it["posicao"] = {"qtd": round(o["qtd"], 4), "preco_medio": round(o["preco_medio"], 2)}
            it["recomendacao_posse"] = "Manter até o vencimento" if it.get("vence_em_breve") else POSSE[it["forca"]]
    return sorted(itens, key=lambda i: (ORDEM_FORCA[i["forca"]], -i["score"]))


_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SEGUNDOS = 600


def build(session: Session, classe: str, refresh: bool = True) -> dict:
    """Resultado com cache em memória de 10 min (o simulador chama a cada digitação)."""
    import time

    hit = _CACHE.get(classe)
    if hit and time.time() - hit[0] < CACHE_SEGUNDOS:
        return hit[1]
    out = _build(session, classe, refresh)
    if not out["erros"]:
        _CACHE[classe] = (time.time(), out)
    return out


def clear_cache() -> None:
    _CACHE.clear()


def _build(session: Session, classe: str, refresh: bool = True) -> dict:
    est = estrategia_config()
    forca = est["forca"]
    owned = _owned(session)
    erros: list[str] = []
    itens: list[dict] = []
    fontes: dict[str, str | None] = {}

    def ensure(cat: str) -> dict[str, dict]:
        if refresh:
            try:
                fundamentals.refresh(session, cat)
            except Exception as exc:
                erros.append(f"Falha ao atualizar dados de {cat}: {exc}")
        fontes[cat] = fundamentals.updated_at(session, cat)
        return fundamentals.load(session, cat)

    if classe == "ACAO":
        for d in ensure("ACAO").values():
            itens.append(scoring.score_acao(d, est["acoes"], forca))
    elif classe == "FII":
        for d in ensure("FII").values():
            itens.append(scoring.score_fii(d, est["fii"], forca))
    elif classe == "INTL":
        cfg_at = ativos_config()
        etfs = cfg_at.get("etf_info") or {}
        bdrs = dict(cfg_at.get("bdrs_acompanhados") or {})
        for t in owned:  # BDRs/ETFs que você possui entram mesmo fora das listas
            if _classe_de(t) == "INTL" and t not in etfs and t not in bdrs:
                bdrs[t] = {"nome": t}
        try:
            ranges = _run(fetch_ranges(list(etfs) + list(bdrs)))
        except Exception as exc:
            erros.append(f"Falha nas cotações de ETFs/BDRs: {exc}")
            ranges = {}
        for tk, info in etfs.items():
            q = ranges.get(tk, {})
            itens.append(scoring.score_etf(tk, info, q.get("preco"), q.get("min_52s"), q.get("max_52s"),
                                           est["etf"], forca))
        for tk, info in bdrs.items():
            q = ranges.get(tk, {})
            itens.append(scoring.score_bdr(tk, info, q.get("preco"), q.get("min_52s"), q.get("max_52s"), forca))
        fontes["cotacoes"] = "Yahoo Finance (52 semanas)"
    elif classe == "RF":
        if refresh:
            try:
                tesouro.refresh(session)
            except Exception as exc:
                erros.append(f"Falha ao atualizar Tesouro: {exc}")
        macro = fundamentals.macro(session)
        offers = tesouro.latest_offers(session)
        for off in offers:
            it = scoring.score_tesouro(off, macro, est["renda_fixa"], incluir_curto=_possui_tesouro(owned, off))
            if it:
                itens.append(it)
        fontes["tesouro"] = offers[0]["data_base"] if offers else None
        fontes["macro"] = f"Selic {macro.get('selic')}% · IPCA esperado 12m {macro.get('ipca_12m')}%"
    else:
        raise ValueError("classe inválida")

    itens = _mark(itens, owned)
    # ativos que você possui mas não apareceram na fonte (ex.: ticker antigo)
    vistos = {i["ticker"] for i in itens}
    faltando = [t for t in owned if t not in vistos and _classe_de(t) == classe]
    contagem = {f: sum(1 for i in itens if i["forca"] == f) for f in ORDEM_FORCA}
    return {"classe": classe, "itens": itens, "contagem": contagem, "fontes": fontes, "erros": erros,
            "sem_dados": faltando}


def _possui_tesouro(owned: dict[str, dict], off: dict) -> bool:
    ano = int(off["vencimento"][:4])
    for t in owned:
        rv = tesouro.resolve(t)
        if rv and rv[0] == off["tipo"] and rv[1] == ano:
            return True
    return False


def _classe_de(ticker: str) -> str:
    from app.portfolio.assets import ticker_info

    return ticker_info(ticker).classe


def scores_by_ticker(session: Session, classes: tuple[str, ...] = ("ACAO", "FII", "INTL", "RF"),
                     refresh: bool = True) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in classes:
        try:
            for it in build(session, c, refresh=refresh)["itens"]:
                out[it["ticker"]] = it
        except Exception:
            continue
    return out
