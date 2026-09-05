## Description
Brief summary of the changes made and rationale behind them.

Fixes #(issue)

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature or show plugin (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing behavior to change)
- [ ] Documentation update

## Architectural & Quality Checklist
- [ ] **Zero Hardcoded Secrets:** Confirmed no API keys, tokens, or credentials exist in code or commits.
- [ ] **Framework & Plugin Separation:** Show-specific logic is isolated inside `plugins/<show_slug>/`.
- [ ] **Cross-Platform:** Uses `pathlib.Path` and supports Windows path handling.
- [ ] **Tests Pass:** Verified with `.\venv\Scripts\python.exe -m unittest tests/test_framework.py` (0 errors, 0 failures).
- [ ] **Documentation:** Updated `README.md`, `USERMANUAL.md`, or `plugins/README.md` if applicable.
