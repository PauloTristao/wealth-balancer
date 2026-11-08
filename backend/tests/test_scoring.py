from datetime import date

from app.recommend.rebalance import simulate
from app.recommend.scoring import lin, score_acao, score_fii, score_tesouro
from app.settings import estrategia_config

EST = estrategia_config()
FORCA = EST["forca"]


def acao(**kw):
    base = {"ticker": "BOAA3", "price": 20.0, "p_l": 10.0, "p_vp": 0.9, "dy": 8.0, "roe": 18.0,
            "margem_liquida": 15.0, "dividaliquidaebit": 1.0, "receitas_cagr5": 10.0,
            "liquidezmediadiaria": 50_000_000, "vpa": 22.0, "lpa": 2.0, "financeiro": False}
    base.update(kw)
    return score_acao(base, EST["acoes"], FORCA)


def test_lin():
    assert lin(5, 0, 10) == 0.5
    assert lin(15, 0, 10) == 1.0
    assert lin(1.5, 4.5, 2.5) == 1.0   # sentido inverso (menor é melhor)
    assert lin(None, 0, 1) is None


def test_empresa_boa_e_barata_e_alta():
    r = acao()
    assert r["forca"] == "ALTA" and r["score"] >= 90
    assert r["preco_graham"] > 0 and "margem_seguranca_pct" in r


def test_boa_mas_cara_nao_e_alta():
    r = acao(p_vp=3.0, p_l=25.0)
    assert r["forca"] != "ALTA"


def test_barata_mas_ruim_nao_e_alta():
    r = acao(roe=3.0, margem_liquida=1.0, receitas_cagr5=-8.0)
    assert r["forca"] != "ALTA"


def test_regras_duras_limitam_a_media():
    r = acao(p_vp=1.3)
    assert r["forca"] == "MEDIA"
    assert r["alertas"][0].startswith("Limitada a Média")


def test_pvp_abaixo_do_piso_alerta():
    r = acao(p_vp=0.3)
    assert any("piso" in a for a in r["alertas"])


def test_descartes():
    assert acao(liquidezmediadiaria=10_000)["forca"] == "DESCARTADA"
    assert acao(p_l=-3.0)["forca"] == "DESCARTADA"


def test_dy_suspeito_vale_meio_ponto():
    r = acao(dy=25.0)
    dy = next(c for c in r["criterios"] if c["nome"] == "Dividend Yield")
    assert dy["pontos"] == 0.5


def test_banco_sem_divida_e_margem():
    r = acao(financeiro=True, dividaliquidaebit=None, margem_liquida=0.0)
    nomes = {c["nome"] for c in r["criterios"]}
    assert "Margem líquida" not in nomes and "Dív. líq./EBIT" not in nomes
    assert "saude" not in r["pilares"]


def test_fii_tijolo():
    d = {"ticker": "LOGG11", "price": 90.0, "dy": 11.5, "p_vp": 0.84, "liquidezmediadiaria": 5_000_000,
         "patrimonio": 2e9, "qtd_imoveis": 12, "vacancia": 3.0, "ffo_yield": 12.0, "sectorname": "Fundo de Tijolo"}
    r = score_fii(d, EST["fii"], FORCA)
    assert r["forca"] == "ALTA"
    d2 = {**d, "vacancia": 30.0, "qtd_imoveis": 1, "p_vp": 1.2}
    assert score_fii(d2, EST["fii"], FORCA)["forca"] != "ALTA"


def test_tesouro_ipca_e_curto_prazo():
    macro = {"selic": 13.75, "ipca_12m": 5.0}
    off = {"tipo": "Tesouro IPCA+", "vencimento": "2035-05-15", "taxa_compra": 7.5, "pu_compra": 2500.0}
    r = score_tesouro(off, macro, EST["renda_fixa"], hoje=date(2026, 11, 8))
    assert r["forca"] == "ALTA" and r["indicadores"]["juro_real"] == 7.5
    curto = {"tipo": "Tesouro Selic", "vencimento": "2027-03-01", "taxa_compra": 0.02, "pu_compra": 20000.0}
    assert score_tesouro(curto, macro, EST["renda_fixa"], hoje=date(2026, 11, 8)) is None
    r2 = score_tesouro(curto, macro, EST["renda_fixa"], hoje=date(2026, 11, 8), incluir_curto=True)
    assert r2["vence_em_breve"] and r2["forca"] == "MEDIA"


def _at(ticker, classe, qtd, preco):
    return {"ticker": ticker, "classe": classe, "qtd": qtd, "preco_atual": preco, "valor_atual": qtd * preco,
            "manual": False, "nome": ticker}


def test_simulador_usa_score_e_ignora_reavaliar():
    dash = {"ativos": [_at("BOAA3", "ACAO", 100, 10.0), _at("RUIM3", "ACAO", 100, 10.0),
                       _at("FFFF11", "FII", 30, 100.0), _at("Tesouro Selic 2029", "RF", 0.2, 15000.0),
                       _at("IVVB11", "INTL", 6, 500.0)]}
    scores = {
        "BOAA3": {"ticker": "BOAA3", "classe": "ACAO", "forca": "ALTA", "score": 90, "preco": 10.0},
        "RUIM3": {"ticker": "RUIM3", "classe": "ACAO", "forca": "BAIXA", "score": 30, "preco": 10.0},
        "NOVA3": {"ticker": "NOVA3", "classe": "ACAO", "forca": "ALTA", "score": 85, "preco": 20.0},
    }
    cfg = {c: {"alvo": 25, "min": 15, "max": 35} for c in ("ACAO", "FII", "RF", "INTL")}
    r = simulate(dash, 2000, cfg, scores=scores, novos=True)
    tickers = {o["ticker"] for o in r["operacoes"] if o["classe"] == "ACAO"}
    assert "RUIM3" not in tickers
    assert {"BOAA3", "NOVA3"} <= tickers
    r2 = simulate(dash, 2000, cfg, scores=scores, novos=False)
    assert "NOVA3" not in {o["ticker"] for o in r2["operacoes"]}
