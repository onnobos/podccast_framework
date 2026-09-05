import sys
import re
from pathlib import Path
from typing import List
from bs4 import BeautifulSoup
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
from rich.console import Console

from src.auth import ensure_authenticated, AUTH_STATE_PATH
from src.config import settings

import ipaddress
from urllib.parse import urlparse

console = Console()

def validate_url(url: str) -> None:
    """Validate URL scheme and host against SSRF, local file access, and private network probing."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Disallowed URL scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted.")

    host = parsed.hostname
    if not host:
        raise ValueError(f"Invalid URL: Missing host in '{url}'.")

    host_lower = host.lower()
    if host_lower in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1"):
        raise ValueError(f"Access to internal or cloud metadata address '{host}' is strictly forbidden.")

    try:
        ip = ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False

    if is_ip and (ip.is_private or ip.is_loopback or ip.is_link_local):
        raise ValueError(f"Access to private IP address '{host}' is strictly forbidden.")


def get_url_slug(url: str) -> str:
    """Extract clean filename slug from URL."""
    clean_url = url.split("?")[0].split("#")[0].rstrip("/")
    path_segment = clean_url.split("/")[-1]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", path_segment).lower().strip("_")
    return slug if (slug and slug != "volleybrains.com") else "masterclass"

class ScrapedArticle(BaseModel):
    url: str
    title: str
    coach_name: str
    content_markdown: str
    video_urls: List[str]

def extract_video_urls(soup: BeautifulSoup, page_content: str) -> List[str]:
    """Extract embedded video URLs (Vimeo, YouTube, HTML5 video)."""
    video_urls = []

    # 1. Iframes (Vimeo / YouTube)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or iframe.get("data-lazy-src")
        if src:
            if "vimeo.com" in src or "youtube.com" in src or "youtu.be" in src:
                if src.startswith("//"):
                    src = "https:" + src
                video_urls.append(src)

    # 2. HTML5 Video & Source tags
    for video in soup.find_all("video"):
        src = video.get("src")
        if src:
            video_urls.append(src)
        for source in video.find_all("source"):
            ssrc = source.get("src")
            if ssrc:
                video_urls.append(ssrc)

    # 3. Ghost / Vimeo specific data attributes (e.g. data-vimeo-id, data-vimeo-url)
    for elem in soup.find_all(True):
        v_id = elem.get("data-vimeo-id")
        v_url = elem.get("data-vimeo-url")
        if v_id:
            video_urls.append(f"https://player.vimeo.com/video/{v_id}")
        if v_url:
            video_urls.append(v_url)

    # 4. Direct links to video hosts in anchor tags
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ("vimeo.com/" in href or "youtube.com/watch" in href or "youtu.be/" in href) and href not in video_urls:
            video_urls.append(href)

    # 5. Regex fallback in raw HTML source for video URLs & embeds
    vimeo_matches = re.findall(r'https?://(?:player\.)?vimeo\.com/(?:video/)?\d+[^\s"\'<>]*', page_content)
    yt_matches = re.findall(r'https?://(?:www\.)?youtube\.com/(?:embed/|watch\?v=)[a-zA-Z0-9_-]+', page_content)
    for match in vimeo_matches + yt_matches:
        if match not in video_urls:
            video_urls.append(match)

    # Normalize iframe embed URLs to direct watchable URLs for yt-dlp
    normalized_urls = []
    for url in video_urls:
        if "youtube.com/embed/" in url:
            match = re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]+)', url)
            if match:
                url = f"https://www.youtube.com/watch?v={match.group(1)}"
        elif "player.vimeo.com/video/" in url:
            match = re.search(r'vimeo\.com/video/(\d+)', url)
            if match:
                url = f"https://vimeo.com/{match.group(1)}"
        if url not in normalized_urls:
            normalized_urls.append(url)

    return normalized_urls

def scrape_article(url: str, output_path: Path | None = None, headless: bool = False) -> ScrapedArticle:
    """Scrape paywalled VolleyBrains article using Playwright auth session state."""
    validate_url(url)
    auth_path = ensure_authenticated()
    
    console.print(f"[bold cyan]Navigating to article (headless={headless}):[/bold cyan] {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            storage_state=str(auth_path),
            viewport={"width": 1400, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        
        # Dynamic adaptive auto-scroll down to trigger all lazy-loaded embeds until true bottom
        prev_scroll_y = -1
        stagnant_count = 0
        max_scroll_steps = 150

        for step in range(1, max_scroll_steps + 1):
            page.evaluate("window.scrollBy(0, 900)")
            page.wait_for_timeout(400)
            current_scroll_y = page.evaluate("window.scrollY")
            scroll_height = page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
            viewport_bottom = page.evaluate("window.scrollY + window.innerHeight")

            if current_scroll_y == prev_scroll_y or viewport_bottom >= (scroll_height - 50):
                page.wait_for_timeout(800)
                new_scroll_height = page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
                if new_scroll_height <= scroll_height:
                    stagnant_count += 1
                    if stagnant_count >= 3:
                        break
                else:
                    stagnant_count = 0
            else:
                stagnant_count = 0

            prev_scroll_y = current_scroll_y

        # Scroll back up to ensure full DOM top-level elements remain clean
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        try:
            page.wait_for_timeout(1000)
            html_content = page.content()
        except Exception:
            console.print("[yellow]Browser window was closed. Reading captured state...[/yellow]")

        soup = BeautifulSoup(html_content, "html.parser")

        # Paywall detection check
        if "gh-post-upgrade-cta" in html_content or soup.find("aside", class_="gh-post-upgrade-cta"):
            console.print("[bold red]============================================================\n"
                          "WARNING: Ghost paywall banner detected on article page!\n"
                          "Cookies in .auth/storageState.json are unauthenticated.\n"
                          "Please re-run `python -m src.auth` and make sure login completes.\n"
                          "============================================================[/bold red]")

        # Save debug dump for inspection
        debug_dir = Path("temp")
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / "debug_scraped.html").write_text(html_content, encoding="utf-8")

        # Title extraction
        title_el = soup.find("h1") or soup.find("title")
        title = title_el.get_text(strip=True) if title_el else "VolleyBrains Masterclass"

        # Coach name extraction
        coach_name = title
        if ":" in title:
            coach_name = title.split(":")[0].strip()
        elif " with " in title:
            coach_name = title.split(" with ")[-1].strip()
        elif " - " in title:
            coach_name = title.split(" - ")[0].strip()

        # Target main content containers in Ghost CMS or standard articles (<section class="gh-content">, <div class="gh-content">, <article>, etc.)
        content_parts = []
        container = (
            soup.find(True, class_=re.compile(r"gh-content|post-content|kg-canvas|c-content|entry-content"))
            or soup.find("article")
            or soup.find("main")
            or soup.find("body")
        )

        if container:
            for elem in container.find_all(["h1", "h2", "h3", "h4", "h5", "p", "li", "blockquote"]):
                text = elem.get_text(strip=True)
                if not text or len(text) < 2:
                    continue

                tag = elem.name
                if tag == "h1":
                    content_parts.append(f"# {text}")
                elif tag == "h2":
                    content_parts.append(f"## {text}")
                elif tag == "h3":
                    content_parts.append(f"### {text}")
                elif tag == "h4":
                    content_parts.append(f"#### {text}")
                elif tag == "blockquote":
                    content_parts.append(f"> {text}")
                elif tag == "li":
                    content_parts.append(f"- {text}")
                elif tag == "p":
                    content_parts.append(text)

        content_markdown = "\n\n".join(content_parts)
        video_urls = extract_video_urls(soup, html_content)

        browser.close()

    article = ScrapedArticle(
        url=url,
        title=title,
        coach_name=coach_name,
        content_markdown=content_markdown,
        video_urls=video_urls
    )

    # Save output markdown file (slug-isolated)
    if output_path is None:
        slug = get_url_slug(url)
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"scraped_{slug}.md"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    md_content = f"# {article.title}\n\n**Coach:** {article.coach_name}  \n**URL:** {article.url}  \n\n## Found Videos ({len(article.video_urls)})\n"
    for v in article.video_urls:
        md_content += f"- {v}\n"
    md_content += f"\n## Content ({len(content_parts)} blocks)\n\n{article.content_markdown}\n"
    output_path.write_text(md_content, encoding="utf-8")

    console.print(f"[bold green]Successfully scraped article:[/bold green] {title}")
    console.print(f"[yellow]Paragraph/Header count:[/yellow] {len(content_parts)}")
    console.print(f"[yellow]Found video URLs:[/yellow] {len(video_urls)}")
    for v_url in video_urls:
        console.print(f"  - {v_url}")
    console.print(f"[bold cyan]Saved scraped article to:[/bold cyan] {output_path}")

    return article

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape VolleyBrains article.")
    parser.add_argument("--url", type=str, help="VolleyBrains article URL", default="https://volleybrains.com/")
    parser.add_argument("--headful", action="store_true", help="Show browser window for debugging")
    args = parser.parse_args()

    scrape_article(args.url, headless=not args.headful)
