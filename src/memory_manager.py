"""
Show Knowledge & Cross-Episode Memory Manager
Extracts, formats, and maintains persistent episode memory (MEMORY.md) for podcast plugins.
Enables hosts and curators to draw parallels, compare tactics, and quote past guests.
"""
import re
import json
from pathlib import Path
from typing import Optional, Dict, Any
from rich.console import Console

from src.config import settings
from src.cost_tracker import cost_tracker

console = Console()


def get_memory_openrouter_client():
    """Instantiate OpenAI client configured for OpenRouter."""
    from openai import OpenAI
    api_key = settings.OPENROUTER_API_KEY or settings.effective_api_key
    base_url = settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
    return OpenAI(api_key=api_key, base_url=base_url)


def extract_episode_memory(
    master_content_path: Path,
    script_path: Optional[Path] = None,
    client: Optional[Any] = None,
    plugin: Optional[Any] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract core lessons, principles, memorable quotes, and keywords from an episode's
    mastercontent and script using an LLM.
    """
    if not master_content_path.exists():
        raise FileNotFoundError(f"Master content not found at {master_content_path}")

    master_text = master_content_path.read_text(encoding="utf-8")
    script_text = script_path.read_text(encoding="utf-8") if script_path and script_path.exists() else ""

    if client is None:
        client = get_memory_openrouter_client()

    chosen_model = model or getattr(getattr(plugin, "script_config", None), "audit_model", "google/gemini-2.5-flash")

    system_prompt = (
        "You are an expert podcast editorial archivist. Your job is to extract high-value, "
        "permanent institutional knowledge from a podcast masterclass episode to store in show memory.\n\n"
        "Extract the following structured fields:\n"
        "1. title: Episode title or subject matter\n"
        "2. featured_expert: Name of the featured coach, author, or guest\n"
        "3. core_lessons: List of 3 to 5 actionable principles, mental models, or coaching rules\n"
        "4. standout_quotes: List of 2 to 4 verbatim, memorable quotes from the expert\n"
        "5. keywords: List of 4 to 8 thematic tags/tactics (e.g. ['serve-receive', 'accountability', 'drill design'])\n\n"
        "Respond strictly with valid JSON conforming to this schema:\n"
        "{\n"
        '  "title": "string",\n'
        '  "featured_expert": "string",\n'
        '  "core_lessons": ["string"],\n'
        '  "standout_quotes": ["string"],\n'
        '  "keywords": ["string"]\n'
        "}"
    )

    user_content = (
        f"--- MASTER CONTENT EXCERPT ---\n{master_text[:25000]}\n\n"
    )
    if script_text:
        user_content += f"--- SCRIPT EXCERPT ---\n{script_text[:15000]}\n\n"
    user_content += "Extract the core lessons, memorable quotes, and tactical keywords. Output ONLY JSON."

    console.print(f"[bold cyan]Extracting Institutional Memory for Episode ({chosen_model})...[/bold cyan]")

    call_kwargs = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2
    }
    if "gpt" in chosen_model or "gemini" in chosen_model:
        call_kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = client.chat.completions.create(**call_kwargs)
        if hasattr(resp, "usage") and resp.usage:
            cost_tracker.log_llm(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                model=chosen_model,
                step_label="Memory Extraction"
            )
        raw_json = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", raw_json, re.DOTALL)
        clean_json = match.group(0) if match else raw_json
        data = json.loads(clean_json)
        return data
    except Exception as err:
        console.print(f"[yellow]Memory extraction failed with model {chosen_model} ({err}). Using fallback extraction.[/yellow]")
        # Fallback heuristic extraction
        title = master_content_path.stem.replace("master_", "").replace("-", " ").replace("_", " ").title()
        for line in master_text.splitlines():
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break
        return {
            "title": title,
            "featured_expert": "Featured Coach",
            "core_lessons": ["Emphasize fundamental execution under pressure.", "Design drills that simulate game stress."],
            "standout_quotes": [],
            "keywords": [w.lower() for w in title.split() if len(w) > 3][:6]
        }


def format_memory_entry(episode_slug: str, data: Dict[str, Any]) -> str:
    """Format an episode's extracted memory into standard Markdown with slug delimiter tags."""
    title = data.get("title", episode_slug.replace("-", " ").replace("_", " ").title())
    expert = data.get("featured_expert", "Featured Expert")
    lessons = data.get("core_lessons", [])
    quotes = data.get("standout_quotes", [])
    keywords = data.get("keywords", [])

    lines = [
        f"<!-- episode: {episode_slug} -->",
        f"### {title}",
        f"- **Featured Expert:** {expert}",
        "- **Core Lessons & Mental Models:**"
    ]
    for lesson in lessons:
        lines.append(f"  - {lesson}")

    if quotes:
        lines.append("- **Standout Quotes & Philosophy:**")
        for q in quotes:
            clean_q = q.strip('"\'')
            lines.append(f'  - "{clean_q}"')

    if keywords:
        keywords_str = ", ".join(f"`{k}`" for k in keywords)
        lines.append(f"- **Tactical Themes:** {keywords_str}")

    lines.append(f"<!-- end_episode: {episode_slug} -->")
    return "\n".join(lines)


def update_podcast_memory(
    master_content_path: Path,
    script_path: Optional[Path] = None,
    plugin: Optional[Any] = None,
    client: Optional[Any] = None
) -> Path:
    """
    Extracts memory from an episode, formats it, and inserts/replaces the entry in the plugin's MEMORY.md.
    Returns path to updated MEMORY.md.
    """
    if plugin is None:
        from src.framework.registry import get_active_plugin
        plugin = get_active_plugin()

    episode_slug = master_content_path.stem.replace("master_", "")
    memory_path = plugin.memory_path

    # Extract memory from content
    memory_data = extract_episode_memory(
        master_content_path=master_content_path,
        script_path=script_path,
        client=client,
        plugin=plugin
    )

    new_entry = format_memory_entry(episode_slug, memory_data)

    # Read existing memory or initialize template
    if memory_path.exists():
        existing_text = memory_path.read_text(encoding="utf-8")
    else:
        show_name = getattr(plugin, "name", "Podcast")
        existing_text = (
            f"# {show_name} — Show Knowledge & Episode Memory (MEMORY.md)\n\n"
            "This repository accumulates key tactical lessons, coaching mental models, and standout quotes across all produced episodes.\n"
            "During scriptwriting and curation, hosts reference, compare, and quote these past insights whenever thematic similarities arise.\n\n"
            "---\n\n"
        )

    # Check if slug already exists in MEMORY.md (idempotent replace)
    pattern = re.compile(
        rf"<!-- episode:\s*{re.escape(episode_slug)}\s*-->.*?<!-- end_episode:\s*{re.escape(episode_slug)}\s*-->\n?",
        re.DOTALL
    )

    if pattern.search(existing_text):
        updated_text = pattern.sub(new_entry + "\n", existing_text)
        action_desc = "Updated existing"
    else:
        # Append to the end
        updated_text = existing_text.rstrip() + "\n\n" + new_entry + "\n"
        action_desc = "Appended new"

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(updated_text, encoding="utf-8")
    console.print(f"[bold green]{action_desc} episode entry in show memory: [cyan]{memory_path}[/cyan][/bold green]")
    return memory_path


def get_relevant_memory_context(plugin: Optional[Any] = None, max_chars: int = 4000) -> str:
    """
    Load the show's cumulative MEMORY.md to pass to Curator or Scriptwriter prompts.
    Returns truncated memory context or empty string if no memory exists.
    """
    if plugin is None:
        try:
            from src.framework.registry import get_active_plugin
            plugin = get_active_plugin()
        except Exception:
            return ""

    if not hasattr(plugin, "get_memory"):
        return ""

    memory = plugin.get_memory()
    if not memory:
        return ""

    # Return up to max_chars, keeping latest entries
    if len(memory) > max_chars:
        return memory[-max_chars:]
    return memory


def rebuild_all_show_memory(plugin: Optional[Any] = None, fresh: bool = False, client: Optional[Any] = None) -> Path:
    """
    Scan all available output/master_*.md files and extract/rebuild MEMORY.md
    for the given plugin. If fresh=True, starts from a clean MEMORY.md header.
    """
    if plugin is None:
        from src.framework.registry import get_active_plugin
        plugin = get_active_plugin()

    master_files = sorted(Path("output").glob("master_*.md"))
    master_files = [f for f in master_files if f.stem != "master_content"]

    if not master_files:
        console.print("[yellow]No master content files (output/master_*.md) found to rebuild memory from.[/yellow]")
        return plugin.memory_path

    if fresh:
        show_name = getattr(plugin, "name", "Podcast")
        header = (
            f"# {show_name} — Show Knowledge & Episode Memory (MEMORY.md)\n\n"
            "This document accumulates core coaching lessons, tactical mental models, and standout coach quotes across all produced episodes.\n"
            "During scriptwriting and curation, hosts reference, compare, and quote these past insights whenever thematic similarities arise.\n\n"
            "---\n\n"
        )
        plugin.save_memory(header)

    console.print(f"[bold cyan]Rebuilding show memory for {len(master_files)} episode(s) [{plugin.name}]...[/bold cyan]")
    for mf in master_files:
        slug = mf.stem.replace("master_", "")
        script_file = Path(f"output/scripts/{slug}_script.md")
        script_path = script_file if script_file.exists() else None
        update_podcast_memory(mf, script_path=script_path, plugin=plugin, client=client)

    console.print(f"[bold green]Show memory rebuild complete: {plugin.memory_path}[/bold green]")
    return plugin.memory_path
