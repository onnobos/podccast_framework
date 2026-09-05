# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## Reporting a Vulnerability

The security of the Podcast Automation Framework and the protection of user API credentials is our highest priority.

### Strict Zero-Hardcoded-Secrets Policy
This framework relies on LLM, transcription, and cloud storage APIs (OpenRouter, OpenAI, Cloudflare R2). 

- **Do NOT file a public GitHub issue** for sensitive vulnerabilities or credential exposure concerns.
- If you discover a security vulnerability or accidental credential leakage vector, please report it directly to the repository maintainers via private security advisory or via private message to [@onnobos](https://github.com/onnobos).

### What to Include in Your Report
- A clear description of the vulnerability.
- Steps to reproduce the issue.
- Potential impact and affected components.
- Any suggested fixes or mitigations.

### Response Timeline
- We will acknowledge receipt of your vulnerability report within 48 hours.
- A fix or mitigation will be developed, tested, and released as quickly as possible.
