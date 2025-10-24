from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich import box
from rich.text import Text
import time

console = Console()

class WayOutWestDisplay:
    def __init__(self):
        self.console = Console()
        self.turn = 0
        self.phase = "Setup"
        self.alive_count = {"locals": 6, "out_of_towners": 3, "natives": 1}
        
    def show_header(self):
        header = Panel(
            "[bold yellow]🤠 WAY OUT WEST - Murder Mystery in Cactus Gulch 🤠[/bold yellow]\n"
            f"[cyan]Phase: {self.phase}[/cyan] | [green]Turn: {self.turn}[/green]",
            box=box.DOUBLE,
            style="white on dark_blue"
        )
        self.console.print(header)
    
    def show_teams(self):
        table = Table(title="Character Status", box=box.ROUNDED)
        table.add_column("Team", style="cyan", no_wrap=True)
        table.add_column("Alive", style="green")
        table.add_column("Status", style="yellow")
        
        for team, count in self.alive_count.items():
            status = "✅ Active" if count > 0 else "💀 Eliminated"
            table.add_row(team.upper(), str(count), status)
        
        self.console.print(table)
    
    def show_action(self, character, action_type, text, team="locals"):
        # Color by team
        colors = {
            "locals": "blue",
            "out_of_towners": "red",
            "natives": "green"
        }
        color = colors.get(team, "white")
        
        # Truncate long text
        display_text = text[:200] + "..." if len(text) > 200 else text
        
        panel = Panel(
            f"[{color}]{character}[/{color}]: {display_text}",
            title=f"[bold]{action_type.upper()}[/bold]",
            border_style=color,
            box=box.ROUNDED
        )
        self.console.print(panel)
        time.sleep(0.5)  # Pause for readability
    
    def show_phase_transition(self, new_phase, message):
        self.phase = new_phase
        transition = Panel(
            f"[bold magenta]{message}[/bold magenta]",
            title=f"📜 PHASE CHANGE: {new_phase.upper()}",
            box=box.DOUBLE_EDGE,
            style="magenta"
        )
        self.console.print(transition)
        time.sleep(2)
    
    def show_death(self, character, killer=None):
        death_text = f"💀 {character} has died!"
        if killer:
            death_text += f"\n[red]Killed by: {killer}[/red]"
        
        panel = Panel(
            death_text,
            title="[bold red]DEATH[/bold red]",
            border_style="red",
            box=box.HEAVY
        )
        self.console.print(panel)
        time.sleep(1.5)
    
    def show_winner(self, team, message):
        winner = Panel(
            f"[bold gold1]🏆 {team.upper()} WINS! 🏆[/bold gold1]\n\n{message}",
            title="GAME OVER",
            box=box.DOUBLE_EDGE,
            style="gold1 on black",
            padding=(2, 4)
        )
        self.console.print(winner)