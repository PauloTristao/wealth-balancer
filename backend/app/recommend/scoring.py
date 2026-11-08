"""Pontuação de oportunidades: Ações, FIIs, BDRs, ETFs internacionais e Tesouro Direto.

Cada critério vale 0..1 (transição linear entre "zero" e "cheio"), agrupado em pilares
com pesos. Pilares sem dado (ex.: dívida de bancos) são ignorados e os pesos renormalizados.

Força:
- Alta  : score >= forca.alta  E pilar de preço E de qualidade >= pilar_minimo
- Média : score >= forca.media
- Baixa : o resto
- Descartada: falhou num filtro eliminatório (liquidez, prejuízo, dado ausente)
"""
from __future__ import annotations

import math
from datetime import date

BANCOS_SEGMENTOS = ("bancos", "seguradoras", "intermediários financeiros", "previdência", "serviços financeiros")


def lin(v: float | None, zero: float, cheio: float) -> float | None:
    """0 em `zero`, 1 em `cheio`, linear entre eles (funciona nos dois sentidos)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if zero == cheio:
        return 1.0 if v >= cheio else 0.0
    t = (v - zero) / (cheio - zero)
    return max(0.0, min(1.0, t))


def _num(d: dict, k: str) -> float | None:
    v = d.get(k)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _crit(nome: str, pilar: str, valor, pontos: float | None, fmt: str, explic: str) -> dict:
    return {"nome": nome, "pilar": pilar, "valor": valor, "pontos": None if pontos is None else round(pontos, 3),
            "fmt": fmt, "explicacao": explic}


def _finalize(item: dict, criterios: list[dict], pesos: dict[str, float], forca_cfg: dict,
              pilares_essenciais: tuple[str, ...] = ("preco", "qualidade")) -> dict:
    por_pilar: dict[str, list[float]] = {}
    for c in criterios:
        if c["pontos"] is not None:
            por_pilar.setdefault(c["pilar"], []).append(c["pontos"])
    pilares = {p: 100 * sum(v) / len(v) for p, v in por_pilar.items() if v}
    peso_total = sum(pesos[p] for p in pilares if p in pesos) or 1.0
    score = sum(pilares[p] * pesos[p] for p in pilares if p in pesos) / peso_total
    essenciais_ok = all(pilares.get(p, 0) >= forca_cfg["pilar_minimo"] for p in pilares_essenciais if p in pesos)
    if item.get("descartada"):
        forca = "DESCARTADA"
    elif score >= forca_cfg["alta"] and essenciais_ok:
        forca = "ALTA"
    elif score >= forca_cfg["media"]:
        forca = "MEDIA"
    else:
        forca = "BAIXA"
    if score >= forca_cfg["alta"] and not essenciais_ok and not item.get("descartada") and item.get("setor") != "BDR":
        item["alertas"].append("Score alto, mas preço OU qualidade abaixo do mínimo — não basta um só.")
    item.update({
        "score": round(score, 1),
        "forca": forca,
        "pilares": {p: round(v, 1) for p, v in pilares.items()},
        "criterios": criterios,
    })
    return item


def _cap_alta(item: dict, regras: dict | None) -> dict:
    """Regras duras da filosofia: fora delas o ativo não chega a Alta."""
    if not regras or item["forca"] != "ALTA":
        return item
    ind = item["indicadores"]
    motivos = []
    pl, pvp = ind.get("p_l"), ind.get("p_vp")
    if "pl_min" in regras and pl is not None and pl < regras["pl_min"]:
        motivos.append(f"P/L {pl:.1f} abaixo de {regras['pl_min']}")
    if "pl_max" in regras and pl is not None and pl > regras["pl_max"]:
        motivos.append(f"P/L {pl:.1f} acima de {regras['pl_max']}")
    if "pvp_max" in regras and pvp is not None and pvp > regras["pvp_max"]:
        motivos.append(f"P/VP {pvp:.2f} acima de {regras['pvp_max']}")
    if motivos:
        item["forca"] = "MEDIA"
        item["alertas"].insert(0, "Limitada a Média: " + "; ".join(motivos) + ".")
    return item


# ------------------------------------------------------------------ AÇÕES (e BDRs)
def score_acao(d: dict, cfg: dict, forca_cfg: dict, liquidez_min: float | None = None, classe: str = "ACAO") -> dict:
    preco = _num(d, "price")
    pvp, pl, roe, dy = _num(d, "p_vp"), _num(d, "p_l"), _num(d, "roe"), _num(d, "dy")
    divida = _num(d, "dividaliquidaebit")
    cagr_r, margem = _num(d, "receitas_cagr5"), _num(d, "margem_liquida")
    liq = _num(d, "liquidezmediadiaria")
    vpa, lpa = _num(d, "vpa"), _num(d, "lpa")
    if vpa is None and preco and pvp:
        vpa = preco / pvp            # derivado: valor patrimonial por ação
    if lpa is None and preco and pl:
        lpa = preco / pl             # derivado: lucro por ação
    segmento = (d.get("segmentname") or "").strip()
    setor = (d.get("sectorname") or "").strip()
    financeiro = bool(d.get("financeiro")) or any(
        s in (segmento + " " + (d.get("subsectorname") or "")).lower() for s in BANCOS_SEGMENTOS)

    item = {
        "ticker": d["ticker"], "nome": d.get("companyname", ""), "classe": classe, "setor": setor,
        "segmento": segmento, "preco": preco, "alertas": [], "descartada": False, "motivo_descarte": None,
        "indicadores": {"p_vp": pvp, "p_l": pl, "roe": roe, "dy": dy, "div_liq_ebit": divida,
                        "margem_liquida": margem, "cagr_receita_5a": cagr_r, "liquidez_diaria": liq},
    }

    lmin = liquidez_min if liquidez_min is not None else cfg["liquidez_diaria_min"]
    if liq is None or liq < lmin:
        item.update(descartada=True, motivo_descarte=f"liquidez diária abaixo de R$ {lmin:,.0f}".replace(",", "."))
    elif pl is None or pl <= 0:
        item.update(descartada=True, motivo_descarte="prejuízo nos últimos 12 meses (P/L negativo)")
    elif pvp is None or pvp <= 0:
        item.update(descartada=True, motivo_descarte="patrimônio líquido negativo ou sem P/VP")

    c = cfg
    crit = []
    # --- preço
    if pvp is not None and pvp > 0:
        if pvp < c["pvp"]["piso"]:
            pts = 0.0
            item["alertas"].append(f"P/VP {pvp:.2f} abaixo do piso de segurança ({c['pvp']['piso']}): "
                                   "desconto grande pode indicar problema.")
        elif pvp <= c["pvp"]["ideal_max"]:
            pts = 1.0
        else:
            pts = lin(pvp, c["pvp"]["zero_em"], c["pvp"]["ideal_max"])
        crit.append(_crit("P/VP", "preco", pvp, pts, "x",
                          f"ideal entre {c['pvp']['piso']} e {c['pvp']['ideal_max']}; zera em {c['pvp']['zero_em']}"))
    if pl is not None and pl > 0:
        p = c["pl"]
        if pl < p["min_ideal"]:
            pts = lin(pl, p["zero_baixo"], p["min_ideal"])
            if pl < p["min_ideal"]:
                item["alertas"].append(f"P/L {pl:.1f} muito baixo: pode ser lucro não recorrente ou ciclo de alta.")
        elif pl <= p["max_ideal"]:
            pts = 1.0
        else:
            pts = lin(pl, p["zero_alto"], p["max_ideal"])
        crit.append(_crit("P/L", "preco", pl, pts, "x", f"ideal entre {p['min_ideal']} e {p['max_ideal']}"))
    # --- qualidade
    crit.append(_crit("ROE", "qualidade", roe, lin(roe, c["roe"]["zero"], c["roe"]["cheio"]), "%",
                      f"cheio a partir de {c['roe']['cheio']}%"))
    if not financeiro:
        crit.append(_crit("Margem líquida", "qualidade", margem,
                          lin(margem, c["margem_liquida"]["zero"], c["margem_liquida"]["cheio"]), "%",
                          f"cheio a partir de {c['margem_liquida']['cheio']}%"))
    crit.append(_crit("CAGR receita 5a", "qualidade", cagr_r,
                      lin(cagr_r, c["cagr_receita_5a"]["zero"], c["cagr_receita_5a"]["cheio"]), "%",
                      f"cheio a partir de {c['cagr_receita_5a']['cheio']}% a.a."))
    # --- dividendos
    if "dy" in d:
        pts = lin(dy, c["dy"]["zero"], c["dy"]["cheio"])
        if dy is not None and dy > c["dy"]["suspeito"]:
            pts = min(pts or 0, 0.5)
            item["alertas"].append(f"DY {dy:.1f}% muito alto: pode conter dividendo extraordinário (vale meio ponto).")
        crit.append(_crit("Dividend Yield", "dividendos", dy, pts, "%", f"cheio a partir de {c['dy']['cheio']}%"))
    # --- saúde
    if financeiro:
        item["alertas"].append("Banco/financeira: dívida e margem não se aplicam; avalie Basileia e inadimplência.")
    else:
        dlp = _num(d, "div_liq_patrimonio")
        if divida is not None:
            pts = 1.0 if divida < 0 else lin(divida, c["div_liq_ebit"]["zero"], c["div_liq_ebit"]["cheio"])
            crit.append(_crit("Dív. líq./EBIT", "saude", divida, pts, "x",
                              f"cheio até {c['div_liq_ebit']['cheio']}; zera em {c['div_liq_ebit']['zero']}"))
        elif dlp is not None:
            pts = 1.0 if dlp < 0 else lin(dlp, c["div_liq_patrimonio"]["zero"], c["div_liq_patrimonio"]["cheio"])
            crit.append(_crit("Dív. líq./Patrimônio", "saude", dlp, pts, "x",
                              "EBIT pouco representativo (ex.: holding); "
                              f"cheio até {c['div_liq_patrimonio']['cheio']}"))

    # preço justo de referência
    if dy and preco:
        item["preco_teto_bazin"] = round(preco * dy / 100 / 0.06, 2)
    if lpa and vpa and lpa > 0 and vpa > 0:
        item["preco_graham"] = round(math.sqrt(22.5 * lpa * vpa), 2)
    ref = [v for v in (item.get("preco_teto_bazin"), item.get("preco_graham")) if v]
    if ref and preco:
        item["margem_seguranca_pct"] = round(100 * (min(ref) / preco - 1), 1)

    return _cap_alta(_finalize(item, crit, c["pesos"], forca_cfg), c.get("alta_exige"))


# ------------------------------------------------------------------ FIIs
def score_fii(d: dict, cfg: dict, forca_cfg: dict) -> dict:
    preco, dy, pvp = _num(d, "price"), _num(d, "dy"), _num(d, "p_vp")
    liq, patr = _num(d, "liquidezmediadiaria"), _num(d, "patrimonio")
    vac, imoveis = _num(d, "vacancia"), _num(d, "qtd_imoveis")
    dcagr = _num(d, "dividend_cagr")
    setor = (d.get("sectorname") or "").strip()
    segmento = (d.get("segment") or d.get("subsectorname") or "").strip()
    tijolo = "tijolo" in setor.lower() or (imoveis or 0) > 0

    item = {
        "ticker": d["ticker"], "nome": d.get("companyname", ""), "classe": "FII", "setor": setor,
        "segmento": segmento, "preco": preco, "alertas": [], "descartada": False, "motivo_descarte": None,
        "indicadores": {"dy": dy, "p_vp": pvp, "vacancia": vac if tijolo else None,
                        "qtd_imoveis": imoveis if tijolo else None, "patrimonio": patr, "liquidez_diaria": liq,
                        "dividend_cagr": dcagr, "cap_rate": _num(d, "cap_rate"), "ultimo_rendimento": _num(d, "lastdividend")},
    }
    c = cfg
    if liq is None or liq < c["liquidez_diaria_min"]:
        item.update(descartada=True,
                    motivo_descarte=f"liquidez diária abaixo de R$ {c['liquidez_diaria_min']:,.0f}".replace(",", "."))
    elif not dy:
        item.update(descartada=True, motivo_descarte="sem rendimentos nos últimos 12 meses")
    elif not pvp:
        item.update(descartada=True, motivo_descarte="sem P/VP")

    crit = []
    if pvp:
        if pvp < c["pvp"]["piso"]:
            pts = 0.0
            item["alertas"].append(f"P/VP {pvp:.2f} abaixo do piso ({c['pvp']['piso']}): mercado pode estar "
                                   "precificando problema (crédito, vacância, alavancagem).")
        else:
            pts = lin(pvp, c["pvp"]["zero_em"], c["pvp"]["cheio_ate"])
        crit.append(_crit("P/VP", "preco", pvp, pts, "x",
                          f"cheio até {c['pvp']['cheio_ate']} (piso {c['pvp']['piso']}); zera em {c['pvp']['zero_em']}"))
    ffo = _num(d, "ffo_yield")
    if ffo and dy and tijolo:
        cob = ffo / dy
        item["indicadores"]["cobertura_ffo"] = round(cob, 2)
        crit.append(_crit("Cobertura FFO/DY", "renda", round(cob, 2),
                          lin(cob, c["cobertura_ffo"]["zero"], c["cobertura_ffo"]["cheio"]), "x",
                          "FFO yield ÷ DY: >= 1 indica que o fundo gera o que distribui"))
    crit.append(_crit("Dividend Yield 12m", "renda", dy, lin(dy, c["dy"]["zero"], c["dy"]["cheio"]), "%",
                      f"cheio a partir de {c['dy']['cheio']}%"))
    if dy and dy > c["dy"]["suspeito"]:
        crit[-1]["pontos"] = min(crit[-1]["pontos"] or 0, 0.5)
        item["alertas"].append(f"DY {dy:.1f}% muito alto: verifique rendimento extraordinário ou queda forte da cota.")
    if dcagr is not None:
        crit.append(_crit("Crescimento dos rendimentos", "renda", dcagr,
                          lin(dcagr, c["dividend_cagr"]["zero"], c["dividend_cagr"]["cheio"]), "%",
                          "CAGR dos rendimentos (Status Invest)"))
    if tijolo:
        crit.append(_crit("Vacância média", "qualidade", vac,
                          lin(vac, c["vacancia"]["zero"], c["vacancia"]["cheio"]) if vac is not None else None, "%",
                          f"cheio até {c['vacancia']['cheio']}%; zera em {c['vacancia']['zero']}%"))
        crit.append(_crit("Qtd. de imóveis", "qualidade", imoveis,
                          lin(imoveis, c["imoveis"]["zero"], c["imoveis"]["cheio"]), "",
                          f"diversificação: cheio a partir de {c['imoveis']['cheio']}"))
    crit.append(_crit("Patrimônio", "qualidade", patr, lin(patr, c["patrimonio"]["zero"], c["patrimonio"]["cheio"]),
                      "R$", "porte do fundo"))
    return _cap_alta(_finalize(item, crit, c["pesos"], forca_cfg, pilares_essenciais=("preco", "qualidade")),
                     c.get("alta_exige"))


# ------------------------------------------------------------------ ETFs internacionais
def score_etf(ticker: str, info: dict, preco: float | None, min52: float | None, max52: float | None,
              cfg: dict, forca_cfg: dict) -> dict:
    item = {"ticker": ticker, "nome": info.get("nome", ""), "classe": "INTL", "setor": "ETF",
            "segmento": info.get("indice", ""), "preco": preco, "alertas": [], "descartada": False,
            "motivo_descarte": None,
            "indicadores": {"taxa_adm": info.get("taxa"), "min_52s": min52, "max_52s": max52}}
    crit = []
    if preco and min52 and max52 and max52 > min52:
        pos = (preco - min52) / (max52 - min52)
        item["indicadores"]["posicao_52s_pct"] = round(100 * pos, 1)
        item["indicadores"]["desconto_max_52s_pct"] = round(100 * (1 - preco / max52), 1)
        crit.append(_crit("Posição na faixa de 52 semanas", "preco", round(100 * pos, 1), 1 - pos, "%",
                          "0% = na mínima do ano (mais barato), 100% = na máxima"))
    else:
        item.update(descartada=True, motivo_descarte="sem cotação")
    crit.append(_crit("Taxa de administração", "qualidade", info.get("taxa"),
                      lin(info.get("taxa"), cfg["taxa"]["zero"], cfg["taxa"]["cheio"]), "%", "quanto menor, melhor"))
    foco = info.get("foco", "tema")
    crit.append(_crit("Diversificação", "qualidade", foco, {"core": 1.0, "protecao": 0.7, "tema": 0.4}.get(foco, 0.4), "",
                      "core = índice amplo (S&P 500/global); tema = setorial/país/cripto"))
    if foco == "tema":
        item["alertas"].append("ETF temático/regional: use como satélite, não como base da classe.")
    return _finalize(item, crit, {"preco": 40, "qualidade": 60}, forca_cfg)


# ------------------------------------------------------------------ BDRs (sem fundamentos gratuitos)
def score_bdr(ticker: str, info: dict, preco: float | None, min52: float | None, max52: float | None,
              forca_cfg: dict) -> dict:
    item = {"ticker": ticker, "nome": info.get("nome", ""), "classe": "INTL", "setor": "BDR",
            "segmento": info.get("setor", ""), "preco": preco, "alertas": [
                "Sem fonte gratuita de fundamentos para BDR: avaliado só pelo preço; força limitada a Média."],
            "descartada": False, "motivo_descarte": None,
            "indicadores": {"min_52s": min52, "max_52s": max52}}
    crit = []
    if preco and min52 and max52 and max52 > min52:
        pos = (preco - min52) / (max52 - min52)
        item["indicadores"]["posicao_52s_pct"] = round(100 * pos, 1)
        item["indicadores"]["desconto_max_52s_pct"] = round(100 * (1 - preco / max52), 1)
        crit.append(_crit("Posição na faixa de 52 semanas", "preco", round(100 * pos, 1), 1 - pos, "%",
                          "0% = na mínima do ano (mais barato), 100% = na máxima"))
    else:
        item.update(descartada=True, motivo_descarte="sem cotação")
    item = _finalize(item, crit, {"preco": 100, "qualidade": 0}, forca_cfg)
    item["score"] = round(item["score"] * 0.6, 1)  # desconto por não haver dados de qualidade
    if item["forca"] != "DESCARTADA":
        item["forca"] = "MEDIA" if item["score"] >= forca_cfg["media"] else "BAIXA"
    item["alertas"][0] += " Score reduzido em 40% pela falta de dados de qualidade."
    return item


# ------------------------------------------------------------------ Tesouro Direto
def score_tesouro(offer: dict, macro: dict, cfg: dict, hoje: date | None = None,
                  incluir_curto: bool = False) -> dict | None:
    hoje = hoje or date.today()
    venc = date.fromisoformat(offer["vencimento"])
    anos = (venc - hoje).days / 365.25
    disponivel = offer.get("taxa_compra") not in (None, 0) and bool(offer.get("pu_compra"))
    if not incluir_curto and (anos < cfg["vencimento_min_anos"] or not disponivel):
        return None
    tipo = offer["tipo"]
    taxa = offer["taxa_compra"] if disponivel else (offer.get("taxa_venda") or 0.0)
    ipca = macro.get("ipca_12m")
    selic = macro.get("selic")
    nome = f"{tipo} {venc.year}"
    item = {"ticker": nome, "nome": nome, "classe": "RF", "setor": "Tesouro Direto", "segmento": tipo,
            "preco": offer["pu_compra"] if disponivel else offer.get("pu_venda"), "alertas": [] if disponivel else [
                "Título não disponível para compra hoje (só resgate); taxa de referência = taxa de venda."], "descartada": False, "motivo_descarte": None,
            "indicadores": {"taxa": taxa, "vencimento": offer["vencimento"], "anos": round(anos, 1),
                            "selic": selic, "ipca_esperado": ipca}}
    t = tipo.lower()
    if "selic" in t:
        real = None
        item["indicadores"]["retorno_nominal_est"] = round((selic or 0) + taxa, 2) if selic is not None else None
        score, explic = 60.0, f"Selic + {taxa:.2f}%: liquidez diária, ideal para reserva e caixa de oportunidade"
        forca = "MEDIA"
    else:
        if "ipca" in t or "renda+" in t or "educa+" in t:
            real = taxa
            r = cfg["ipca_real"]
            explic = f"IPCA + {taxa:.2f}% (juro real)"
        else:  # prefixado
            if ipca is None:
                return None
            real = 100 * ((1 + taxa / 100) / (1 + ipca / 100) - 1)
            r = cfg["prefixado_real"]
            explic = f"{taxa:.2f}% prefixado ≈ {real:.2f}% real com IPCA esperado de {ipca:.2f}%"
        item["indicadores"]["juro_real"] = round(real, 2)
        score = 100 * (lin(real, r["baixa_ate"] - 1.5, r["alta_a_partir"] + 3.5) or 0)
        forca = "ALTA" if real >= r["alta_a_partir"] else "MEDIA" if real >= r["baixa_ate"] else "BAIXA"
        if "renda+" in t or "educa+" in t:
            item["alertas"].append("Título para aposentadoria/educação: venda antes do prazo pode ter deságio grande.")
        if anos > 15:
            item["alertas"].append("Prazo longo: o preço oscila bastante com a curva de juros (marcação a mercado).")
        if "juros semestrais" in t:
            item["alertas"].append("Paga cupons semestrais (IR a cada pagamento); bom para renda, pior para juros compostos.")
    if anos < cfg["vencimento_min_anos"]:
        forca = "MEDIA"
        item["vence_em_breve"] = True
        item["alertas"].insert(0, f"Vence em {anos:.1f} ano(s): manter até o vencimento; não é para novos aportes.")
    item.update({"score": round(score, 1), "forca": forca,
                 "pilares": {"taxa": round(score, 1)},
                 "criterios": [_crit("Taxa", "taxa", taxa, score / 100, "%", explic)]})
    return item
