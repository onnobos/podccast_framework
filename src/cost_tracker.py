from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

class CostTracker:
    def __init__(self):
        self.total_cost = 0.0
        self.breakdown = []

    def log_whisper(self, duration_sec: float, model: str = "whisper-1") -> float:
        cost = (duration_sec / 60.0) * 0.006
        self.total_cost += cost
        self.breakdown.append(("Whisper Transcription", f"{duration_sec:.1f} sec audio", model, f"${cost:.4f}"))
        return cost

    def log_llm(self, prompt_tokens: int, completion_tokens: int, model: str, step_label: str = "LLM Call") -> float:
        m_lower = model.lower()
        if "flash" in m_lower or "gemini" in m_lower:
            p_rate, c_rate = 0.075, 0.30
        elif "gpt-4o" in m_lower:
            p_rate, c_rate = 2.50, 10.00
        else: # Claude Sonnet default
            p_rate, c_rate = 3.00, 15.00

        cost = (prompt_tokens / 1_000_000 * p_rate) + (completion_tokens / 1_000_000 * c_rate)
        self.total_cost += cost
        tokens_info = f"{prompt_tokens:,} in / {completion_tokens:,} out"
        self.breakdown.append((step_label, tokens_info, model, f"${cost:.4f}"))
        return cost

    def log_tts(self, char_count: int, model: str = "tts-1-hd") -> float:
        cost = (char_count / 1000.0) * 0.030
        self.total_cost += cost
        self.breakdown.append(("TTS Speech Synthesis", f"{char_count:,} characters", model, f"${cost:.4f}"))
        return cost

    def print_summary(self):
        if not self.breakdown:
            return

        table = Table(title="API Cost Breakdown Per Call", title_style="bold cyan", show_header=True, header_style="bold magenta")
        table.add_column("Step / Operation", style="yellow")
        table.add_column("Usage Metrics", style="dim")
        table.add_column("Model Used", style="cyan")
        table.add_column("Cost (USD)", style="bold green", justify="right")

        for step, metrics, model, cost_str in self.breakdown:
            table.add_row(step, metrics, model, cost_str)

        table.add_section()
        table.add_row("[bold white]TOTAL API COST[/bold white]", "", "", f"[bold green]${self.total_cost:.4f}[/bold green]")

        console.print("\n")
        console.print(table)
        console.print("\n")

cost_tracker = CostTracker()
