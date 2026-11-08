from app.market.tesouro import resolve
from app.portfolio.assets import classify, ticker_info


def test_resolve_tesouro():
    assert resolve("Tesouro Selic 2027") == ("Tesouro Selic", 2027)
    assert resolve("Tesouro IPCA+ 2029") == ("Tesouro IPCA+", 2029)
    assert resolve("Tesouro IPCA+ com Juros Semestrais 2035") == ("Tesouro IPCA+ com Juros Semestrais", 2035)
    assert resolve("Tesouro Renda+ Aposentadoria Extra 2065") == ("Tesouro Renda+ Aposentadoria Extra", 2084)


def test_classificacao():
    assert classify("IVVB11") == ("INTL", "ETF")
    assert classify("ROXO34") == ("INTL", "BDR")
    assert classify("XPML11") == ("FII", "FII")
    assert classify("TAEE11") == ("ACAO", "Unit")
    assert ticker_info("XPML12").base == "XPML11"
    assert ticker_info("ITSA10").base == "ITSA4"
    assert ticker_info("ITSA4F").base == "ITSA4"
