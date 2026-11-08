"""Caminhos e carregamento das configurações YAML."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

try:  # backend/.env (chaves opcionais: ANTHROPIC_API_KEY, BRAPI_TOKEN, CARTEIRA_DATA_DIR...)
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

DATA_DIR = Path(os.environ.get("CARTEIRA_DATA_DIR", PROJECT_DIR / "data"))
IMPORTS_DIR = DATA_DIR / "imports"
DB_URL = os.environ.get("CARTEIRA_DB_URL", f"sqlite:///{(DATA_DIR / 'carteira.db').as_posix()}")
CONFIG_DIR = Path(__file__).resolve().parent / "config"


@lru_cache
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ativos_config() -> dict:
    return load_yaml("ativos.yaml")


def estrategia_config() -> dict:
    return load_yaml("estrategia.yaml")
