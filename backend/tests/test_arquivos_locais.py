"""Testes opcionais com os SEUS extratos reais da B3 (pulados se não houver arquivos).

Usa os arquivos em data/imports/ (ou na pasta da variável CARTEIRA_TESTE_ARQUIVOS). Nada aqui vai
para o git: os extratos ficam em data/ e as posições esperadas em tests/local/ (ambos ignorados).
"""
import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, make_engine
from app.importers.b3 import parse_report
from app.importers.service import import_file, load_rows
from app.portfolio.ledger import run_ledger

from conftest import LOCAL_EXPECTED


def _importa(files, tmp_path, monkeypatch):
    monkeypatch.setattr("app.importers.service.IMPORTS_DIR", tmp_path)
    eng = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    results = [import_file(s, f.name, f.read_bytes()) for f in files]
    return s, results


def test_parse_hashes_unicos(arquivos_b3):
    for f in arquivos_b3["movimentacao"] + arquivos_b3["negociacao"]:
        _, rows = parse_report(f)
        assert rows, f"{f.name} sem linhas"
        assert len({r.row_hash for r in rows}) == len(rows), f"hash repetido em {f.name}"


def test_importacao_idempotente(arquivos_b3, tmp_path, monkeypatch):
    files = arquivos_b3["movimentacao"]
    s, primeira = _importa(files, tmp_path, monkeypatch)
    segunda = [import_file(s, f.name, f.read_bytes()) for f in files]
    assert sum(r["novas"] for r in primeira) > 0
    assert sum(r["novas"] for r in segunda) == 0


def test_ledger_sem_divergencia(arquivos_b3, tmp_path, monkeypatch):
    s, _ = _importa(arquivos_b3["movimentacao"], tmp_path, monkeypatch)
    res = run_ledger(load_rows(s))
    assert not [r for r in res.reconciliation if r["status"] == "DIVERGENTE"], res.reconciliation
    assert not [w for w in res.warnings if w["codigo"] == "MOV_DESCONHECIDA"], res.warnings


def test_negociacao_nao_duplica_liquidacoes(arquivos_b3, tmp_path, monkeypatch):
    if not arquivos_b3["negociacao"]:
        pytest.skip("sem relatório de Negociação")
    s, _ = _importa(arquivos_b3["movimentacao"], tmp_path / "a", monkeypatch)
    so_mov = {p.ticker: round(p.qtd, 2) for p in run_ledger(load_rows(s)).open_positions()}
    s2, _ = _importa(arquivos_b3["movimentacao"] + arquivos_b3["negociacao"], tmp_path / "b", monkeypatch)
    res = run_ledger(load_rows(s2))
    assert {p.ticker: round(p.qtd, 2) for p in res.open_positions()} == so_mov
    assert not [w for w in res.warnings if w["codigo"] == "VENDA_MAIOR_QUE_POSICAO"]


def test_posicoes_esperadas(arquivos_b3, tmp_path, monkeypatch):
    if not LOCAL_EXPECTED.exists():
        pytest.skip("sem tests/local/posicoes_esperadas.json")
    esperado = json.loads(LOCAL_EXPECTED.read_text(encoding="utf-8"))
    s, _ = _importa(arquivos_b3["movimentacao"], tmp_path, monkeypatch)
    qtd = {p.ticker: round(p.qtd, 2) for p in run_ledger(load_rows(s)).open_positions()}
    assert qtd == esperado
