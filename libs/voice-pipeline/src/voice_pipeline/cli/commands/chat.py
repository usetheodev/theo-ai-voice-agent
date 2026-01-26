"""Chat command - Text-based conversation with the agent."""

import asyncio
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt

console = Console()


async def run_chat(
    model: str,
    system_prompt: Optional[str],
    temperature: float,
):
    """Run text-based chat session.

    Args:
        model: LLM model name.
        system_prompt: Optional system prompt.
        temperature: LLM temperature.
    """
    from voice_pipeline import VoiceAgent

    console.print(Panel(
        "[bold blue]Voice Pipeline Chat[/bold blue]\n"
        f"Model: [cyan]{model}[/cyan]\n"
        "Type 'quit' or 'exit' to end the session.\n"
        "Type 'clear' to clear conversation history.",
        title="Welcome",
    ))

    # Create agent
    try:
        agent = VoiceAgent.local(
            llm_model=model,
            system_prompt=system_prompt or "You are a friendly and helpful voice assistant. Respond concisely.",
        )
        await agent.llm.connect()
        console.print("[green]Agent connected successfully![/green]\n")
    except Exception as e:
        console.print(f"[red]Error connecting to agent: {e}[/red]")
        console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
        return

    # Chat loop
    try:
        while True:
            try:
                user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input.strip():
                continue

            if user_input.lower() in ("quit", "exit", "sair"):
                console.print("[yellow]Goodbye![/yellow]")
                break

            if user_input.lower() == "clear":
                await agent.clear_memory()
                console.print("[yellow]Conversation cleared.[/yellow]")
                continue

            # Stream response
            console.print("[bold green]Assistant[/bold green]: ", end="")

            response_text = ""
            try:
                async for token in agent.astream(user_input):
                    console.print(token, end="")
                    response_text += token
            except Exception as e:
                console.print(f"\n[red]Error: {e}[/red]")
                continue

            console.print()  # New line after response
            console.print()  # Extra spacing

    finally:
        # Cleanup
        if hasattr(agent.llm, 'disconnect'):
            await agent.llm.disconnect()


if __name__ == "__main__":
    asyncio.run(run_chat("qwen2.5:0.5b", None, 0.7))
