"""Configuracao do projeto.

Carrega dados do .env e define constantes para o projeto.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_ENV = RAIZ / ".env"
PASTA_SQL = RAIZ / "db"


def _ler_env() -> dict[str, str]:
    valores: dict[str, str] = {}
    if not ARQUIVO_ENV.exists():
        return valores
    for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


_ENV = _ler_env()

# --- OpenAI ---------------------------------------------------------------
OPENAI_API_KEY = _ENV.get("OPENAI_API_KEY", "")
MODELO_CHAT = _ENV.get("MODELO_CHAT", "gpt-4.1-mini")
MODELO_GUARDRAIL = _ENV.get("MODELO_GUARDRAIL", "gpt-4.1-nano")
MODELO_EMBEDDING = _ENV.get("MODELO_EMBEDDING", "text-embedding-3-small")

# --- Banco ----------------------------------------------------------------
DATABASE_URL = _ENV.get(
    "DATABASE_URL", "postgresql+psycopg://anamnese:anamnese@localhost:55432/anamnese"
)

# --- Limites --------------------------------------------------------------
MAX_ITERACOES = int(_ENV.get("MAX_ITERACOES", "5"))


def checar_chave() -> None:
    if not OPENAI_API_KEY:
        raise SystemExit(
            "OPENAI_API_KEY nao encontrada.\n"
            f"Crie o arquivo {ARQUIVO_ENV} com a linha:\n\n"
            "    OPENAI_API_KEY=sk-...\n\n"
            "Ha um modelo pronto em .env.example."
        )
