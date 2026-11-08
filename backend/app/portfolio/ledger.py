"""Reconstrói a carteira (quantidade, preço médio, proventos, lucro realizado)
a partir das linhas brutas dos relatórios da B3.

É uma função pura: recebe as linhas (RawRow ou dict) e devolve o resultado.
Assim, mudanças de regra não exigem reimportar arquivos.

Regras principais (derivadas do relatório de Movimentação da B3):
- "Transferência - Liquidação" com preço = compra (Crédito) / venda (Débito).
- Liquidações casadas com uma linha de "Empréstimo" (mesmo ativo e quantidade,
  datas próximas) são pernas de aluguel de ações (BTC) e não alteram a posição.
- Liquidação a débito sem preço e sem empréstimo = saída com valor desconhecido (aviso).
- Direitos/recibos (ex.: XPML12, ITSA2, ITSA10) são mapeados ao ativo-base.
- "Atualização" é tratada como: checkpoint da posição, conversão de subscrição
  exercida em ativos, ou troca de ticker (ex.: CPLE6 -> CPLE5).
- Se houver relatório de Negociação, as compras/vendas dele substituem as
  liquidações correspondentes da Movimentação.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Iterable

from app.importers.common import RawRow, norm_text
from app.portfolio.assets import root_of, split_produto, ticker_info
from app.settings import ativos_config

EPS = 1e-6
TESOURO_EPS = 0.005  # títulos aparecem com 2 casas decimais na B3

# ---- tipos de evento normalizados ----
BUY, SELL = "BUY", "SELL"
SPLIT_IN, SPLIT_OUT = "SPLIT_IN", "SPLIT_OUT"
BONUS = "BONUS"
FRACTION_OUT, FRACTION_AUCTION = "FRACTION_OUT", "FRACTION_AUCTION"
UPDATE = "UPDATE"
SUBS_EXERCISE = "SUBS_EXERCISE"
RIGHTS_BUY, RIGHTS_SELL = "RIGHTS_BUY", "RIGHTS_SELL"
INCOME = "INCOME"
FEE = "FEE"
LEND_OUT, LEND_RETURN = "LEND_OUT", "LEND_RETURN"
IGNORE = "IGNORE"

# ordem de processamento dentro do mesmo dia
PRIORITY = {
    SPLIT_IN: 0, SPLIT_OUT: 0, BONUS: 1, SUBS_EXERCISE: 2, RIGHTS_BUY: 2, RIGHTS_SELL: 2,
    BUY: 3, FEE: 3, LEND_RETURN: 3, SELL: 4, LEND_OUT: 4, FRACTION_OUT: 5, FRACTION_AUCTION: 6, UPDATE: 7, INCOME: 8, IGNORE: 9,
}

INCOME_TYPES = {
    "rendimento": "RENDIMENTO",
    "dividendo": "DIVIDENDO",
    "juros sobre capital proprio": "JCP",
    "reembolso": "REEMBOLSO",
}

IGNORED_MOVS = {
    "transferencia",                      # custódia entre corretoras
    "juros sobre capital proprio - transferido",
    "rendimento - transferido",
    "dividendo - transferido",
    "direito de subscricao",
    "direitos de subscricao - nao exercido",
    "direito sobras de subscricao",
    "direito sobras de subscricao - nao exercido",
    "cessao de direitos",
    "cessao de direitos - solicitada",
    "solicitacao de subscricao",
    "recibo de subscricao",
}


@dataclass
class Event:
    data: date
    kind: str
    ticker: str              # ativo-base
    raw_ticker: str
    qtd: float
    preco: float | None
    valor: float | None
    mov: str
    source: str
    income_type: str | None = None
    seq: int = 0


@dataclass
class Position:
    ticker: str
    nome: str
    classe: str
    subtipo: str
    qtd: float = 0.0
    custo_total: float = 0.0
    lucro_realizado: float = 0.0
    proventos: float = 0.0
    primeira_data: date | None = None
    ultima_data: date | None = None
    # internos
    pending_subs: list = field(default_factory=list)  # [[qtd, custo], ...]
    rights_pool: float = 0.0
    pending_fraction_cost: float = 0.0

    @property
    def preco_medio(self) -> float:
        return self.custo_total / self.qtd if self.qtd > EPS else 0.0

    def is_open(self) -> bool:
        eps = TESOURO_EPS if self.classe == "RF" and self.ticker.lower().startswith("tesouro") else EPS
        return self.qtd > eps

    def public(self) -> dict:
        return {
            "ticker": self.ticker,
            "nome": self.nome,
            "classe": self.classe,
            "subtipo": self.subtipo,
            "qtd": round(self.qtd, 8),
            "preco_medio": round(self.preco_medio, 6),
            "custo_total": round(self.custo_total, 2),
            "lucro_realizado": round(self.lucro_realizado, 2),
            "proventos": round(self.proventos, 2),
            "primeira_data": self.primeira_data.isoformat() if self.primeira_data else None,
            "ultima_data": self.ultima_data.isoformat() if self.ultima_data else None,
        }


@dataclass
class LedgerResult:
    positions: dict[str, Position]
    trades: list[dict]
    income: list[dict]
    warnings: list[dict]
    reconciliation: list[dict]
    ignored: dict[str, int]
    # data -> {ticker: (qtd, custo_total, classe)} para as datas pedidas em run_ledger(snapshot_dates=...)
    snapshots: dict[date, dict[str, tuple[float, float, str]]] = field(default_factory=dict)

    def open_positions(self) -> list[Position]:
        return sorted((p for p in self.positions.values() if p.is_open()), key=lambda p: (p.classe, p.ticker))

    def closed_positions(self) -> list[Position]:
        return sorted((p for p in self.positions.values() if not p.is_open()), key=lambda p: p.ticker)


# ----------------------------------------------------------------------------
# Normalização das linhas em eventos
# ----------------------------------------------------------------------------

def _as_raw(r: RawRow | dict) -> RawRow:
    if isinstance(r, RawRow):
        return r
    d = dict(r)
    if isinstance(d.get("data"), str):
        d["data"] = date.fromisoformat(d["data"])
    return RawRow(**{k: d[k] for k in RawRow.__dataclass_fields__ if k in d})


def _classify_row(r: RawRow) -> tuple[str, str | None]:
    m = norm_text(r.mov)
    credit = r.es == "C"
    if r.source == "negociacao":
        return (BUY if credit else SELL), None
    if m in INCOME_TYPES:
        return (INCOME if credit else IGNORE), INCOME_TYPES[m]
    if m == "emprestimo":
        # linha de aluguel; se tiver valor é a remuneração do aluguel
        if credit and r.valor:
            return INCOME, "ALUGUEL"
        return IGNORE, None
    if m in ("compra",):
        return BUY, None
    if m in ("venda", "resgate", "vencimento"):
        return SELL, None
    if m == "transferencia - liquidacao":
        return (BUY if credit else SELL), None
    if m == "desdobro":
        return (SPLIT_IN if credit else SPLIT_OUT), None
    if m == "grupamento":
        return SPLIT_OUT, None
    if m.startswith("bonificacao"):
        return BONUS, None
    if m == "fracao em ativos":
        return (FRACTION_OUT if not credit else SPLIT_IN), None
    if m == "leilao de fracao":
        return FRACTION_AUCTION, None
    if m == "atualizacao":
        return UPDATE, None
    if m == "direitos de subscricao - exercido":
        return SUBS_EXERCISE, None
    if m.startswith("cobranca de taxa"):
        return FEE, None
    if m in IGNORED_MOVS:
        return IGNORE, None
    return IGNORE, "__unknown__"


def _to_events(rows: list[RawRow]) -> tuple[list[Event], dict[str, int], list[dict]]:
    events: list[Event] = []
    ignored: dict[str, int] = defaultdict(int)
    unknown: list[dict] = []
    for i, r in enumerate(rows):
        raw_tk, _nome = split_produto(r.produto)
        info = ticker_info(raw_tk)
        kind, extra = _classify_row(r)
        if info.base == "FUTURO":
            kind = IGNORE
        if kind == IGNORE:
            ignored[r.mov] += 1
            if extra == "__unknown__":
                unknown.append({"data": r.data.isoformat(), "ticker": info.base, "codigo": "MOV_DESCONHECIDA",
                                "mensagem": f"Tipo de movimentação não tratado: {r.mov}"})
        # liquidações/compra/venda de direitos
        if info.is_right and kind in (BUY, SELL):
            kind = RIGHTS_BUY if kind == BUY else RIGHTS_SELL
        events.append(Event(
            data=r.data, kind=kind, ticker=info.base, raw_ticker=info.raw, qtd=r.qtd or 0.0,
            preco=r.preco, valor=r.valor, mov=r.mov, source=r.source,
            income_type=extra if kind == INCOME else None, seq=i,
        ))
    return events, dict(ignored), unknown


def _mark_lending_legs(events: list[Event], window: int) -> int:
    """Liquidações de aluguel (BTC) viram IGNORE. Retorna quantas foram marcadas."""
    loans: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for e in events:
        if norm_text(e.mov) == "emprestimo" and e.qtd > EPS:
            loans[e.ticker].append((e.data, e.qtd))
    n = 0
    for e in events:
        if e.source != "movimentacao" or norm_text(e.mov) != "transferencia - liquidacao":
            continue
        if e.kind not in (BUY, SELL):
            continue
        for d, q in loans.get(e.ticker, []):
            if abs(q - e.qtd) < EPS and (e.data - timedelta(days=window)) <= d <= (e.data + timedelta(days=1)):
                e.kind = LEND_RETURN if e.kind == BUY else LEND_OUT
                e.mov = e.mov + " (aluguel)"
                n += 1
                break
    return n


def _supersede_with_negociacao(events: list[Event], window: int = 10) -> int:
    """Se houver Negociação, remove as liquidações equivalentes da Movimentação.

    A liquidação cai D+1/D+2 úteis depois do pregão; com feriados (Carnaval, Semana Santa) isso chega a
    6+ dias corridos. Procura do dia mais próximo para trás, até `window` dias corridos.
    """
    neg = [e for e in events if e.source == "negociacao" and e.kind in (BUY, SELL)]
    if not neg:
        return 0
    groups: dict[tuple[str, str, date], float] = defaultdict(float)
    for e in neg:
        groups[(e.ticker, e.kind, e.data)] += e.qtd
    used: set[tuple[str, str, date]] = set()
    n = 0
    for e in events:
        if e.source != "movimentacao" or e.kind not in (BUY, SELL):
            continue
        if norm_text(e.mov) != "transferencia - liquidacao":
            continue
        for back in range(0, window + 1):
            key = (e.ticker, e.kind, e.data - timedelta(days=back))
            if key in groups and key not in used and abs(groups[key] - e.qtd) < EPS:
                used.add(key)
                e.kind = IGNORE
                e.mov = e.mov + " (substituída por Negociação)"
                n += 1
                break
    return n


# ----------------------------------------------------------------------------
# Execução
# ----------------------------------------------------------------------------

def run_ledger(rows: Iterable[RawRow | dict], until: date | None = None,
               snapshot_dates: list[date] | None = None) -> LedgerResult:
    cfg = ativos_config()
    raw = [_as_raw(r) for r in rows]
    events, ignored, unknown = _to_events(raw)
    _mark_lending_legs(events, int(cfg.get("janela_emprestimo_dias", 5)))
    _supersede_with_negociacao(events, int(cfg.get("janela_liquidacao_dias", 10)))
    events.sort(key=lambda e: (e.data, PRIORITY[e.kind], e.seq))

    bonus_cost = cfg.get("custo_bonificacao") or {}
    names: dict[str, str] = {}
    for r in raw:
        tk, nome = split_produto(r.produto)
        base = ticker_info(tk).base
        if not ticker_info(tk).is_right and nome:
            names[base] = nome

    positions: dict[str, Position] = {}
    trades: list[dict] = []
    income: list[dict] = []
    warnings: list[dict] = list(unknown)
    recon: list[dict] = []

    def pos(tk: str) -> Position:
        if tk not in positions:
            info = ticker_info(tk)
            positions[tk] = Position(tk, names.get(tk, tk), info.classe, info.subtipo)
        return positions[tk]

    def warn(e: Event, code: str, msg: str) -> None:
        warnings.append({"data": e.data.isoformat(), "ticker": e.ticker, "codigo": code, "mensagem": msg})

    def trade(e: Event, side: str, valor: float | None, extra: str = "") -> None:
        trades.append({
            "data": e.data.isoformat(), "ticker": e.ticker, "lado": side, "qtd": e.qtd,
            "preco": e.preco, "valor": valor, "origem": e.source, "obs": extra,
        })

    snaps_pending = sorted(snapshot_dates or [])
    snapshots: dict[date, dict[str, tuple[float, float, str]]] = {}

    def take_snapshots(before: date | None) -> None:
        while snaps_pending and (before is None or snaps_pending[0] < before):
            d = snaps_pending.pop(0)
            snapshots[d] = {t: (q.qtd, q.custo_total, q.classe) for t, q in positions.items() if q.is_open()}

    for e in events:
        if until and e.data > until:
            break
        take_snapshots(e.data)
        if e.kind == IGNORE:
            continue
        p = pos(e.ticker)

        if e.kind == BUY:
            valor = e.valor if e.valor is not None else (e.preco * e.qtd if e.preco is not None else None)
            if valor is None:
                warn(e, "ENTRADA_SEM_PRECO", f"Entrada de {e.qtd:g} sem preço ({e.mov}); custo considerado zero.")
                valor = 0.0
            p.qtd += e.qtd
            p.custo_total += valor
            p.primeira_data = p.primeira_data or e.data
            p.ultima_data = e.data
            trade(e, "C", valor)

        elif e.kind == SELL:
            valor = e.valor if e.valor is not None else (e.preco * e.qtd if e.preco is not None else None)
            if p.qtd + EPS < e.qtd:
                warn(e, "VENDA_MAIOR_QUE_POSICAO", f"Venda de {e.qtd:g} com posição calculada de {p.qtd:g}.")
            q = min(e.qtd, p.qtd) if p.qtd > 0 else 0.0
            custo_saida = p.preco_medio * q
            p.qtd -= e.qtd
            p.custo_total -= custo_saida
            if p.qtd < EPS:
                p.qtd = max(p.qtd, 0.0) if p.qtd > -EPS else p.qtd
                if abs(p.qtd) < EPS:
                    p.custo_total = 0.0
            if valor is None:
                warn(e, "SAIDA_SEM_PRECO", f"Saída de {e.qtd:g} sem preço ({e.mov}); lucro não calculado. "
                                           "Importe o relatório de Negociação ou confirme o evento.")
            else:
                p.lucro_realizado += valor - custo_saida
            p.ultima_data = e.data
            trade(e, "V", valor)

        elif e.kind == SPLIT_IN:
            p.qtd += e.qtd
        elif e.kind == SPLIT_OUT:
            p.qtd -= e.qtd

        elif e.kind == BONUS:
            custo_unit = (bonus_cost.get(e.ticker) or {}).get(e.data.isoformat())
            p.qtd += e.qtd
            if custo_unit is not None:
                p.custo_total += float(custo_unit) * e.qtd
            else:
                warn(e, "BONIFICACAO_SEM_CUSTO",
                     f"Bonificação de {e.qtd:g} ações sem custo atribuído (configure em ativos.yaml).")

        elif e.kind == FRACTION_OUT:
            q = min(e.qtd, p.qtd)
            custo = p.preco_medio * q
            p.qtd -= q
            p.custo_total -= custo
            p.pending_fraction_cost += custo
        elif e.kind == FRACTION_AUCTION:
            valor = e.valor or 0.0
            p.lucro_realizado += valor - p.pending_fraction_cost
            p.pending_fraction_cost = 0.0
            trade(e, "V", valor, "leilão de fração")

        elif e.kind == SUBS_EXERCISE:
            custo = e.valor if e.valor is not None else (e.preco * e.qtd if e.preco is not None else None)
            if custo is None:
                warn(e, "SUBSCRICAO_SEM_CUSTO", f"Subscrição de {e.qtd:g} exercida sem valor informado; custo zero.")
                custo = 0.0
            if e.qtd > EPS:
                p.pending_subs.append([e.qtd, custo])
                if custo:
                    trade(e, "C", custo, f"subscrição {e.raw_ticker}")
        elif e.kind == RIGHTS_BUY:
            p.rights_pool += e.valor or 0.0
            if e.valor:
                trade(e, "C", e.valor, f"compra de direitos {e.raw_ticker}")
        elif e.kind == RIGHTS_SELL:
            if e.valor:
                p.lucro_realizado += e.valor
                trade(e, "V", e.valor, f"venda de direitos {e.raw_ticker}")

        elif e.kind == FEE:
            p.custo_total += e.valor or 0.0

        elif e.kind == INCOME:
            v = e.valor or 0.0
            p.proventos += v
            income.append({"data": e.data.isoformat(), "ticker": e.ticker, "tipo": e.income_type,
                           "valor": v, "qtd_base": e.qtd, "valor_unit": e.preco, "classe": p.classe})

        elif e.kind == LEND_OUT:
            pass  # ações alugadas continuam sendo suas
        elif e.kind == LEND_RETURN:
            # devolução de aluguel com ticker novo (ex.: CPLE5 alugada, devolvida como CPLE3)
            if p.qtd < EPS:
                _convert_from_sibling(e, p, positions, recon, warn, "DEVOLUCAO_ALUGUEL")

        elif e.kind == UPDATE:
            _apply_update(e, p, positions, recon, warn)


    take_snapshots(None)
    return LedgerResult(positions, trades, income, warnings, recon, ignored, snapshots)


def _apply_update(e: Event, p: Position, positions: dict[str, Position], recon: list[dict], warn) -> None:
    q = e.qtd
    entry = {"data": e.data.isoformat(), "ticker": e.ticker, "qtd_b3": q, "qtd_calculada": round(p.qtd, 6)}
    if abs(p.qtd - q) < EPS:
        recon.append({**entry, "status": "OK"})
        return
    # 1) conversão de subscrição exercida em ativos
    if p.pending_subs:
        idx = next((i for i, (sq, _) in enumerate(p.pending_subs) if abs(sq - q) < EPS), None)
        if idx is not None:
            sq, custo = p.pending_subs.pop(idx)
            p.qtd += sq
            p.custo_total += custo + p.rights_pool
            p.rights_pool = 0.0
            recon.append({**entry, "status": "SUBSCRICAO_CONVERTIDA"})
            return
        total = sum(sq for sq, _ in p.pending_subs)
        if abs(total - q) < EPS:
            p.qtd += total
            p.custo_total += sum(c for _, c in p.pending_subs) + p.rights_pool
            p.pending_subs.clear()
            p.rights_pool = 0.0
            recon.append({**entry, "status": "SUBSCRICAO_CONVERTIDA"})
            return
    # 2) troca de ticker (mesma raiz, ex.: CPLE6 -> CPLE5)
    if p.qtd < EPS and _convert_from_sibling(e, p, positions, recon, warn, "ATUALIZACAO"):
        return
    recon.append({**entry, "status": "DIVERGENTE"})
    warn(e, "DIVERGENCIA_B3", f"B3 informa {q:g} e o cálculo tem {p.qtd:g}. Verifique eventos ausentes.")


def _convert_from_sibling(e: Event, p: Position, positions: dict[str, Position], recon: list[dict],
                          warn, origem: str) -> bool:
    root = root_of(e.ticker)
    if not root:
        return False
    for other in positions.values():
        if other is p or root_of(other.ticker) != root or abs(other.qtd - e.qtd) >= EPS:
            continue
        p.qtd, p.custo_total = other.qtd, other.custo_total
        p.primeira_data = other.primeira_data
        other.qtd, other.custo_total = 0.0, 0.0
        recon.append({"data": e.data.isoformat(), "ticker": e.ticker, "qtd_b3": e.qtd, "qtd_calculada": 0.0,
                      "status": f"CONVERSAO_DE_{other.ticker}"})
        warn(e, "CONVERSAO_TICKER", f"{other.ticker} convertido em {e.ticker} ({e.qtd:g} unidades, via {origem}).")
        return True
    return False


def summarize(result: LedgerResult) -> dict:
    return {
        "posicoes": [p.public() for p in result.open_positions()],
        "encerradas": [p.public() for p in result.closed_positions()],
        "avisos": result.warnings,
        "reconciliacao": result.reconciliation,
        "ignorados": result.ignored,
    }


def position_dict(p: Position) -> dict:
    return asdict(p)
