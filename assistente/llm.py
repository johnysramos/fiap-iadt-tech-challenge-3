"""Modelos da OpenAI.

Tres papeis, tres modelos, escolhidos por custo:

* chat      gpt-4.1-mini  raciocinio e redacao, com tool calling confiavel
* guardrail gpt-4.1-nano  classificacao binaria, roda a cada pergunta
* embedding text-embedding-3-small  1536 dimensoes, casa com o vector(1536)
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from assistente import config


@lru_cache(maxsize=1)
def chat() -> ChatOpenAI:
    return ChatOpenAI(
        model=config.MODELO_CHAT,
        temperature=0,
        api_key=config.OPENAI_API_KEY,
        timeout=60,
    )


@lru_cache(maxsize=1)
def guardrail() -> ChatOpenAI:
    return ChatOpenAI(
        model=config.MODELO_GUARDRAIL,
        temperature=0,
        api_key=config.OPENAI_API_KEY,
        timeout=30,
    )


@lru_cache(maxsize=1)
def embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=config.MODELO_EMBEDDING, api_key=config.OPENAI_API_KEY
    )
