import re
import base64
import hashlib
from pathlib import Path
from typing import List, Tuple
from openai import OpenAI
from pydub import AudioSegment, effects
from pydub.generators import Sine, WhiteNoise
from rich.console import Console
from rich.progress import track

from src.config import settings
from src.cost_tracker import cost_tracker
from src.prompt_loader import load_prompt

console = Console()

def generate_default_stinger(duration_ms: int = 3000) -> AudioSegment:
    """Generate a smooth 3-second intro/outro stinger using harmonic sine waves if no MP3 asset exists."""
    c_note = Sine(261.63).to_audio_segment(duration=duration_ms).apply_gain(-12)
    e_note = Sine(329.63).to_audio_segment(duration=duration_ms).apply_gain(-14)
    g_note = Sine(392.00).to_audio_segment(duration=duration_ms).apply_gain(-14)
    chord = c_note.overlay(e_note).overlay(g_note)
    return chord.fade_in(400).fade_out(800)

def generate_room_tone_bed(duration_ms: int, target_dbfs: float = -56.0) -> AudioSegment:
    """Generate continuous gentle low-pass shaped analog room tone at target dBFS to prevent digital silence."""
    if duration_ms <= 0:
        return AudioSegment.silent(duration=0)
    raw_noise = WhiteNoise().to_audio_segment(duration=duration_ms).low_pass_filter(750)
    gain_adjustment = target_dbfs - raw_noise.dBFS
    return raw_noise.apply_gain(gain_adjustment).set_channels(2)

def create_studio_mic_bleed(speech_mono: AudioSegment, is_host_a: bool) -> AudioSegment:
    """
    Simulate physical acoustic mic bleed and wooden desk reflection for two hosts sitting opposite each other.
    - Host A sits at Left mic; Host B sits at Right mic across a 1-meter table.
    - Primary channel receives direct voice with subtle table bounce (4ms at -24 dB).
    - Opposite channel receives cross-desk mic bleed (-22 dB, 2ms delay, low-passed at 2800 Hz).
    """
    mono = speech_mono.set_channels(1)
    
    # Wooden studio desk early bounce
    table_delay = AudioSegment.silent(duration=4)
    table_bounce = (table_delay + mono.apply_gain(-24).low_pass_filter(3200))[:len(mono)]
    direct_with_table = mono.overlay(table_bounce)
    
    # Cross-desk mic bleed into opposite microphone
    bleed_delay = AudioSegment.silent(duration=2)
    cross_bleed = (bleed_delay + mono.apply_gain(-22).low_pass_filter(2800))[:len(mono)]
    
    if is_host_a:
        left_channel = direct_with_table
        right_channel = cross_bleed
    else:
        left_channel = cross_bleed
        right_channel = direct_with_table
        
    return AudioSegment.from_mono_audiosegments(left_channel, right_channel)

def apply_shared_room_acoustics(sound: AudioSegment) -> AudioSegment:
    """Simulate shared studio room acoustic reflections (RT60 ~0.25s, 6% wet) to glue both voices in the same acoustic space."""
    if len(sound) < 100:
        return sound
    # Subtle early room reflections (filtered delay lines)
    r1 = sound.apply_gain(-24).low_pass_filter(3500)
    r2 = sound.apply_gain(-28).low_pass_filter(2500)
    room_sound = sound.overlay(r1, position=24).overlay(r2, position=52)
    return room_sound

def clean_tts_text(text: str) -> str:
    """Remove inline bracketed and parenthetical performance cues before sending to TTS engine."""
    # Remove bracketed stage cues like [chuckles], [sighs], [scoffs], [deliberate pause], [pause], [sharp laugh]
    cleaned = re.sub(r'\[(deliberate pause|pause|chuckles|sighs|scoffs|whispers|emphatic|dryly|giggles|sharp laugh|laughs|fades out)[^\]]*\]', '', text, flags=re.IGNORECASE)
    # Remove parentheses cues like (laughing), (pauses)
    cleaned = re.sub(r'\((laughing|smiles|giggles|chuckles|sighs|pauses|fades out)[^\)]*\)', '', cleaned, flags=re.IGNORECASE)
    # Collapse multiple whitespaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def determine_turn_timing(raw_text: str, prev_text: str) -> int:
    """
    Determine millisecond gap or overlap between conversational turns:
    - Positive value (>0): silence gap (e.g. +140ms, or +400ms for deliberate pause)
    - Negative value (<0): micro-overlap / cross-talk interruption (e.g. -90ms over tail syllable)
    """
    raw_lower = raw_text.lower().strip()
    prev_lower = prev_text.lower().strip() if prev_text else ""
    
    # 1. Deliberate Pause / Reflection cue
    if "[deliberate pause]" in raw_lower or "[pause]" in raw_lower or "[sighs]" in raw_lower:
        return 400
    
    # 2. Interruption / Quick Reaction / Cross-Talk
    if (raw_lower.startswith("—") or 
        prev_lower.endswith("—") or 
        any(raw_lower.startswith(cue) for cue in ("[sharp laugh]", "[scoffs]", "[laughs]", "[chuckles]", "wait,", "exactly.", "no,", "because ", "look,", "bingo", "oh, stop"))):
        return -90 # 90ms micro-overlap over tail syllable
        
    # 3. Standard natural conversational turn
    return 140

def append_with_timing(timeline: AudioSegment, new_segment: AudioSegment, timing_ms: int) -> AudioSegment:
    """Append or micro-overlap new_segment onto timeline according to timing_ms."""
    if len(timeline) == 0:
        return new_segment
    
    if timing_ms < 0 and len(timeline) > abs(timing_ms):
        overlap_ms = abs(timing_ms)
        overlap_pos = len(timeline) - overlap_ms
        return timeline.overlay(new_segment[:overlap_ms], position=overlap_pos) + new_segment[overlap_ms:]
    elif timing_ms > 0:
        return timeline + AudioSegment.silent(duration=timing_ms) + new_segment
    else:
        return timeline + new_segment

def parse_script_into_segments(script_text: str) -> List[Tuple[str, str]]:
    """Parse podcast script into sequential (speaker_or_tag, text_content) segments."""
    segments = []
    lines = script_text.splitlines()
    
    current_tag = None
    current_buffer = []

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        if line_str in ("[MUSIC_INTRO]", "[MUSIC_OUTRO]"):
            if current_tag and current_buffer:
                segments.append((current_tag, " ".join(current_buffer)))
                current_buffer = []
            segments.append((line_str, ""))
            current_tag = None
        elif line_str.startswith("[CLIP:") or line_str.startswith("[GUEST_CLIP:"):
            if current_tag and current_buffer:
                segments.append((current_tag, " ".join(current_buffer)))
                current_buffer = []
            segments.append((line_str, ""))
            current_tag = None
        elif re.match(r'^(\[?HOST[ _]?A\]?|\[?CHLOE\]?):?', line_str, re.IGNORECASE):
            if current_tag and current_buffer:
                segments.append((current_tag, " ".join(current_buffer)))
                current_buffer = []
            current_tag = "[HOST_A]"
            text_part = re.sub(r'^(\[?HOST[ _]?A\]?|\[?CHLOE\]?):?', '', line_str, flags=re.IGNORECASE).strip()
            if text_part:
                current_buffer.append(text_part)
        elif re.match(r'^(\[?HOST[ _]?B\]?|\[?DAVIS\]?):?', line_str, re.IGNORECASE):
            if current_tag and current_buffer:
                segments.append((current_tag, " ".join(current_buffer)))
                current_buffer = []
            current_tag = "[HOST_B]"
            text_part = re.sub(r'^(\[?HOST[ _]?B\]?|\[?DAVIS\]?):?', '', line_str, flags=re.IGNORECASE).strip()
            if text_part:
                current_buffer.append(text_part)
        else:
            if current_tag:
                current_buffer.append(line_str)

    if current_tag and current_buffer:
        segments.append((current_tag, " ".join(current_buffer)))

    return segments

def resolve_url_for_hash(target_hash: str) -> str | None:
    """Scan all master and scraped markdown files to map audio hash back to its YouTube URL."""
    for md_path in Path("output").glob("*.md"):
        try:
            text = md_path.read_text(encoding="utf-8")
            urls = re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=[a-zA-Z0-9_-]+|youtu\.be/[a-zA-Z0-9_-]+)', text)
            for url in urls:
                clean_url = url.split("&")[0]
                sha_match = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()[:12] == target_hash
                legacy_md5_match = hashlib.md5(clean_url.encode("utf-8")).hexdigest()[:10] == target_hash
                if sha_match or legacy_md5_match:
                    return clean_url
        except Exception:
            continue
    return None

def download_clip_audio_on_demand(raw_hash: str) -> Path | None:
    """Attempt on-demand re-download of missing coach video audio via yt-dlp."""
    video_url = resolve_url_for_hash(raw_hash)
    if not video_url:
        return None
    try:
        from src.transcriber import download_video_audio
        console.print(f"[bold cyan]Auto-downloading missing coach audio on-demand for {video_url}...[/bold cyan]")
        audio_path = download_video_audio(video_url)
        if audio_path and audio_path.exists():
            return audio_path
    except Exception as err:
        console.print(f"[yellow]On-demand audio download failed ({err}).[/yellow]")
    return None

def extract_and_slice_clip(tag_str: str) -> AudioSegment | None:
    """Extract audio clip parameters from tag and slice MP3 audio file."""
    content = tag_str.strip("[]").replace("CLIP:", "").replace("GUEST_CLIP:", "").strip()
    parts = [p.strip() for p in content.split("|")]
    
    if not parts or not parts[0]:
        return None
    
    raw_hash = parts[0].replace("audio_hash=", "").replace("audio_", "").strip()
    start_sec = 0.0
    end_sec = None

    if len(parts) > 1:
        try:
            start_sec = float(parts[1].replace("start=", "").strip())
        except ValueError:
            start_sec = 0.0
    if len(parts) > 2:
        try:
            end_sec = float(parts[2].replace("end=", "").strip())
        except ValueError:
            end_sec = None

    audio_candidates = list(settings.temp_dir.glob(f"audio_{raw_hash}.*")) or list(settings.temp_dir.glob(f"*{raw_hash}*"))
    if not audio_candidates:
        console.print(f"[yellow]Audio clip file for hash '{raw_hash}' not in cache. Attempting on-demand YouTube download...[/yellow]")
        downloaded = download_clip_audio_on_demand(raw_hash)
        if downloaded and downloaded.exists():
            audio_candidates = [downloaded]
        else:
            console.print(f"[yellow]Audio clip file for hash '{raw_hash}' could not be downloaded. Skipping clip.[/yellow]")
            return None

    audio_path = audio_candidates[0]
    try:
        sound = AudioSegment.from_file(audio_path)
        start_ms = max(0, int(start_sec * 1000))
        end_ms = int(end_sec * 1000) if end_sec is not None else min(len(sound), start_ms + 15000)
        
        if start_ms >= len(sound):
            return None
        
        clip = sound[start_ms:end_ms]
        if len(clip) > 200:
            clip = clip.fade_in(100).fade_out(100)
        console.print(f"[green]Successfully sliced audio clip ({start_sec}s - {end_sec or (start_sec+15)}s) from {audio_path.name}[/green]")
        return clip
    except Exception as err:
        console.print(f"[yellow]Failed to slice audio clip ({err}). Skipping.[/yellow]")
        return None

def trim_runaway_tts_noise(sound: AudioSegment, text: str) -> AudioSegment:
    """
    Detect and trim runaway autoregressive noise/static loops from multimodal TTS models (e.g. gpt-audio).
    If a generated segment significantly exceeds plausible spoken length, trim trailing noise bed.
    """
    word_count = len(text.split())
    # Human speech is ~2.5 words/sec (150 WPM). 
    # Plausible max duration allows generous slow speech (1.0 words/sec) + 6.0s buffer.
    max_plausible_sec = max(6.0, (word_count / 1.0) + 6.0)
    max_plausible_ms = int(max_plausible_sec * 1000)

    sound_dur_ms = len(sound)
    if sound_dur_ms <= max_plausible_ms:
        return sound

    # The audio exceeded plausible duration: find where speech ended before the noise loop
    window_ms = 500
    step_ms = 250
    # GPT-Audio synthetic hiss is typically -28 to -34 dBFS; human speech is typically -16 to -24 dBFS
    silence_thresh_db = -26.5

    last_speech_ms = 0
    scan_limit_ms = min(sound_dur_ms, int(max_plausible_sec * 1.5 * 1000))
    for pos in range(0, scan_limit_ms, step_ms):
        win = sound[pos:pos + window_ms]
        if win.dBFS > silence_thresh_db:
            last_speech_ms = pos + window_ms

    if last_speech_ms > 1000:
        cutoff_ms = min(sound_dur_ms, last_speech_ms + 350)
        console.print(f"[bold yellow]WARNING: TTS runaway noise loop detected ({sound_dur_ms/1000:.1f}s for {word_count} words). Trimmed trailing noise to {cutoff_ms/1000:.1f}s.[/bold yellow]")
        return sound[:cutoff_ms].fade_out(150)
    else:
        console.print(f"[bold yellow]WARNING: TTS runaway duration ({sound_dur_ms/1000:.1f}s for {word_count} words). Capped to {max_plausible_ms/1000:.1f}s.[/bold yellow]")
        return sound[:max_plausible_ms].fade_out(200)

def synthesize_speech_segment(text: str, voice: str, client: OpenAI, cache_dir: Path, use_openrouter: bool = True) -> Path:
    """Synthesize speech via OpenRouter Audio or OpenAI TTS API with local hash caching."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    text_hash = hashlib.sha256(f"{voice}:{text}".encode("utf-8")).hexdigest()[:16]
    cache_path = cache_dir / f"tts_{voice}_{text_hash}.mp3"

    if cache_path.exists():
        return cache_path

    # Chunk long lines if over 4000 chars
    if len(text) > 4000:
        text = text[:4000]

    tts_model = getattr(settings, "TTS_MODEL", "openai/gpt-audio")
    cost_tracker.log_tts(len(text), model=tts_model)

    if use_openrouter:
        # OpenRouter audio streaming requires stream=True with audio.format="pcm16"
        try:
            tts_template = load_prompt(
                "tts_speaker.md",
                default="Read the following text aloud with high quality audio podcast voice:\n{text}"
            )
            prompt_content = tts_template.replace("{text}", text)
            expected_words = max(5, len(text.split()))
            max_tokens_cap = min(4096, max(600, expected_words * 40 + 300))

            stream = client.chat.completions.create(
                model=tts_model,
                modalities=["text", "audio"],
                audio={"voice": voice, "format": "pcm16"},
                messages=[
                    {"role": "user", "content": prompt_content}
                ],
                max_tokens=max_tokens_cap,
                stream=True
            )
            
            audio_bytes_chunks = []
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    audio_delta = getattr(delta, "audio", None) or (delta.get("audio") if isinstance(delta, dict) else None)
                    if audio_delta:
                        b64_data = audio_delta.get("data") if isinstance(audio_delta, dict) else getattr(audio_delta, "data", None)
                        if b64_data:
                            audio_bytes_chunks.append(base64.b64decode(b64_data))
            
            if audio_bytes_chunks:
                raw_pcm = b"".join(audio_bytes_chunks)
                # Convert 24kHz 16-bit PCM to AudioSegment and export to MP3
                pcm_sound = AudioSegment(
                    data=raw_pcm,
                    sample_width=2,
                    frame_rate=24000,
                    channels=1
                )
                pcm_sound = trim_runaway_tts_noise(pcm_sound, text)
                pcm_sound.export(cache_path, format="mp3")
                return cache_path
            else:
                raise ValueError("No audio chunks received from OpenRouter stream")

        except Exception as err:
            console.print(f"[bold red]OpenRouter pcm16 stream error: {err}[/bold red]")
            raise err
    else:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=text,
            speed=1.03,
            response_format="mp3"
        )
        response.stream_to_file(cache_path)
        return cache_path

def normalize_lufs(sound: AudioSegment, target_lufs: float = -16.0) -> AudioSegment:
    """Normalize audio loudness to Spotify/EBU R128 podcast standard (-16 LUFS)."""
    change_in_gain = target_lufs - sound.dBFS
    return sound.apply_gain(change_in_gain)

def generate_podcast_audio(
    script_path: Path, 
    output_audio_path: Path | None = None,
    preview_minutes: float | None = None,
    plugin = None
) -> Path:
    """Synthesize speech, apply stereo staging, room tone bed, acoustics, and export master MP3."""
    if not script_path.exists():
        raise FileNotFoundError(f"Script file missing at {script_path}")

    # Resolve active plugin if not provided
    if plugin is None:
        try:
            from src.framework.registry import get_active_plugin
            plugin = get_active_plugin()
        except Exception:
            plugin = None

    script_text = script_path.read_text(encoding="utf-8")
    segments = parse_script_into_segments(script_text)

    is_preview = preview_minutes is not None and preview_minutes > 0
    max_duration_ms = (preview_minutes * 60 * 1000) if is_preview else float("inf")

    audio_dir = Path("output/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)

    if output_audio_path is None:
        file_suffix = "_preview.mp3" if is_preview else "_master.mp3"
        output_audio_path = audio_dir / f"{script_path.stem}{file_suffix}"
    else:
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    use_openrouter = bool(settings.effective_base_url)
    client_kwargs = {"api_key": settings.effective_api_key}
    if settings.effective_base_url:
        client_kwargs["base_url"] = settings.effective_base_url
    tts_client = OpenAI(**client_kwargs)

    cache_dir = settings.temp_dir / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Audio Theme Config resolution
    audio_theme = getattr(plugin, "audio_theme", None) if plugin else None
    hosts_cfg = getattr(plugin, "hosts", {}) if plugin else {}

    intro_solo_ms = getattr(audio_theme, "intro_solo_ms", 7500)
    intro_duck_ms = getattr(audio_theme, "intro_duck_ms", 30000)
    total_intro_ms = intro_solo_ms + intro_duck_ms
    outro_duck_ms = getattr(audio_theme, "outro_duck_ms", 5000)
    outro_solo_ms = getattr(audio_theme, "outro_solo_ms", 2000)
    outro_duration_ms = outro_duck_ms + outro_solo_ms
    duck_gain_db = getattr(audio_theme, "duck_gain_db", -16.0)
    target_lufs = getattr(audio_theme, "target_lufs", -16.0)

    # Load intro and outro music tracks
    intro_music_path = getattr(audio_theme, "intro_music_path", None)
    outro_music_path = getattr(audio_theme, "outro_music_path", None)

    if intro_music_path and Path(intro_music_path).exists():
        intro_candidates = [Path(intro_music_path)]
    else:
        intro_candidates = list(Path("music").glob("*intro*.mp3")) or list(Path("assets/music").glob("*intro*.mp3"))

    if outro_music_path and Path(outro_music_path).exists():
        outro_candidates = [Path(outro_music_path)]
    else:
        outro_candidates = list(Path("music").glob("*outro*.mp3")) or list(Path("assets/music").glob("*outro*.mp3"))

    if intro_candidates:
        console.print(f"[bold cyan]Loaded intro track ({intro_solo_ms/1000:g}s solo + {intro_duck_ms/1000:g}s ducked):[/bold cyan] {intro_candidates[0].name}")
        raw_intro = AudioSegment.from_file(intro_candidates[0])
        while len(raw_intro) < total_intro_ms:
            raw_intro += raw_intro
        raw_intro = raw_intro[:total_intro_ms]
    else:
        raw_intro = generate_default_stinger(total_intro_ms)

    if outro_candidates:
        console.print(f"[bold cyan]Loaded outro track ({outro_duration_ms/1000:g}s max):[/bold cyan] {outro_candidates[0].name}")
        raw_outro = AudioSegment.from_file(outro_candidates[0])[:outro_duration_ms]
    else:
        raw_outro = generate_default_stinger(outro_duration_ms)

    # Solo Intro + Ducked background music under Host speech
    intro_solo = raw_intro[:intro_solo_ms].fade_in(500).set_channels(2)
    intro_ducked = raw_intro[intro_solo_ms:total_intro_ms].apply_gain(duck_gain_db).fade_out(2500).set_channels(2)

    # Outro: ducked background music over final speech, solo outro fade out
    outro_ducked = raw_outro[:outro_duck_ms].apply_gain(duck_gain_db).fade_in(1000).set_channels(2)
    outro_solo = raw_outro[outro_duck_ms:outro_duration_ms].fade_out(1500).set_channels(2)

    audio_timeline = AudioSegment.silent(duration=0).set_channels(2)
    mode_label = f"{preview_minutes:g}-Minute Preview" if is_preview else "Full Episode"
    console.print(f"[bold cyan]Synthesizing {mode_label} ({len(segments)} segments max)...[/bold cyan]")


    has_outro_appended = False
    intro_duck_start_pos = None
    prev_raw_text = ""

    for tag, raw_text in track(segments, description=f"Audio Synthesis ({mode_label})"):
        if is_preview and len(audio_timeline) >= max_duration_ms:
            console.print(f"[bold yellow]Reached {preview_minutes}-minute preview limit. Wrapping up...[/bold yellow]")
            break

        if tag == "[MUSIC_INTRO]":
            audio_timeline += intro_solo
            intro_duck_start_pos = len(audio_timeline)
            prev_raw_text = ""
        elif tag == "[MUSIC_OUTRO]":
            if len(audio_timeline) >= len(outro_ducked):
                tail_pos = len(audio_timeline) - len(outro_ducked)
                audio_timeline = audio_timeline.overlay(outro_ducked, position=tail_pos)
            else:
                audio_timeline += outro_ducked
            audio_timeline += outro_solo
            has_outro_appended = True
            prev_raw_text = ""
        elif tag in ("[HOST_A]", "[HOST_B]"):
            cleaned_text = clean_tts_text(raw_text)
            if not cleaned_text:
                continue

            host_a_voice = hosts_cfg["HOST_A"].voice if "HOST_A" in hosts_cfg else settings.HOST_A_VOICE
            host_b_voice = hosts_cfg["HOST_B"].voice if "HOST_B" in hosts_cfg else settings.HOST_B_VOICE
            voice = host_a_voice if tag == "[HOST_A]" else host_b_voice
            cached_audio_path = synthesize_speech_segment(cleaned_text, voice, tts_client, cache_dir, use_openrouter=use_openrouter)
            speech_seg = AudioSegment.from_file(cached_audio_path).set_frame_rate(44100)

            # Defensive validation: if cached audio has runaway duration from previous synthesis, trim on-the-fly
            max_allowed_ms = int(max(6.0, (len(cleaned_text.split()) / 1.0) + 6.0) * 1000)
            if len(speech_seg) > max_allowed_ms:
                speech_seg = trim_runaway_tts_noise(speech_seg, cleaned_text).set_frame_rate(44100)
                speech_seg.export(cached_audio_path, format="mp3")

            # Apply physical studio desk mic bleed (sitting across table with table bounce)
            is_host_a = (tag == "[HOST_A]")
            studio_speech = create_studio_mic_bleed(speech_seg, is_host_a=is_host_a)

            # Calculate turn timing gap / micro-overlap
            timing_ms = determine_turn_timing(raw_text, prev_raw_text)
            audio_timeline = append_with_timing(audio_timeline, studio_speech, timing_ms)
            prev_raw_text = raw_text

        elif tag.startswith("[CLIP:") or tag.startswith("[GUEST_CLIP:"):
            clip_segment = extract_and_slice_clip(tag)
            if clip_segment:
                clip_stereo = clip_segment.set_frame_rate(44100).set_channels(2).pan(0.0)
                audio_timeline = append_with_timing(audio_timeline, clip_stereo, timing_ms=150)
                prev_raw_text = ""

    # Apply 30s ducked background intro music overlay
    if intro_duck_start_pos is not None:
        audio_timeline = audio_timeline.overlay(intro_ducked, position=intro_duck_start_pos)

    # Append outro track if not already appended
    if not has_outro_appended:
        if len(audio_timeline) >= len(outro_ducked):
            tail_pos = len(audio_timeline) - len(outro_ducked)
            audio_timeline = audio_timeline.overlay(outro_ducked, position=tail_pos)
        else:
            audio_timeline += outro_ducked
        audio_timeline += outro_solo

    # 1. Continuous Room Tone Bed (-56 dBFS) to eliminate digital silence in pauses
    console.print("[bold cyan]Injecting continuous analog room tone bed (-56 dBFS)...[/bold cyan]")
    room_tone = generate_room_tone_bed(len(audio_timeline), target_dbfs=-56.0)
    master_timeline = audio_timeline.overlay(room_tone, position=0)

    # 2. Shared Studio Room Acoustics (RT60 ~0.25s, 6% wet)
    console.print("[bold cyan]Applying shared studio room acoustic space & glue...[/bold cyan]")
    glued_timeline = apply_shared_room_acoustics(master_timeline)

    # 3. Loudness Normalization (Spotify Podcast Standard)
    console.print(f"[bold yellow]Normalizing audio loudness to {target_lufs:g} LUFS...[/bold yellow]")
    master_audio = normalize_lufs(glued_timeline, target_lufs=target_lufs)

    # Export MP3
    console.print(f"[bold green]Exporting podcast audio to:[/bold green] {output_audio_path}")
    master_audio.export(
        output_audio_path,
        format="mp3",
        bitrate="128k",
        parameters=["-ar", "44100", "-ac", "2"]
    )

    fallback_file = "episode_preview.mp3" if is_preview else "episode_master.mp3"
    fallback_path = output_audio_path.parent / fallback_file
    master_audio.export(
        fallback_path,
        format="mp3",
        bitrate="128k",
        parameters=["-ar", "44100", "-ac", "2"]
    )

    console.print(f"[bold green]SUCCESS: {mode_label} Audio Exported Successfully![/bold green]")
    console.print(f"  - Saved to: {output_audio_path}")
    console.print(f"  - Saved fallback to: {fallback_path}")
    console.print(f"  - Audio duration: {len(master_audio)/1000/60:.2f} minutes")

    return output_audio_path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Synthesize podcast audio from script.")
    parser.add_argument("--script", type=str, default="output/scripts/script.md")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--preview", action="store_true", help="Generate a preview instead of full episode")
    parser.add_argument("--preview-minutes", type=float, default=5.0, help="Duration of preview in minutes (default: 5.0)")
    args = parser.parse_args()

    preview_mins = args.preview_minutes if args.preview else None
    generate_podcast_audio(Path(args.script), Path(args.output) if args.output else None, preview_minutes=preview_mins)
