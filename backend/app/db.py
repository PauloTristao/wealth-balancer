"""Banco SQLite (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.settings import DATA_DIR, DB_URL


class Base(DeclarativeBase):
    pass


class ImportLog(Base):
    __tablename__ = "import_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    file_sha: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(String(500), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    date_min: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_max: Mapped[date | None] = mapped_column(Date, nullable=True)


class RawEvent(Base):
    """Linha bruta de relatório da B3 (fonte da verdade; o ledger é recalculado a partir daqui)."""
    __tablename__ = "raw_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_hash: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("import_log.id"))
    source: Mapped[str] = mapped_column(String(32))
    data: Mapped[date] = mapped_column(Date, index=True)
    es: Mapped[str] = mapped_column(String(1))
    mov: Mapped[str] = mapped_column(String(120))
    produto: Mapped[str] = mapped_column(String(255))
    instituicao: Mapped[str] = mapped_column(String(255))
    qtd: Mapped[float] = mapped_column(Float, default=0.0)
    preco: Mapped[float | None] = mapped_column(Float, nullable=True)
    valor: Mapped[float | None] = mapped_column(Float, nullable=True)

    def as_row(self) -> dict:
        return {
            "source": self.source, "data": self.data, "es": self.es, "mov": self.mov, "produto": self.produto,
            "instituicao": self.instituicao, "qtd": self.qtd, "preco": self.preco, "valor": self.valor,
            "row_hash": self.row_hash,
        }


class ManualPosition(Base):
    """Posições fora da B3: reserva de emergência, CDB em banco, cripto etc."""
    __tablename__ = "manual_positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    classe: Mapped[str] = mapped_column(String(16))           # ACAO|FII|RF|INTL|OUTROS
    subtipo: Mapped[str] = mapped_column(String(60), default="")
    instituicao: Mapped[str] = mapped_column(String(120), default="")
    valor_aplicado: Mapped[float] = mapped_column(Float, default=0.0)
    valor_atual: Mapped[float] = mapped_column(Float, default=0.0)
    data_ref: Mapped[date] = mapped_column(Date, default=date.today)
    reserva_emergencia: Mapped[int] = mapped_column(Integer, default=0)  # 1 = fora do balanceamento
    obs: Mapped[str] = mapped_column(Text, default="")

    def public(self) -> dict:
        return {
            "id": self.id, "nome": self.nome, "classe": self.classe, "subtipo": self.subtipo,
            "instituicao": self.instituicao, "valor_aplicado": self.valor_aplicado,
            "valor_atual": self.valor_atual, "data_ref": self.data_ref.isoformat(),
            "reserva_emergencia": bool(self.reserva_emergencia), "obs": self.obs,
        }


class Quote(Base):
    """Última cotação conhecida por ticker (cache)."""
    __tablename__ = "quotes"
    ticker: Mapped[str] = mapped_column(String(80), primary_key=True)
    preco: Mapped[float] = mapped_column(Float)
    variacao_dia: Mapped[float | None] = mapped_column(Float, nullable=True)
    nome: Mapped[str] = mapped_column(String(200), default="")
    max_52s: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_52s: Mapped[float | None] = mapped_column(Float, nullable=True)
    fonte: Mapped[str] = mapped_column(String(20), default="")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class TesouroPrice(Base):
    """Histórico de preços/taxas do Tesouro Direto (Tesouro Transparente)."""
    __tablename__ = "tesouro_precos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(80), index=True)
    vencimento: Mapped[date] = mapped_column(Date, index=True)
    data_base: Mapped[date] = mapped_column(Date, index=True)
    taxa_compra: Mapped[float | None] = mapped_column(Float, nullable=True)
    taxa_venda: Mapped[float | None] = mapped_column(Float, nullable=True)
    pu_compra: Mapped[float | None] = mapped_column(Float, nullable=True)
    pu_venda: Mapped[float | None] = mapped_column(Float, nullable=True)


class PriceMonthly(Base):
    """Fechamento mensal (sem ajuste de proventos/desdobramentos) e séries de referência (CDI, IBOV)."""
    __tablename__ = "price_monthly"
    ticker: Mapped[str] = mapped_column(String(80), primary_key=True)
    mes: Mapped[str] = mapped_column(String(7), primary_key=True)   # AAAA-MM
    valor: Mapped[float] = mapped_column(Float)
    fonte: Mapped[str] = mapped_column(String(20), default="")


class Fundamental(Base):
    """Indicadores fundamentalistas (cache diário). dados = JSON com os campos da fonte."""
    __tablename__ = "fundamentals"
    ticker: Mapped[str] = mapped_column(String(80), primary_key=True)
    categoria: Mapped[str] = mapped_column(String(16), primary_key=True)  # ACAO | FII | BDR
    dados: Mapped[str] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KV(Base):
    """Metadados simples (ex.: data da última atualização do Tesouro)."""
    __tablename__ = "kv"
    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[str] = mapped_column(Text, default="")


def make_engine(url: str = DB_URL):
    if url.startswith("sqlite:///") and ":memory:" not in url:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng=None) -> None:
    Base.metadata.create_all(eng or engine)


def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
