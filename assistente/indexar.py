"""Calculo dos embeddings dos protocolos.
"""

from assistente import llm
from assistente.db import consultar, executar

LOTE = 64


def pendentes() -> int:
    return consultar(
        "SELECT count(*) AS n FROM knowledge.trechos WHERE embedding IS NULL"
    )[0]["n"]


def indexar(anunciar=lambda _: None) -> int:
    """Calcula e grava os embeddings que faltam. Devolve quantos processou."""
    faltando = consultar(
        """
        SELECT t.id, t.secao, t.texto, p.titulo, p.especialidade
          FROM knowledge.trechos t
          JOIN knowledge.protocolos p ON p.id = t.protocolo_id
         WHERE t.embedding IS NULL
         ORDER BY t.id
        """
    )
    if not faltando:
        return 0

    modelo = llm.embeddings()
    for inicio in range(0, len(faltando), LOTE):
        lote = faltando[inicio : inicio + LOTE]
        anunciar(f"{inicio + len(lote)}/{len(faltando)} trechos")

        textos = [
            f"{l['titulo']} ({l['especialidade']}) - {l['secao']}: {l['texto']}"
            for l in lote
        ]
        for linha, vetor in zip(lote, modelo.embed_documents(textos)):
            executar(
                "UPDATE knowledge.trechos SET embedding = CAST(:v AS vector) WHERE id = :id",
                v="[" + ",".join(f"{x:.7f}" for x in vetor) + "]",
                id=linha["id"],
            )
    return len(faltando)
