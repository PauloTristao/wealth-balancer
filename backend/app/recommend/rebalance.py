"""Simulador de aporte/rebalanceamento.

SOMENTE SIMULAÇÃO: nada aqui grava no banco. A carteira só muda quando os
relatórios da B3 do mês seguinte forem importados.

Regras:
1. Classes (Ações, FIIs, RF, Internacional) têm alvo e faixa (estrategia.yaml).
2. O aporte vai para as classes abaixo do alvo, proporcional ao quanto falta
   (preenchimento por "nível de água": a classe mais distante recebe primeiro).
   Se sobrar depois de todas atingirem o alvo, divide-se pelo peso alvo.
3. Opcional: vender o excesso das classes ACIMA da faixa máxima (só até voltar
   ao máximo, não ao alvo, para evitar giro e imposto) e redistribuir.
4. Dentro da classe, com scores (tela de Oportunidades): até N candidatos por classe —
   seus ativos com força Alta/Média e, se permitido, as melhores oportunidades novas
   de força Alta — com peso proporcional ao score. Ativos "Reavaliar" e títulos perto do
   vencimento não recebem aporte.
   Sem scores disponíveis: entre os ativos que você já tem, prioriza quem está abaixo
   da classe proporcionalmente ao que você já tem (mantém a composição); ações/FIIs/
   ETFs/BDRs em unidades inteiras, Tesouro em frações de 0,01. A escolha por
   qualidade/preço (score) entra na Fase 5.
"""
from __future__ import annotations

import math
from collections import defaultdict

CLASSES = ("ACAO", "FII", "RF", "INTL")
EPS = 0.01


def _water_fill(atual: dict[str, float], alvo_val: dict[str, float], valor: float) -> dict[str, float]:
    """Distribui `valor` elevando as classes mais abaixo do alvo, por razão atual/alvo."""
    alloc = {c: 0.0 for c in atual}
    restante = valor
    # razão de preenchimento: (atual+alloc)/alvo; sobe a menor até igualar a seguinte
    for _ in range(100):
        if restante <= EPS:
            break
        ativos = [c for c in atual if alvo_val[c] > 0]
        ratio = {c: (atual[c] + alloc[c]) / alvo_val[c] for c in ativos}
        menor = min(ratio.values())
        if menor >= 1 - 1e-9:
            break
        grupo = [c for c in ativos if abs(ratio[c] - menor) < 1e-9]
        outros = sorted(r for c, r in ratio.items() if c not in grupo)
        prox = min(outros[0] if outros else 1.0, 1.0)
        custo = sum((prox - menor) * alvo_val[c] for c in grupo)
        passo = min(custo, restante)
        peso = sum(alvo_val[c] for c in grupo)
        for c in grupo:
            alloc[c] += passo * alvo_val[c] / peso
        restante -= passo
    if restante > EPS:  # todas no alvo: divide pelo peso do alvo
        peso = sum(alvo_val.values()) or 1.0
        for c in alloc:
            alloc[c] += restante * alvo_val[c] / peso
    return alloc


def _whole_units(itens: list[dict], valor: float, fracionado: bool) -> tuple[list[dict], float]:
    """Converte valor da classe em quantidades. itens: [{ticker, preco, valor_atual, ...}]."""
    if not itens or valor <= EPS:
        return [], valor
    # sem score ainda: mantém a composição atual da classe (proporcional ao que você já tem)
    base_total = sum(i["valor_atual"] for i in itens) or float(len(itens))
    desejado = {i["ticker"]: valor * (i["valor_atual"] or 1.0) / base_total for i in itens}

    passo_qtd = 0.01 if fracionado else 1.0
    compras: dict[str, float] = {}
    gasto = 0.0
    for i in itens:
        p = i["preco"]
        q = math.floor(desejado[i["ticker"]] / p / passo_qtd + 1e-9) * passo_qtd
        if q > 0:
            compras[i["ticker"]] = q
            gasto += q * p
    # sobra de arredondamento: compra mais 1 unidade de quem ainda está mais longe do desejado
    sobra = valor - gasto
    while True:
        cand = [i for i in itens if i["preco"] * passo_qtd <= sobra + 1e-9]
        if not cand:
            break
        best = max(cand, key=lambda i: desejado[i["ticker"]] - compras.get(i["ticker"], 0.0) * i["preco"])
        compras[best["ticker"]] = compras.get(best["ticker"], 0.0) + passo_qtd
        sobra -= best["preco"] * passo_qtd
    out = []
    for i in itens:
        q = round(compras.get(i["ticker"], 0.0), 2)
        if q > 0:
            out.append({
                "ticker": i["ticker"], "nome": i.get("nome", ""), "classe": i["classe"], "acao": "COMPRAR",
                "qtd": q, "preco": round(i["preco"], 2), "valor": round(q * i["preco"], 2),
                "motivo": "mantém a composição atual da classe",
            })
    return out, max(sobra, 0.0)


def _candidatos(classe: str, owned_itens: list[dict], scores: dict[str, dict], novos: bool,
                max_ativos: int, novos_por_classe: int) -> list[dict] | None:
    """Candidatos ao aporte na classe com peso = score. None = sem scores (usar composição atual)."""
    if not scores:
        return None
    cands: list[dict] = []
    for i in owned_itens:
        sc = scores.get(i["ticker"])
        if not sc:
            continue
        if sc["forca"] in ("ALTA", "MEDIA") and not sc.get("vence_em_breve") and sc.get("preco"):
            cands.append({**i, "preco": sc["preco"], "score": sc["score"], "forca": sc["forca"], "novo": False})
    if novos:
        possuidos = {i["ticker"] for i in owned_itens}
        extras = [s for s in scores.values() if s["classe"] == classe and s["forca"] == "ALTA"
                  and s["ticker"] not in possuidos and s.get("preco") and not s.get("vence_em_breve")]
        extras.sort(key=lambda s: -s["score"])
        for s in extras[:novos_por_classe]:
            cands.append({"ticker": s["ticker"], "nome": s.get("nome", ""), "classe": classe, "preco": s["preco"],
                          "valor_atual": 0.0, "qtd": 0.0, "score": s["score"], "forca": s["forca"], "novo": True})
    cands.sort(key=lambda c: (-(c["forca"] == "ALTA"), -c["score"]))
    return cands[:max_ativos]


def _buy_by_score(cands: list[dict], valor: float, fracionado: bool) -> tuple[list[dict], float]:
    peso_total = sum(c["score"] for c in cands) or 1.0
    passo = 0.01 if fracionado else 1.0
    desejado = {c["ticker"]: valor * c["score"] / peso_total for c in cands}
    compras: dict[str, float] = {}
    gasto = 0.0
    for c in cands:
        q = math.floor(desejado[c["ticker"]] / c["preco"] / passo + 1e-9) * passo
        if q > 0:
            compras[c["ticker"]] = q
            gasto += q * c["preco"]
    sobra = valor - gasto
    while True:
        cand = [c for c in cands if c["preco"] * passo <= sobra + 1e-9]
        if not cand:
            break
        best = max(cand, key=lambda c: desejado[c["ticker"]] - compras.get(c["ticker"], 0.0) * c["preco"])
        compras[best["ticker"]] = compras.get(best["ticker"], 0.0) + passo
        sobra -= best["preco"] * passo
    out = []
    for c in cands:
        q = round(compras.get(c["ticker"], 0.0), 2)
        if q > 0:
            rotulo = {"ALTA": "força Alta", "MEDIA": "força Média"}[c["forca"]]
            out.append({
                "ticker": c["ticker"], "nome": c.get("nome", ""), "classe": c["classe"], "acao": "COMPRAR",
                "qtd": q, "preco": round(c["preco"], 2), "valor": round(q * c["preco"], 2),
                "motivo": f"{'nova oportunidade · ' if c['novo'] else ''}{rotulo} · score {c['score']:.0f}",
                "novo": c["novo"],
            })
    return out, max(sobra, 0.0)


def _sell_units(itens: list[dict], valor: float, fracionado: bool) -> list[dict]:
    """Vende `valor` da classe começando pelos ativos mais acima do peso igual."""
    if not itens or valor <= EPS:
        return []
    base_total = sum(i["valor_atual"] for i in itens) or 1.0
    excesso = {i["ticker"]: i["valor_atual"] for i in itens}
    soma = base_total
    passo = 0.01 if fracionado else 1.0
    out = []
    for i in itens:
        v = valor * excesso[i["ticker"]] / soma
        q = math.ceil(v / i["preco"] / passo - 1e-9) * passo
        q = min(q, i["qtd"])
        if q > 0:
            out.append({
                "ticker": i["ticker"], "nome": i.get("nome", ""), "classe": i["classe"], "acao": "VENDER",
                "qtd": round(q, 2), "preco": round(i["preco"], 2), "valor": round(q * i["preco"], 2),
                "motivo": "classe acima da faixa máxima",
            })
    return out


def simulate(dashboard: dict, aporte: float, alocacao_cfg: dict, permitir_vendas: bool = False,
             scores: dict[str, dict] | None = None, novos: bool = True, max_ativos: int = 3,
             novos_por_classe: int = 2) -> dict:
    ativos = [a for a in dashboard["ativos"] if a["classe"] in CLASSES]
    atual = {c: 0.0 for c in CLASSES}
    for a in ativos:
        atual[a["classe"]] += a["valor_atual"]
    total = sum(atual.values())
    cfg = {c: alocacao_cfg.get(c, {"alvo": 25, "min": 15, "max": 35}) for c in CLASSES}

    # ---- vendas opcionais (classes acima do máximo, considerando o total já com o aporte)
    vendas_classe = {c: 0.0 for c in CLASSES}
    if permitir_vendas:
        total_pos = total + aporte
        for c in CLASSES:
            limite = cfg[c]["max"] / 100 * total_pos
            if atual[c] > limite:
                vendas_classe[c] = atual[c] - limite

    caixa = aporte + sum(vendas_classe.values())
    base = {c: atual[c] - vendas_classe[c] for c in CLASSES}
    total_final = sum(base.values()) + caixa
    alvo_val = {c: cfg[c]["alvo"] / 100 * total_final for c in CLASSES}
    por_classe = _water_fill(base, alvo_val, caixa)

    # ---- ativos
    operacoes: list[dict] = []
    sobra_total = 0.0
    sem_ativo: list[str] = []
    sem_candidato: list[str] = []
    por_ticker = defaultdict(list)
    for a in ativos:
        if a.get("manual") or a.get("preco_atual") in (None, 0):
            continue
        por_ticker[a["classe"]].append({
            "ticker": a["ticker"], "nome": a.get("nome", ""), "classe": a["classe"], "preco": a["preco_atual"],
            "valor_atual": a["valor_atual"], "qtd": a["qtd"] or 0.0,
        })
    for c in CLASSES:
        itens = por_ticker.get(c, [])
        frac = c == "RF"
        if vendas_classe[c] > EPS:
            operacoes += _sell_units(itens, vendas_classe[c], frac)
        if por_classe[c] > EPS:
            if not itens:
                sem_ativo.append(c)
                sobra_total += por_classe[c]
                continue
            cands = _candidatos(c, itens, scores or {}, novos, max_ativos, novos_por_classe)
            if cands:
                compras, sobra = _buy_by_score(cands, por_classe[c], frac)
                for cc in cands:
                    if cc["novo"]:
                        por_ticker[c].append(cc)  # entra na 2ª passada de sobras
            elif cands is None:
                compras, sobra = _whole_units(itens, por_classe[c], frac)
            else:
                compras, sobra = [], por_classe[c]
                sem_candidato.append(c)
            operacoes += compras
            sobra_total += sobra

    # ---- antes/depois (com as quantidades arredondadas)
    depois = dict(atual)
    for op in operacoes:
        depois[op["classe"]] += op["valor"] if op["acao"] == "COMPRAR" else -op["valor"]

    # ---- 2ª passada: a sobra de arredondamento vai, uma unidade por vez, para a classe mais abaixo do alvo
    vendendo = {c for c in CLASSES if vendas_classe[c] > EPS}
    compras_idx = {(o["ticker"]): o for o in operacoes if o["acao"] == "COMPRAR"}
    while sobra_total > EPS:
        cands = []
        for c in CLASSES:
            if c in vendendo:
                continue
            for i in por_ticker.get(c, []):
                sc = (scores or {}).get(i["ticker"])
                if scores and (not sc or sc["forca"] not in ("ALTA", "MEDIA") or sc.get("vence_em_breve")):
                    continue
                passo = 0.01 if c == "RF" else 1.0
                if i["preco"] * passo <= sobra_total + 1e-9:
                    cands.append((depois[c] / alvo_val[c] if alvo_val[c] else 9e9, i["valor_atual"], i, passo))
        if not cands:
            break
        _, _, i, passo = min(cands, key=lambda x: (x[0], x[1]))
        custo = i["preco"] * passo
        op = compras_idx.get(i["ticker"])
        if not op:
            op = {"ticker": i["ticker"], "nome": i.get("nome", ""), "classe": i["classe"], "acao": "COMPRAR", "qtd": 0.0,
                  "preco": round(i["preco"], 2), "valor": 0.0, "motivo": "aproveitar sobra do aporte"}
            compras_idx[i["ticker"]] = op
            operacoes.append(op)
        op["qtd"] = round(op["qtd"] + passo, 2)
        op["valor"] = round(op["qtd"] * i["preco"], 2)
        depois[i["classe"]] += custo
        sobra_total -= custo
    total_depois = sum(depois.values())
    classes = []
    for c in CLASSES:
        comprado = sum(o["valor"] for o in operacoes if o["classe"] == c and o["acao"] == "COMPRAR")
        vendido = sum(o["valor"] for o in operacoes if o["classe"] == c and o["acao"] == "VENDER")
        classes.append({
            "classe": c,
            "alvo": cfg[c]["alvo"], "min": cfg[c]["min"], "max": cfg[c]["max"],
            "antes": round(atual[c], 2),
            "antes_pct": round(100 * atual[c] / total, 2) if total else 0.0,
            "sugerido": round(por_classe[c], 2),
            "comprar": round(comprado, 2),
            "vender": round(vendido, 2),
            "depois": round(depois[c], 2),
            "depois_pct": round(100 * depois[c] / total_depois, 2) if total_depois else 0.0,
        })

    avisos = []
    if any(vendas_classe.values()):
        avisos.append(
            "Vendas: ações têm isenção de IR para vendas até R$ 20 mil/mês; FIIs pagam 20% sobre o lucro. "
            "Confira o preço médio antes de vender."
        )
    for c in sem_ativo:
        avisos.append(f"Você ainda não tem ativos em {c}; o valor sugerido para a classe ficou como sobra. "
                      "As oportunidades da Fase 5 vão sugerir onde comprar.")
    for c in sem_candidato:
        avisos.append(f"Nenhum candidato com força Alta/Média em {c}: o valor da classe ficou como sobra. "
                      "Veja a tela de Oportunidades.")
    if scores:
        avisos.append(f"Dentro de cada classe: até {max_ativos} ativos, priorizando força Alta e depois o score "
                      "(seus ativos Alta/Média" + (" + melhores oportunidades novas" if novos else "") + ").")
    else:
        avisos.append("Sem scores disponíveis agora: dentro de cada classe a sugestão mantém a composição atual.")

    return {
        "simulacao": True,
        "aporte": round(aporte, 2),
        "vendas": round(sum(o["valor"] for o in operacoes if o["acao"] == "VENDER"), 2),
        "total_antes": round(total, 2),
        "total_depois": round(total_depois, 2),
        "sobra": round(sobra_total, 2),
        "classes": classes,
        "operacoes": sorted(operacoes, key=lambda o: (o["acao"] != "VENDER", CLASSES.index(o["classe"]), -o["valor"])),
        "avisos": avisos,
    }
