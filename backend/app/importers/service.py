"""Importação idempotente de relatórios da B3 para o banco."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ImportLog, RawEvent
from app.importers.b3 import parse_report
from app.security import nome_arquivo_seguro
from app.settings import IMPORTS_DIR


def import_file(session: Session, filename: str, content: bytes, archive: bool = True) -> dict:
    filename = nome_arquivo_seguro(filename)  # sem diretórios/caracteres perigosos; extensão da allowlist
    kind, rows = parse_report(content if not filename.lower().endswith(".csv") else _named(content, filename))
    file_sha = hashlib.sha256(content).hexdigest()

    existing = set(
        session.scalars(select(RawEvent.row_hash).where(RawEvent.row_hash.in_([r.row_hash for r in rows]))).all()
    ) if rows else set()
    new_rows = [r for r in rows if r.row_hash not in existing]

    dates = [r.data for r in rows]
    stored = ""
    if archive and rows:
        folder = IMPORTS_DIR / max(dates).strftime("%Y-%m")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / Path(filename).name
        if not target.exists():
            target.write_bytes(content)
        stored = str(target)

    log = ImportLog(
        filename=Path(filename).name, kind=kind, file_sha=file_sha, stored_path=stored,
        rows_total=len(rows), rows_new=len(new_rows),
        date_min=min(dates) if dates else None, date_max=max(dates) if dates else None,
    )
    session.add(log)
    session.flush()
    for r in new_rows:
        session.add(RawEvent(import_id=log.id, **{k: v for k, v in r.to_dict().items()}))
    session.commit()
    return {
        "id": log.id, "arquivo": log.filename, "tipo": kind, "linhas": len(rows), "novas": len(new_rows),
        "duplicadas": len(rows) - len(new_rows),
        "periodo": [log.date_min.isoformat() if log.date_min else None,
                    log.date_max.isoformat() if log.date_max else None],
    }


def _named(content: bytes, filename: str):
    import io

    buf = io.BytesIO(content)
    buf.name = filename
    return buf


def load_rows(session: Session) -> list[dict]:
    return [e.as_row() for e in session.scalars(select(RawEvent).order_by(RawEvent.id)).all()]
