# Contributing to Podcast Automation Framework

First off, thank you for considering contributing to the Podcast Automation Framework! It is people like you that make this tool great for everyone.

Following these guidelines helps to keep the development cycle smooth and ensures high code quality and security.

---

## Code of Conduct

This project and everyone participating in it is governed by the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior via GitHub issues or private outreach to the maintainers.

---

## How Can I Contribute?

### 1. Reporting Bugs
- Ensure the bug was not already reported by searching on GitHub under [Issues](https://github.com/onnobos/podccast_framework/issues).
- If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/onnobos/podccast_framework/issues/new).
- Use the **Bug Report** template: include clear reproduction steps, Python version, OS platform, and relevant logs (omitting any private API keys).

### 2. Suggesting Enhancements
- Feature requests are welcome! Open an issue describing:
  - What problem you are trying to solve.
  - Your proposed solution or desired workflow.
  - Any alternative approaches considered.

### 3. Writing Show Plugins
- We actively encourage community-contributed show plugins!
- Consult [`plugins/README.md`](plugins/README.md) for the plugin architecture and required methods (`get_metadata()`, `get_hosts()`, `get_audio_theme()`, `get_ingester()`).
- Place new plugins in `plugins/<show_slug>/`.

### 4. Improving Documentation
- Clear documentation, typos, and architecture diagrams are always appreciated.

---

## Development Setup

1. **Fork and clone the repo:**
   ```powershell
   git clone https://github.com/<your-username>/podccast_framework.git
   cd podccast_framework
   ```

2. **Set up virtual environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Install FFmpeg & Playwright:**
   ```powershell
   winget install FFmpeg
   python -m playwright install chromium
   ```

4. **Configure environment:**
   ```powershell
   copy .env.example .env
   # Edit .env with your own development keys
   ```

---

## Architectural & Security Invariants

All contributions must respect our core architectural standards:

1. **STRICT ZERO-HARDCODED-SECRETS POLICY:**
   - NEVER commit API keys, tokens, or credentials in any `.py` file, commit message, or pull request.
   - `.env` must remain in `.gitignore`.
2. **Framework & Plugin Separation:**
   - Core framework modules in `src/framework/` and `src/` must remain completely domain-agnostic.
   - Show-specific logic, host identities, or custom scraping belong strictly inside `plugins/<show_slug>/`.
3. **Cross-Platform & Windows Path Compatibility:**
   - Always use `pathlib.Path` and `tempfile.gettempdir()`. Never hardcode Unix `/tmp/` paths.
4. **Broadcast Audio Standards:**
   - Output files must adhere to EBU R128 (-16 LUFS) broadcast loudness specifications.

---

## Mandatory Test Suite

Before submitting any Pull Request, you MUST run and pass the full unit test suite:

```powershell
.\venv\Scripts\python.exe -m unittest tests/test_framework.py
```

All tests must pass with **0 errors and 0 failures**.

---

## Pull Request Guidelines

1. Create a feature branch (`git checkout -b feat/my-new-feature` or `git checkout -b fix/issue-description`).
2. Follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
3. Write clean, well-commented code following PEP 8.
4. Update documentation in `README.md` or `USERMANUAL.md` if your change introduces new configuration or CLI commands.
5. Ensure the test suite passes (`unittest tests/test_framework.py`).
6. Push to your fork and submit a Pull Request describing your changes and linking any related issues.
