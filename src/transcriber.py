import os
import hashlib
from pathlib import Path
from typing import List, Dict
import yt_dlp
from openai import OpenAI
from rich.console import Console
from pydantic import BaseModel

from src.config import settings
from src.cost_tracker import cost_tracker
from src.prompt_loader import load_prompt

console = Console()

class VideoTranscript(BaseModel):
    video_url: str
    audio_path: str
    transcript: str

def get_url_hash(url: str) -> str:
    """Generate SHA-256 hash for collision-resistant URL caching."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]

COMMON_YDL_OPTS = {
    'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
    'quiet': True,
    'no_warnings': True,
}


import time
import random

PLAYER_CLIENT_FALLBACKS = [
    ['android'],
    ['android', 'ios'],
    ['ios'],
    ['mweb'],
    ['web'],
]

def download_video_audio(video_url: str) -> Path:
    """Download audio stream from YouTube/Vimeo video using yt-dlp with 5 retries and randomized 5-10s backoff."""
    url_hash = get_url_hash(video_url)

    # Check if any cached audio file exists for this URL hash
    for f in settings.temp_dir.glob(f"audio_{url_hash}.*"):
        if f.suffix.lower() in [".mp3", ".m4a", ".webm", ".opus", ".wav", ".aac"]:
            console.print(f"[dim]Audio cache hit for {video_url} -> {f.name}[/dim]")
            return f

    expected_mp3 = settings.temp_dir / f"audio_{url_hash}.mp3"
    console.print(f"[cyan]Downloading audio with yt-dlp:[/cyan] {video_url}")

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        client_choice = PLAYER_CLIENT_FALLBACKS[(attempt - 1) % len(PLAYER_CLIENT_FALLBACKS)]
        ydl_opts = {
            **COMMON_YDL_OPTS,
            'extractor_args': {'youtube': {'player_client': client_choice}},
            'format': 'bestaudio/best',
            'outtmpl': str(settings.temp_dir / f"audio_{url_hash}.%(ext)s"),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            break
        except Exception as err:
            err_msg = str(err).lower()
            if "not available" in err_msg or "private" in err_msg or "removed" in err_msg:
                console.print(f"[yellow]Video unavailable on YouTube ({err}). Skipping retries.[/yellow]")
                raise err
            if attempt < max_retries:
                wait_sec = random.uniform(5.0, 10.0)
                console.print(f"[yellow]yt-dlp download attempt {attempt}/{max_retries} failed ({err}). Waiting {wait_sec:.1f}s before retry with client {client_choice}...[/yellow]")
                time.sleep(wait_sec)
            else:
                raise err

    for f in settings.temp_dir.glob(f"audio_{url_hash}.*"):
        return f

    return expected_mp3

def transcribe_audio(audio_path: Path, video_url: str) -> str:
    """Transcribe audio file using OpenAI / OpenRouter Whisper or multimodal audio model with caching."""
    url_hash = get_url_hash(video_url)
    transcript_cache = settings.temp_dir / f"transcript_{url_hash}.txt"

    if transcript_cache.exists():
        console.print(f"[dim]Transcript cache hit for {video_url}[/dim]")
        return transcript_cache.read_text(encoding="utf-8")

    # Initialize OpenAI client with effective API key and optional OpenRouter base_url
    client_kwargs = {"api_key": settings.effective_api_key}
    if settings.effective_base_url:
        client_kwargs["base_url"] = settings.effective_base_url
    client = OpenAI(**client_kwargs)

    transcription_model = "openai/whisper-1" if settings.effective_base_url else "whisper-1"

    try:
        with console.status(f"[bold cyan]Transcribing audio ({audio_path.name})... Please wait...[/bold cyan]"):
            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=transcription_model,
                    file=audio_file,
                    response_format="verbose_json"
                )

            duration = getattr(response, "duration", 60.0)
            if not duration or duration <= 0:
                try:
                    from pydub import AudioSegment
                    duration = len(AudioSegment.from_file(audio_path)) / 1000.0
                except Exception:
                    duration = 60.0
            cost_tracker.log_whisper(duration, model=transcription_model)

            segments = getattr(response, "segments", None)
            if isinstance(response, dict):
                segments = response.get("segments")

            if segments:
                formatted_lines = []
                for seg in segments:
                    s_start = getattr(seg, "start", seg.get("start", 0) if isinstance(seg, dict) else 0)
                    s_end = getattr(seg, "end", seg.get("end", 0) if isinstance(seg, dict) else 0)
                    s_text = getattr(seg, "text", seg.get("text", "") if isinstance(seg, dict) else "").strip()
                    if s_text:
                        formatted_lines.append(f'[CLIP_REF: audio_hash={url_hash} | start={s_start:.1f} | end={s_end:.1f}] "{s_text}"')
                transcript_text = "\n".join(formatted_lines)
            else:
                raw_text = getattr(response, "text", str(response) if not isinstance(response, dict) else response.get("text", "")).strip()
                # Default chunking every ~15 seconds for fallback raw text
                words = raw_text.split()
                formatted_lines = []
                chunk_size = 25
                for idx, i in enumerate(range(0, len(words), chunk_size)):
                    chunk_words = " ".join(words[i:i+chunk_size])
                    start_s = idx * 10.0
                    end_s = (idx + 1) * 10.0
                    formatted_lines.append(f'[CLIP_REF: audio_hash={url_hash} | start={start_s:.1f} | end={end_s:.1f}] "{chunk_words}"')
                transcript_text = "\n".join(formatted_lines)

    except Exception as err:
        console.print(f"[yellow]Whisper audio API failed ({err}). Trying OpenRouter multimodal audio fallback...[/yellow]")
        import base64
        audio_data = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
        
        # OpenRouter multimodal audio transcription fallback
        fallback_model = "google/gemini-2.5-flash"
        transcribe_template = load_prompt(
            "audio_transcriber_fallback.md",
            default='Provide an exact, verbatim transcript of this coaching audio clip. Group into 10-second timestamped lines using format: [CLIP_REF: audio_hash={url_hash} | start=X.X | end=Y.Y] "spoken text".'
        )
        transcribe_instruction = transcribe_template.replace("{url_hash}", url_hash)
        response = client.chat.completions.create(
            model=fallback_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": transcribe_instruction
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_data,
                                "format": "mp3"
                            }
                        }
                    ]
                }
            ]
        )
        transcript_text = response.choices[0].message.content.strip()

    transcript_cache.write_text(transcript_text, encoding="utf-8")
    return transcript_text

def is_volleybrains_video(video_url: str) -> bool:
    """Verify if YouTube video belongs to the @volleybrains channel."""
    if "youtube.com" not in video_url and "youtu.be" not in video_url:
        return True

    try:
        with yt_dlp.YoutubeDL(COMMON_YDL_OPTS) as ydl:
            info = ydl.extract_info(video_url, download=False)
            uploader_id = str(info.get('uploader_id', '')).lower()
            uploader = str(info.get('uploader', '')).lower()
            uploader_url = str(info.get('uploader_url', '')).lower()

            is_valid = ("volleybrains" in uploader_id or "volleybrains" in uploader or "volleybrains" in uploader_url)
            if not is_valid:
                console.print(f"[yellow]Skipping YouTube video not from @volleybrains channel ({uploader}):[/yellow] {video_url}")
            return is_valid
    except Exception as err:
        err_msg = str(err).lower()
        if "not available" in err_msg or "private" in err_msg or "removed" in err_msg:
            console.print(f"[yellow]Skipping unavailable/private YouTube video ({err}):[/yellow] {video_url}")
            return False
        console.print(f"[yellow]Could not verify YouTube video channel ({err}). Proceeding.[/yellow]")
        return True

from collections import deque

def process_video_transcripts(video_urls: List[str]) -> List[VideoTranscript]:
    """Download and transcribe list of video URLs with retry queueing until all videos are completed."""
    queue = deque(video_urls)
    transcripts_by_url: Dict[str, VideoTranscript] = {}
    attempts_per_url: Dict[str, int] = {url: 0 for url in video_urls}
    total_unique = len(video_urls)

    while queue:
        url = queue.popleft()
        attempts_per_url[url] += 1
        pass_num = attempts_per_url[url]
        remaining_in_queue = len(queue)
        completed_count = len(transcripts_by_url)

        console.print(f"\n[bold yellow]Processing Video ({completed_count + 1}/{total_unique} done, Pass {pass_num}, {remaining_in_queue} in queue):[/bold yellow] {url}")

        # Filter non-VolleyBrains YouTube videos
        if not is_volleybrains_video(url):
            console.print(f"[dim]Skipping video {url} (not from @volleybrains channel or removed).[/dim]")
            transcripts_by_url[url] = VideoTranscript(
                video_url=url,
                audio_path="",
                transcript="[Video skipped: not @volleybrains channel]"
            )
            continue

        try:
            audio_path = download_video_audio(url)
            transcript = transcribe_audio(audio_path, url)
            transcripts_by_url[url] = VideoTranscript(
                video_url=url,
                audio_path=str(audio_path),
                transcript=transcript
            )
            console.print(f"[green]Successfully transcribed video ({completed_count + 1}/{total_unique})[/green] ({len(transcript.split())} words)")
        except Exception as e:
            err_msg = str(e).lower()
            if "not available" in err_msg or "private" in err_msg or "removed" in err_msg:
                console.print(f"[yellow]Video permanently unavailable ({e}). Skipping permanently.[/yellow]")
                transcripts_by_url[url] = VideoTranscript(
                    video_url=url,
                    audio_path="",
                    transcript=f"[Video unavailable: {e}]"
                )
            else:
                # Video download failed after 5 retries: re-enqueue at the end
                console.print(f"[bold red]Download attempt failed for {url} ({e}). Moving to end of queue to retry later...[/bold red]")
                wait_sec = random.uniform(5.0, 10.0)
                time.sleep(wait_sec)
                queue.append(url)

        # Brief pause between video items
        time.sleep(1.5)

    return [transcripts_by_url[u] for u in video_urls if u in transcripts_by_url]

def merge_article_and_transcripts(scraped_md_path: Path, output_master_path: Path) -> Path:
    """Combine scraped article markdown with video transcripts into master_content.md."""
    if not scraped_md_path.exists():
        raise FileNotFoundError(f"Scraped article markdown not found at {scraped_md_path}")

    content = scraped_md_path.read_text(encoding="utf-8")

    # Extract video URLs from markdown
    video_urls = []
    for line in content.splitlines():
        line_str = line.strip()
        if line_str.startswith("- https://www.youtube.com/") or line_str.startswith("- https://vimeo.com/"):
            url = line_str.lstrip("- ").strip()
            if url not in video_urls:
                video_urls.append(url)

    console.print(f"[bold cyan]Found {len(video_urls)} video URLs in {scraped_md_path.name}[/bold cyan]")
    transcripts = process_video_transcripts(video_urls)

    # Map video URLs to their transcripts
    transcript_map = {vt.video_url: vt.transcript for vt in transcripts}

    # Inline video transcripts directly into the article text where the video URLs appear
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        new_lines.append(line)
        line_str = line.strip()
        if line_str.startswith("- https://www.youtube.com/") or line_str.startswith("- https://vimeo.com/"):
            url = line_str.lstrip("- ").strip()
            if url in transcript_map:
                t_text = transcript_map[url]
                new_lines.append("\n> **[EMBEDDED VIDEO TRANSCRIPT]**")
                for t_line in t_text.splitlines():
                    new_lines.append(f"> {t_line}")
                new_lines.append("\n")

    master_md = "\n".join(new_lines)

    output_master_path.parent.mkdir(parents=True, exist_ok=True)
    output_master_path.write_text(master_md, encoding="utf-8")
    console.print(f"\n[bold green]Saved compiled inlined master content to:[/bold green] {output_master_path}")
    return output_master_path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract video transcripts and create master content.")
    parser.add_argument("--input", type=str, default="output/scraped_article.md", help="Path to scraped article markdown")
    parser.add_argument("--output", type=str, default="output/master_content.md", help="Path to output master content markdown")
    args = parser.parse_args()

    merge_article_and_transcripts(Path(args.input), Path(args.output))
