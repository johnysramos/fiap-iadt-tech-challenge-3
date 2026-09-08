"""Acesso ao banco.
"""

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text

from assistente import config


@lru_cache(maxsize=1)
def engine() -> Engine:
    return create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)


def consultar(sql: str, **params: Any) -> list[dict[str, Any]]:
    """SELECT parametrizado. Devolve as linhas como dicionarios."""
    with engine().connect() as conn:
        return [dict(l) for l in conn.execute(text(sql), params).mappings()]


def executar(sql: str, **params: Any) -> None:
    """INSERT/UPDATE parametrizado, com commit."""
    with engine().begin() as conn:
        conn.execute(text(sql), params)


def rodar_script(sql: str) -> None:
    """Executa um arquivo .sql inteiro, com varias instrucoes.
    """
    import psycopg

    with psycopg.connect(config.DATABASE_URL.replace("+psycopg", "")) as conn:
        conn.execute(sql)
        conn.commit()
