"""As ferramentas que o assistente pode chamar.

Cinco ferramentas, cobrindo as tres funcoes do assistente:

    listar dados       dados_do_paciente, exames_do_paciente, consultas_do_paciente
    sugerir tratamento buscar_protocolo
    marcar consulta    marcar_consulta
"""

import json
from datetime import date, datetime
from typing import Any

from langchain_core.tools import tool

from assistente import llm
from assistente.db import consultar, executar


def _json(dados: Any) -> str:
    return json.dumps(dados, ensure_ascii=False, default=str)


def _idade(nascimento: date) -> int:
    hoje = date.today()
    return hoje.year - nascimento.year - (
        (hoje.month, hoje.day) < (nascimento.month, nascimento.day)
    )


# ---------------------------------------------------------------------------
# consulta ao prontuario
# ---------------------------------------------------------------------------
@tool
def dados_do_paciente(paciente_id: str) -> str:
    """Ficha do paciente: nome, idade, sexo, convenio, doencas, alergias,
    medicamentos em uso e os atendimentos mais recentes.

    Args:
        paciente_id: identificador no formato P-0001.
    """
    pid = paciente_id.strip().upper()
    paciente = consultar(
        "SELECT id, nome, data_nascimento, sexo, convenio "
        "FROM clinical.pacientes WHERE id = :pid",
        pid=pid,
    )
    if not paciente:
        return _json({"erro": f"Paciente {pid} nao encontrado."})

    p = paciente[0]
    return _json(
        {
            "paciente_id": p["id"],
            "nome": p["nome"],
            "idade": _idade(p["data_nascimento"]),
            "sexo": p["sexo"],
            "convenio": p["convenio"],
            "doencas": consultar(
                "SELECT cid10, descricao, status, diagnosticado_em "
                "FROM clinical.condicoes WHERE paciente_id = :pid "
                "ORDER BY diagnosticado_em DESC",
                pid=pid,
            ),
            "alergias": consultar(
                "SELECT substancia, classe, gravidade FROM clinical.alergias "
                "WHERE paciente_id = :pid",
                pid=pid,
            ),
            "medicamentos_em_uso": consultar(
                "SELECT medicamento, classe, dose, via, frequencia, inicio "
                "FROM clinical.prescricoes WHERE paciente_id = :pid AND status = 'ativa' "
                "ORDER BY inicio DESC",
                pid=pid,
            ),
            "atendimentos_recentes": consultar(
                "SELECT id, tipo, setor, inicio, queixa_principal, medico_responsavel, status "
                "FROM clinical.encontros WHERE paciente_id = :pid "
                "ORDER BY inicio DESC LIMIT 5",
                pid=pid,
            ),
        }
    )


@tool
def exames_do_paciente(paciente_id: str, apenas_pendentes: bool = False) -> str:
    """Exames do paciente, com valor, unidade, faixa de referencia e situacao.

    Com apenas_pendentes=True, devolve so os que foram solicitados e ainda nao
    tem resultado liberado.

    Args:
        paciente_id: identificador no formato P-0001.
        apenas_pendentes: restringe aos exames sem resultado.
    """
    pid = paciente_id.strip().upper()
    filtro = "AND e.status IN ('solicitado', 'coletado')" if apenas_pendentes else ""
    linhas = consultar(
        f"""
        SELECT e.id, e.nome, e.categoria, e.urgencia, e.status, e.solicitado_em,
               r.analito, r.valor, r.unidade, r.ref_min, r.ref_max, r.flag, r.laudo
          FROM clinical.exames e
          LEFT JOIN clinical.resultados_exame r ON r.exame_id = e.id
         WHERE e.paciente_id = :pid AND e.status <> 'cancelado' {filtro}
         ORDER BY e.solicitado_em DESC
         LIMIT 20
        """,
        pid=pid,
    )
    return _json({"paciente_id": pid, "exames": linhas})


@tool
def consultas_do_paciente(paciente_id: str) -> str:
    """Agenda do paciente: consultas marcadas, com data, especialidade e se ja
    foram confirmadas pela recepcao.

    Args:
        paciente_id: identificador no formato P-0001.
    """
    pid = paciente_id.strip().upper()
    return _json(
        {
            "paciente_id": pid,
            "consultas": consultar(
                "SELECT id, especialidade, data_hora, motivo, confirmada, agendada_por "
                "FROM clinical.consultas WHERE paciente_id = :pid ORDER BY data_hora",
                pid=pid,
            ),
        }
    )


# ---------------------------------------------------------------------------
# conhecimento do hospital
# ---------------------------------------------------------------------------
@tool
def buscar_protocolo(pergunta: str, k: int = 4) -> str:
    """Busca trechos dos protocolos internos do hospital.

    E a fonte de qualquer sugestao de tratamento, conduta, criterio ou meta.
    Pergunta em linguagem natural e completa: a busca e semantica, nao por
    palavra-chave. Cada trecho vem com uma referencia para voce citar.

    Args:
        pergunta: o que voce quer saber, em uma frase.
        k: quantos trechos devolver (padrao 4).
    """
    vetor = "[" + ",".join(f"{v:.7f}" for v in llm.embeddings().embed_query(pergunta)) + "]"
    linhas = consultar(
        """
        SELECT t.id, t.protocolo_id, t.secao, t.texto, p.titulo, p.especialidade,
               ROUND((1 - (t.embedding <=> CAST(:vetor AS vector)))::numeric, 4) AS similaridade
          FROM knowledge.trechos t
          JOIN knowledge.protocolos p ON p.id = t.protocolo_id
         WHERE t.embedding IS NOT NULL
         ORDER BY t.embedding <=> CAST(:vetor AS vector)
         LIMIT :k
        """,
        vetor=vetor,
        k=max(1, min(k, 8)),
    )
    if not linhas:
        return _json(
            {
                "erro": "Nenhum trecho indexado. Rode: python main.py setup",
                "trechos": [],
            }
        )
    return _json(
        {
            "trechos": [
                {
                    "referencia": f"{l['protocolo_id']} - {l['secao']}",
                    "protocolo": l["titulo"],
                    "especialidade": l["especialidade"],
                    "texto": l["texto"],
                    "similaridade": float(l["similaridade"]),
                }
                for l in linhas
            ]
        }
    )


# ---------------------------------------------------------------------------
# agenda
# ---------------------------------------------------------------------------
@tool
def marcar_consulta(
    paciente_id: str, especialidade: str, data_hora: str, motivo: str
) -> str:
    """Marca uma consulta para o paciente na agenda do hospital.

    A consulta entra como NAO CONFIRMADA: agendamento feito pelo assistente e
    uma solicitacao, que a recepcao ou o medico confirmam depois.

    Args:
        paciente_id: identificador no formato P-0001.
        especialidade: ex. cardiologia, nefrologia, pneumologia.
        data_hora: data e hora no formato ISO, ex. 2026-10-15T14:30.
        motivo: por que a consulta esta sendo marcada.
    """
    pid = paciente_id.strip().upper()

    if not consultar("SELECT 1 FROM clinical.pacientes WHERE id = :pid", pid=pid):
        return _json({"erro": f"Paciente {pid} nao encontrado. Nada foi agendado."})

    try:
        quando = datetime.fromisoformat(data_hora.replace("Z", "+00:00"))
    except ValueError:
        return _json(
            {"erro": f"Data '{data_hora}' invalida. Use o formato ISO: 2026-10-15T14:30."}
        )

    if quando.tzinfo is not None:
        quando = quando.replace(tzinfo=None)
    if quando < datetime.now():
        return _json(
            {"erro": f"A data {quando:%d/%m/%Y %H:%M} ja passou. Nada foi agendado."}
        )

    executar(
        """
        INSERT INTO clinical.consultas (paciente_id, especialidade, data_hora, motivo)
        VALUES (:pid, :esp, :quando, :motivo)
        """,
        pid=pid,
        esp=especialidade.strip().lower(),
        quando=quando,
        motivo=motivo.strip(),
    )
    nova = consultar(
        "SELECT id, especialidade, data_hora, motivo, confirmada FROM clinical.consultas "
        "WHERE paciente_id = :pid ORDER BY id DESC LIMIT 1",
        pid=pid,
    )[0]
    return _json(
        {
            "agendada": True,
            "consulta": nova,
            "observacao": "Registrada como nao confirmada; depende de validacao da equipe.",
        }
    )


FERRAMENTAS = [
    dados_do_paciente,
    exames_do_paciente,
    consultas_do_paciente,
    buscar_protocolo,
    marcar_consulta,
]
