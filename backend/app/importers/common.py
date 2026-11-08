"""Utilidades comuns aos parsers de relatórios da B3."""
from __future__ import annotations

import hashlib
import io
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import BinaryIO

import pandas as pd


@dataclass
class RawRow:
    source: str            # "movimentacao" | "negociacao"
    data: date
    es: str                # "C" (crédito/entrada/compra) | "D" (débito/saída/venda)
    mov: str               # tipo de movimentação (texto original da B3)
    produto: str
    instituicao: str
    qtd: float
    preco: float | None
    valor: float | None
    row_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def norm_text(s: object) -> str:
    """Minúsculas, sem acento, espaços colapsados."""
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def norm_inst(s: object) -> str:
    s = " ".join(str(s or "").split())
    return s.rstrip(".").strip()


def parse_num(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return None
        return float(v)
    s = str(v).strip()
    if s in ("", "-", "nan", "None"):
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s:  # formato brasileiro 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(v: object) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, pd.Timestamp):
        return v.date()
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {v!r}")


def read_table(src: str | Path | bytes | BinaryIO) -> pd.DataFrame:
    if isinstance(src, bytes):
        src = io.BytesIO(src)
    name = str(getattr(src, "name", src)).lower()
    if name.endswith(".csv"):
        df = pd.read_csv(src, sep=None, engine="python", dtype=str)
    else:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pd.read_excel(src, dtype=object)
    df.columns = [norm_text(c) for c in df.columns]
    return df.dropna(how="all")


def _ticker_key(produto: str) -> str:
    produto = (produto or "").strip()
    if " - " in produto and not produto.lower().startswith("tesouro"):
        produto = produto.split(" - ", 1)[0]
    return norm_text(produto)


def assign_hashes(rows: list[RawRow]) -> list[RawRow]:
    """Hash estável por conteúdo + nº da ocorrência (linhas idênticas legítimas no mesmo arquivo)."""
    seen: dict[str, int] = {}
    for r in rows:
        key = "|".join(
            [
                r.source,
                r.data.isoformat(),
                r.es,
                norm_text(r.mov),
                _ticker_key(r.produto),
                norm_text(r.instituicao),
                f"{r.qtd:.6f}",
                "" if r.preco is None else f"{r.preco:.6f}",
                "" if r.valor is None else f"{r.valor:.2f}",
            ]
        )
        n = seen.get(key, 0)
        seen[key] = n + 1
        r.row_hash = hashlib.sha1(f"{key}#{n}".encode()).hexdigest()
    return rows
