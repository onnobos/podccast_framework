import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.scraper import scrape_article, get_url_slug
from src.transcriber import merge_article_and_transcripts
from src.scriptwriter import generate_podcast_script, generate_article_summary
from src.script_verifier import verify_and_refine_script, compute_trainer_audio_ratio
from src.audio_engine import generate_podcast_audio
from src.rss_publisher import publish_episode, delete_episode_from_r2
from src.cost_tracker import cost_tracker
from src.framework import registry, get_active_plugin
from src.memory_manager import update_podcast_memory, rebuild_all_show_memory

app = typer.Typer(help="Podcast Pipeline CLI (Framework & Plugins)", no_args_is_help=False)
console = Console()

def get_available_episodes() -> list[dict]:
    """Scan output/ directory and return all discovered podcast episode records with creation dates."""
    episodes = {}

    # Read feed.xml pubDates if available
    feed_dates = {}
    feed_path = Path("output/feed.xml")
    if feed_path.exists():
        try:
            tree = ET.parse(feed_path)
            for item in tree.findall(".//item"):
                enclosure = item.find("enclosure")
                pub_date = item.find("pubDate")
                if enclosure is not None and pub_date is not None and pub_date.text:
                    url = enclosure.get("url", "")
                    slug = url.split("/")[-1].replace("_master.mp3", "").replace(".mp3", "")
                    dt = parsedate_to_datetime(pub_date.text)
                    feed_dates[slug] = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # 1. Scraped markdown files
    for f in Path("output").glob("scraped_*.md"):
        slug = f.stem.replace("scraped_", "")
        if slug in {"article"}:
            continue
        episodes.setdefault(slug, {"slug": slug, "scraped": True, "master": False, "script": False, "audio": False, "title": "", "created_date": ""})
        episodes[slug]["scraped"] = True

    # 2. Master content files
    for f in Path("output").glob("master_*.md"):
        slug = f.stem.replace("master_", "")
        if slug in {"content"}:
            continue
        episodes.setdefault(slug, {"slug": slug, "scraped": False, "master": True, "script": False, "audio": False, "title": "", "created_date": ""})
        episodes[slug]["master"] = True

    # 3. Generated scripts
    for f in Path("output/scripts").glob("*_script.md"):
        slug = f.stem.replace("_script", "")
        if slug in {"demo_clip", "script", "master_content"}:
            continue
        episodes.setdefault(slug, {"slug": slug, "scraped": False, "master": False, "script": True, "audio": False, "title": "", "created_date": ""})
        episodes[slug]["script"] = True

    # 4. Master audio episodes
    for f in Path("output/audio").glob("*_master.mp3"):
        slug = f.stem.replace("_master", "")
        if slug in {"demo_clip", "episode"}:
            continue
        episodes.setdefault(slug, {"slug": slug, "scraped": False, "master": False, "script": False, "audio": True, "title": "", "created_date": ""})
        episodes[slug]["audio"] = True

    # Extract readable titles and dates from master, scraped, or audio files
    for slug, data in episodes.items():
        title = slug.replace("-", " ").replace("_", " ").title()
        master_file = Path(f"output/master_{slug}.md")
        scraped_file = Path(f"output/scraped_{slug}.md")
        script_file = Path(f"output/scripts/{slug}_script.md")
        audio_file = Path(f"output/audio/{slug}_master.mp3")

        target_file = master_file if master_file.exists() else (scraped_file if scraped_file.exists() else None)
        if target_file:
            try:
                for line in target_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("# "):
                        title = line.replace("# ", "").strip()
                        break
            except Exception:
                pass
        data["title"] = title

        # Determine creation date: feed pubDate or earliest/latest local file mtime
        if slug in feed_dates:
            data["created_date"] = feed_dates[slug]
        else:
            ref_file = audio_file if audio_file.exists() else (script_file if script_file.exists() else (master_file if master_file.exists() else scraped_file))
            if ref_file and ref_file.exists():
                data["created_date"] = datetime.fromtimestamp(ref_file.stat().st_mtime).strftime("%Y-%m-%d")
            else:
                data["created_date"] = "—"

    # Filter to real masterclass episodes only (must have scraped or master content, not test/demo artifacts)
    real_episodes = [
        ep for ep in episodes.values()
        if (ep["scraped"] or ep["master"])
        and not ep["slug"].startswith("test_")
        and not ep["slug"].startswith("demo_")
        and ep["slug"] not in {"voice_demo", "demo_clip", "script", "master_content", "article"}
    ]

    return sorted(real_episodes, key=lambda x: x["slug"])

def run_pipeline_for_slug(
    slug: str,
    url: str,
    force_scrape: bool = False,
    force_transcribe: bool = False,
    force_curate: bool = False,
    skip_scrape: bool = False,
    skip_transcribe: bool = False,
    publish: bool = False,
    headless: bool = False,
    skip_review: bool = False,
    plugin_name: str = "volleyball"
):
    """Execute end-to-end pipeline for a given episode slug using active show plugin."""
    plugin = registry.get_plugin(plugin_name) or registry.active_plugin
    console.print(Panel(f"[bold green]Running Pipeline for Episode: {slug} [Plugin: {plugin.name}][/bold green]", expand=False))

    scraped_md_path = Path(f"output/scraped_{slug}.md")
    master_content_path = Path(f"output/master_{slug}.md")

    # Step 1: Ingest Content Source (auto-skip if already exists)
    if scraped_md_path.exists() and scraped_md_path.stat().st_size > 200 and not force_scrape and not skip_scrape:
        console.print(f"[bold green]Step 1/6: Scraped article already exists at {scraped_md_path} ({scraped_md_path.stat().st_size} bytes). Skipping scrape step.[/bold green]")
    else:
        console.print(f"[bold cyan]Step 1/6: Ingesting source using {plugin.name} ingester...[/bold cyan]")
        try:
            ingester = plugin.get_ingester()
            ingester.ingest(url, force_scrape=force_scrape, headless=headless)
        except Exception:
            scrape_article(url, output_path=scraped_md_path, headless=headless)

    # Step 2: Transcribe Videos & Build Master Content (auto-skip if slug master exists)
    if master_content_path.exists() and master_content_path.stat().st_size > 500 and not force_transcribe and not skip_transcribe:
        console.print(f"[bold green]Step 2/6: Master content already exists at {master_content_path} ({master_content_path.stat().st_size} bytes). Skipping transcribe step.[/bold green]")
    else:
        console.print("[bold cyan]Step 2/6: Transcribing Videos & Assembling Master Content...[/bold cyan]")
        merge_article_and_transcripts(scraped_md_path, master_content_path)

    # Step 3: Synthesize 2-Host Script
    console.print(f"[bold cyan]Step 3/6: Generating 2-Host Podcast Script ({plugin.name})...[/bold cyan]")
    output_script_path = Path(f"output/scripts/{slug}_script.md")
    script_path = generate_podcast_script(master_content_path, output_script_path=output_script_path, force_curate=force_curate, plugin=plugin)

    # Step 3.5: Automated Fact-Check Audit & Refinement Loop (97%+ Target)
    console.print("[bold cyan]Step 3.5/6: Running Fact-Check Audit & Verification Loop (97%+ Target)...[/bold cyan]")
    verify_and_refine_script(master_content_path, script_path, min_score=97.0, plugin=plugin)

    # Step 3.6: Update Show Institutional Memory (MEMORY.md)
    console.print(f"[bold cyan]Step 3.6/6: Updating Show Knowledge Memory (MEMORY.md) for {plugin.name}...[/bold cyan]")
    try:
        update_podcast_memory(master_content_path, script_path=script_path, plugin=plugin)
    except Exception as mem_err:
        console.print(f"[yellow]Note: Memory update skipped ({mem_err})[/yellow]")

    # Step 4: Interactive Human-in-the-Loop Pause (AGENTS.md Requirement, Skipped if skip_review=True)
    script_txt = script_path.read_text(encoding="utf-8")
    clip_sec, host_words, host_sec, total_sec, ratio_pct = compute_trainer_audio_ratio(script_txt)
    target_ratio = getattr(getattr(plugin, "script_config", None), "target_clip_ratio", 0.40) * 100.0
    badge = f"[bold green][PASS: >= {target_ratio:.0f}% EXPERT VOICE][/bold green]" if ratio_pct >= target_ratio else f"[bold yellow][WARNING: {ratio_pct:.1f}% < {target_ratio:.0f}% TARGET][/bold yellow]"

    console.print("\n" + "=" * 76)
    console.print(f"[bold yellow]Script confirmed at: [cyan]{script_path}[/cyan][/bold yellow]")
    console.print(
        f"Expert Audio: [bold cyan]{clip_sec:.1f}s ({clip_sec/60:.1f}m)[/bold cyan] | "
        f"Host Dialogue: [bold cyan]{host_words} words ({host_sec/60:.1f}m)[/bold cyan] | "
        f"Ratio: [bold]{ratio_pct:.1f}%[/bold] {badge}"
    )

    if not skip_review:
        console.print("[bold yellow]Review or edit the script now in your editor.[/bold yellow]")
        console.print("[bold yellow]Press [ENTER] to confirm and begin Audio Synthesis, or type 'q' to abort.[/bold yellow]")
        console.print("=" * 76 + "\n")

        user_input = input("Proceed to Audio Synthesis? (ENTER / 'q'): ").strip().lower()
        if user_input == 'q':
            console.print("[bold red]Pipeline aborted by user. Script saved for editing.[/bold red]")
            sys.exit(0)
    else:
        console.print("[dim]Skipping manual script review pause (skip_review active). Proceeding to audio synthesis...[/dim]")
        console.print("=" * 76 + "\n")

    # Step 5: Audio Synthesis & Studio Engine
    console.print("[bold cyan]Step 5/6: Synthesizing Audio & Mixing Studio Master...[/bold cyan]")
    output_audio_path = Path(f"output/audio/{slug}_master.mp3")
    audio_path = generate_podcast_audio(script_path, output_audio_path=output_audio_path, plugin=plugin)

    # Step 6: Cloudflare R2 RSS Publishing
    if publish:
        console.print(f"[bold cyan]Step 6/6: Uploading Episode & Publishing RSS Feed ({plugin.name})...[/bold cyan]")
        episode_title = f"Masterclass: {slug.replace('_', ' ').replace('-', ' ').title()}"
        episode_summary = generate_article_summary(master_content_path, plugin=plugin)
        publish_episode(audio_path, title=episode_title, description=episode_summary, plugin=plugin)
    else:
        console.print("[dim]Step 6/6: Skipping R2 publishing. Pass --publish to upload episode and update RSS feed.[/dim]")

    # Step 7: Display API Cost Breakdown
    cost_tracker.print_summary()
    console.print(f"\n[bold green]SUCCESS: {plugin.name.upper()} PIPELINE COMPLETED SUCCESSFULLY![/bold green]")

def run_audio_only_rebuild(slug: str, publish: bool = False, plugin_name: str = "volleyball"):
    """Rebuild audio master directly from an existing script without re-calling LLM script generator."""
    plugin = registry.get_plugin(plugin_name) or registry.active_plugin
    script_path = Path(f"output/scripts/{slug}_script.md")
    if not script_path.exists():
        fallback = Path("output/scripts/script.md")
        if fallback.exists():
            script_path = fallback
        else:
            console.print(f"[bold red]Script file for episode '{slug}' not found at {script_path}.[/bold red]")
            sys.exit(1)

    console.print(Panel(f"[bold green]Rebuilding Studio Audio Master for: {slug} [Plugin: {plugin.name}][/bold green]", expand=False))
    output_audio_path = Path(f"output/audio/{slug}_master.mp3")
    audio_path = generate_podcast_audio(script_path, output_audio_path=output_audio_path, plugin=plugin)

    if publish:
        console.print("[bold cyan]Uploading Episode & Publishing RSS Feed to Cloudflare R2...[/bold cyan]")
        master_content_path = Path(f"output/master_{slug}.md")
        episode_title = f"Masterclass: {slug.replace('_', ' ').replace('-', ' ').title()}"
        episode_summary = generate_article_summary(master_content_path, plugin=plugin) if master_content_path.exists() else f"Masterclass breakdown for {episode_title}"
        publish_episode(audio_path, title=episode_title, description=episode_summary, plugin=plugin)

    cost_tracker.print_summary()
    console.print("\n[bold green]SUCCESS: AUDIO MASTER REBUILT SUCCESSFULLY![/bold green]")


@app.command(name="plugins")
def list_plugins_cmd():
    """List all installed podcast show plugins."""
    plugins = registry.list_plugins()
    table = Table(title="Installed Podcast Plugins")
    table.add_column("Slug", style="bold cyan")
    table.add_column("Name", style="green")
    table.add_column("Hosts", style="yellow")
    table.add_column("Target Duration", justify="center")
    for slug, p in plugins.items():
        hosts_str = ", ".join(f"{h.name} ({h.voice})" for h in p.hosts.values())
        table.add_row(slug, p.name, hosts_str, f"{p.script_config.target_duration_min}m")
    console.print(table)


@app.command(name="memory")
def memory_cmd(
    action: str = typer.Argument("show", help="Action: 'show' (display memory), 'update' (single episode), or 'rebuild' (rebuild all memory)"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="Episode slug to update"),
    plugin: str = typer.Option("volleyball", "--plugin", help="Podcast show plugin to use"),
    fresh: bool = typer.Option(False, "--fresh", "-f", help="Fresh rebuild: reset memory file before re-extracting")
):
    """Manage show institutional memory (MEMORY.md) across episodes."""
    plugin_obj = registry.get_plugin(plugin) or registry.active_plugin
    if action.lower() == "show":
        mem = plugin_obj.get_memory()
        if not mem:
            console.print(f"[yellow]No memory found in {plugin_obj.memory_path}[/yellow]")
        else:
            console.print(Panel(mem, title=f"Show Memory — {plugin_obj.name}", expand=False))
    elif action.lower() == "update":
        if not slug:
            console.print("[bold red]Please specify --slug <episode_slug> to update memory.[/bold red]")
            sys.exit(1)
        master_file = Path(f"output/master_{slug}.md")
        if not master_file.exists():
            console.print(f"[bold red]Master content not found for slug '{slug}' at {master_file}.[/bold red]")
            sys.exit(1)
        script_file = Path(f"output/scripts/{slug}_script.md")
        update_podcast_memory(master_file, script_path=script_file if script_file.exists() else None, plugin=plugin_obj)
        console.print(f"[bold green]Successfully updated memory for '{slug}' in {plugin_obj.memory_path}[/bold green]")
    elif action.lower() == "rebuild":
        if slug:
            master_file = Path(f"output/master_{slug}.md")
            if not master_file.exists():
                console.print(f"[bold red]Master content not found for slug '{slug}' at {master_file}.[/bold red]")
                sys.exit(1)
            script_file = Path(f"output/scripts/{slug}_script.md")
            update_podcast_memory(master_file, script_path=script_file if script_file.exists() else None, plugin=plugin_obj)
            console.print(f"[bold green]Rebuilt memory for '{slug}' in {plugin_obj.memory_path}[/bold green]")
        else:
            rebuild_all_show_memory(plugin=plugin_obj, fresh=fresh)
    else:
        console.print(f"[bold red]Unknown action '{action}'. Use 'show', 'update', or 'rebuild'.[/bold red]")


@app.command()
def generate(
    url: str = typer.Argument(..., help="Article or source URL"),
    plugin: str = typer.Option("volleyball", "--plugin", help="Podcast show plugin to use (default: volleyball)"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode (default: False for headful browser window)"),
    force_scrape: bool = typer.Option(False, "--force-scrape", help="Force re-scraping even if scraped article exists"),
    force_transcribe: bool = typer.Option(False, "--force-transcribe", help="Force re-transcribing even if master content exists"),
    skip_scrape: bool = typer.Option(False, "--skip-scrape", help="Legacy flag: skip scraping"),
    skip_transcribe: bool = typer.Option(False, "--skip-transcribe", help="Legacy flag: skip transcription"),
    publish: bool = typer.Option(False, "--publish", help="Publish episode and update RSS feed to Cloudflare R2"),
    skip_review: bool = typer.Option(False, "--skip-review", "-y", help="Skip manual script review pause and proceed directly to audio")
):
    """Run full content to podcast pipeline for a given URL using selected plugin."""
    plugin_obj = registry.get_plugin(plugin) or registry.active_plugin
    slug = plugin_obj.get_ingester().get_slug(url) if hasattr(plugin_obj, "get_ingester") else get_url_slug(url)
    run_pipeline_for_slug(
        slug=slug,
        url=url,
        force_scrape=force_scrape,
        force_transcribe=force_transcribe,
        skip_scrape=skip_scrape,
        skip_transcribe=skip_transcribe,
        publish=publish,
        headless=headless,
        skip_review=skip_review,
        plugin_name=plugin
    )

def parse_episode_selection(choice: str, episodes: list[dict]) -> list[dict]:
    """Parse single or multiple episode selections: indices ('1, 3, 4'), ranges ('1-4'), 'all', or slugs."""
    choice = choice.strip()
    if not choice or choice.lower() == 'q':
        return []

    if choice.lower() in {'all', '*'}:
        return [ep for ep in episodes]

    selected = []
    slug_map = {ep["slug"].lower(): ep for ep in episodes}

    # Split by comma or whitespace
    tokens = [t.strip() for t in choice.replace(',', ' ').split() if t.strip()]

    for token in tokens:
        # Range e.g. 1-4
        if '-' in token and not token.startswith('-'):
            parts = token.split('-', 1)
            if parts[0].isdigit() and parts[1].isdigit():
                start_idx, end_idx = int(parts[0]), int(parts[1])
                for idx in range(start_idx, end_idx + 1):
                    if 1 <= idx <= len(episodes):
                        ep = episodes[idx - 1]
                        if ep not in selected:
                            selected.append(ep)
                continue

        # Single numeric index
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(episodes):
                ep = episodes[idx - 1]
                if ep not in selected:
                    selected.append(ep)
            continue

        # Exact slug match (case insensitive)
        if token.lower() in slug_map:
            ep = slug_map[token.lower()]
            if ep not in selected:
                selected.append(ep)

    return selected

@app.command()
def rebuild(
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="Episode slug(s) or indices to rebuild (e.g. 'andre-sa,dan-lewis', '1,3', 'all')"),
    plugin: str = typer.Option("volleyball", "--plugin", help="Podcast show plugin to use (default: volleyball)"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help="Rebuild mode: 'scratch' (full pipeline), 'recurate' (re-curate storylines + script + audio), 'script' (script + audio), 'audio' (audio only)"),
    force_curate: bool = typer.Option(False, "--force-curate", "-c", help="Force re-curating fresh storylines with Olympic Coach Curator"),
    publish: bool = typer.Option(False, "--publish", "-p", help="Publish regenerated episode(s) to Cloudflare R2"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode if re-scraping"),
    skip_review: bool = typer.Option(False, "--skip-review", "-y", help="Skip manual script review pause")
):
    """Interactively select and reproduce/rebuild single or multiple podcast episodes."""
    if not isinstance(slug, str):
        slug = None
    if not isinstance(mode, str):
        mode = None
    if not isinstance(publish, bool):
        publish = False
    if not isinstance(headless, bool):
        headless = False

    episodes = get_available_episodes()
    if not episodes:
        console.print("[bold red]No existing podcast episodes found in output/ directory.[/bold red]")
        sys.exit(1)

    selected_episodes = []
    if slug:
        selected_episodes = parse_episode_selection(slug, episodes)
        if not selected_episodes:
            console.print(f"[bold red]No valid episodes matching '{slug}' found in output/ directory.[/bold red]")
            sys.exit(1)
    else:
        # Show interactive selection table
        table = Table(title="Available Podcast Episodes to Reproduce / Rebuild")
        table.add_column("#", style="cyan", justify="right", no_wrap=True)
        table.add_column("Slug", style="bold yellow", no_wrap=True)
        table.add_column("Coach / Masterclass Title", style="white", overflow="ellipsis")
        table.add_column("Created", style="dim cyan", justify="center", no_wrap=True)
        table.add_column("Scraped", justify="center", no_wrap=True)
        table.add_column("Master Content", justify="center", no_wrap=True)
        table.add_column("Script", justify="center", no_wrap=True)
        table.add_column("Audio Master", justify="center", no_wrap=True)

        for idx, ep in enumerate(episodes, start=1):
            table.add_row(
                str(idx),
                ep["slug"],
                ep["title"][:45],
                ep.get("created_date", "—"),
                "[green]YES[/green]" if ep["scraped"] else "[dim red]NO[/dim red]",
                "[green]YES[/green]" if ep["master"] else "[dim red]NO[/dim red]",
                "[green]YES[/green]" if ep["script"] else "[dim red]NO[/dim red]",
                "[green]YES[/green]" if ep["audio"] else "[dim red]NO[/dim red]"
            )
        console.print(table)
        console.print("\n[bold yellow]Enter episode number(s), range, or slug(s) (e.g. '1, 3', '1-4', 'all') (or 'q' to cancel):[/bold yellow]")
        choice = input("Selection: ").strip()
        selected_episodes = parse_episode_selection(choice, episodes)
        if not selected_episodes:
            console.print("[dim]Rebuild cancelled.[/dim]")
            sys.exit(0)

    # Show selection confirmation
    console.print(f"\n[bold green]Selected {len(selected_episodes)} Episode(s) for Rebuild:[/bold green]")
    for i, ep in enumerate(selected_episodes, start=1):
        console.print(f"  {i}. [bold cyan]{ep['slug']}[/bold cyan] ({ep['title']})")

    # Select Rebuild Depth / Mode if not provided
    if not mode:
        console.print("\n[bold yellow]Choose Rebuild Scope:[/bold yellow]")
        console.print("  [1] [bold green]Full Rebuild from Scratch[/bold green] (Re-scrape article, re-transcribe videos, re-curate storylines, fresh script & audio, republish to Spotify)")
        console.print("  [2] [bold cyan]Re-curate Storylines, Script & Audio[/bold cyan] (Keep raw transcripts, re-run Olympic Coach Gemini Pro curation, fresh script & audio, republish to Spotify)")
        console.print("  [3] [bold blue]Rebuild Script & Audio[/bold blue] (Keep existing curated storylines, synthesize fresh script & studio audio, republish to Spotify)")
        console.print("  [4] [bold magenta]Rebuild Audio Only[/bold magenta] (Keep current script, re-mix acoustic studio master audio, republish to Spotify)")
        mode_choice = input("\nRebuild mode [1/2/3/4] (default 2): ").strip()
        if mode_choice == "1":
            mode = "scratch"
            force_curate = True
        elif mode_choice == "3":
            mode = "script"
            force_curate = False
        elif mode_choice == "4":
            mode = "audio"
            force_curate = False
        else:
            mode = "recurate"
            force_curate = True

        if not publish:
            pub_input = input("Republish rebuilt episode(s) to Cloudflare R2 / Spotify feed? [Y/n] (default Y): ").strip().lower()
            if pub_input in {"", "y", "yes"}:
                publish = True
            else:
                publish = False

        if not skip_review:
            rev_input = input("Skip manual script review pause? (Auto-proceed to audio) [Y/n] (default Y): ").strip().lower()
            if rev_input in {"", "y", "yes"}:
                skip_review = True
            else:
                skip_review = False
    elif mode == "recurate":
        force_curate = True

    # Execute batch rebuild for all selected episodes
    for ep_idx, ep in enumerate(selected_episodes, start=1):
        ep_slug = ep["slug"]
        article_url = f"https://volleybrains.com/{ep_slug}/"
        console.print(f"\n{'='*76}")
        console.print(f"[bold cyan]Processing [{ep_idx}/{len(selected_episodes)}]: {ep_slug}[/bold cyan] ({ep['title']})")
        console.print(f"{'='*76}\n")

        if mode == "audio":
            run_audio_only_rebuild(ep_slug, publish=publish, plugin_name=plugin)
        elif mode == "script":
            run_pipeline_for_slug(ep_slug, article_url, force_scrape=False, force_transcribe=False, force_curate=False, publish=publish, headless=headless, skip_review=skip_review, plugin_name=plugin)
        elif mode == "recurate":
            run_pipeline_for_slug(ep_slug, article_url, force_scrape=False, force_transcribe=False, force_curate=True, publish=publish, headless=headless, skip_review=skip_review, plugin_name=plugin)
        else: # scratch
            run_pipeline_for_slug(ep_slug, article_url, force_scrape=True, force_transcribe=True, force_curate=True, publish=publish, headless=headless, skip_review=skip_review, plugin_name=plugin)

    console.print(f"\n[bold green]ALL {len(selected_episodes)} EPISODE(S) REBUILT SUCCESSFULLY![/bold green]")

@app.command("list")
def list_episodes():
    """List all available generated podcast episodes."""
    episodes = get_available_episodes()
    if not episodes:
        console.print("[bold yellow]No episodes found in output/.[/bold yellow]")
        return
    table = Table(title="Generated VolleyBrains Podcast Episodes")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("Slug", style="bold yellow")
    table.add_column("Coach / Masterclass Title", style="white")
    table.add_column("Scraped", justify="center")
    table.add_column("Master Content", justify="center")
    table.add_column("Script", justify="center")
    table.add_column("Audio Master", justify="center")
    for idx, ep in enumerate(episodes, start=1):
        table.add_row(
            str(idx),
            ep["slug"],
            ep["title"][:50],
            "[green]YES[/green]" if ep["scraped"] else "[dim red]NO[/dim red]",
            "[green]YES[/green]" if ep["master"] else "[dim red]NO[/dim red]",
            "[green]YES[/green]" if ep["script"] else "[dim red]NO[/dim red]",
            "[green]YES[/green]" if ep["audio"] else "[dim red]NO[/dim red]"
        )
    console.print(table)

@app.command(name="sync-feed")
def sync_feed():
    """Synchronize Cloudflare R2 RSS feed.xml to exactly match the local episodes list."""
    import xml.etree.ElementTree as ET
    from src.rss_publisher import get_r2_client, upload_file_to_r2
    from src.config import settings

    episodes = get_available_episodes()
    valid_slugs = {ep['slug'] for ep in episodes if ep['audio']}
    
    console.print(Panel("[bold cyan]Synchronizing Cloudflare R2 RSS Feed with Local Episodes List[/bold cyan]", expand=False))
    console.print(f"[dim]Active local audio episodes ({len(valid_slugs)}): {', '.join(sorted(valid_slugs))}[/dim]")

    try:
        s3 = get_r2_client()
        obj = s3.get_object(Bucket=settings.R2_BUCKET_NAME, Key="feed.xml")
        xml_data = obj['Body'].read().decode("utf-8")
        root = ET.fromstring(xml_data)
        channel = root.find("channel")

        removed_count = 0
        kept_count = 0
        if channel is not None:
            for item in list(channel.findall("item")):
                title = item.findtext("title", "")
                enclosure = item.find("enclosure")
                enc_url = enclosure.attrib.get("url", "") if enclosure is not None else ""
                
                matched = any(f"{slug}_master.mp3" in enc_url or f"/{slug}.mp3" in enc_url for slug in valid_slugs)
                if matched:
                    kept_count += 1
                else:
                    channel.remove(item)
                    removed_count += 1
                    console.print(f"[yellow]Removed orphan/outdated item from RSS feed:[/yellow] {title} ({enc_url})")

        feed_path = Path("output/feed.xml")
        tree = ET.ElementTree(root)
        tree.write(str(feed_path), encoding="utf-8", xml_declaration=True)
        upload_file_to_r2(feed_path, "feed.xml", content_type="application/rss+xml")
        console.print(f"\n[bold green]SUCCESS: RSS feed synchronized ({kept_count} active episodes retained, {removed_count} orphan items removed)![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to sync R2 feed ({e})[/bold red]")

@app.command()
def delete(
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="Episode slug to delete (e.g. andre-sa)"),
    from_r2: bool = typer.Option(False, "--from-r2", help="Also delete episode from Cloudflare R2 bucket and RSS feed"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
):
    """Interactively select and completely delete/remove a podcast episode."""
    if not isinstance(slug, str):
        slug = None
    if not isinstance(from_r2, bool):
        from_r2 = False
    if not isinstance(yes, bool):
        yes = False

    episodes = get_available_episodes()
    if not episodes:
        console.print("[bold red]No existing podcast episodes found in output/ directory.[/bold red]")
        sys.exit(1)

    selected_ep = None
    if slug:
        for ep in episodes:
            if ep["slug"] == slug:
                selected_ep = ep
                break
        if not selected_ep:
            console.print(f"[bold red]Episode '{slug}' not found in output/ directory.[/bold red]")
            sys.exit(1)
    else:
        table = Table(title="Select Episode to Delete")
        table.add_column("#", style="cyan", justify="right")
        table.add_column("Slug", style="bold red")
        table.add_column("Coach / Masterclass Title", style="white")
        table.add_column("Scraped", justify="center")
        table.add_column("Master Content", justify="center")
        table.add_column("Script", justify="center")
        table.add_column("Audio Master", justify="center")
        for idx, ep in enumerate(episodes, start=1):
            table.add_row(
                str(idx),
                ep["slug"],
                ep["title"][:50],
                "[green]YES[/green]" if ep["scraped"] else "[dim red]NO[/dim red]",
                "[green]YES[/green]" if ep["master"] else "[dim red]NO[/dim red]",
                "[green]YES[/green]" if ep["script"] else "[dim red]NO[/dim red]",
                "[green]YES[/green]" if ep["audio"] else "[dim red]NO[/dim red]"
            )
        console.print(table)
        console.print("\n[bold red]Enter episode number or slug to DELETE (or 'q' to cancel):[/bold red]")
        choice = input("Selection to delete: ").strip()
        if choice.lower() == 'q' or not choice:
            console.print("[dim]Deletion cancelled.[/dim]")
            sys.exit(0)
        
        for ep in episodes:
            if ep["slug"] == choice:
                selected_ep = ep
                break
        if not selected_ep:
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(episodes):
                    selected_ep = episodes[choice_idx]
                else:
                    console.print("[bold red]Invalid selection number.[/bold red]")
                    sys.exit(1)
            except ValueError:
                console.print("[bold red]Invalid input.[/bold red]")
                sys.exit(1)

    ep_slug = selected_ep["slug"]
    import re
    if not re.match(r"^[a-zA-Z0-9_-]+$", ep_slug):
        console.print(f"[bold red]Security error: Invalid slug format '{ep_slug}'. Only alphanumeric, hyphens, and underscores permitted.[/bold red]")
        sys.exit(1)

    # Check R2 deletion preference
    if not from_r2 and not yes:
        r2_prompt = input(f"Also delete '{ep_slug}' from Cloudflare R2 bucket & RSS feed? [y/N]: ").strip().lower()
        if r2_prompt in {"y", "yes"}:
            from_r2 = True

    # Confirmation
    if not yes:
        confirm = input(f"[WARNING] Are you sure you want to permanently delete all files for '{ep_slug}'? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            console.print("[dim]Deletion aborted.[/dim]")
            sys.exit(0)

    # Local Files to Delete (strictly bounded to output/ directory)
    output_root = Path("output").resolve()
    target_files = [
        Path(f"output/scraped_{ep_slug}.md"),
        Path(f"output/master_{ep_slug}.md"),
        Path(f"output/scripts/{ep_slug}_script.md"),
        Path(f"output/audio/{ep_slug}_master.mp3"),
        Path(f"output/summaries/{ep_slug}_summary.md")
    ]

    deleted_count = 0
    for file_path in target_files:
        resolved = file_path.resolve()
        if not str(resolved).startswith(str(output_root)):
            console.print(f"[bold red]Security error: Path traversal detected: {resolved}[/bold red]")
            sys.exit(1)
        if file_path.exists():
            file_path.unlink()
            console.print(f"[red]Deleted:[/red] {file_path}")
            deleted_count += 1

    if from_r2:
        delete_episode_from_r2(ep_slug)

    console.print(f"\n[bold green]SUCCESS: Episode '{ep_slug}' completely removed ({deleted_count} local files deleted).[/bold green]")

def interactive_main_menu():
    """Guided interactive master menu when running main.py with no args."""
    while True:
        active_plugin = get_active_plugin()
        all_plugins = registry.list_plugins()
        console.print("\n" + "=" * 76)
        console.print(Panel(f"[bold cyan]PODCAST GENERATION FRAMEWORK[/bold cyan]\n[green]Active Show:[/green] [bold yellow]{active_plugin.name}[/bold yellow] ([cyan]{active_plugin.slug}[/cyan])", expand=False))
        console.print("[bold yellow]What would you like to do?[/bold yellow]\n")
        console.print(f"  [bold green][1] Generate New Episode from URL[/bold green] (Using [cyan]{active_plugin.name}[/cyan] pipeline)")
        console.print("  [bold cyan][2] Rebuild / Reproduce an Episode[/bold cyan] (Full rebuild, script+audio, or audio-only)")
        console.print(f"  [bold yellow][3] Rebuild Show Memory (MEMORY.md)[/bold yellow] (Extract lessons & quotes for [cyan]{active_plugin.name}[/cyan])")
        console.print("  [bold white][4] List Generated Episodes[/bold white] (View scraped, master content, script & audio status)")
        console.print("  [bold magenta][5] Synchronize R2 RSS Feed[/bold magenta] (Clean feed.xml so it strictly matches local episodes)")
        console.print("  [bold red][6] Delete / Purge an Episode[/bold red] (Delete local episode files and/or Cloudflare R2 bucket items)")
        console.print(f"  [bold blue][7] Switch Podcast Show Plugin[/bold blue] (Installed: {len(all_plugins)})")
        console.print("  [dim][8] Exit[/dim]")
        console.print("=" * 76)

        choice = input("\nEnter choice [1-8] (or 'q' to quit): ").strip()
        if choice in {"8", "q", "quit", "exit"}:
            console.print("[dim]Goodbye![/dim]")
            sys.exit(0)

        if choice == "1":
            console.print(f"\n[bold cyan]--- Generate New Episode [{active_plugin.name}] ---[/bold cyan]")
            url = input("Enter Source Content / Article URL: ").strip()
            if not url:
                console.print("[yellow]No URL entered. Returning to menu.[/yellow]")
                continue
            pub_choice = input("Publish episode to Cloudflare R2 when done? [y/N]: ").strip().lower()
            publish = pub_choice in {"y", "yes"}
            headless_choice = input("Run browser in headless mode? [y/N]: ").strip().lower()
            headless = headless_choice in {"y", "yes"}
            slug = active_plugin.get_ingester().get_slug(url) if hasattr(active_plugin, "get_ingester") else get_url_slug(url)
            run_pipeline_for_slug(slug, url, publish=publish, headless=headless, plugin_name=active_plugin.slug)
            break

        elif choice == "2":
            rebuild(plugin=active_plugin.slug)
            break

        elif choice == "3":
            console.print(f"\n[bold cyan]--- Rebuild Show Memory (MEMORY.md) [{active_plugin.name}] ---[/bold cyan]")
            console.print("  [1] Rebuild memory for ALL episodes (incremental / update existing)")
            console.print("  [2] Rebuild memory for ALL episodes (fresh start, wipe existing memory)")
            console.print("  [3] Update memory for a SINGLE episode")
            console.print("  [4] View current MEMORY.md")
            console.print("  [5] Cancel / Return to main menu")

            sub_choice = input("\nEnter choice [1-5]: ").strip()
            if sub_choice == "1":
                rebuild_all_show_memory(plugin=active_plugin, fresh=False)
            elif sub_choice == "2":
                confirm = input("Are you sure you want to reset MEMORY.md and re-extract all episodes? [y/N]: ").strip().lower()
                if confirm in {"y", "yes"}:
                    rebuild_all_show_memory(plugin=active_plugin, fresh=True)
                else:
                    console.print("[dim]Reset cancelled.[/dim]")
            elif sub_choice == "3":
                episodes = get_available_episodes()
                valid_eps = [e for e in episodes if e["master"]]
                if not valid_eps:
                    console.print("[bold red]No episodes with master content found in output/ directory.[/bold red]")
                else:
                    console.print("\nEpisodes with master content:")
                    for idx, ep in enumerate(valid_eps, start=1):
                        console.print(f"  [{idx}] {ep['title']} ([cyan]{ep['slug']}[/cyan])")
                    ep_pick = input("\nSelect episode number or slug: ").strip()
                    target_ep = None
                    for ep in valid_eps:
                        if ep["slug"] == ep_pick:
                            target_ep = ep
                            break
                    if not target_ep and ep_pick.isdigit():
                        idx = int(ep_pick) - 1
                        if 0 <= idx < len(valid_eps):
                            target_ep = valid_eps[idx]
                    if target_ep:
                        mf = Path(f"output/master_{target_ep['slug']}.md")
                        sf = Path(f"output/scripts/{target_ep['slug']}_script.md")
                        update_podcast_memory(mf, script_path=sf if sf.exists() else None, plugin=active_plugin)
                    else:
                        console.print("[yellow]Invalid selection.[/yellow]")
            elif sub_choice == "4":
                mem = active_plugin.get_memory()
                if not mem:
                    console.print(f"[yellow]No memory found in {active_plugin.memory_path}[/yellow]")
                else:
                    console.print(Panel(mem, title=f"Show Memory — {active_plugin.name}", expand=False))
            input("\nPress [ENTER] to return to main menu...")

        elif choice == "4":
            list_episodes()
            input("\nPress [ENTER] to return to main menu...")

        elif choice == "5":
            sync_feed()
            input("\nPress [ENTER] to return to main menu...")

        elif choice == "6":
            delete()
            input("\nPress [ENTER] to return to main menu...")

        elif choice == "7":
            console.print("\n[bold cyan]--- Available Podcast Show Plugins ---[/bold cyan]")
            p_list = list(all_plugins.items())
            for idx, (p_slug, p_obj) in enumerate(p_list, start=1):
                marker = "[bold green](active)[/bold green]" if p_slug == active_plugin.slug else ""
                console.print(f"  [{idx}] [bold yellow]{p_obj.name}[/bold yellow] ([cyan]{p_slug}[/cyan]) {marker}")
            p_choice = input("\nSelect plugin number to activate (or ENTER to cancel): ").strip()
            if p_choice.isdigit():
                p_idx = int(p_choice) - 1
                if 0 <= p_idx < len(p_list):
                    selected_slug = p_list[p_idx][0]
                    registry.set_active_plugin(selected_slug)
                    console.print(f"[bold green]Switched active show to: {all_plugins[selected_slug].name}[/bold green]")
            continue

        else:
            console.print("[bold red]Invalid option. Please enter 1 to 8.[/bold red]")

@app.command()
def menu():
    """Launch the interactive guided wizard menu."""
    interactive_main_menu()

if __name__ == "__main__":
    # If user provides a direct URL as the first argument, route to generate command
    if len(sys.argv) > 1 and (sys.argv[1].startswith("http://") or sys.argv[1].startswith("https://")):
        sys.argv.insert(1, "generate")
    elif len(sys.argv) == 1:
        # If user runs `python main.py` with no args, open the interactive guided menu
        interactive_main_menu()
        sys.exit(0)
    app()
