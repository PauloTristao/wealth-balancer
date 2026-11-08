"""Análise com IA (Claude): resume notícias e explica a recomendação à luz da filosofia do investidor.

- Gerada somente sob demanda (botão) e guardada em KV até o usuário gerar de novo — controla custo.
- A IA recebe apenas os indicadores, critérios, alertas, posição e manchetes coletadas
  pelo app, e é instruída a não inventar fatos fora desse material.
- Requer ANTHROPIC_API_KEY (variável de ambiente ou backend/.env).
"""
from __future__ import annotations

import json
import os
from datetime import date

from sqlalchemy.orm import Session

from app.db import KV

MODEL = "claude-sonnet-5-5"

SYSTEM = """Você é um analista que apoia um investidor pessoa física brasileiro de longo prazo.
A filosofia dele:
- Comprar empresas BOAS a um BOM PREÇO — não adianta só uma das duas coisas.
- Preferir boas pagadoras de dividendos, com saúde financeira equilibrada para sustentar a carteira no longo prazo.
- Aproveitar oportunidades ao longo do tempo, sem giro excessivo.
- Ações: P/VP abaixo de 1 (com piso de segurança), P/L entre ~8 e 20, ROE alto, DY bom, dívida líquida saudável, crescimento.
- FIIs: DY, vacância, P/VP, qualidade e diversificação dos imóveis.
- Carteira balanceada em 25% para Ações, FIIs, Renda Fixa e Internacional (faixa de 15% a 35%).

Regras:
- Use SOMENTE os dados e manchetes fornecidos. Não invente números, eventos ou datas. Se as manchetes forem
  insuficientes ou genéricas, diga isso.
- Manchetes são só títulos: não presuma o conteúdo além do que o título diz.
- Seja direto, em português do Brasil, frases curtas. Nada de jargão desnecessário.
- Não prometa retorno. Isto é apoio à decisão, não recomendação formal de investimento.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "resumo_noticias": {"type": "string", "description": "2 a 4 frases sobre o que as manchetes indicam"},
        "pontos_positivos": {"type": "array", "items": {"type": "string"}},
        "riscos": {"type": "array", "items": {"type": "string"}},
        "leitura_filosofia": {"type": "string",
                              "description": "Como o ativo se encaixa (ou não) em 'empresa boa a bom preço' e no papel dele na carteira"},
        "veredito": {"type": "string", "enum": ["Comprar/Reforçar", "Manter", "Aguardar melhor preço", "Evitar/Reavaliar"]},
        "confianca": {"type": "string", "enum": ["baixa", "média", "alta"]},
        "noticias_relevantes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"titulo": {"type": "string"}, "por_que_importa": {"type": "string"}},
                "required": ["titulo", "por_que_importa"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["resumo_noticias", "pontos_positivos", "riscos", "leitura_filosofia", "veredito", "confianca",
                 "noticias_relevantes"],
    "additionalProperties": False,
}


class InsightError(RuntimeError):
    pass


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        from app.settings import BACKEND_DIR

        load_dotenv(BACKEND_DIR / ".env")
    except ImportError:
        pass


def configured() -> bool:
    _load_dotenv()
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _key(ticker: str) -> str:
    return f"insight:{ticker.upper()}"


def cached(session: Session, ticker: str) -> dict | None:
    kv = session.get(KV, _key(ticker))
    return json.loads(kv.valor) if kv and kv.valor else None


def _material(oportunidade: dict, noticias: list[dict], contexto_carteira: dict | None) -> str:
    op = {k: oportunidade.get(k) for k in (
        "ticker", "nome", "classe", "setor", "segmento", "preco", "score", "forca", "pilares", "indicadores",
        "alertas", "motivo_descarte", "possui", "recomendacao_posse", "posicao", "preco_teto_bazin",
        "preco_graham", "margem_seguranca_pct")}
    op["criterios"] = [{k: c[k] for k in ("nome", "valor", "pontos", "explicacao")}
                       for c in oportunidade.get("criterios", [])]
    return json.dumps({
        "data_de_hoje": date.today().isoformat(),
        "ativo_e_indicadores": op,
        "carteira": contexto_carteira or {},
        "manchetes_recentes": [{k: n.get(k) for k in ("data", "fonte", "titulo")} for n in noticias],
    }, ensure_ascii=False, indent=1)


def generate(session: Session, oportunidade: dict, noticias: list[dict],
             contexto_carteira: dict | None = None) -> dict:
    if not configured():
        raise InsightError("ANTHROPIC_API_KEY não configurada. Crie backend/.env com ANTHROPIC_API_KEY=... "
                           "e reinicie a API.")
    import anthropic

    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": (
                "Analise o ativo abaixo para o investidor descrito. Material coletado pelo app:\n\n"
                + _material(oportunidade, noticias, contexto_carteira))}],
        )
    except anthropic.AuthenticationError as exc:
        raise InsightError("Chave da API inválida.") from exc
    except anthropic.RateLimitError as exc:
        raise InsightError("Limite de uso da API atingido; tente de novo em instantes.") from exc
    except anthropic.APIStatusError as exc:
        raise InsightError(f"Erro da API ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise InsightError("Sem conexão com a API da Anthropic.") from exc

    if resp.stop_reason == "refusal":
        raise InsightError("A IA não gerou esta análise (recusa de segurança).")
    if resp.stop_reason == "max_tokens":
        raise InsightError("Resposta da IA veio incompleta; tente novamente.")
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if not texto:
        raise InsightError("Resposta vazia da IA.")
    dados = json.loads(texto)
    out = {
        "dia": date.today().isoformat(),
        "ticker": oportunidade["ticker"],
        "modelo": resp.model,
        "analise": dados,
        "noticias_usadas": len(noticias),
        "tokens": {"entrada": resp.usage.input_tokens, "saida": resp.usage.output_tokens},
    }
    kv = session.get(KV, _key(oportunidade["ticker"])) or KV(chave=_key(oportunidade["ticker"]))
    kv.valor = json.dumps(out, ensure_ascii=False)
    session.merge(kv)
    session.commit()
    return out
