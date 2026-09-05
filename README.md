# Podcast Automation Framework

An automated, studio-grade **Podcast Generation Framework** with a modular **Plugin Architecture**. The engine transforms rich source content (articles, newsletters, video masterclasses, blogs) into professional, high-retention 2-host audio podcast episodes with human-level conversational dynamics and physical studio acoustics.

Individual podcast shows are built as **plugins** on top of the framework, completely separating podcast identities, host personas, and sound themes from the core audio and scripting engine.

---

## 📐 System Architecture

```
                               ┌────────────────────────────────┐
                               │  Content Source (URL, Feed)    │
                               └───────────────┬────────────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  PODCAST ENGINE CORE (Generic Framework)                                                    │
│                                                                                             │
│  1. Ingestion Interface (BaseIngester)                                                      │
│     └── Executes active plugin ingester (Playwright, BeautifulSoup, RSS, YouTube)          │
│                                                                                             │
│  2. Media Extraction & Transcription Engine (yt-dlp + OpenAI Whisper)                       │
│     ├── Downloads embedded video clips with client rotation (android -> ios)                │
│     └── Transcribes clips into timestamped audio segments with unique clip hashes           │
│                                                                                             │
│  3. Two-Brain Editorial & Scripting Engine (OpenRouter)                                     │
│     ├── Brain 1 (Curator - Gemini 2.5 Pro): Curates storylines & substantive audio clips     │
│     ├── Brain 2 (Scriptwriter - Claude 3.5 Sonnet): Generates continuous 2-host script      │
│     └── Auditor (Gemini 2.5 Flash): Empirical fact-checking & clip ratio verification      │
│                                                                                             │
│  4. Interactive Human-in-the-Loop CLI Pause                                                 │
│     └── Live summary badge -> inspect/edit markdown script -> confirm before TTS synthesis  │
│                                                                                             │
│  5. Acoustic Studio Sound Engine (OpenAI GPT-Audio + FFmpeg + Pydub)                        │
│     ├── Synthesizes host lines with plugin-defined studio voices (e.g. shimmer, ash, alloy) │
│     ├── Slices and mixes real interview audio clips directly into dialogue ([CLIP: ...])    │
│     ├── Cross-desk mic bleed (-22dB, 2ms delay) + Desk reflection (-24dB, 4ms delay)        │
│     ├── Procedural analog room tone bed (-56 dBFS) + conversational micro-overlaps (-90ms)  │
│     └── Loudness normalization to EBU R128 (-16 LUFS broadcast standard)                   │
│                                                                                             │
│  6. Cloud Distribution & RSS Publisher (Cloudflare R2 + feedgen)                            │
│     ├── Uploads MP3 & cover art to Cloudflare R2 bucket                                     │
│     └── Updates Spotify v1.10 compliant feed.xml with mandatory RFC-2822 pubDate            │
└──────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                               │
                                               ▼
                               ┌────────────────────────────────┐
                               │  Spotify / Apple Podcasts RSS  │
                               └────────────────────────────────┘
```

---

## 📂 Project Directory Structure

```
podcast_framework/
├── src/
│   ├── framework/                      # Framework Core
│   │   ├── models.py                   # Data models (HostConfig, AudioTheme, ShowMetadata, etc.)
│   │   ├── base_plugin.py              # PodcastPlugin Abstract Base Class
│   │   ├── base_ingester.py            # BaseIngester Abstract Base Class
│   │   └── registry.py                 # Dynamic discovery, loading & active plugin management
│   │
│   ├── audio_engine.py                 # Multi-host acoustic synthesis, clip mixing & LUFS mastering
│   ├── scriptwriter.py                 # Two-brain curation & script synthesis
│   ├── script_verifier.py              # Cross-model fact & ratio auditor
│   ├── transcriber.py                  # Video extraction & Whisper transcription
│   ├── rss_publisher.py                # Cloudflare R2 distribution & RFC-2822 RSS generator
│   ├── prompt_loader.py                # Plugin-first prompt resolver with fallback
│   ├── cost_tracker.py                 # Token, TTS character & Whisper usage tracker
│   └── config.py                       # Environment validation via pydantic-settings
│
├── plugins/                            # Pluggable Shows Directory
│   ├── README.md                       # Developer guide for creating new podcast plugins
│   └── volleyball/                     # Flagship Reference Show Plugin
│       ├── plugin.py                   # VolleyballPodcastPlugin implementation
│       ├── ingester.py                 # VolleyBrains authenticated scraper ingester
│       └── prompts/                    # Volleyball-specific prompt overrides (optional)
│
├── tests/
│   └── test_framework.py               # Comprehensive unit test suite (23 passing tests)
│
├── output/                             # Generated artifacts (git-ignored, keyed by slug)
│   ├── audio/                          # Master MP3 episodes
│   ├── scripts/                        # Markdown production scripts
│   └── feed.xml                        # Local RSS feed copy
│
├── main.py                             # Unified CLI with interactive TUI & plugin switcher
└── requirements.txt                    # Project dependencies
```

---

## 🔄 The 6-Stage Framework Pipeline

The core framework executes a structured 6-stage lifecycle:

### Stage 1: Content Ingestion (`BaseIngester`)
- Dispatches source URL to the active plugin's ingester (e.g. Playwright browser automation with saved session cookies).
- Extracts article text, tactical breakdowns, and embedded video/audio links.
- Writes slug-strict `output/scraped_{slug}.md`.

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
- **Studio Physics**:
  - Procedural `-56 dBFS` shaped analog room tone bed eliminates dead digital silence.
  - Symmetrical cross-desk mic bleed (`-22 dB`, `2ms` acoustic delay) and early desk reflection (`-24 dB`, `4ms`).
  - Context-aware turn pacing: `-90ms` micro-overlaps and `+400ms` contemplative pauses.
- **Mastering**: EBU R128 loudness normalization applied to master stereo MP3 at `-16 LUFS`.

### Stage 6: Distribution & Spotify RSS Sync (`src/rss_publisher.py`)
- Uploads the master MP3 and cover artwork to Cloudflare R2 object storage.
- Updates `feed.xml` with mandatory RFC-2822 `<pubDate>`, iTunes category, and duration tags.
- Prints an itemized cost table detailing Whisper seconds, LLM tokens, and TTS characters.

---

## 🧩 Building Show Plugins

Any new podcast can be built on top of the framework in 3 steps:

1. Create a directory `plugins/<show_slug>/` containing `plugin.py` subclassing `PodcastPlugin`.
2. Configure `ShowMetadata`, `HostConfig`, `AudioThemeConfig`, `CloudDistributionConfig`, and `ScriptConfig`.
3. Provide a `BaseIngester` implementation (e.g. for blog feeds, PDFs, or YouTube channels).

```python
from src.framework.base_plugin import PodcastPlugin
from src.framework.models import ShowMetadata, HostConfig, AudioThemeConfig

class TechPodcastPlugin(PodcastPlugin):
    @property
    def name(self) -> str:
        return "Silicon Tactical"

    @property
    def slug(self) -> str:
        return "tech"

    @property
    def show_metadata(self) -> ShowMetadata:
        return ShowMetadata(
            title="Silicon Tactical",
            author="Studio Media",
            email="tech@example.com",
            description="Deep tactical breakdowns of engineering leadership."
        )

    @property
    def hosts(self) -> dict[str, HostConfig]:
        return {
            "HOST_A": HostConfig(name="Alex", role="Anchor", voice="alloy", mic_position="left"),
            "HOST_B": HostConfig(name="Jordan", role="Analyst", voice="echo", mic_position="right")
        }
```

Consult [`plugins/README.md`](plugins/README.md) for full instructions and prompt customization.

---

## 🏐 Reference Flagship Plugin: "Volleyball Coaching Uncovered"

Located in `plugins/volleyball/`:

- **Show Context:** Converts rich masterclass articles and video interviews from volleyball masterclass platforms into audio episodes for coaches on their morning commute.
- **Hosts:**
  - **Host A: Chloe Miller (The Hardline Locker-Room Realist):** Voice `shimmer`. European pro / NCAA D1 realist. Focuses on practice rigor, accountability, and drill mechanics.
  - **Host B: Davis Hayes (The Broadcast Analyst):** Voice `ash`. Veteran commentator. Focuses on macro-psychology, sideline body language, agent leverage, and timeout pacing.
- **Key Invariants:**
  - **Brand Neutrality (STRICT):** Show title is strictly *"Volleyball Coaching Uncovered"*. Platform brand names are never spoken in audio.
  - **Coach Voice Ratio (>= 40%):** Coach speech represents 10–12 minutes of total 20–30 minute duration.
  - **Four Evolutionary Chapters:**
    1. *Origin & Risk:* Setting audacious timelines, breaking from comfort.
    2. *Tactical Systems & Opponent Classification:* Game preparation matrices, simplifying complexity.
    3. *Self-Enforcing Culture & Accountability:* Player ownership, physical standards.
    4. *Tactical Evolution & Future:* Innovations, block-out rules, technical takeaways.

---

## 🛠️ Windows Installation & Setup Guide

### Step 1: System Requirements & FFmpeg Installation
```powershell
winget install FFmpeg
```
*Note: Restart PowerShell after installation so `ffmpeg` is available in system `PATH`.*

### Step 2: Clone Repository & Virtual Environment Setup
```powershell
git clone https://github.com/onnobos/podccast_framework.git
cd podccast_framework
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies & Playwright Chromium
```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

### Step 4: Configure Environment Variables
Copy `.env.example` to `.env` and enter your API keys:
```powershell
copy .env.example .env
```
*(Never commit `.env` or write API keys into source code).*

---

## 🚀 CLI Usage & Commands

### Interactive Guided Wizard
Launch the guided TUI:
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

  [1] Generate New Episode from URL (Using Volleyball Coaching Uncovered pipeline)
  [2] Rebuild / Reproduce an Episode (Full rebuild, script+audio, or audio-only)
  [3] List Generated Episodes (View scraped, master content, script & audio status)
  [4] Synchronize R2 RSS Feed (Clean feed.xml so it strictly matches local episodes)
  [5] Delete / Purge an Episode (Delete local episode files and/or Cloudflare R2 bucket items)
  [6] Switch Podcast Show Plugin (Installed: 1)
  [7] Exit
============================================================================
```

### Direct CLI Commands

#### 1. List Installed Show Plugins
```powershell
python main.py plugins
```

#### 2. Generate a New Episode from URL
```powershell
# Generate episode with default active show (volleyball) and publish to Cloudflare R2:
python main.py generate "https://example.com/masterclass/" --publish

# Generate using a specific plugin in headless mode without publishing:
python main.py generate "https://example.com/masterclass/" --plugin volleyball --headless
```

#### 3. Rebuild Single or Multiple Episodes
```powershell
# Interactive rebuild selector (supports '1, 3', '1-4', or 'all'):
python main.py rebuild

# Re-curate storylines + fresh script & audio:
python main.py rebuild --slug dan-lewis-part2 --mode recurate --publish

# Full rebuild from scratch (re-scrape, re-transcribe, re-curate, fresh audio):
python main.py rebuild --slug andre-sa --mode scratch --publish

# Rebuild audio only (keep current script, re-mix studio acoustics):
python main.py rebuild --slug andre-sa --mode audio
```

#### 4. List Generated Episodes
```powershell
python main.py list
```

#### 5. Synchronize RSS Feed
```powershell
python main.py sync-feed
```

#### 6. Delete / Purge an Episode
```powershell
# Interactive deletion:
python main.py delete

# Delete local files and purge from Cloudflare R2 bucket & RSS feed:
python main.py delete --slug andre-sa --from-r2 --yes
```

---

## 🧪 Automated Framework Testing

The framework includes a unit test suite verifying data models, base ingesters, plugin contracts, prompt fallbacks, and script validation:

```powershell
python -m unittest tests/test_framework.py
```
*Expected Output:*
```text
..........................
----------------------------------------------------------------------
Ran 26 tests in 0.816s

OK
```

---

## 📱 Subscribing in Spotify & Mobile Podcast Apps

1. **Public RSS Feed URL**: `https://<YOUR_R2_PUBLIC_DOMAIN>/feed.xml`
2. Open Spotify, Apple Podcasts, Pocket Casts, or Overcast.
3. Select **Add Podcast by RSS Feed / URL**.
4. Paste your feed URL. Published episodes will appear immediately with show notes and cover artwork.

---

## 🤝 Community & Contributing

We welcome contributions of all kinds! Please see our community guides:

- **[Code of Conduct](CODE_OF_CONDUCT.md)**: Our standards for creating an open, welcoming community.
- **[Contributing Guide](CONTRIBUTING.md)**: Setup instructions, architectural standards, and PR guidelines.
- **[Security Policy](SECURITY.md)**: How to securely report vulnerabilities.

---

## 📄 License & Attribution

This project is licensed under the [MIT License](LICENSE).

### Attribution
Anyone using, forking, or building upon this code should refer to and attribute credit to the repository [podccast_framework](https://github.com/onnobos/podccast_framework).

