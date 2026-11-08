import pytest

from app.recommend.rebalance import simulate

CFG = {c: {"alvo": 25, "min": 15, "max": 35} for c in ("ACAO", "FII", "RF", "INTL")}


def at(ticker, classe, qtd, preco):
    return {"ticker": ticker, "classe": classe, "qtd": qtd, "preco_atual": preco, "valor_atual": qtd * preco,
            "manual": False, "nome": ticker}


DASH = {"ativos": [
    at("AAAA3", "ACAO", 100, 30.0),     # 3000
    at("FFFF11", "FII", 10, 100.0),     # 1000
    at("Tesouro Selic 2029", "RF", 0.25, 16000.0),  # 4000
    at("IVVB11", "INTL", 4, 500.0),     # 2000
]}


def test_aporte_vai_para_classes_abaixo_do_alvo():
    r = simulate(DASH, 2000, CFG)
    by = {c["classe"]: c for c in r["classes"]}
    # total final 12000 -> alvo 3000 por classe. Falta: FII 2000, INTL 1000. Aporte 2000: nível de água
    assert by["RF"]["comprar"] == 0 and by["ACAO"]["comprar"] == 0
    assert by["FII"]["sugerido"] == pytest.approx(1500)
    assert by["INTL"]["sugerido"] == pytest.approx(500)
    assert r["vendas"] == 0
    assert r["sobra"] < 500  # IVVB11 custa 500: cabe 1 cota


def test_unidades_inteiras_e_tesouro_fracionado():
    r = simulate(DASH, 2000, CFG)
    for op in r["operacoes"]:
        if not op["ticker"].startswith("Tesouro"):
            assert op["qtd"] == int(op["qtd"])
    assert sum(o["valor"] for o in r["operacoes"]) + r["sobra"] == pytest.approx(2000, abs=0.05)


def test_vendas_opcionais_reduzem_classe_acima_da_faixa():
    dash = {"ativos": [at("AAAA3", "ACAO", 100, 10.0), at("FFFF11", "FII", 10, 100.0),
                       at("Tesouro Selic 2029", "RF", 0.5, 16000.0), at("IVVB11", "INTL", 2, 500.0)]}
    # RF = 8000 de 11000 (72%)
    sem = simulate(dash, 0, CFG)
    assert sem["operacoes"] == []
    com = simulate(dash, 0, CFG, permitir_vendas=True)
    by = {c["classe"]: c for c in com["classes"]}
    assert by["RF"]["vender"] > 0
    assert by["RF"]["depois_pct"] <= 35.5
    assert all(o["acao"] == "COMPRAR" for o in com["operacoes"] if o["classe"] != "RF")


def test_nada_e_gravado():
    r = simulate(DASH, 1000, CFG)
    assert r["simulacao"] is True
