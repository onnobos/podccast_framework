import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from rich.console import Console
from src.config import settings

console = Console()
AUTH_STATE_PATH = Path(".auth/storageState.json")

def ensure_authenticated(force: bool = False) -> Path:
    """Ensure persistent Playwright browser auth state exists."""
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if AUTH_STATE_PATH.exists() and not force:
        console.print(f"[green]Found existing auth state at {AUTH_STATE_PATH}[/green]")
        return AUTH_STATE_PATH

    if force and AUTH_STATE_PATH.exists():
        console.print("[yellow]Force flag set. Removing old auth state...[/yellow]")
        AUTH_STATE_PATH.unlink()

    console.print("[bold yellow]No session state found. Launching browser for login...[/bold yellow]")
    console.print(f"Target email: [cyan]{settings.VOLLEYBRAINS_EMAIL}[/cyan]")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Open sign-in modal directly (Ghost CMS portal)
        console.print("[bold cyan]Navigating to VolleyBrains Sign In...[/bold cyan]")
        page.goto("https://volleybrains.com/#/portal/signin", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Attempt to auto-fill email if field present
        try:
            email_input = page.locator("input[type='email']")
            if email_input.is_visible(timeout=3000):
                email_input.fill(settings.VOLLEYBRAINS_EMAIL)
                console.print(f"[green]Auto-filled email:[/green] {settings.VOLLEYBRAINS_EMAIL}")
                page.locator("button[type='submit']").click()
                console.print("[cyan]Submitted email form. Check mailbox for auth code...[/cyan]")
        except Exception as e:
            console.print("[dim]Manual email entry required in browser.[/dim]")

        console.print("\n[bold yellow]====================================================[/bold yellow]")
        console.print("[bold yellow]1. Check your email for authentication code/link.[/bold yellow]")
        console.print("[bold yellow]2. Enter code in the opened browser window.[/bold yellow]")
        console.print("[bold yellow]3. Once logged in, press ENTER in this terminal to save session.[/bold yellow]")
        console.print("[bold yellow]====================================================[/bold yellow]\n")

        input("Press ENTER after login is complete (page shows your member profile or full content): ")
        page.wait_for_timeout(3000)

        state = context.storage_state(path=str(AUTH_STATE_PATH))
        cookies = state.get("cookies", [])
        console.print(f"[bold green]Saved session state with {len(cookies)} cookies to {AUTH_STATE_PATH}[/bold green]")
        browser.close()

    return AUTH_STATE_PATH

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Authenticate VolleyBrains Playwright session.")
    parser.add_argument("--force", action="store_true", help="Force re-authentication")
    args = parser.parse_args()

    # If run directly as module, default to force=True if stale or requested
    ensure_authenticated(force=args.force or True)
