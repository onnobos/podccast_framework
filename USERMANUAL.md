# Podcast Automation Framework — Complete User Manual

Welcome to the **Podcast Automation Framework** (`podcast-framework`) operational manual. This document provides an exhaustive, step-by-step guide for producers, developers, and sound engineers running the modular podcast generation engine on Windows 10/11.

---

## Table of Contents

1. [System Overview & Framework Architecture](#1-system-overview--framework-architecture)
2. [Prerequisites & System Setup](#2-prerequisites--system-setup)
3. [Environment Configuration (`.env`)](#3-environment-configuration-env)
4. [Interactive Main Menu & CLI Operation](#4-interactive-main-menu--cli-operation)
5. [Generating a New Episode](#5-generating-a-new-episode)
6. [Rebuilding Single & Multiple Episodes](#6-rebuilding-single--multiple-episodes)
7. [The 6-Stage Framework Pipeline](#7-the-6-stage-framework-pipeline)
8. [Audio Broadcast Standards & Physical Acoustics](#8-audio-broadcast-standards--physical-acoustics)
9. [Universal Editorial Standards & Scriptwriting Rules](#9-universal-editorial-standards--scriptwriting-rules)
10. [Developing Custom Show Plugins](#10-developing-custom-show-plugins)
11. [Flagship Reference Plugin: Volleyball Coaching Uncovered](#11-flagship-reference-plugin-volleyball-coaching-uncovered)
12. [Subscribing in Spotify & Mobile Podcast Apps](#12-subscribing-in-spotify--mobile-podcast-apps)
13. [Maintenance, Feed Sync & Episode Deletion](#13-maintenance-feed-sync--episode-deletion)
14. [Automated Framework Testing](#14-automated-framework-testing)
15. [Troubleshooting & Frequently Asked Questions](#15-troubleshooting--frequently-asked-questions)

---

## 1. System Overview & Framework Architecture

The framework is a modular, studio-grade audio production engine that converts rich source material (web articles, video masterclasses, newsletters, YouTube channels) into 2-host conversational audio podcast episodes.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PODCAST FRAMEWORK CORE                          │
│                                                                        │
│   src/framework/                                                       │
│   ├── models.py          # Data models (Hosts, Themes, ShowMetadata)   │
│   ├── base_plugin.py     # PodcastPlugin Abstract Base Class           │
│   ├── base_ingester.py   # BaseIngester Abstract Base Class            │
│   └── registry.py        # Dynamic discovery & active show management  │
│                                                                        │
│   Core Engines (src/)                                                  │
│   ├── audio_engine.py    # Multi-host synthesis, clip mixing & LUFS    │
│   ├── scriptwriter.py    # Two-brain curation & script synthesis       │
│   ├── script_verifier.py # Empirical fact & ratio audit loop           │
│   ├── transcriber.py     # Video extraction & Whisper transcription    │
│   └── rss_publisher.py   # Cloudflare R2 uploader & RSS generator      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Pluggable Interface
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       PLUGINS DIRECTORY (plugins/)                     │
│                                                                        │
│   plugins/volleyball/    # Flagship: Volleyball Coaching Uncovered     │
│   plugins/<custom_show>/ # Your custom podcast show                    │
└────────────────────────────────────────────────────────────────────────┘
```

### Core Architectural Pillars
- **Framework & Plugin Decoupling**: Core engines (`src/`) contain zero hardcoded show titles, host names, or domain logic. All show configuration lives in `plugins/<slug>/`.
- **Two-Brain LLM Architecture**: Curates high-leverage audio clips with `google/gemini-2.5-pro` and writes natural 20–30 minute host dialogue with `anthropic/claude-sonnet-4`.
- **Physical Studio Acoustics**: Slices source interview audio directly into conversation, layered over cross-desk mic bleed, desk reflection, room tone beds, and ducked music normalized to **-16 LUFS** (EBU R128).
- **Private Cloud Distribution**: Publishes compliant Spotify v1.10 RSS feeds (`feed.xml`) directly to Cloudflare R2 object storage.

---

## 2. Prerequisites & System Setup

### Hardware & OS Requirements
- **Operating System**: Windows 10 or Windows 11 (PowerShell 5.1+ or PowerShell 7+).
- **Python**: Version 3.11 or higher (tested on 3.11, 3.12, 3.13).
- **Disk Space**: At least 5 GB free disk space for raw media caching and master WAV stems.

### Step 1: Install FFmpeg (System Dependency)
FFmpeg is required for loudness normalization, audio filtering, and clip slicing:
```powershell
winget install FFmpeg
```
> **IMPORTANT**: Restart PowerShell after installing so `ffmpeg` is loaded in your `PATH`. Verify with:
```powershell
ffmpeg -version
```

### Step 2: Set Up Python Virtual Environment
Open PowerShell, navigate to the repository directory, and initialize the virtual environment:
```powershell
cd c:\projects\volleyball-podccast

# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1
```

### Step 3: Install Python Dependencies & Playwright
```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

---

## 3. Environment Configuration (`.env`)

Configuration is managed securely via `pydantic-settings`. 

> **SECURITY INVARIANT**: AI agents and automated scripts MUST NEVER read, edit, or commit `.env`. All environment setup must be performed manually.

Create your `.env` file from the provided template:
```powershell
copy .env.example .env
```

Populate your `.env` with your API credentials:
```env
# OpenRouter API Key (Routes Gemini 2.5 Pro, Claude Sonnet 4, and GPT-Audio)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# OpenAI API Key (For Whisper-1 transcription)
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Cloudflare R2 Storage Credentials (For podcast distribution)
R2_ACCOUNT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
R2_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
R2_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
R2_BUCKET_NAME=your-podcast-bucket
R2_PUBLIC_DOMAIN=https://pub-xxxxxxxxxxxxxxxx.r2.dev

# Volleyball Show Ingester Account (Only needed when running volleyball plugin)
VOLLEYBRAINS_EMAIL=your-email@example.com
```

---

## 4. Interactive Main Menu & CLI Operation

Running `main.py` with no arguments launches the interactive TUI:

```powershell
python main.py
```

```text
============================================================================
╭───────────────────────────────────────────────────────────────────────╮
│ PODCAST GENERATION FRAMEWORK                                          │
│ Active Show: Volleyball Coaching Uncovered (volleyball)               │
╰───────────────────────────────────────────────────────────────────────╯
What would you like to do?

  [1] Generate New Episode from URL (Using active show pipeline)
  [2] Rebuild / Reproduce an Episode (Full rebuild, script+audio, or audio-only)
  [3] List Generated Episodes (View scraped, master content, script & audio status)
  [4] Synchronize R2 RSS Feed (Clean feed.xml so it strictly matches local episodes)
  [5] Delete / Purge an Episode (Delete local episode files and/or Cloudflare R2 bucket items)
  [6] Switch Podcast Show Plugin (Installed: 1)
  [7] Exit
============================================================================
```

### Direct CLI Commands

```powershell
# List all installed show plugins
python main.py plugins

# Generate an episode using the active plugin
python main.py generate "https://example.com/source-url" --publish

# Generate using a specific plugin
python main.py generate "https://example.com/source-url" --plugin volleyball --publish

# Batch rebuild existing episodes
python main.py rebuild

# Synchronize Cloudflare R2 RSS feed
python main.py sync-feed

# Delete an episode locally and from Cloudflare R2
python main.py delete --slug episode-slug --from-r2 --yes
```

---

## 5. Generating a New Episode

To generate a complete episode from an online source:

### Option A: Via Main Menu
1. Run `python main.py` and select `[1]`.
2. Paste the target source URL.
3. Confirm whether to publish automatically to Cloudflare R2 (`Y/n`).

### Option B: Via Command Line
```powershell
# Generate with active plugin and publish:
python main.py generate "https://example.com/article" --publish

# Generate offline without publishing (for local inspection):
python main.py generate "https://example.com/article"

# Run browser in headless mode:
python main.py generate "https://example.com/article" --headless
```

---

## 6. Rebuilding Single & Multiple Episodes

The rebuild engine allows reproducing, re-curating, or re-rendering any existing episode without re-scraping from scratch.

### Interactive Rebuild Selector
Run:
```powershell
python main.py rebuild
```
Select target episodes using:
- **Comma lists**: `1, 3, 5`
- **Ranges**: `1-4`
- **Keywords**: `all`
- **Slugs**: `andre-sa`

### The Four Rebuild Scopes
```text
Choose Rebuild Scope:
  [1] Full Rebuild from Scratch (Re-scrape source, re-transcribe, re-curate, fresh script & audio)
  [2] Re-curate Storylines, Script & Audio (DEFAULT: re-runs Gemini 2.5 Pro curator on transcripts, fresh script & audio)
  [3] Rebuild Script & Audio (Keeps existing curated themes, synthesizes fresh script & audio)
  [4] Rebuild Audio Only (Keeps existing script, re-mixes acoustic studio audio master)
```

---

## 7. The 6-Stage Framework Pipeline

The core framework executes a structured 6-stage lifecycle:

### Stage 1: Ingestion (`BaseIngester`)
- Dispatches the source URL to the active plugin's ingester.
- Extracts article text, tactical breakdowns, and embedded video/audio links.
- Generates slug-strict `output/scraped_{slug}.md`.

### Stage 2: Media Extraction & Whisper Transcription (`src/transcriber.py`)
- Downloads video audio using `yt-dlp` with mobile client rotation (`android` -> `ios`) and resilient backoff queueing.
- Transcribes clips via OpenAI Whisper (`whisper-1`).
- Produces `output/master_{slug}.md` tagging all speech segments with unique hashes: `[CLIP_REF: audio_hash | start | end | quote]`.

### Stage 3: Two-Brain Editorial & Script Synthesis (`src/scriptwriter.py`)
- **Brain 1 — Curator (`google/gemini-2.5-pro`)**: Ingests full master content (25k+ words); extracts core tensions, evolutionary storyline chapters, and high-leverage clips.
- **Brain 2 — Scriptwriter (`anthropic/claude-sonnet-4`)**: Synthesizes 20–30 minute conversational scripts (~1,800–2,500 host words) using the active plugin's host lenses.
- **Auditor (`google/gemini-2.5-flash`)**: Audits empirical fact-checking, clip ratios, and prohibited buzzwords via `src/script_verifier.py`.

### Stage 4: Interactive Human-in-the-Loop Review (`main.py`)
- Halts before spending TTS synthesis credits.
- Displays an episode summary table with word counts, clip durations, and status badges.
- Allows live inspection/editing of `output/scripts/{slug}_script.md` in your editor before pressing Enter.

### Stage 5: Acoustic Studio Audio Engineering (`src/audio_engine.py`)
- **Studio Voices (`openai/gpt-audio`)**: Synthesizes host lines with assigned studio voices (`shimmer`, `ash`, `alloy`, `echo`).
- **Clip Slicing**: Slices authentic WAV audio segments using `[CLIP: audio_hash | start | end]` tags.
- **Mastering**: EBU R128 loudness normalization applied to master stereo MP3 at `-16 LUFS`.

### Stage 6: Distribution & Spotify RSS Sync (`src/rss_publisher.py`)
- Uploads the master MP3 and cover artwork to Cloudflare R2 object storage.
- Updates `feed.xml` with mandatory RFC-2822 `<pubDate>`, iTunes category, and duration tags.
- Prints an itemized cost table detailing Whisper seconds, LLM tokens, and TTS characters.

---

## 8. Audio Broadcast Standards & Physical Acoustics

| Audio Parameter | Value / Standard | Technical Implementation |
| :--- | :--- | :--- |
| **Integrated Loudness** | **-16.0 LUFS** | EBU R128 / Spotify podcast standard |
| **Format & Bitrate** | Stereo MP3, 44.1 kHz, 128 kbps | High-efficiency broadcast compression |
| **Room Tone Bed** | `-56 dBFS` continuous | Eliminates unnatural digital zero silence |
| **Cross-Desk Mic Bleed** | `-22 dB`, `2ms` acoustic delay | Symmetrical acoustic bleed between Host A & Host B |
| **Desk Bounce Reflection** | `-24 dB`, `4ms` delay | Simulates sound reflecting off studio desk |
| **Turn Timing** | `-90ms` to `+400ms` | Dynamic conversational overlaps & thoughtful pauses |
| **Intro Music** | 7.5s solo, 30s bed ducked at `-16dB` | Smooth acoustic transition into speech |
| **Outro Music** | 5s ducked at `-16dB`, 2s solo fade | Clean broadcast conclusion |

---

## 9. Universal Editorial Standards & Scriptwriting Rules

All plugins benefit from framework-level editorial rules enforced across prompt templates:

1. **One Unified Continuous Storyline:**
   The episode flows as a single continuous conversation. Meta-announcements like *"in our next chapter"* or *"moving on to part 2"* are strictly banned.
2. **Zero Tolerance for Hype Clichés:**
   Cheerleading buzzwords (*"incredible"*, *"this is huge"*, *"fascinating"*, *"game-changer"*, *"insane"*, *"unbelievable"*, *"mind-blowing"*) are prohibited and replaced with domain-specific analysis.
3. **"Yes, But" Conversational Friction:**
   Hosts avoid reflexive agreement (*"Right!"*, *"Exactly!"*). They stress-test edge cases before reaching consensus.
4. **Anti-Announcer Clip Seams:**
   Eliminates radio announcer tropes (*"Listen to this clip"*, *"Let's hear what he says"*). Clips are led into with argumentative assertions or open questions.
5. **Structural Audio Cues:**
   Scripts strictly use parseable cue tags:
   - `[MUSIC_INTRO]` / `[MUSIC_OUTRO]`
   - `[HOST_A]` / `[HOST_B]`
   - `[CLIP: audio_hash | start | end]`

---

## 10. Developing Custom Show Plugins

Plugins live in `plugins/<show_slug>/` and encapsulate all show-specific configuration.

### Plugin Directory Layout
```text
plugins/
  └── <your_podcast_slug>/
      ├── __init__.py
      ├── plugin.py              # PodcastPlugin subclass (Required)
      ├── ingester.py            # BaseIngester subclass (Required)
      ├── prompts/               # Custom Prompt Markdown files (Optional)
      │   ├── curator_system.md
      │   ├── hosts.md
      │   ├── script_generator_system.md
      │   └── script_verifier_system.md
      └── assets/                # Audio stingers & artwork (Optional)
          ├── cover_art.jpg
          └── music/
```

### Implementing `plugin.py`
```python
from typing import Dict
from src.framework.base_plugin import PodcastPlugin
from src.framework.base_ingester import BaseIngester
from src.framework.models import (
    ShowMetadata, HostConfig, AudioThemeConfig,
    CloudDistributionConfig, ScriptConfig
)

class MyCustomPlugin(PodcastPlugin):
    @property
    def name(self) -> str:
        return "Silicon Tactical"

    @property
    def slug(self) -> str:
        return "silicon_tactical"

    @property
    def show_metadata(self) -> ShowMetadata:
        return ShowMetadata(
            title="Silicon Tactical",
            author="Studio Media",
            email="show@example.com",
            description="Engineering leadership and startup tactics."
        )

    @property
    def hosts(self) -> Dict[str, HostConfig]:
        return {
            "HOST_A": HostConfig(name="Alex", role="Anchor", voice="alloy", mic_position="left"),
            "HOST_B": HostConfig(name="Jordan", role="Analyst", voice="echo", mic_position="right")
        }

    def get_ingester(self) -> BaseIngester:
        from .ingester import MyCustomIngester
        return MyCustomIngester()
```

Consult [`plugins/README.md`](file:///c:/projects/volleyball-podccast/plugins/README.md) for full instructions.

---

## 11. Flagship Reference Plugin: Volleyball Coaching Uncovered

Located in `plugins/volleyball/`, this reference plugin showcases advanced paywalled web scraping and sports analytics:

- **Target Audience:** Volleyball coaches listening during their morning commute.
- **Hosts:**
  - **Host A (Chloe Miller, voice: `shimmer`):** Former European pro & NCAA D1 realist. Focuses on locker room realities, drill mechanics, and accountability.
  - **Host B (Davis Hayes, voice: `ash`):** Broadcast color commentator. Focuses on macro-psychology, sideline body language, and timeout communication.
- **Key Invariants:**
  - **Brand Neutrality (STRICT):** Show title is strictly *"Volleyball Coaching Uncovered"*. Platform brand names are omitted from dialogue.
  - **Coach Audio Ratio (>= 40%):** Coach speech accounts for 10–12 minutes of total runtime.
  - **Four Evolutionary Chapters:**
    1. *Origin & Risk*
    2. *Tactical Systems & Opponent Classification*
    3. *Self-Enforcing Culture & Accountability*
    4. *Tactical Evolution & The Future*
- **One-Time Paywall Authentication**:
  Run once to save Ghost CMS login cookies to `.auth/storageState.json`:
  ```powershell
  python -m src.auth
  ```

---

## 12. Subscribing in Spotify & Mobile Podcast Apps

1. Obtain your public RSS feed link: `https://<YOUR_R2_PUBLIC_DOMAIN>/feed.xml`
2. Open Spotify, Pocket Casts, Apple Podcasts, or Overcast.
3. Select **Add Podcast by RSS Feed / URL**.
4. Paste your feed URL. Newly published episodes appear immediately with full show notes and cover artwork.

---

## 13. Maintenance, Feed Sync & Episode Deletion

### Synchronizing the RSS Feed
If local files were manually removed or you need to rebuild `feed.xml`:
```powershell
python main.py sync-feed
```

### Deleting an Episode
```powershell
# Interactive deletion wizard:
python main.py delete

# Automated deletion locally and from Cloudflare R2:
python main.py delete --slug episode-slug --from-r2 --yes
```

---

## 14. Automated Framework Testing

The framework includes 23 unit tests verifying data models, base ingesters, plugin contracts, registry discovery, prompt fallbacks, and script validation:

```powershell
.\venv\Scripts\python.exe -m unittest tests/test_framework.py
```
*Expected Output:*
```text
.......................
----------------------------------------------------------------------
Ran 23 tests in 0.043s

OK
```

---

## 15. Troubleshooting & Frequently Asked Questions

### 1. Scraping / Paywall Issues
- **Symptom**: `Playwright error: Target closed` or login loop.
- **Solution**: Re-authenticate by running `python -m src.auth` with `--headless False` to refresh `.auth/storageState.json`.

### 2. Video Download 403 Forbidden Errors
- **Symptom**: `yt-dlp: HTTP Error 403: Forbidden`.
- **Solution**: The pipeline uses mobile client emulation (`{'player_client': ['android', 'ios']}`). Ensure desktop user-agents are not overridden.

### 3. Windows Terminal Unicode Errors
- **Symptom**: `UnicodeEncodeError: 'charmap' codec can't encode...`.
- **Solution**: The codebase strictly uses ASCII-safe status tags (`[PASS]`, `SUCCESS:`). Ensure PowerShell uses UTF-8:
  ```powershell
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  ```

### 4. OpenRouter API Errors
- **Symptom**: `AuthenticationError` or `401 Unauthorized`.
- **Solution**: Verify `OPENROUTER_API_KEY` in `.env`. All LLM calls route through `https://openrouter.ai/api/v1`.
