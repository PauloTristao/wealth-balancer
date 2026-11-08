"""Evolução patrimonial mês a mês (a "foto" do fim de cada mês).

Para cada fim de mês: posições do ledger × fechamento do mês. Rentabilidade mensal pelo
método de Dietz modificado (aportes/resgates do mês não contam como ganho; proventos contam),
acumulada e comparada com CDI e Ibovespa.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.importers.service import load_rows
from app.market import history, tesouro
from app.market.service import cached_quotes
from app.portfolio.ledger import run_ledger
from app.settings import ativos_config

CLASSES = ("ACAO", "FII", "RF", "INTL", "OUTROS")


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _prev(mes: str) -> str:
    y, m = map(int, mes.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def build_evolution(session: Session, refresh: bool = True, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    rows = load_rows(session)
    if not rows:
        return {"meses": [], "resumo": None, "erros": []}

    base = run_ledger(rows)
    datas_trades = [t["data"] for t in base.trades if t["valor"]]
    if not datas_trades:
        return {"meses": [], "resumo": None, "erros": []}
    inicio = date.fromisoformat(min(datas_trades))
    meses = _months(inicio, hoje)
    fins = {m: min(_month_end(*map(int, m.split("-"))), hoje) for m in meses}
    res = run_ledger(rows, snapshot_dates=list(fins.values()))

    # -------- séries de preço
    tickers = sorted({t for snap in res.snapshots.values() for t in snap if not t.lower().startswith("tesouro")})
    proxy = ativos_config().get("proxy_historico") or {}
    series_tickers = sorted(set(tickers) | {proxy[t] for t in tickers if t in proxy} | {history.IBOV})
    erros: list[str] = []
    if refresh:
        try:
            erros += history.refresh_series(session, series_tickers, date(inicio.year - (inicio.month == 1),
                                                                          (inicio.month - 2) % 12 + 1, 1))
        except Exception as exc:
            erros.append(f"Falha ao atualizar históricos: {exc}")
        if any(t.lower().startswith("tesouro") for snap in res.snapshots.values() for t in snap):
            try:
                tesouro.refresh(session)
            except Exception as exc:
                erros.append(f"Falha ao atualizar Tesouro: {exc}")
    series = history.load_series(session, series_tickers + [history.CDI])
    atuais = cached_quotes(session, tickers)
    mes_atual = hoje.strftime("%Y-%m")
    book = tesouro.PriceBook(session)

    def preco(ticker: str, mes: str) -> tuple[float | None, str]:
        if ticker.lower().startswith("tesouro"):
            pu = book.price(ticker, fins[mes])
            return (pu, "tesouro") if pu is not None else (None, "")
        if mes == mes_atual and ticker in atuais:
            return atuais[ticker].preco, "cotacao"
        v = series.get(ticker, {}).get(mes)
        if v is not None:
            return v, "historico"
        if ticker in proxy:
            v = series.get(proxy[ticker], {}).get(mes)
            if v is not None:
                return v, f"proxy {proxy[ticker]}"
        return None, ""

    # -------- fluxos por mês
    aportes: dict[str, float] = defaultdict(float)
    for t in res.trades:
        if t["valor"]:
            aportes[t["data"][:7]] += t["valor"] if t["lado"] == "C" else -t["valor"]
    proventos: dict[str, float] = defaultdict(float)
    for i in res.income:
        proventos[i["data"][:7]] += i["valor"]

    # -------- loop mensal
    out = []
    v_prev = 0.0
    acum = cdi_acum = 1.0
    ibov = series.get(history.IBOV, {})
    ibov_base = ibov.get(_prev(meses[0])) or ibov.get(meses[0])
    for mes in meses:
        snap = res.snapshots.get(fins[mes], {})
        por_classe: dict[str, float] = defaultdict(float)
        aplicado = 0.0
        estimados = []
        for tk, (qtd, custo, classe) in snap.items():
            p, _fonte = preco(tk, mes)
            if p is None:
                valor = custo
                estimados.append(tk)
            else:
                valor = p * qtd
            por_classe[classe] += valor
            aplicado += custo
        v_end = sum(por_classe.values())
        f = aportes.get(mes, 0.0)
        inc = proventos.get(mes, 0.0)
        denom = v_prev + 0.5 * f
        r = (v_end - v_prev - f + inc) / denom if denom > 1e-6 else 0.0
        acum *= 1 + r
        cdi_m = series.get(history.CDI, {}).get(mes)
        if cdi_m is not None:
            cdi_acum *= 1 + cdi_m / 100
        ib = ibov.get(mes)
        out.append({
            "mes": mes,
            "patrimonio": round(v_end, 2),
            "aplicado": round(aplicado, 2),
            "por_classe": {c: round(por_classe.get(c, 0.0), 2) for c in CLASSES if por_classe.get(c)},
            "aportes": round(f, 2),
            "proventos": round(inc, 2),
            "rent_mes_pct": round(100 * r, 2),
            "rent_acum_pct": round(100 * (acum - 1), 2),
            "cdi_mes_pct": cdi_m,
            "cdi_acum_pct": round(100 * (cdi_acum - 1), 2),
            "ibov_acum_pct": round(100 * (ib / ibov_base - 1), 2) if ib and ibov_base else None,
            "estimados": estimados,
        })
        v_prev = v_end

    def janela(n: int) -> dict:
        sub = out[-n:]
        if not sub:
            return {}
        r = c = 1.0
        for x in sub:
            r *= 1 + x["rent_mes_pct"] / 100
            c *= 1 + (x["cdi_mes_pct"] or 0) / 100
        i0 = ibov.get(_prev(sub[0]["mes"]))
        i1 = ibov.get(sub[-1]["mes"])
        return {
            "carteira_pct": round(100 * (r - 1), 2),
            "cdi_pct": round(100 * (c - 1), 2),
            "ibov_pct": round(100 * (i1 / i0 - 1), 2) if i0 and i1 else None,
            "aportes": round(sum(x["aportes"] for x in sub), 2),
            "proventos": round(sum(x["proventos"] for x in sub), 2),
        }

    ult = out[-1]
    resumo = {
        "inicio": meses[0],
        "patrimonio": ult["patrimonio"],
        "aplicado": ult["aplicado"],
        "desde_inicio": {**janela(len(out)), "ibov_pct": ult["ibov_acum_pct"]},
        "ultimos_12m": janela(12),
        "no_ano": janela(hoje.month),
    }
    return {"meses": out, "resumo": resumo, "erros": erros}
