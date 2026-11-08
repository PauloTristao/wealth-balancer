"""Parsers dos relatórios da Área do Investidor B3: Movimentação e Negociação."""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.importers.common import (
    RawRow,
    assign_hashes,
    norm_inst,
    norm_text,
    parse_date,
    parse_num,
    read_table,
)

MOV_COLS = {
    "entrada/saida": "es",
    "data": "data",
    "movimentacao": "mov",
    "produto": "produto",
    "instituicao": "inst",
    "quantidade": "qtd",
    "preco unitario": "preco",
    "valor da operacao": "valor",
}

NEG_COLS = {
    "data do negocio": "data",
    "tipo de movimentacao": "tipo",
    "mercado": "mercado",
    "prazo/vencimento": "prazo",
    "instituicao": "inst",
    "codigo de negociacao": "ticker",
    "quantidade": "qtd",
    "preco": "preco",
    "valor": "valor",
}


class UnknownReportError(ValueError):
    pass


def detect_kind(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    if {"entrada/saida", "movimentacao", "produto"} <= cols:
        return "movimentacao"
    if {"data do negocio", "codigo de negociacao"} <= cols:
        return "negociacao"
    raise UnknownReportError(
        "Arquivo não reconhecido. Esperado relatório de Movimentação ou Negociação da B3. "
        f"Colunas encontradas: {sorted(cols)}"
    )


def _parse_movimentacao(df: pd.DataFrame) -> list[RawRow]:
    df = df.rename(columns=MOV_COLS)
    rows: list[RawRow] = []
    for rec in df.to_dict("records"):
        es_txt = norm_text(rec.get("es"))
        if not es_txt:
            continue
        rows.append(
            RawRow(
                source="movimentacao",
                data=parse_date(rec["data"]),
                es="C" if es_txt.startswith("c") else "D",
                mov=" ".join(str(rec["mov"]).split()),
                produto=" ".join(str(rec["produto"]).split()),
                instituicao=norm_inst(rec.get("inst")),
                qtd=parse_num(rec.get("qtd")) or 0.0,
                preco=parse_num(rec.get("preco")),
                valor=parse_num(rec.get("valor")),
            )
        )
    return rows


def _parse_negociacao(df: pd.DataFrame) -> list[RawRow]:
    df = df.rename(columns=NEG_COLS)
    rows: list[RawRow] = []
    for rec in df.to_dict("records"):
        tipo = norm_text(rec.get("tipo"))
        if tipo not in ("compra", "venda"):
            continue
        mercado = norm_text(rec.get("mercado"))
        rows.append(
            RawRow(
                source="negociacao",
                data=parse_date(rec["data"]),
                es="C" if tipo == "compra" else "D",
                mov=f"Negociação - {'Compra' if tipo == 'compra' else 'Venda'}"
                + (f" ({mercado})" if mercado else ""),
                produto=str(rec["ticker"]).strip().upper(),
                instituicao=norm_inst(rec.get("inst")),
                qtd=parse_num(rec.get("qtd")) or 0.0,
                preco=parse_num(rec.get("preco")),
                valor=parse_num(rec.get("valor")),
            )
        )
    return rows


def parse_report(src: str | Path | bytes | BinaryIO) -> tuple[str, list[RawRow]]:
    df = read_table(src)
    kind = detect_kind(df)
    rows = _parse_movimentacao(df) if kind == "movimentacao" else _parse_negociacao(df)
    return kind, assign_hashes(rows)
