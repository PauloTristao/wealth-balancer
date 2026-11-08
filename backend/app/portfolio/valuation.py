"""Consolidação a preço de mercado: o que aparece no Dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ManualPosition
from app.importers.service import load_rows
from app.market import tesouro
from app.market.service import cached_quotes, refresh_quotes
from app.portfolio.ledger import LedgerResult, run_ledger
from app.settings import estrategia_config

CLASSES = ("ACAO", "FII", "RF", "INTL")
CLASS_LABEL = {"ACAO": "Ações", "FII": "FIIs", "RF": "Renda Fixa", "INTL": "Internacional", "OUTROS": "Outros"}


def _is_tesouro(ticker: str) -> bool:
    return ticker.lower().startswith("tesouro")


def build_dashboard(session: Session, refresh: bool = True, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    res: LedgerResult = run_ledger(load_rows(session))
    abertas = res.open_positions()

    # -------- preços
    tickers_b3 = [p.ticker for p in abertas if not _is_tesouro(p.ticker)]
    erros: list[str] = []
    if refresh:
        try:
            quotes = refresh_quotes(session, tickers_b3)
        except Exception as exc:  # rede indisponível: segue com cache
            erros.append(f"Falha ao atualizar cotações: {exc}")
            quotes = cached_quotes(session, tickers_b3)
        if any(_is_tesouro(p.ticker) for p in abertas):
            try:
                tesouro.refresh(session)
            except Exception as exc:
                erros.append(f"Falha ao atualizar Tesouro Direto: {exc}")
    else:
        quotes = cached_quotes(session, tickers_b3)

    inicio_12m = (hoje - timedelta(days=365)).isoformat()
    prov_12m: dict[str, float] = defaultdict(float)
    for i in res.income:
        if i["data"] >= inicio_12m:
            prov_12m[i["ticker"]] += i["valor"]

    ativos = []
    for p in abertas:
        preco = fonte = data_preco = None
        var_dia = None
        if _is_tesouro(p.ticker):
            tp = tesouro.price(session, p.ticker)
            if tp:
                preco, data_preco, fonte = tp[0], tp[1].isoformat(), "tesouro"
        elif p.ticker in quotes:
            q = quotes[p.ticker]
            preco, var_dia, fonte, data_preco = q.preco, q.variacao_dia, q.fonte, q.atualizado_em.isoformat(
                timespec="minutes")
        if preco is None:
            erros.append(f"Sem cotação para {p.ticker}; usando preço médio.")
        valor = (preco if preco is not None else p.preco_medio) * p.qtd
        lucro = valor - p.custo_total
        ativos.append({
            **p.public(),
            "preco_atual": round(preco, 4) if preco is not None else None,
            "variacao_dia": round(var_dia, 2) if var_dia is not None else None,
            "cotacao_fonte": fonte, "cotacao_em": data_preco,
            "valor_atual": round(valor, 2),
            "lucro": round(lucro, 2),
            "rentabilidade_pct": round(100 * lucro / p.custo_total, 2) if p.custo_total else None,
            "rent_com_proventos_pct": round(100 * (lucro + p.proventos) / p.custo_total, 2) if p.custo_total else None,
            "proventos_12m": round(prov_12m.get(p.ticker, 0.0), 2),
            "yoc_12m_pct": round(100 * prov_12m.get(p.ticker, 0.0) / p.custo_total, 2) if p.custo_total else None,
            "manual": False,
        })

    # -------- posições manuais
    reserva = []
    for m in session.scalars(select(ManualPosition)).all():
        item = {
            "ticker": m.nome, "nome": m.nome, "classe": m.classe, "subtipo": m.subtipo or "Manual",
            "qtd": None, "preco_medio": None, "custo_total": round(m.valor_aplicado, 2),
            "preco_atual": None, "variacao_dia": None, "cotacao_fonte": "manual",
            "cotacao_em": m.data_ref.isoformat(), "valor_atual": round(m.valor_atual, 2),
            "lucro": round(m.valor_atual - m.valor_aplicado, 2),
            "rentabilidade_pct": round(100 * (m.valor_atual / m.valor_aplicado - 1), 2) if m.valor_aplicado else None,
            "rent_com_proventos_pct": None, "proventos": 0.0, "proventos_12m": 0.0, "yoc_12m_pct": None,
            "lucro_realizado": 0.0, "manual": True, "id": m.id,
        }
        (reserva if m.reserva_emergencia else ativos).append(item)

    # -------- totais e alocação
    alvo_cfg = estrategia_config().get("alocacao", {})
    por_classe: dict[str, float] = defaultdict(float)
    for a in ativos:
        por_classe[a["classe"]] += a["valor_atual"]
    total_balanceavel = sum(por_classe[c] for c in CLASSES) or 0.0
    total = sum(por_classe.values())

    for a in ativos:
        a["pct_carteira"] = round(100 * a["valor_atual"] / total, 2) if total else 0.0
        a["pct_classe"] = round(100 * a["valor_atual"] / por_classe[a["classe"]], 2) if por_classe[a["classe"]] else 0.0

    alocacao = []
    for c in CLASSES:
        cfg = alvo_cfg.get(c, {"alvo": 25, "min": 15, "max": 35})
        v = por_classe.get(c, 0.0)
        pct = 100 * v / total_balanceavel if total_balanceavel else 0.0
        status = "abaixo" if pct < cfg["min"] else "acima" if pct > cfg["max"] else "ok"
        alocacao.append({
            "classe": c, "label": CLASS_LABEL[c], "valor": round(v, 2), "pct": round(pct, 2),
            "alvo": cfg["alvo"], "min": cfg["min"], "max": cfg["max"], "status": status,
            "falta_para_alvo": round(total_balanceavel * cfg["alvo"] / 100 - v, 2),
        })
    if por_classe.get("OUTROS"):
        alocacao.append({"classe": "OUTROS", "label": "Outros (fora do balanceamento)",
                         "valor": round(por_classe["OUTROS"], 2), "pct": None, "alvo": None, "min": None,
                         "max": None, "status": "fora", "falta_para_alvo": None})

    custo = sum(a["custo_total"] for a in ativos)
    prov_total = sum(i["valor"] for i in res.income)
    mes_atual = hoje.strftime("%Y-%m")
    resumo = {
        "patrimonio": round(total, 2),
        "reserva_emergencia": round(sum(r["valor_atual"] for r in reserva), 2),
        "custo": round(custo, 2),
        "lucro_nao_realizado": round(total - custo, 2),
        "rentabilidade_pct": round(100 * (total / custo - 1), 2) if custo else None,
        "lucro_realizado": round(sum(p.lucro_realizado for p in res.positions.values()), 2),
        "proventos_total": round(prov_total, 2),
        "proventos_12m": round(sum(prov_12m.values()), 2),
        "proventos_mes": round(sum(i["valor"] for i in res.income if i["data"].startswith(mes_atual)), 2),
        "yoc_12m_pct": round(100 * sum(prov_12m.values()) / custo, 2) if custo else None,
        "variacao_dia": round(sum((a["variacao_dia"] or 0) / 100 * a["valor_atual"] / (1 + (a["variacao_dia"] or 0) / 100)
                                  for a in ativos), 2),
    }

    return {
        "resumo": resumo,
        "alocacao": alocacao,
        "ativos": sorted(ativos, key=lambda a: (CLASSES.index(a["classe"]) if a["classe"] in CLASSES else 9,
                                               -a["valor_atual"])),
        "reserva": reserva,
        "avisos": res.warnings,
        "erros": erros,
        "atualizado_em": date.today().isoformat(),
    }
