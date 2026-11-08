import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, make_engine
from app.market.news import parse_rss
from app.recommend import insights

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>BB (BBAS3) cai 3% - Money Times</title><link>https://x/1</link>
<pubDate>Fri, 06 Nov 2026 12:00:00 GMT</pubDate><source url="https://moneytimes.com.br">Money Times</source></item>
<item><title>BB (BBAS3) cai 3% - Outro</title><link>https://x/2</link>
<pubDate>Fri, 06 Nov 2026 11:00:00 GMT</pubDate><source url="https://o">Outro</source></item>
<item><title>Noticia antiga</title><link>https://x/3</link>
<pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate><source url="https://o">Velho</source></item>
</channel></rss>"""


def test_parse_rss_limpa_fonte_dedup_e_janela():
    itens = parse_rss(RSS, hoje=datetime(2026, 11, 8, tzinfo=timezone.utc))
    assert len(itens) == 1
    assert itens[0]["titulo"] == "BB (BBAS3) cai 3%"
    assert itens[0]["fonte"] == "Money Times" and itens[0]["data"] == "2026-11-06"


@pytest.fixture
def session():
    eng = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


OP = {"ticker": "BBAS3", "nome": "", "classe": "ACAO", "score": 48.1, "forca": "BAIXA", "pilares": {},
      "indicadores": {"p_vp": 0.54}, "alertas": [], "criterios": [{"nome": "ROE", "valor": 8.0, "pontos": 0.3,
                                                                   "explicacao": "x", "pilar": "qualidade", "fmt": "%"}]}


def test_sem_chave_da_erro_claro(session, monkeypatch):
    monkeypatch.setattr(insights, "configured", lambda: False)
    with pytest.raises(insights.InsightError, match="ANTHROPIC_API_KEY"):
        insights.generate(session, OP, [])


def test_generate_monta_requisicao_e_guarda_cache(session, monkeypatch):
    chamadas = {}
    resposta = {"resumo_noticias": "x", "pontos_positivos": [], "riscos": ["r"], "leitura_filosofia": "y",
                "veredito": "Manter", "confianca": "média", "noticias_relevantes": []}

    class FakeMessages:
        def create(self, **kw):
            chamadas.update(kw)
            return SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                                   content=[SimpleNamespace(type="text", text=json.dumps(resposta))],
                                   usage=SimpleNamespace(input_tokens=100, output_tokens=50))

    fake = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    import anthropic

    monkeypatch.setattr(insights, "configured", lambda: True)
    monkeypatch.setattr(anthropic, "Anthropic", lambda: fake)
    out = insights.generate(session, OP, [{"data": "2026-11-06", "fonte": "MT", "titulo": "BB cai"}])
    assert out["analise"]["veredito"] == "Manter"
    assert chamadas["model"] == "claude-sonnet-5-5"
    assert chamadas["fallbacks"] == "default"
    assert chamadas["output_config"]["format"]["type"] == "json_schema"
    assert "BB cai" in chamadas["messages"][0]["content"]
    assert insights.cached(session, "BBAS3")["analise"]["veredito"] == "Manter"


def test_recusa_vira_erro(session, monkeypatch):
    class FakeMessages:
        def create(self, **kw):
            return SimpleNamespace(stop_reason="refusal", content=[], model=kw["model"],
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=0))

    import anthropic

    monkeypatch.setattr(insights, "configured", lambda: True)
    monkeypatch.setattr(anthropic, "Anthropic", lambda: SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())))
    with pytest.raises(insights.InsightError, match="recusa"):
        insights.generate(session, OP, [])
