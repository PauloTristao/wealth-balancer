import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Extratos reais da B3 usados pelos testes opcionais (test_arquivos_locais.py).
# Padrão: os arquivos que o app arquivou ao importar (data/imports/, fora do git).
LOCAL_FILES_DIR = Path(os.environ.get("CARTEIRA_TESTE_ARQUIVOS", BACKEND.parent / "data" / "imports"))
# Posições esperadas da SUA carteira (opcional, fora do git): {"TICKER": qtd, ...}
LOCAL_EXPECTED = BACKEND / "tests" / "local" / "posicoes_esperadas.json"


@pytest.fixture
def arquivos_b3() -> dict[str, list[Path]]:
    from app.importers.b3 import UnknownReportError, parse_report

    found: dict[str, list[Path]] = {"movimentacao": [], "negociacao": []}
    if LOCAL_FILES_DIR.exists():
        for f in sorted(LOCAL_FILES_DIR.rglob("*")):
            if f.suffix.lower() not in (".xlsx", ".csv"):
                continue
            try:
                kind, _ = parse_report(f)
            except (UnknownReportError, ValueError):
                continue
            found[kind].append(f)
    if not found["movimentacao"]:
        pytest.skip(f"nenhum extrato de Movimentação da B3 em {LOCAL_FILES_DIR}")
    return found
