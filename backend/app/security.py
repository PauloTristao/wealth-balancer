"""Validação de entradas externas (sempre por allowlist) e regras de origem/host da API local.

Tudo que vem de fora — parâmetros de URL, nomes de arquivo enviados, links de feeds RSS, cabeçalhos
Origin/Host — passa por aqui. Funções puras e sem efeitos colaterais, para serem testadas por completo.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

# ---------------------------------------------------------------- allowlists
CLASSES_OPORTUNIDADE: frozenset[str] = frozenset({"ACAO", "FII", "INTL", "RF"})
CLASSES_MANUAIS: frozenset[str] = frozenset({"ACAO", "FII", "RF", "INTL", "OUTROS"})

# App local: só o site local pode disparar escrita; só nomes de host locais são aceitos (anti DNS rebinding).
ALLOWED_ORIGINS: frozenset[str] = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})
ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

UPLOAD_EXTS: frozenset[str] = frozenset({".xlsx", ".xls", ".csv"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FILENAME_STEM = 100
URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})
MAX_URL_LEN = 2048

# Código de negociação B3: 4 letras + 1–2 dígitos (+F do fracionário). Ex.: PETR4, TAEE11, ROXO34, ITSA4F.
_TICKER_B3 = re.compile(r"[A-Z]{4}\d{1,2}F?")
# Títulos do Tesouro como a B3 nomeia. Ex.: "Tesouro IPCA+ com Juros Semestrais 2035".
_TESOURO = re.compile(r"Tesouro [A-Za-zÀ-ÿ0-9+ ]{1,60}")
# Nome de empresa/fundo usado só como termo de busca de notícias.
_NOME_BUSCA = re.compile(r"[\w .,&'()/:+-]{1,80}")
_FILENAME_PERMITIDO = re.compile(r"[^A-Za-z0-9._-]")


class InvalidInput(ValueError):
    """Entrada fora da allowlist. A mensagem é segura para mostrar ao usuário."""


# ---------------------------------------------------------------- parâmetros de URL
def classe_oportunidade(raw: str) -> str:
    classe = raw.strip().upper()
    if classe not in CLASSES_OPORTUNIDADE:
        raise InvalidInput("Classe inválida. Use ACAO, FII, INTL ou RF.")
    return classe


def ticker(raw: str) -> str:
    """Normaliza e valida um ticker B3 ou nome de título do Tesouro."""
    texto = " ".join(raw.split())
    if _TICKER_B3.fullmatch(texto.upper()):
        return texto.upper()
    if _TESOURO.fullmatch(texto):
        return texto
    raise InvalidInput("Ticker inválido.")


def nome_busca(raw: str | None) -> str | None:
    if raw is None:
        return None
    texto = " ".join(raw.split())
    if not texto:
        return None
    if not _NOME_BUSCA.fullmatch(texto):
        raise InvalidInput("Nome inválido para busca de notícias.")
    return texto


# ---------------------------------------------------------------- upload
def upload_permitido(filename: str | None) -> bool:
    if not filename:
        return False
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower() in UPLOAD_EXTS


def nome_arquivo_seguro(filename: str) -> str:
    """Nome para arquivar o upload: só a parte final, caracteres seguros, extensão da allowlist.

    Remove diretórios (inclusive `..` e caminhos do Windows), troca qualquer caractere fora de
    [A-Za-z0-9._-] por "_", tira pontos iniciais (arquivos ocultos) e limita o tamanho.
    """
    base = PurePosixPath(filename.replace("\\", "/")).name
    caminho = PurePosixPath(base)
    ext = caminho.suffix.lower()
    if ext not in UPLOAD_EXTS:
        raise InvalidInput("Formato não suportado: envie o .xlsx (ou .csv) exportado da B3.")
    stem = _FILENAME_PERMITIDO.sub("_", caminho.stem).lstrip(".")[:MAX_FILENAME_STEM]
    return f"{stem or 'arquivo'}{ext}"


# ---------------------------------------------------------------- conteúdo externo
def url_http_segura(url: str | None) -> str:
    """Devolve a URL só se for http(s) com host; senão "" (bloqueia javascript:, data:, file: ...)."""
    if not url:
        return ""
    url = url.strip()
    if len(url) > MAX_URL_LEN or any(ord(c) < 0x20 for c in url):
        return ""
    try:
        partes = urlsplit(url)
    except ValueError:
        return ""
    if partes.scheme.lower() not in URL_SCHEMES or not partes.hostname:
        return ""
    return url


# ---------------------------------------------------------------- origem das requisições
def origem_permitida(method: str, origin: str | None) -> bool:
    """Métodos de leitura passam sempre; escrita só sem Origin (curl/CLI) ou vinda do site local."""
    if method.upper() in SAFE_METHODS:
        return True
    return origin is None or origin in ALLOWED_ORIGINS
