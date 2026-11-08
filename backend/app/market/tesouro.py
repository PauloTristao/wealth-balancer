"""Preços e taxas do Tesouro Direto a partir do CSV público do Tesouro Transparente."""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import KV, TesouroPrice

CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
    "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)
KV_KEY = "tesouro_atualizado_em"
MAX_AGE = timedelta(hours=12)

NAME_RE = re.compile(r"^(Tesouro .+?)\s+(\d{4})$")


def parse_csv(content: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(content), sep=";", decimal=",", encoding="latin-1", dtype=str)
    df.columns = ["tipo", "vencimento", "data_base", "taxa_compra", "taxa_venda", "pu_compra", "pu_venda", "pu_base"]
    for c in ("vencimento", "data_base"):
        df[c] = pd.to_datetime(df[c], format="%d/%m/%Y").dt.date
    for c in ("taxa_compra", "taxa_venda", "pu_compra", "pu_venda"):
        df[c] = pd.to_numeric(df[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                              errors="coerce")
    return df.drop(columns=["pu_base"])


def needs_refresh(session: Session) -> bool:
    kv = session.get(KV, KV_KEY)
    if not kv or not kv.valor:
        return True
    return datetime.now() - datetime.fromisoformat(kv.valor) > MAX_AGE


def refresh(session: Session, force: bool = False) -> int:
    if not force and not needs_refresh(session):
        return 0
    r = httpx.get(CSV_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    df = parse_csv(r.content)
    session.execute(delete(TesouroPrice))
    session.bulk_insert_mappings(TesouroPrice, df.to_dict("records"))
    kv = session.get(KV, KV_KEY) or KV(chave=KV_KEY)
    kv.valor = datetime.now().isoformat(timespec="seconds")
    session.merge(kv)
    session.commit()
    return len(df)


def resolve(nome: str) -> tuple[str, int] | None:
    """'Tesouro Selic 2027' -> ('Tesouro Selic', 2027) — ano de vencimento do título."""
    m = NAME_RE.match(nome.strip())
    if not m:
        return None
    tipo, ano = m.group(1), int(m.group(2))
    if tipo.startswith("Tesouro Renda+"):
        return "Tesouro Renda+ Aposentadoria Extra", ano + 19   # nome = ano de início dos pagamentos
    if tipo.startswith("Tesouro Educa+"):
        return "Tesouro Educa+", ano + 4
    return tipo, ano


def price(session: Session, nome: str, em: date | None = None) -> tuple[float, date, float | None] | None:
    """PU de venda (valor de resgate antecipado) mais recente até `em`. Retorna (pu, data_base, taxa)."""
    rv = resolve(nome)
    if not rv:
        return None
    tipo, ano = rv
    q = select(TesouroPrice).where(
        TesouroPrice.tipo == tipo,
        func.strftime("%Y", TesouroPrice.vencimento) == str(ano),
    )
    if em:
        q = q.where(TesouroPrice.data_base <= em)
    row = session.scalars(q.order_by(TesouroPrice.data_base.desc()).limit(1)).first()
    if not row or row.pu_venda is None:
        return None
    return row.pu_venda, row.data_base, row.taxa_venda


class PriceBook:
    """Histórico de PU de venda carregado uma vez por título; consulta por data em memória."""

    def __init__(self, session: Session):
        self.session = session
        self._cache: dict[str, tuple[list[date], list[float]]] = {}

    def _load(self, nome: str) -> tuple[list[date], list[float]]:
        if nome not in self._cache:
            rv = resolve(nome)
            datas: list[date] = []
            pus: list[float] = []
            if rv:
                tipo, ano = rv
                rows = self.session.execute(
                    select(TesouroPrice.data_base, TesouroPrice.pu_venda, TesouroPrice.vencimento)
                    .where(TesouroPrice.tipo == tipo)
                    .order_by(TesouroPrice.data_base)
                ).all()
                for d, pu, venc in rows:
                    if venc.year == ano and pu is not None:
                        datas.append(d)
                        pus.append(pu)
            self._cache[nome] = (datas, pus)
        return self._cache[nome]

    def price(self, nome: str, em: date) -> float | None:
        import bisect

        datas, pus = self._load(nome)
        i = bisect.bisect_right(datas, em) - 1
        return pus[i] if i >= 0 else None


def latest_offers(session: Session) -> list[dict]:
    """Títulos com taxa do último dia disponível (usado nas oportunidades de renda fixa)."""
    last = session.scalar(select(func.max(TesouroPrice.data_base)))
    if not last:
        return []
    rows = session.scalars(select(TesouroPrice).where(TesouroPrice.data_base == last)).all()
    return [
        {"tipo": r.tipo, "vencimento": r.vencimento.isoformat(), "data_base": r.data_base.isoformat(),
         "taxa_compra": r.taxa_compra, "pu_compra": r.pu_compra, "taxa_venda": r.taxa_venda, "pu_venda": r.pu_venda}
        for r in rows
    ]
