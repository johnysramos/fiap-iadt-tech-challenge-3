"""Assistente clinico do hospital -- ponto de entrada.

    python main.py            conversa com o assistente
    python main.py setup      carrega o banco e calcula os embeddings
"""

import sys

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from assistente import config
from assistente.db import consultar, rodar_script

console = Console()

# O console legado do Windows abre em cp1252 e engole os acentos das respostas.
for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")

EXEMPLOS = [
    ("P-0001", "Quais os dados e exames deste paciente?"),
    ("P-0002", "O que o protocolo recomenda para o INR deste paciente?"),
    ("P-0003", "Sugira o tratamento adequado para este paciente."),
    ("P-0004", "Quais consultas ele tem marcadas?"),
    ("P-0005", "Marque um retorno na pneumologia daqui a 15 dias."),
]


# ---------------------------------------------------------------------------
def cmd_setup() -> None:
    """Carrega os dados e calcula os embeddings."""
    from assistente.indexar import indexar, pendentes

    config.checar_chave()

    arquivos = sorted(config.PASTA_SQL.glob("*.sql"))
    if not arquivos:
        console.print(f"[red]Nenhum .sql em {config.PASTA_SQL}[/]")
        raise SystemExit(1)

    try:
        with console.status("Aplicando os arquivos SQL..."):
            for arquivo in arquivos:
                rodar_script(arquivo.read_text(encoding="utf-8"))
    except Exception as erro:
        console.print(
            f"[red]Nao consegui falar com o banco.[/]\n{erro}\n\n"
            "O container esta de pe? Tente: [bold]docker compose up -d[/]"
        )
        raise SystemExit(1) from None

    console.print("Aplicados: " + ", ".join(f"[cyan]{a.name}[/]" for a in arquivos))

    tabela = Table(title="Dados carregados", header_style="bold")
    tabela.add_column("tabela", style="cyan")
    tabela.add_column("linhas", justify="right")
    for nome in (
        "clinical.pacientes", "clinical.condicoes", "clinical.alergias",
        "clinical.encontros", "clinical.exames", "clinical.prescricoes",
        "clinical.consultas", "knowledge.protocolos", "knowledge.trechos",
    ):
        total = consultar(f"SELECT count(*) AS n FROM {nome}")[0]["n"]
        tabela.add_row(nome, f"{total:,}".replace(",", "."))
    console.print(tabela)

    faltando = pendentes()
    if faltando:
        with console.status(f"Calculando embeddings de {faltando} trechos...") as st:
            total = indexar(anunciar=lambda m: st.update(f"Calculando embeddings: {m}"))
        console.print(f"[green]Pronto.[/] {total} trechos indexados.")
    else:
        console.print("[green]Pronto.[/] Os embeddings ja estavam calculados.")

    console.print("\nAgora rode: [bold]python main.py[/]")


# ---------------------------------------------------------------------------
def cmd_chat() -> None:
    """Conversa com o assistente."""
    from assistente.grafo import perguntar

    config.checar_chave()

    try:
        indexados = consultar(
            "SELECT count(*) AS n FROM knowledge.trechos WHERE embedding IS NOT NULL"
        )[0]["n"]
    except Exception as erro:
        console.print(
            f"[red]Nao consegui falar com o banco.[/]\n{erro}\n\n"
            "Suba o container com [bold]docker compose up -d[/] e rode "
            "[bold]python main.py setup[/]."
        )
        raise SystemExit(1) from None

    if not indexados:
        console.print(
            "[yellow]Os protocolos ainda nao foram indexados.[/]\n"
            "Rode [bold]python main.py setup[/] uma vez antes de comecar."
        )
        raise SystemExit(1)

    exemplos = "\n".join(f"  [dim]{p}[/]  {q}" for p, q in EXEMPLOS)
    console.print(
        Panel(
            "Digite a pergunta e Enter.\n"
            "[dim]/paciente P-0002[/] troca o paciente em foco  ·  "
            "[dim]sair[/] encerra.\n\n"
            f"Exemplos:\n{exemplos}",
            title="[bold]Assistente clinico[/]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    paciente = "P-0001"
    historico: list = []

    while True:
        try:
            pergunta = console.input(f"\n[bold cyan]{paciente} >[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not pergunta or pergunta.lower() in {"sair", "exit", "quit"}:
            break

        if pergunta.lower().startswith("/paciente"):
            partes = pergunta.split()
            if len(partes) > 1:
                paciente = partes[1].upper()
                historico = []
                console.print(f"[dim]Paciente em foco: {paciente}. Conversa reiniciada.[/]")
            continue

        with console.status("Consultando..."):
            r = perguntar(pergunta, paciente, historico=historico)

        console.print()
        console.print(
            Panel(
                Markdown(r["resposta"]),
                border_style="red" if r["bloqueado"] else "cyan",
                padding=(1, 2),
            )
        )
        console.print(
            f"[dim]sessao {r['sessao_id'][:8]}  ·  {r['iteracoes']} iteracoes  ·  "
            f"{r['tokens'][0]}/{r['tokens'][1]} tokens  ·  {r['segundos']}s[/]"
        )

        # Guarda so o par pergunta/resposta: o vaivem com as ferramentas nao
        # precisa voltar ao modelo na proxima rodada.
        historico.append(HumanMessage(content=pergunta))
        historico.append(AIMessage(content=r["resposta"].split("\n\n---\n")[0]))


# ---------------------------------------------------------------------------
def ajuda() -> None:
    """Imprime o docstring como texto puro.
    """
    console.print(__doc__ or "", highlight=False)


def main() -> None:
    comando = sys.argv[1] if len(sys.argv) > 1 else "chat"
    if comando == "setup":
        cmd_setup()
    elif comando == "chat":
        cmd_chat()
    elif comando in {"-h", "--help", "help"}:
        ajuda()
    else:
        console.print(f"[red]Comando desconhecido: {comando}[/]\n")
        ajuda()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
