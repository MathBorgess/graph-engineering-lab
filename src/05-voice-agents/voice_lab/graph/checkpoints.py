"""Gerenciamento de Checkpointers do LangGraph para persistência e recuperação de sessão."""

import sqlite3
from pathlib import Path
from typing import Generator
from contextlib import contextmanager
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from voice_lab.config import settings


def get_sqlite_connection(db_path: Path = settings.checkpoints_db) -> sqlite3.Connection:
    """Retorna uma conexão SQLite com suporte a WAL mode e thread safety."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


@contextmanager
def get_checkpointer(db_path: Path = settings.checkpoints_db) -> Generator[SqliteSaver, None, None]:
    """Context manager que fornece uma instância ativa de SqliteSaver."""
    conn = get_sqlite_connection(db_path)
    serde = JsonPlusSerializer(allowed_msgpack_modules=[
        ("voice_lab.contracts.state", "ActionProposal"),
        ("voice_lab.contracts.state", "ToolResult"),
        ("voice_lab.contracts.state", "VoiceTurn"),
        ("voice_lab.state", "ActionProposal"),
        ("voice_lab.state", "ToolResult"),
        ("voice_lab.state", "VoiceTurn"),
    ])
    checkpointer = SqliteSaver(conn, serde=serde)
    checkpointer.setup()
    try:
        yield checkpointer
    finally:
        conn.close()
