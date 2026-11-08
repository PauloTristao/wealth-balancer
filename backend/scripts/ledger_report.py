"""Uso: python scripts/ledger_report.py <arquivo.xlsx> [<arquivo2.xlsx> ...]

Lê relatórios da B3 (sem gravar no banco) e imprime posições, avisos e reconciliação.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importers.b3 import parse_report  # noqa: E402
from app.portfolio.ledger import run_ledger  # noqa: E402


def main(paths: list[str]) -> None:
    rows = []
    for p in paths:
        kind, r = parse_report(p)
        print(f"{p}: {kind}, {len(r)} linhas")
        rows += r
    res = run_ledger(rows)
    print(f"\n{'TICKER':<42}{'CLASSE':<7}{'QTD':>10}{'PM':>11}{'CUSTO':>12}{'PROVENTOS':>11}{'REALIZ.':>10}")
    for p in res.open_positions():
        print(f"{p.ticker:<42}{p.classe:<7}{p.qtd:>10.2f}{p.preco_medio:>11.2f}{p.custo_total:>12.2f}"
              f"{p.proventos:>11.2f}{p.lucro_realizado:>10.2f}")
    print("\nEncerradas:")
    for p in res.closed_positions():
        print(f"  {p.ticker:<40} qtd={p.qtd:.4f} realizado={p.lucro_realizado:.2f} proventos={p.proventos:.2f}")
    print("\nAvisos:")
    for w in res.warnings:
        print(f"  {w['data']} {w['ticker']:<10} {w['codigo']:<24} {w['mensagem']}")
    print("\nReconciliação:")
    for r in res.reconciliation:
        print(f"  {r['data']} {r['ticker']:<8} B3={r['qtd_b3']:g} calc={r['qtd_calculada']:g} {r['status']}")
    print("\nIgnorados:", res.ignored)
    print("\nProventos totais:", round(sum(i["valor"] for i in res.income), 2))


if __name__ == "__main__":
    main(sys.argv[1:])
