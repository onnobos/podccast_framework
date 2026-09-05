import os
import boto3
from pathlib import Path
from typing import Tuple
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from rich.console import Console

from src.config import settings

console = Console()

from botocore.config import Config
import certifi

def get_r2_client(verify_ssl: bool | str = True):
    """Initialize boto3 S3 client for Cloudflare R2."""
    endpoint_url = f"https://{settings.clean_r2_account_id}.r2.cloudflarestorage.com"
    r2_config = Config(
        region_name="auto",
        signature_version="s3v4",
        s3={"addressing_style": "path"}
    )
    ssl_verify = certifi.where() if verify_ssl is True else verify_ssl
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=r2_config,
        verify=ssl_verify
    )

from botocore.exceptions import SSLError

def upload_file_to_r2(local_file_path: Path, r2_key: str, content_type: str = "audio/mpeg") -> str:
    """Upload a file to Cloudflare R2 and return its public URL."""
    console.print(f"[bold cyan]Uploading {local_file_path.name} to R2 bucket '{settings.R2_BUCKET_NAME}' at '{r2_key}'...[/bold cyan]")
    
    try:
        s3 = get_r2_client(verify_ssl=True)
        with open(local_file_path, "rb") as f:
            s3.put_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=r2_key,
                Body=f,
                ContentType=content_type
            )
    except SSLError as ssl_err:
        console.print(
            f"[bold red]FATAL: SSL certificate verification failed during R2 upload: {ssl_err}[/bold red]\n"
            "[yellow]To fix: Ensure system clock is accurate and run 'pip install --upgrade certifi'. "
            "Insecure unencrypted fallback is strictly disabled per OWASP A02/A04 standards.[/yellow]"
        )
        raise ssl_err

    public_url = f"https://{settings.clean_r2_public_domain}/{r2_key}"
    console.print(f"[bold green]SUCCESS: File available at:[/bold green] {public_url}")
    return public_url

import xml.etree.ElementTree as ET

def update_podcast_rss_feed(
    episode_title: str,
    episode_description: str,
    audio_url: str,
    audio_file_size: int,
    output_feed_path: Path | None = None,
    plugin = None
) -> Tuple[Path, str]:
    """Generate or update podcast RSS feed xml preserving previous episodes and upload to Cloudflare R2."""
    if plugin is None:
        try:
            from src.framework.registry import get_active_plugin
            plugin = get_active_plugin()
        except Exception:
            plugin = None

    meta = getattr(plugin, "show_metadata", None) if plugin else None
    dist = getattr(plugin, "distribution", None) if plugin else None

    show_title = getattr(meta, "title", "Volleyball Coaching Uncovered")
    show_author = getattr(meta, "author", "Volleyball Coaching Uncovered")
    show_email = getattr(meta, "email", "ebook53-podcast@yahoo.com")
    show_desc = getattr(meta, "description", "Transforming rich masterclasses into high-retention 2-host audio podcast episodes.")
    show_category = getattr(meta, "category", "Sports")
    show_subcategory = getattr(meta, "subcategory", "Volleyball")
    show_explicit = "yes" if getattr(meta, "explicit", False) else "no"

    public_domain = getattr(dist, "public_domain", None) or settings.clean_r2_public_domain
    bucket_name = getattr(dist, "bucket_name", None) or settings.R2_BUCKET_NAME
    feed_key = getattr(dist, "feed_key", "feed.xml")

    if output_feed_path is None:
        feed_dir = Path("output")
        if plugin and hasattr(plugin, "slug") and plugin.slug != "volleyball":
            feed_dir = Path(f"output/{plugin.slug}")
        output_feed_path = feed_dir / "feed.xml"

    output_feed_path.parent.mkdir(parents=True, exist_ok=True)

    # First attempt to sync/download remote R2 feed.xml to preserve all existing episodes across runs
    try:
        s3 = get_r2_client()
        obj = s3.get_object(Bucket=bucket_name, Key=feed_key)
        r2_feed_xml = obj['Body'].read().decode("utf-8")
        output_feed_path.write_text(r2_feed_xml, encoding="utf-8")
        console.print(f"[dim]Synced latest remote RSS feed from Cloudflare R2.[/dim]")
    except Exception as err:
        console.print(f"[dim]Note: Could not sync remote R2 feed ({err}). Using local feed if present.[/dim]")

    existing_items = []
    seen_urls = set()
    if output_feed_path.exists():
        try:
            tree = ET.parse(output_feed_path)
            root = tree.getroot()
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item"):
                    guid = item.findtext("guid")
                    title = item.findtext("title")
                    desc = item.findtext("description")
                    pub_date = item.findtext("pubDate")
                    enclosure = item.find("enclosure")
                    enc_url = enclosure.get("url") if enclosure is not None else None
                    enc_len = enclosure.get("length") if enclosure is not None else "0"
                    
                    if enc_url and enc_url not in seen_urls and ".cloudflarestorage.com" not in enc_url:
                        seen_urls.add(enc_url)
                        if enc_url != audio_url:
                            existing_items.append({
                                "id": guid or enc_url,
                                "title": title or f"{show_title} Episode",
                                "description": desc or "",
                                "pubDate": pub_date,
                                "url": enc_url,
                                "size": enc_len
                            })
        except Exception as err:
            console.print(f"[yellow]Could not parse existing feed ({err}). Building clean feed.[/yellow]")

    # Check for cover art image asset
    cover_art_candidates = []
    if meta and getattr(meta, "cover_art_path", None) and Path(meta.cover_art_path).exists():
        cover_art_candidates.append(Path(meta.cover_art_path))
    cover_art_candidates.extend(
        list(Path("assets/images").glob("cover_art.*"))
        + list(Path("assets").glob("cover_art.*"))
        + list(Path("assets/images").glob("*.jpg"))
        + list(Path("assets/images").glob("*.png"))
    )

    cover_art_url = None
    if cover_art_candidates:
        c_file = cover_art_candidates[0]
        ext = c_file.suffix.lower()
        c_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        r2_cover_key = f"cover_art{ext}"
        console.print(f"[bold cyan]Uploading cover art ({c_file.name}) to R2...[/bold cyan]")
        cover_art_url = upload_file_to_r2(c_file, r2_cover_key, content_type=c_type)

    def clean_text_no_vb(text: str) -> str:
        if not text:
            return ""
        return (
            text.replace("VolleyBrains Masterclass:", "Masterclass:")
                .replace("VolleyBrains 2-Host Audio Masterclass", f"{show_title} 2-Host Audio Masterclass")
                .replace("VolleyBrains", show_title)
                .strip()
        )

    # Clean new episode title and description
    episode_title = clean_text_no_vb(episode_title)
    episode_description = clean_text_no_vb(episode_description)

    fg = FeedGenerator()
    fg.load_extension('podcast')

    public_feed_url = f"https://{public_domain}/{feed_key}"
    fg.id(public_feed_url)
    fg.title(show_title)
    fg.author({'name': show_author, 'email': show_email})
    fg.link(href=public_feed_url, rel='self')
    fg.description(show_desc)
    fg.language('en')

    # Podcast specific tags
    if show_subcategory:
        fg.podcast.itunes_category(show_category, show_subcategory)
    else:
        fg.podcast.itunes_category(show_category)
    fg.podcast.itunes_author(show_author)
    fg.podcast.itunes_owner(name=show_author, email=show_email)
    fg.podcast.itunes_explicit(show_explicit)

    if cover_art_url:
        fg.podcast.itunes_image(cover_art_url)
        fg.image(url=cover_art_url, title=show_title, link=public_feed_url)

    # Add existing episodes
    for item_data in existing_items:
        fe = fg.add_entry()
        fe.id(item_data["id"])
        fe.title(clean_text_no_vb(item_data["title"]))
        fe.description(clean_text_no_vb(item_data["description"]))
        fe.enclosure(item_data["url"], str(item_data["size"]), 'audio/mpeg')
        if item_data.get("pubDate"):
            fe.published(item_data["pubDate"])
        else:
            fe.published(datetime.now(timezone.utc))

    # Add new Episode Entry
    fe = fg.add_entry()
    fe.id(audio_url)
    fe.title(episode_title)
    fe.description(episode_description)
    fe.enclosure(audio_url, str(audio_file_size), 'audio/mpeg')
    fe.published(datetime.now(timezone.utc))

    # Save RSS XML locally
    fg.rss_str(pretty=True)
    fg.rss_file(str(output_feed_path))
    console.print(f"[bold green]Updated local RSS feed ({len(existing_items) + 1} total episodes) at:[/bold green] {output_feed_path}")

    # Upload updated feed.xml to Cloudflare R2
    feed_public_url = upload_file_to_r2(output_feed_path, feed_key, content_type="application/rss+xml")
    return output_feed_path, feed_public_url

def publish_episode(
    audio_path: Path, 
    title: str = "Podcast Masterclass Episode", 
    description: str = "2-Host Audio Masterclass",
    plugin = None
) -> Tuple[str, str]:
    """Publish master MP3 audio episode to R2 and update RSS feed."""
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file missing at {audio_path}")

    file_size = audio_path.stat().st_size
    r2_audio_key = f"episodes/{audio_path.name}"

    # 1. Upload MP3 to R2
    audio_public_url = upload_file_to_r2(audio_path, r2_audio_key, content_type="audio/mpeg")

    # 2. Update and Upload RSS Feed
    feed_path, feed_url = update_podcast_rss_feed(
        episode_title=title,
        episode_description=description,
        audio_url=audio_public_url,
        audio_file_size=file_size,
        plugin=plugin
    )


    console.print("\n" + "=" * 76)
    console.print("[bold green]SUCCESS: EPISODE PUBLISHED SUCCESSFULLY TO CLOUDFLARE R2 RSS FEED![/bold green]")
    console.print(f"[bold yellow]Audio Episode Direct URL:[/bold yellow] [cyan]{audio_public_url}[/cyan]")
    console.print(f"[bold yellow]Podcast RSS Feed Public URL:[/bold yellow] [cyan]{feed_url}[/cyan]")
    console.print("=" * 76 + "\n")

    return audio_public_url, feed_url

def delete_episode_from_r2(slug: str, output_feed_path: Path | None = None) -> bool:
    """Delete audio file from Cloudflare R2 bucket and remove its item from feed.xml."""
    if output_feed_path is None:
        output_feed_path = Path("output/feed.xml")

    # 1. Delete MP3 object from R2
    r2_audio_key = f"episodes/{slug}_master.mp3"
    console.print(f"[bold cyan]Deleting remote R2 object '{r2_audio_key}'...[/bold cyan]")
    try:
        s3 = get_r2_client()
        s3.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=r2_audio_key)
        console.print(f"[green]Deleted {r2_audio_key} from R2 bucket.[/green]")
    except Exception as e:
        console.print(f"[yellow]Could not delete R2 object ({e}). Continuing.[/yellow]")

    # 2. Sync, remove item, and update RSS feed.xml
    try:
        s3 = get_r2_client()
        obj = s3.get_object(Bucket=settings.R2_BUCKET_NAME, Key="feed.xml")
        r2_feed_xml = obj['Body'].read().decode("utf-8")
        output_feed_path.write_text(r2_feed_xml, encoding="utf-8")
    except Exception:
        pass

    if output_feed_path.exists():
        try:
            tree = ET.parse(output_feed_path)
            root = tree.getroot()
            channel = root.find("channel")
            if channel is not None:
                removed_count = 0
                for item in list(channel.findall("item")):
                    guid = item.find("guid")
                    enclosure = item.find("enclosure")
                    url = ""
                    if enclosure is not None and enclosure.attrib.get("url"):
                        url = enclosure.attrib.get("url", "")
                    elif guid is not None and guid.text:
                        url = guid.text
                    
                    if f"{slug}_master.mp3" in url or f"/{slug}.mp3" in url or slug in url:
                        channel.remove(item)
                        removed_count += 1
                
                if removed_count > 0:
                    tree.write(str(output_feed_path), encoding="utf-8", xml_declaration=True)
                    upload_file_to_r2(output_feed_path, "feed.xml", content_type="application/rss+xml")
                    console.print(f"[green]Removed {removed_count} episode entry from RSS feed and updated R2.[/green]")
        except Exception as e:
            console.print(f"[yellow]Failed to update RSS feed XML during deletion ({e}).[/yellow]")

    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Publish audio episode to Cloudflare R2 RSS feed.")
    parser.add_argument("--audio", type=str, default="output/audio/episode_master.mp3")
    parser.add_argument("--title", type=str, default="Volleyball Coaching Masterclass")
    args = parser.parse_args()

    publish_episode(Path(args.audio), title=args.title)
