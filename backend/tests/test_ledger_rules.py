"""Regras do ledger com cenários sintéticos."""
from datetime import date

import pytest

from app.importers.common import RawRow
from app.portfolio.ledger import run_ledger


def row(d, es, mov, produto, qtd, preco=None, valor=None, source="movimentacao", inst="XP"):
    return RawRow(source, date.fromisoformat(d), es, mov, produto, inst, qtd, preco, valor)


LIQ = "Transferência - Liquidação"


def test_preco_medio_com_venda_parcial():
    res = run_ledger([
        row("2024-01-02", "C", LIQ, "ABCD3 - ABC", 10, 10.0, 100.0),
        row("2024-02-02", "C", LIQ, "ABCD3 - ABC", 10, 20.0, 200.0),
        row("2024-03-02", "D", LIQ, "ABCD3 - ABC", 5, 30.0, 150.0),
    ])
    p = res.positions["ABCD3"]
    assert p.qtd == 15
    assert p.preco_medio == pytest.approx(15.0)
    assert p.lucro_realizado == pytest.approx(150 - 75)


def test_desdobro_mantem_custo():
    res = run_ledger([
        row("2024-01-02", "C", LIQ, "ABCD3 - ABC", 10, 40.0, 400.0),
        row("2024-04-17", "C", "Desdobro", "ABCD3 - ABC", 10),
    ])
    p = res.positions["ABCD3"]
    assert p.qtd == 20 and p.custo_total == pytest.approx(400) and p.preco_medio == pytest.approx(20)


def test_bonificacao_fracao_e_leilao():
    res = run_ledger([
        row("2024-01-02", "C", LIQ, "ITSA4 - ITAUSA", 100, 10.0, 1000.0),
        row("2024-12-04", "C", "Bonificação em Ativos", "ITSA4 - ITAUSA", 5.5),
        row("2025-01-06", "D", "Fração em Ativos", "ITSA4 - ITAUSA", 0.5),
        row("2025-01-28", "C", "Leilão de Fração", "ITSA4 - ITAUSA", 0.5, 9.0, 4.5),
    ])
    p = res.positions["ITSA4"]
    assert p.qtd == pytest.approx(105)
    assert any(w["codigo"] == "BONIFICACAO_SEM_CUSTO" for w in res.warnings)
    # PM após bonificação = 1000/105.5; fração vendida a 9,00 -> pequeno prejuízo
    assert p.lucro_realizado == pytest.approx(4.5 - 0.5 * 1000 / 105.5)


def test_aluguel_nao_altera_posicao():
    res = run_ledger([
        row("2025-01-02", "C", LIQ, "WEGE3 - WEG", 26, 30.0, 780.0),
        row("2025-10-28", "C", "Empréstimo", "WEGE3 - WEG", 26),
        row("2025-10-28", "D", LIQ, "WEGE3 - WEG", 26),
        row("2025-11-25", "C", "Empréstimo", "WEGE3 - WEG", 26, None, 0.05),
        row("2025-11-26", "C", LIQ, "WEGE3 - WEG", 26, 42.96, 1116.96),
    ])
    p = res.positions["WEGE3"]
    assert p.qtd == 26 and p.custo_total == pytest.approx(780)
    assert [i["tipo"] for i in res.income] == ["ALUGUEL"]


def test_devolucao_de_aluguel_com_ticker_novo_converte():
    res = run_ledger([
        row("2023-04-25", "C", LIQ, "CPLE6 - COPEL", 100, 8.0, 800.0),
        row("2025-11-11", "C", "Atualização", "CPLE5 - COPEL", 100),
        row("2025-11-12", "C", "Empréstimo", "CPLE5 - COPEL", 100),
        row("2025-11-12", "D", LIQ, "CPLE5 - COPEL", 100),
        row("2025-12-26", "C", "Empréstimo", "CPLE3 - COPEL", 100, None, 0.10),
        row("2025-12-29", "C", LIQ, "CPLE3 - COPEL", 100, 13.0, 1300.0),
    ])
    assert res.positions["CPLE3"].qtd == 100
    assert res.positions["CPLE3"].custo_total == pytest.approx(800.0)
    assert res.positions["CPLE6"].qtd == 0 and res.positions["CPLE5"].qtd == 0


def test_subscricao_convertida_via_atualizacao():
    res = run_ledger([
        row("2024-01-02", "C", LIQ, "ITSA4 - ITAUSA", 100, 10.0, 1000.0),
        row("2025-04-17", "D", "Direitos de Subscrição - Exercido", "ITSA2 - ITAUSA", 3, 6.7, 20.1),
        row("2025-04-22", "C", "Recibo de Subscrição", "ITSA10 - ITAUSA", 3),
        row("2025-05-28", "C", "Atualização", "ITSA4 - ITAUSA", 3),
    ])
    p = res.positions["ITSA4"]
    assert p.qtd == 103 and p.custo_total == pytest.approx(1020.1)
    assert res.reconciliation[-1]["status"] == "SUBSCRICAO_CONVERTIDA"


def test_atualizacao_divergente_gera_aviso():
    res = run_ledger([
        row("2024-01-02", "C", LIQ, "BBAS3 - BB", 10, 20.0, 200.0),
        row("2024-05-01", "C", "Atualização", "BBAS3 - BB", 12),
    ])
    assert res.reconciliation[-1]["status"] == "DIVERGENTE"
    assert any(w["codigo"] == "DIVERGENCIA_B3" for w in res.warnings)


def test_negociacao_substitui_liquidacao():
    res = run_ledger([
        row("2024-01-04", "C", LIQ, "ABCD3 - ABC", 10, 10.0, 100.0),
        row("2024-01-02", "C", "Negociação - Compra", "ABCD3F", 4, 10.0, 40.0, source="negociacao"),
        row("2024-01-02", "C", "Negociação - Compra", "ABCD3", 6, 10.0, 60.0, source="negociacao"),
    ])
    assert res.positions["ABCD3"].qtd == 10


def test_tesouro_compra_venda_e_taxa():
    res = run_ledger([
        row("2022-03-21", "C", "Compra", "Tesouro Prefixado 2025", 1.38, 722.58, 997.16),
        row("2024-01-01", "D", "Cobrança de Taxa Semestral", "Tesouro Prefixado 2025", 0, None, 11.2),
        row("2025-01-02", "D", "Resgate", "Tesouro Prefixado 2025", 1.38, 1000, 1380),
    ])
    p = res.positions["Tesouro Prefixado 2025"]
    assert p.classe == "RF" and not p.is_open()
    assert p.lucro_realizado == pytest.approx(1380 - 997.16 - 11.2)


def test_proventos_classificados():
    res = run_ledger([
        row("2024-01-02", "C", LIQ, "XPML11 - XP MALLS", 10, 100.0, 1000.0),
        row("2024-02-15", "C", "Rendimento", "XPML11 - XP MALLS", 10, 0.9, 9.0),
        row("2024-02-15", "C", "Rendimento - Transferido", "XPML11 - XP MALLS", 10, 0.9, 9.0),
    ])
    assert [(i["tipo"], i["valor"], i["classe"]) for i in res.income] == [("RENDIMENTO", 9.0, "FII")]


def test_snapshots_fim_de_mes():
    res = run_ledger(
        [
            row("2024-01-10", "C", LIQ, "ABCD3 - ABC", 10, 10.0, 100.0),
            row("2024-02-05", "C", LIQ, "ABCD3 - ABC", 10, 12.0, 120.0),
            row("2024-03-15", "D", LIQ, "ABCD3 - ABC", 20, 15.0, 300.0),
        ],
        snapshot_dates=[date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)],
    )
    assert res.snapshots[date(2024, 1, 31)]["ABCD3"][:2] == (10, 100.0)
    assert res.snapshots[date(2024, 2, 29)]["ABCD3"][:2] == (20, 220.0)
    assert res.snapshots[date(2024, 3, 31)] == {}
