"""Casse que registra auditoria de perguntas e respostas do assistente.
"""

import json
import time
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from assistente.db import executar


class Auditor:
    """Uma instancia por pergunta."""

    def __init__(self, usuario: str, pergunta: str, paciente_id: str | None) -> None:
        self.sessao_id = str(uuid4())
        self.usuario = usuario
        self.pergunta = pergunta
        self.paciente_id = paciente_id
        self.tokens_entrada = 0
        self.tokens_saida = 0
        self._ordem = 0

    def abrir(self) -> None:
        executar(
            """
            INSERT INTO audit.sessoes (id, usuario, paciente_id, pergunta)
            VALUES (CAST(:id AS uuid), :usuario, :paciente_id, :pergunta)
            """,
            id=self.sessao_id,
            usuario=self.usuario,
            paciente_id=self.paciente_id,
            pergunta=self.pergunta,
        )

    def fechar(self, status: str, resposta: str) -> None:
        executar(
            """
            UPDATE audit.sessoes
               SET status = :status, resposta = :resposta, finalizada_em = now(),
                   tokens_entrada = :te, tokens_saida = :ts
             WHERE id = CAST(:id AS uuid)
            """,
            id=self.sessao_id,
            status=status,
            resposta=resposta,
            te=self.tokens_entrada,
            ts=self.tokens_saida,
        )

    def registrar(
        self, tipo: str, nome: str, detalhe: dict[str, Any] | None = None,
        latencia_ms: int | None = None,
    ) -> None:
        self._ordem += 1
        executar(
            """
            INSERT INTO audit.eventos (sessao_id, ordem, tipo, nome, detalhe, latencia_ms)
            VALUES (CAST(:sid AS uuid), :ordem, :tipo, :nome,
                    CAST(:detalhe AS jsonb), :lat)
            """,
            sid=self.sessao_id,
            ordem=self._ordem,
            tipo=tipo,
            nome=nome,
            detalhe=json.dumps(detalhe or {}, ensure_ascii=False, default=str),
            lat=latencia_ms,
        )

    @contextmanager
    def no(self, nome: str):
        """Cronometra um no do grafo e grava o evento mesmo se ele falhar."""
        registro: dict[str, Any] = {}
        inicio = time.perf_counter()
        try:
            yield registro
        finally:
            self.registrar(
                "no", nome, registro, int((time.perf_counter() - inicio) * 1000)
            )

    def somar_tokens(self, resposta: Any) -> None:
        uso = getattr(resposta, "usage_metadata", None) or {}
        self.tokens_entrada += uso.get("input_tokens", 0)
        self.tokens_saida += uso.get("output_tokens", 0)
