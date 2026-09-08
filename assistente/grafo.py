"""O fluxo do assistente, em LangGraph.

Quatro nos:

    guardrail  -> recusa pedido de prescricao direta, antes de qualquer coisa
    agente     -> raciocina e escolhe ferramentas (laco ReAct)
    ferramentas-> executa o que o agente pediu e devolve para ele
    finalizar  -> carimba a resposta como sugestao que exige revisao medica
"""

import time
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from assistente import llm
from assistente.auditoria import Auditor
from assistente.config import MAX_ITERACOES
from assistente.tools import FERRAMENTAS

# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------
SISTEMA = """Voce e o assistente clinico deste hospital, conversando com um medico.

O que voce faz:
1. Consulta a ficha do paciente -- idade, doencas, alergias, medicamentos,
   exames e consultas marcadas.
2. Sugere tratamentos com base nos PROTOCOLOS INTERNOS do hospital.
3. Marca consultas na agenda quando o medico pedir.

Como trabalhar:
- Pergunta sobre um paciente comeca por dados_do_paciente.
- Toda sugestao de conduta vem de buscar_protocolo. Cite a referencia do trecho
  que usou, no formato (PROT-XXX-00 - nome da secao). Se o protocolo nao cobrir
  o caso, diga isso em vez de responder com conhecimento geral.
- Para marcar consulta voce precisa de quatro dados: paciente, especialidade,
  data/hora e motivo. Tendo os quatro, marque direto -- nao peca confirmacao ao
  medico, porque a consulta ja entra como NAO CONFIRMADA e a equipe valida
  depois. Faltando algum, pergunte so o que falta.
- Portugues do Brasil, tom objetivo e colegial. Sem floreio.

Limite absoluto: voce NAO prescreve. Voce descreve o que o protocolo do hospital
estabelece, e a decisao e sempre do medico assistente."""

GUARDRAIL = """Voce classifica pedidos feitos por medicos a um assistente clinico.

Responda se o pedido e uma PRESCRICAO DIRETA: o medico pedindo que o assistente
prescreva, receite, defina a dose para um paciente especifico ou emita uma
receita pronta para uso.

NAO e prescricao direta (libere estes):
- perguntar o que o protocolo recomenda para um quadro
- pedir sugestao de tratamento ou de conduta
- pedir dados, exames ou consultas do paciente
- pedir para marcar consulta

Na duvida, libere: bloquear pergunta legitima de plantao atrapalha o
atendimento."""

RECUSA = """Nao posso prescrever nem emitir receita. Minha saida e sempre uma
sugestao de apoio a decisao, e quem prescreve e o medico assistente.

O que posso fazer: dizer o que o protocolo do hospital estabelece para esse
quadro, mostrar o que ja consta no prontuario e marcar uma consulta. Tente
perguntar "o que o protocolo recomenda para..." que eu respondo."""

CARIMBO = (
    "\n\n---\n"
    "Sugestao de apoio a decisao, baseada nos protocolos internos e no prontuario. "
    "PRECISA SER REVISADA POR UM MEDICO antes de qualquer conduta. "
    "Sessao {sessao} registrada para auditoria."
)


# ---------------------------------------------------------------------------
# estado
# ---------------------------------------------------------------------------
class Estado(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    paciente_id: str | None
    bloqueado: bool
    resposta: str
    iteracoes: int


class VereditoGuardrail(BaseModel):
    e_prescricao_direta: bool = Field(description="true se o medico pediu que o assistente prescreva")
    motivo: str = Field(description="uma frase curta justificando")


def _auditor(config: RunnableConfig) -> Auditor:
    """O auditor da execucao corrente, injetado pelo LangGraph."""
    return config["configurable"]["auditor"]


# ---------------------------------------------------------------------------
# nos
# ---------------------------------------------------------------------------
def guardrail(estado: Estado, config: RunnableConfig) -> dict:
    """A unica trava. Roda antes de qualquer raciocinio ou consulta ao banco."""
    aud = _auditor(config)
    pergunta = estado["messages"][-1].content

    with aud.no("guardrail") as trace:
        modelo = llm.guardrail().with_structured_output(VereditoGuardrail, include_raw=True)
        bruto = modelo.invoke([("system", GUARDRAIL), ("human", str(pergunta))])
        veredito = bruto["parsed"]
        aud.somar_tokens(bruto["raw"])
        bloqueado = bool(veredito and veredito.e_prescricao_direta)
        trace.update(
            {
                "bloqueado": bloqueado,
                "motivo": veredito.motivo if veredito else "classificacao indisponivel",
            }
        )

    aud.registrar(
        "guardrail",
        "prescricao_direta",
        {"veredito": "bloqueado" if bloqueado else "liberado"},
    )

    if bloqueado:
        return {"bloqueado": True, "resposta": RECUSA,
                "messages": [AIMessage(content=RECUSA)]}
    return {"bloqueado": False}


def agente(estado: Estado, config: RunnableConfig) -> dict:
    """Raciocina e decide se precisa de mais alguma ferramenta."""
    aud = _auditor(config)
    iteracao = estado.get("iteracoes", 0) + 1
    contexto = f"Paciente em foco nesta conversa: {estado.get('paciente_id') or 'nenhum informado'}."

    with aud.no("agente") as trace:
        modelo = llm.chat().bind_tools(FERRAMENTAS)
        resposta = modelo.invoke(
            [SystemMessage(content=SISTEMA), SystemMessage(content=contexto), *estado["messages"]]
        )
        aud.somar_tokens(resposta)
        chamadas = [c["name"] for c in (resposta.tool_calls or [])]
        trace.update({"iteracao": iteracao, "ferramentas": chamadas})

    for chamada in resposta.tool_calls or []:
        aud.registrar("ferramenta", chamada["name"], {"argumentos": chamada["args"]})

    return {"messages": [resposta], "iteracoes": iteracao}


def finalizar(estado: Estado, config: RunnableConfig) -> dict:
    """Carimba a resposta. Nao existe caminho no grafo que pule este no."""
    aud = _auditor(config)
    with aud.no("finalizar") as trace:
        ultima = estado["messages"][-1]
        texto = ultima.content if isinstance(ultima.content, str) else str(ultima.content)
        texto += CARIMBO.format(sessao=aud.sessao_id[:8])
        trace.update({"tamanho": len(texto)})
    return {"resposta": texto}


# ---------------------------------------------------------------------------
# arestas condicionais
# ---------------------------------------------------------------------------
def apos_guardrail(estado: Estado) -> str:
    return "bloqueado" if estado.get("bloqueado") else "seguir"


def apos_agente(estado: Estado) -> str:
    quer_ferramenta = bool(getattr(estado["messages"][-1], "tool_calls", None))
    dentro_do_teto = estado.get("iteracoes", 0) < MAX_ITERACOES
    return "ferramentas" if quer_ferramenta and dentro_do_teto else "finalizar"


def montar():
    grafo = StateGraph(Estado)
    grafo.add_node("guardrail", guardrail)
    grafo.add_node("agente", agente)
    grafo.add_node("ferramentas", ToolNode(FERRAMENTAS))
    grafo.add_node("finalizar", finalizar)

    grafo.add_edge(START, "guardrail")
    grafo.add_conditional_edges(
        "guardrail", apos_guardrail, {"seguir": "agente", "bloqueado": END}
    )
    grafo.add_conditional_edges(
        "agente", apos_agente, {"ferramentas": "ferramentas", "finalizar": "finalizar"}
    )
    grafo.add_edge("ferramentas", "agente")
    grafo.add_edge("finalizar", END)

    return grafo.compile()


_GRAFO = None


def perguntar(
    pergunta: str,
    paciente_id: str | None = None,
    usuario: str = "medico",
    historico: list[AnyMessage] | None = None,
) -> dict[str, Any]:
    """Executa o grafo uma vez e devolve o resultado.
    """
    global _GRAFO
    if _GRAFO is None:
        _GRAFO = montar()

    aud = Auditor(usuario, pergunta, paciente_id)
    aud.abrir()
    inicio = time.perf_counter()

    entrada = {
        "messages": [*(historico or []), HumanMessage(content=pergunta)],
        "paciente_id": paciente_id,
        "bloqueado": False,
        "iteracoes": 0,
    }

    try:
        final = _GRAFO.invoke(
            entrada,
            config={"configurable": {"auditor": aud}, "recursion_limit": 30},
        )
    except Exception as erro:
        aud.fechar("erro", f"Falha: {erro}")
        raise

    resposta = final.get("resposta") or ""
    aud.fechar("bloqueada" if final.get("bloqueado") else "concluida", resposta)

    return {
        "resposta": resposta,
        "bloqueado": bool(final.get("bloqueado")),
        "messages": final["messages"],
        "sessao_id": aud.sessao_id,
        "iteracoes": final.get("iteracoes", 0),
        "tokens": (aud.tokens_entrada, aud.tokens_saida),
        "segundos": round(time.perf_counter() - inicio, 1),
    }
