# AGENTS.md — System Guidelines for AntiGravity Vibe Coding

This document governs the rules, architecture, and quality standards for AI autonomous agents operating in **Google AntiGravity**. All agents working on this codebase MUST strictly follow these principles.

---

## 1. Project Context & Vibe

**Project Name:** Podcast Automation Framework (`podcast-framework`)  
**Core Objective:** A modular, studio-grade audio production framework that transforms rich source content (paywalled masterclasses, newsletters, blogs, YouTube channels) into broadcast-ready, 2-host audio podcast episodes with human-level conversational dynamics and studio acoustics.

**Flagship Reference Plugin:** **"Volleyball Coaching Uncovered"** (`plugins/volleyball`)
- Converts paywalled masterclass articles & video interviews from volleyball site into 2-host audio episodes for volleyball coaches on their morning commute.
- **Show Style:** Inspired by *Fitter Radio* and *Coaching Uncovered*. Conversational, energetic, deeply educational.
- **Hosts:** 
  - **Host A (Chloe Miller, voice: `shimmer`):** European pro / NCAA D1 bench realist. Asks clarifying questions, connects ideas to gym reality, pulls out actionable takeaways.
  - **Host B (Davis Hayes, voice: `ash`):** Broadcast analyst. Delivers sharp tactical breakdowns, cites technical terminology, and analyzes macro-psychology.

---

## 2. Inviolable Architectural & Security Rules

1. **STRICT ZERO-HARDCODED-SECRETS & NO-ENV-TOUCH POLICY (NON-NEGOTIABLE):**
   - **NO API keys, passwords, bearer tokens, account IDs, or R2 credentials may EVER be written or committed in any `.py` file, documentation, or script.**
   - **NO AGENT ACCESS TO `.env`:** AI agents MUST NEVER read, open, edit, update, or write to `.env` file under any circumstances. NO EXCUSE. All `.env` changes must be done manually by user.
   - The codebase MUST maintain `.env` in `.gitignore` and supply a dummy `.env.example` for reference.
2. **Windows & Cross-Platform Path Compatibility:**
   - NEVER use hardcoded Unix paths like `/tmp/`. Always use Python's `pathlib.Path` and `tempfile.gettempdir()` to support Windows file paths (`C:\Users\...`).
   - Avoid unencoded Unicode emojis or checkmarks (`✓`, `🎉`) in `rich` `console.print()` output to prevent Windows `cp1252` `UnicodeEncodeError`. Use safe text (`SUCCESS:`).
3. **Session Cookie Security & Auth:**
   - Playwright MUST save browser session cookies to `.auth/storageState.json` (git-ignored) and reload them on subsequent runs.
4. **Video Transcription Integration & yt-dlp Schema:**
   - Never skip embedded videos. Filter YouTube clips to channel `@volleybrains`.
   - **yt-dlp Options Invariant**: In Python `yt_dlp.YoutubeDL`, `extractor_args` MUST use nested dictionaries: `{'youtube': {'player_client': ['android', 'ios']}}`. NEVER pass CLI-style string lists `['player_client=android']`.
   - **Zero User-Agent Overrides**: NEVER set custom desktop `User-Agent` headers in `http_headers` when mobile `player_client` is active; header-client mismatches trigger HTTP 403 Forbidden.
   - Skip unavailable/deleted clips immediately.
5. **Interactive Human-in-the-Loop:**
   - The pipeline MUST pause after generating `script.md` using `rich`/`typer`, allowing user review or editing before consuming TTS API credits.
6. **Audio Broadcast Standards:**
   - Format: Stereo MP3, 44.1 kHz, 128 kbps.
   - Loudness Target: -16 LUFS (EBU R128 standard for Spotify podcasting).
   - Intro Music: 7.5s solo lead-in, 30s background music ducked by -16dB under speech transitions with 2.5s fade out.
   - Outro Music: 5s ducked music (-16dB) over final speech, 2s solo outro fade out.
7. **Cloudflare R2 RSS Integrity:**
   - **Boto3 Client Config**: Use `signature_version='s3v4'` and `s3={'addressing_style': 'path'}` in `Config`.
   - **Public Domain**: Enclosures and RSS feed links MUST use the public domain (`r2.dev` or custom domain), NOT private S3 endpoints (`.r2.cloudflarestorage.com`).
   - **RSS Metadata & Spotify v1.10 Spec**: Include `<itunes:image>`, `<image>`, `<itunes:owner><itunes:email>`, and **MANDATORY RFC-2822 `<pubDate>` on EVERY `<item>`**.
   - **Brand Neutrality**: Keep show title as `"Volleyball Coaching Uncovered"`. Omit brand names from episode titles and AI summaries.
8. **Slug-Strict File Isolation**:
   - All pipeline artifacts MUST be keyed strictly by episode slug (`scraped_{slug}.md`, `master_{slug}.md`, `{slug}_script.md`, `{slug}_master.mp3`).
   - NEVER create or rely on generic fallback paths (`master_content.md`, `scraped_article.md`) that can leak previous episode content across runs.
9. **Resilient Video Download Queueing**:
   - Use `collections.deque` queue processing. If a video fails 5 download attempts with 5–10s randomized backoff, rotate to the end of the queue and continue until all videos complete or are verified deleted/private.
10. **API Cost Tracking**:
   - Log per-call usage metrics (Whisper seconds, LLM tokens, TTS chars) via `src/cost_tracker.py` and print itemized summary table upon pipeline completion.
11. **Adaptive Page Scraping & Lazy Embed Resolution:**
    - Paywalled masterclass pages contain dynamically expanding embeds. Playwright scrapers MUST NOT use fixed short iteration caps (e.g. 15 loops).
    - Scrapers MUST implement adaptive progressive scrolling checking `Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)` and detecting stagnation to ensure complete bottom-of-page extraction.
12. **Mandatory Framework Test Execution After Every Code Change (NON-NEGOTIABLE):**
    - After ANY change to framework modules (`src/framework/`), plugins (`plugins/`), engines (`src/`), or CLI (`main.py`), AI agents MUST execute the framework test suite:
      `.\venv\Scripts\python.exe -m unittest tests/test_framework.py`
    - All tests must pass with 0 errors before reporting completion. Never skip this validation step.
13. **Framework & Plugin Separation (Zero Show-Specific Hardcoding):**
    - Core framework modules (`src/framework/`, `src/audio_engine.py`, `src/scriptwriter.py`, `src/script_verifier.py`, `src/rss_publisher.py`, `src/prompt_loader.py`) MUST remain generic.
    - NEVER hardcode show titles, host names, voice mappings, or domain-specific scraping logic into `src/`. All show-specific logic MUST live in `plugins/<show_slug>/` via `PodcastPlugin` and `BaseIngester`.

---

## 3. Tech Stack Invariants

| Layer | Approved Library / Tool |
|---|---|
| **OS / Environment** | Windows 10/11 with Python 3.11+ `venv` |
| **CLI / TUI** | `typer`, `rich` |
| **Settings / Environment** | `pydantic-settings`, `python-dotenv` |
| **Web Automation & Scraping** | `playwright`, `beautifulsoup4` |
| **Media Extraction** | `yt-dlp` |
| **Two-Brain AI Models** | OpenRouter (`google/gemini-2.5-pro` for curation, `anthropic/claude-sonnet-4` for scriptwriting, `google/gemini-2.5-flash` for audit, `whisper-1` for transcription) |
| **TTS Studio Voices** | `openai/gpt-audio` via OpenRouter (`shimmer` for Host A Chloe, `ash` for Host B Davis) |
| **Audio Processing** | `pydub`, `ffmpeg-python` (system `ffmpeg` via `winget`) |
| **Cloud Storage & RSS** | `boto3` (Cloudflare R2 S3 compatibility), `feedgen` |

---

## 3.5 Two-Brain Pipeline Architecture

1. **Curator (Olympic Head Coach Persona)**: Uses `google/gemini-2.5-pro` to ingest full masterclass articles + all video transcripts (25k+ words). Curates 4 thematic chapters with 10–12 minutes of substantive coach audio clips.
2. **Scriptwriter (Dramatist)**: Uses `anthropic/claude-sonnet-4` to generate 20–30 minute continuous scripts (~1,800–2,500 host words).
3. **Auditor**: Uses `google/gemini-2.5-flash` for empirical fact-checking, terminology auditing, and 40% coach voice verification in a 2-pass refinement loop.
4. **API Provider**: Always route LLM and GPT-Audio calls via `OPENROUTER_API_KEY` and OpenRouter endpoint (`https://openrouter.ai/api/v1`).
5. **Multi-Episode Rebuild CLI**: Support batch episode rebuilding by comma lists (`1, 3, 5`), ranges (`1-4`), keyword `all`, or slugs. Provide 4 rebuild scopes with `[2] Re-curate Storylines, Script & Audio` as default.

---

## 4. AntiGravity Operational Workflow
Always use Context7 when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

When generating code or executing tasks in AntiGravity:
1. **Security Audit Before Code Output:** Verify that no raw secrets exist anywhere in generated code.
2. **Verify System Dependencies:** Ensure `ffmpeg` is accessible in system `PATH` and Playwright Chromium binaries are installed.
3. **Isolated Test Execution:** Ensure each module (`scraper.py`, `transcriber.py`, `scriptwriter.py`, `audio_engine.py`, `rss_publisher.py`) has a runnable isolated CLI test block (e.g., `python -m src.scraper --test`).
4. **Structured Logging:** Use `rich.logging` so every execution step outputs clear status banners, spinners, and informative errors.
5. **Terminal Python Environment Execution:** When executing shell commands (`run_command`), AI agents MUST explicitly invoke `.\venv\Scripts\python.exe` (and set `BypassSandbox: true` on Windows) so virtual environment packages (`openai`, `pydub`, `boto3`, `feedgen`) execute cleanly.
6. **CLI Interactive Architecture:** Support guided interactive wizard menus when running `main.py` with no args. Normalize `typer.models.OptionInfo` objects when calling Typer functions directly within Python.
7. **Always Run Test Framework After Every Change (MANDATORY):** Agents MUST execute `.\venv\Scripts\python.exe -m unittest tests/test_framework.py` with `BypassSandbox: true` after EVERY modification across framework, plugins, audio engine, scriptwriter, or CLI. Zero broken tests tolerated.

---

## 5. Script Writing Rules (LLM System Prompt Rulebook)

### Part A: Universal Framework Script Invariants (All Shows)
- **One Unified Continuous Storyline (STRICT):** Flow as ONE continuous, organic conversation, NOT disconnected acts. Strictly ban meta-announcements (`"in our next act"`, `"moving on to part 2"`, `"next up on our list"`). Bridge topics with conversational cause-and-effect.
- **Zero Tolerance for Hype Clichés (STRICT):** Ban empty cheerleading words: `"incredible"`, `"this is huge"`, `"that is huge"`, `"the fact that"`, `"fascinating"`, `"game-changer"`, `"insane"`, `"unbelievable"`, `"mind-blowing"`, `"super interesting"`, `"at the end of the day"`. Replace with domain-specific analysis.
- **"Yes, But" Conversational Friction:** Strictly ban sycophantic affirmations (`"Right!"`, `"Exactly!"`, `"Of course!"`, `"Bingo!"`). Hosts push back on edge cases before finding common ground.
- **Anti-Announcer Clip Seams:** Strictly ban meta-announcements (`"Listen to this"`, `"Listen to how"`, `"Let's hear"`). Lead into `[CLIP: ...]` with an argumentative assertion or open question that completes the thought.
- **Cold Open & Outro:** Cold open immediately on drama (zero pleasantries like `"Alright, welcome back"`). Outros avoid unison speech (`[together]`); Host A gives sharp practical takeaway, Host B gives solo broadcast sign-off.
- **Audio Cue Structure:** Embed structural tags in markdown (`[MUSIC_INTRO]`, `[MUSIC_OUTRO]`, `[HOST_A]`, `[HOST_B]`, `[CLIP: audio_hash | start | end]`) so the audio mixer parses lines cleanly.
- **Prompt Generalization & Clip Integrity:**
  - System prompts, host instructions, and few-shot examples MUST NEVER hardcode specific interviewees, past plotlines, or concrete audio hashes.
  - The LLM MUST ONLY extract and embed `[CLIP: audio_hash | ...]` tags using hashes present in the current episode's master content.

### Part B: Volleyball Reference Plugin Invariants (`plugins/volleyball`)
- **Brand Neutrality (STRICT):** Show title is strictly `"Volleyball Coaching Uncovered"`. NEVER speak, mention, or write `"VolleyBrains"` or `"VolleyBrains.com"` anywhere in dialogue, intros, or outros.
- **Episode Runtime & Coach Voice Ratio:** Target **20 to 30 minutes** total duration. Coach audio (`[CLIP: ...]`) MUST represent **>= 40%** of total runtime (10–12 minutes of coach speech).
- **Asymmetrical Host Lenses:**
  - **Host A (Chloe Miller, voice: `shimmer`):** European pro / NCAA D1 bench realist. Focuses on locker room realities, accountability, and drill mechanics.
  - **Host B (Davis Hayes, voice: `ash`):** Broadcast analyst. Focuses on macro-psychology, sideline body language, agent leverage, and timeout pacing.
- **Four Evolutionary Chapters (Continuous Arc):**
  - **Act I (The Origin & Risk):** Origin story, breaking away from safety/comfort, setting audacious timelines.
  - **Act II (Tactical Systems & Opponent Classification):** Game preparation matrices, classification models, simplifying complexity for players.
  - **Act III (Self-Enforcing Culture & Accountability):** Player ownership, locker-room standards, physical accountability rules.
  - **Act IV (Tactical Evolution & The Future):** Vulnerability, rule innovations (e.g. block-out rules), technical masterclass takeaways.

