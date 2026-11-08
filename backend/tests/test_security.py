"""Testes da camada de segurança: allowlists (unitário, 100% dos branches) e integração pela API."""
import io
import math

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import security as sec
from app.db import Base, get_session, make_engine
from app.main import app


# ======================================================================== unitários
class TestClasseOportunidade:
    @pytest.mark.parametrize("raw,esperado", [("ACAO", "ACAO"), (" fii ", "FII"), ("intl", "INTL"), ("Rf", "RF")])
    def test_validas(self, raw, esperado):
        assert sec.classe_oportunidade(raw) == esperado

    @pytest.mark.parametrize("raw", ["", "   ", "OUTROS", "ACAO;DROP TABLE", "../RF", "A" * 5_000], ids=lambda v: repr(v)[:30])
    def test_invalidas(self, raw):
        with pytest.raises(sec.InvalidInput):
            sec.classe_oportunidade(raw)


class TestTicker:
    @pytest.mark.parametrize("raw,esperado", [
        ("PETR4", "PETR4"), ("taee11", "TAEE11"), (" ROXO34 ", "ROXO34"), ("ITSA4F", "ITSA4F"),
        ("Tesouro Selic 2029", "Tesouro Selic 2029"),
        ("Tesouro  IPCA+ com Juros Semestrais   2035", "Tesouro IPCA+ com Juros Semestrais 2035"),
        ("Tesouro Renda+ Aposentadoria Extra 2065", "Tesouro Renda+ Aposentadoria Extra 2065"),
    ])
    def test_validos(self, raw, esperado):
        assert sec.ticker(raw) == esperado

    @pytest.mark.parametrize("raw", [
        "", "   ", "PETR", "PET4", "PETR444", "PETR4X", "1234", "PETR4; DROP TABLE x",
        "<script>alert(1)</script>", "../../etc/passwd", "PETR4\x00", "Tesouro", "Tesouro <b>2029</b>",
        "Tesouro " + "A" * 61, "tesouro selic 2029'--", "A" * 5_000,
    ])
    def test_invalidos(self, raw):
        with pytest.raises(sec.InvalidInput):
            sec.ticker(raw)


class TestNomeBusca:
    def test_none(self):
        assert sec.nome_busca(None) is None

    @pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
    def test_vazio_vira_none(self, raw):
        assert sec.nome_busca(raw) is None

    @pytest.mark.parametrize("raw,esperado", [
        ("Itaúsa", "Itaúsa"), ("Johnson & Johnson", "Johnson & Johnson"), ("  Nu   Holdings ", "Nu Holdings"),
        ("BANCO DO BRASIL S.A.", "BANCO DO BRASIL S.A."),
    ])
    def test_validos(self, raw, esperado):
        assert sec.nome_busca(raw) == esperado

    @pytest.mark.parametrize("raw", ['" OR 1=1', "<img src=x onerror=alert(1)>", "a" * 81, "nome\x00", "x;rm -rf"])
    def test_invalidos(self, raw):
        with pytest.raises(sec.InvalidInput):
            sec.nome_busca(raw)


class TestUpload:
    @pytest.mark.parametrize("nome", ["m.xlsx", "M.XLSX", "dados.csv", "velho.xls", "C:\\Users\\x\\m.xlsx"])
    def test_permitido(self, nome):
        assert sec.upload_permitido(nome)

    @pytest.mark.parametrize("nome", [None, "", "foto.png", "m.xlsx.exe", "xlsx", "m.", ".xlsx/evil.sh"])
    def test_nao_permitido(self, nome):
        assert not sec.upload_permitido(nome)

    @pytest.mark.parametrize("nome,esperado", [
        ("movimentacao-2025-01.xlsx", "movimentacao-2025-01.xlsx"),
        ("../../../etc/passwd.xlsx", "passwd.xlsx"),
        ("C:\\Windows\\System32\\x.CSV", "x.csv"),
        ("meu extrato (1).xlsx", "meu_extrato__1_.xlsx"),
        ("..xlsx", "arquivo.xlsx"),
        (".oculto.xlsx", "oculto.xlsx"),
        ("<script>.xlsx", "_script_.xlsx"),
        ("ação.xlsx", "a__o.xlsx"),
        ("a" * 500 + ".xlsx", "a" * sec.MAX_FILENAME_STEM + ".xlsx"),
    ])
    def test_nome_seguro(self, nome, esperado):
        assert sec.nome_arquivo_seguro(nome) == esperado

    @pytest.mark.parametrize("nome", ["", "foto.png", "x.xlsx.sh", "semextensao", "../"])
    def test_nome_seguro_rejeita_extensao(self, nome):
        with pytest.raises(sec.InvalidInput):
            sec.nome_arquivo_seguro(nome)


class TestUrlHttpSegura:
    @pytest.mark.parametrize("url", ["https://news.google.com/a?b=1", "http://exemplo.com", "HTTPS://X.COM/p"])
    def test_validas(self, url):
        assert sec.url_http_segura(url) == url

    def test_remove_espacos(self):
        assert sec.url_http_segura("  https://x.com  ") == "https://x.com"

    @pytest.mark.parametrize("url", [
        None, "", "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>", "file:///etc/passwd",
        "ftp://x.com", "https://", "//x.com/sem-esquema", "https:///sem-host", "https://x.com/\x00",
        "https://x.com/\nSet-Cookie:a", "http://[::1", "https://x.com/" + "a" * sec.MAX_URL_LEN,
    ])
    def test_invalidas(self, url):
        assert sec.url_http_segura(url) == ""


class TestOrigem:
    @pytest.mark.parametrize("method", ["GET", "get", "HEAD", "OPTIONS"])
    def test_leitura_sempre_passa(self, method):
        assert sec.origem_permitida(method, "https://evil.example")

    def test_escrita_sem_origin_passa(self):  # curl / linha de comando
        assert sec.origem_permitida("POST", None)

    @pytest.mark.parametrize("origin", sorted(sec.ALLOWED_ORIGINS))
    def test_escrita_do_site_local_passa(self, origin):
        assert sec.origem_permitida("DELETE", origin)

    @pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:5174", "null", "",
                                        "http://localhost:5173.evil.com"])
    def test_escrita_de_outra_origem_bloqueada(self, origin):
        assert not sec.origem_permitida("POST", origin)


# ======================================================================== integração (API)
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mov_xlsx() -> bytes:
    df = pd.DataFrame([["Credito", "05/03/2025", "Transferência - Liquidação", "ABCD3 - EXEMPLO", "CORRETORA", 10, 1.0, 10.0]],
                      columns=["Entrada/Saída", "Data", "Movimentação", "Produto", "Instituição", "Quantidade",
                               "Preço unitário", "Valor da Operação"])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_upload_nome_malicioso_e_arquivado_com_nome_seguro(client, tmp_path):
    r = client.post("/api/imports", files=[("files", ("../../fora.xlsx", _mov_xlsx()))]).json()["resultados"][0]
    assert r["arquivo"] == "fora.xlsx" and r["novas"] == 1
    arquivados = list((tmp_path / "imports").rglob("*"))
    assert all(tmp_path / "imports" in p.parents for p in arquivados)
    assert not (tmp_path.parent / "fora.xlsx").exists()


def test_upload_vazio(client):
    r = client.post("/api/imports", files=[("files", ("m.xlsx", b""))]).json()["resultados"][0]
    assert r["erro"] == "Arquivo vazio."


def test_upload_grande_demais(client, monkeypatch):
    monkeypatch.setattr(sec, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/imports", files=[("files", ("m.xlsx", b"x" * 11))]).json()["resultados"][0]
    assert "grande demais" in r["erro"]


def test_upload_corrompido_nao_expoe_detalhes(client):
    r = client.post("/api/imports", files=[("files", ("m.xlsx", b"PK\x03\x04lixo"))]).json()["resultados"][0]
    assert r["erro"] == "Não foi possível ler o arquivo. Confira se é o export da B3."


@pytest.mark.parametrize("url", ["/api/news/%3Cscript%3E", "/api/news/PETR4?nome=%3Cimg%3E",
                                 "/api/insight/ACAO/..x", "/api/insight/XXX/PETR4",
                                 "/api/opportunities/OUTROS", "/api/trades?ticker=%27%20OR%201%3D1"])
def test_parametros_fora_da_allowlist_retornam_422(client, url):
    r = client.get(url)
    assert r.status_code == 422
    assert "Traceback" not in r.text


def test_path_traversal_codificado_nao_casa_nenhuma_rota(client):
    assert client.get("/api/insight/ACAO/..%2F..%2Fx").status_code == 404


def test_insight_post_valida_antes_de_chamar_ia(client):
    r = client.post("/api/insight/ACAO/%3Cscript%3E")
    assert r.status_code == 422


def test_falha_de_noticias_nao_expoe_excecao(client, monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("segredo interno: /caminho/do/servidor")

    monkeypatch.setattr("app.main.get_news", explode)
    r = client.get("/api/news/PETR4")
    assert r.status_code == 502
    assert "segredo" not in r.text and "caminho" not in r.text


def test_noticias_ok_com_parametros_validos(client, monkeypatch):
    chamada = {}

    def fake(_s, ticker, nome):
        chamada.update(ticker=ticker, nome=nome)
        return {"itens": []}

    monkeypatch.setattr("app.main.get_news", fake)
    assert client.get("/api/news/petr4?nome=%20Petrobras%20").status_code == 200
    assert chamada == {"ticker": "PETR4", "nome": "Petrobras"}


MANUAL_OK = {"nome": "Reserva", "classe": "RF", "valor_aplicado": 1000, "valor_atual": 1010,
             "reserva_emergencia": True}


@pytest.mark.parametrize("campo,valor", [
    ("classe", "CRIPTO"), ("nome", ""), ("nome", "x" * 81), ("valor_atual", -1), ("valor_aplicado", 1e13),
    ("valor_atual", "abc"), ("obs", "o" * 501), ("data_ref", "2025-13-40"),
])
def test_posicao_manual_invalida(client, campo, valor):
    r = client.post("/api/manual-positions", json={**MANUAL_OK, campo: valor})
    assert r.status_code == 422


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity"])
def test_posicao_manual_rejeita_nan_inf(client, valor):
    corpo = '{"nome":"R","classe":"RF","valor_atual":%s}' % valor
    r = client.post("/api/manual-positions", content=corpo, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_posicao_manual_crud_e_campos_extras_ignorados(client):
    criada = client.post("/api/manual-positions", json={**MANUAL_OK, "nome": "  Reserva  "}).json()
    assert criada["nome"] == "Reserva" and criada["reserva_emergencia"] is True
    mid = criada["id"]
    # o site reenvia "id"; campos desconhecidos são descartados (não sobrescrevem nada)
    r = client.put(f"/api/manual-positions/{mid}", json={**MANUAL_OK, "id": 999, "admin": True, "valor_atual": 2000})
    assert r.status_code == 200 and r.json()["id"] == mid and r.json()["valor_atual"] == 2000
    assert client.put("/api/manual-positions/424242", json=MANUAL_OK).status_code == 404
    assert client.delete(f"/api/manual-positions/{mid}").json() == {"ok": True}
    assert client.delete(f"/api/manual-positions/{mid}").status_code == 404
    assert client.put("/api/manual-positions/abc", json=MANUAL_OK).status_code == 422


def test_valores_extremos_validos(client):
    r = client.post("/api/manual-positions", json={**MANUAL_OK, "valor_aplicado": 0, "valor_atual": 1e12})
    assert r.status_code == 200 and math.isclose(r.json()["valor_atual"], 1e12)
