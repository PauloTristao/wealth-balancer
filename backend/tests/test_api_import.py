"""Ponta a ponta pela API com planilhas SINTÉTICAS no formato da B3 (nenhum dado real)."""
import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session, make_engine
from app.main import app

MOV = pd.DataFrame([
    # Entrada/Saída, Data, Movimentação, Produto, Instituição, Quantidade, Preço unitário, Valor da Operação
    ["Credito", "05/03/2025", "Transferência - Liquidação", "ABCD3 - EMPRESA EXEMPLO S.A.", "CORRETORA EXEMPLO S/A", 100, 10.0, 1000.0],
    ["Credito", "20/03/2025", "Dividendo", "ABCD3 - EMPRESA EXEMPLO S.A.", "CORRETORA EXEMPLO S/A", 100, 0.5, 50.0],
    ["Credito", "10/04/2025", "Transferência - Liquidação", "FUND11 - FII EXEMPLO", "CORRETORA EXEMPLO S/A", 10, 100.0, 1000.0],
    ["Credito", "15/05/2025", "Rendimento", "FUND11 - FII EXEMPLO", "CORRETORA EXEMPLO S/A", 10, 0.9, 9.0],
    ["Debito", "12/06/2025", "Transferência - Liquidação", "ABCD3 - EMPRESA EXEMPLO S.A.", "CORRETORA EXEMPLO S/A", 40, 12.0, 480.0],
], columns=["Entrada/Saída", "Data", "Movimentação", "Produto", "Instituição", "Quantidade",
            "Preço unitário", "Valor da Operação"])

NEG = pd.DataFrame([
    # pregão 6 dias corridos antes da liquidação (feriado longo)
    ["27/02/2025", "Compra", "Mercado à Vista", "-", "CORRETORA EXEMPLO S/A", "ABCD3", 100, 9.98, 998.0],
    ["08/04/2025", "Compra", "Mercado à Vista", "-", "CORRETORA EXEMPLO S/A", "FUND11", 10, 100.0, 1000.0],
    ["10/06/2025", "Venda", "Mercado à Vista", "-", "CORRETORA EXEMPLO S/A", "ABCD3", 40, 12.0, 480.0],
], columns=["Data do Negócio", "Tipo de Movimentação", "Mercado", "Prazo/Vencimento", "Instituição",
            "Código de Negociação", "Quantidade", "Preço", "Valor"])


def _xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.importers.service.IMPORTS_DIR", tmp_path / "imports")
    eng = make_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)

    def _session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)  # sem "with": não roda o startup (não toca o banco real)
    app.dependency_overrides.clear()


def _post(client, nome, conteudo, **kw):
    return client.post("/api/imports", files=[("files", (nome, conteudo))], **kw)


def test_importa_movimentacao_e_negociacao(client):
    r = _post(client, "movimentacao-exemplo.xlsx", _xlsx(MOV)).json()["resultados"][0]
    assert r["tipo"] == "movimentacao" and r["novas"] == 5
    r = _post(client, "negociacao-exemplo.xlsx", _xlsx(NEG)).json()["resultados"][0]
    assert r["tipo"] == "negociacao" and r["novas"] == 3
    # reimportar não duplica
    assert _post(client, "outro-nome.xlsx", _xlsx(MOV)).json()["resultados"][0]["novas"] == 0

    pf = client.get("/api/portfolio").json()
    qtd = {p["ticker"]: p["qtd"] for p in pf["posicoes"]}
    assert qtd == {"ABCD3": 60, "FUND11": 10}
    pm = {p["ticker"]: p["preco_medio"] for p in pf["posicoes"]}
    assert pm["ABCD3"] == pytest.approx(9.98)  # preço do pregão (Negociação), não da liquidação
    assert pf["proventos_total"] == pytest.approx(59.0)


def test_upload_rejeita_formato_e_arquivo_invalido(client):
    r = _post(client, "foto.png", b"\x89PNG").json()["resultados"][0]
    assert "Formato não suportado" in r["erro"]
    r = _post(client, "quebrado.xlsx", b"isto nao e um xlsx").json()["resultados"][0]
    assert "Não foi possível ler" in r["erro"]
    r = _post(client, "planilha.xlsx", _xlsx(pd.DataFrame({"a": [1]}))).json()["resultados"][0]
    assert "não reconhecido" in r["erro"]


def test_bloqueia_post_de_outro_site(client):
    r = _post(client, "m.xlsx", _xlsx(MOV), headers={"Origin": "https://site-malicioso.example"})
    assert r.status_code == 403
    r = _post(client, "m.xlsx", _xlsx(MOV), headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_bloqueia_host_desconhecido(client):
    assert client.get("/api/imports", headers={"Host": "evil.example"}).status_code == 400
