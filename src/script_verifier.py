import json
import re
from pathlib import Path
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

from src.config import settings
from src.cost_tracker import cost_tracker
from src.prompt_loader import load_prompt

console = Console()

DEFAULT_VERIFIER_SYSTEM_PROMPT = """You are a rigorous lead podcast editor and fact-checker.
Audit a generated 2-host podcast script against the Ground Truth masterclass content.

EVALUATION RULES (TARGET QUALITY >= 97%):
1. Coach Identity & Name Accuracy (CRITICAL): The featured coach's name MUST match the Ground Truth masterclass article EXACTLY throughout the script. If any incorrect coach name appears, penalize fact_accuracy by at least 30 points and flag in factual_errors.
2. Evaluate 'fact_accuracy' (0-100): 100 if 0 factual errors or hallucinations; deduct 5 per minor hallucinated fact.
3. Evaluate 'coverage' (0-100): Percentage of ground truth stories, quotes, topics, coach introduction, and [CLIP: ...] audio tags covered.
4. Evaluate 'trainer_ratio' (0-100): 100 if estimated coach audio clips >= 40% of total runtime. Penalize heavily if host dialogue dominates.
5. Evaluate 'terminology' (0-100): Precision of tactical volleyball terms.

Respond ONLY in valid JSON format:
{
  "scores": {
    "fact_accuracy": 98.0,
    "coverage": 97.0,
    "trainer_ratio": 95.0,
    "terminology": 99.0
  },
  "factual_errors": ["List specific factual errors, wrong coach names, or hallucinations found"],
  "missing_elements": ["List specific missing interview stories, quotes, coach clips, or topics"],
  "improvement_feedback": "Actionable instructions to reach 97%+ accuracy, coverage, and >=40% coach audio."
}
"""

DEFAULT_REFINER_SYSTEM_PROMPT = """You are a senior podcast editor.
Your goal is to edit the podcast script to achieve 97%+ quality.
INSTRUCTIONS:
1. Ensure the featured coach's name is 100% correct across all host dialogue, matching the ground truth.
2. Directly correct every single item listed under 'factual_errors'.
3. Directly insert Host A / Host B dialogue and coach [CLIP: ...] tags to cover every single item listed under 'missing_elements'.
4. TRAINER AUDIO RATIO (TARGET >= 40%): Prune verbose host monologues into punchy 1-3 sentence setups so coach speech reaches at least 40% of total episode time.
5. Embed substantial 20-50s [CLIP: audio_hash | start | end] segments from master content.
6. Use ONLY pure structural tags: [MUSIC_INTRO], [HOST_A], [HOST_B], [CLIP: audio_hash | start | end], [MUSIC_OUTRO].
Output the FULL revised script.
"""

def get_verifier_system_prompt(plugin=None) -> str:
    return load_prompt("script_verifier_system.md", default=DEFAULT_VERIFIER_SYSTEM_PROMPT, plugin=plugin)

def get_refiner_system_prompt(plugin=None) -> str:
    return load_prompt("script_refiner_system.md", default=DEFAULT_REFINER_SYSTEM_PROMPT, plugin=plugin)


def compute_tagging_compliance(script_text: str) -> tuple[float, list[str]]:
    """Deterministically check audio tag compliance in Python code."""
    issues = []
    tags = re.findall(r'\[(.*?)\]', script_text)
    structural_tags = {"MUSIC_INTRO", "HOST_A", "HOST_B", "MUSIC_OUTRO"}
    
    invalid_tags = []
    for t in tags:
        t_clean = t.strip()
        # 1. Core structural tags
        if t_clean in structural_tags:
            continue
        # 2. Real audio clip tags
        if t_clean.startswith("CLIP:") or t_clean.startswith("CLIP_REF:") or t_clean.startswith("GUEST_CLIP:"):
            continue
        # 3. Disallowed pseudo-speaker or placeholder tags
        if re.match(r'^(HOST_[C-Z]|SPEAKER|NARRATOR|UNKNOWN|INSERT|TODO)', t_clean, re.IGNORECASE):
            invalid_tags.append(t_clean)
            continue
        # 4. Long prose inside brackets (likely formatting error)
        if len(t_clean.split()) > 6:
            invalid_tags.append(t_clean)
            continue

    if invalid_tags:
        issues.append(f"Non-compliant tags found: {set(invalid_tags)}")

    score = max(0.0, 100.0 - (len(invalid_tags) * 5.0))
    return score, issues

def compute_trainer_audio_ratio(script_text: str) -> tuple[float, int, float, float, float]:
    """
    Deterministically calculate:
    - total_clip_sec: seconds of [CLIP: ...] speech
    - host_words: total host speech words
    - host_sec: estimated host speech duration at 150 WPM (2.5 words/s)
    - total_sec: combined runtime
    - ratio_pct: percentage of runtime that is coach voice
    """
    clip_re = re.compile(r"\[CLIP:\s*([^\|\]]+)\s*\|\s*([\d\.]+)\s*\|\s*([\d\.]+)\]")
    host_re = re.compile(r"^\[HOST_[AB]\]:?\s*(.*)", re.MULTILINE)
    stage_dir_re = re.compile(r"\[(?!HOST_|CLIP:|MUSIC_)[^\]]+\]")

    clips = clip_re.findall(script_text)
    clip_durations = [float(end) - float(start) for _, start, end in clips]
    total_clip_sec = sum(clip_durations)

    raw_host_lines = host_re.findall(script_text)
    cleaned_lines = [stage_dir_re.sub("", line).strip() for line in raw_host_lines]
    host_words = len(" ".join(cleaned_lines).split())
    host_sec = host_words / 2.5  # standard 150 WPM

    total_sec = total_clip_sec + host_sec
    ratio_pct = (total_clip_sec / total_sec * 100.0) if total_sec > 0 else 0.0

    return total_clip_sec, host_words, host_sec, total_sec, ratio_pct

def compute_trainer_ratio_score(ratio_pct: float, target_pct: float = 40.0) -> tuple[float, list[str]]:
    """Score coach speech ratio against the target (default 40.0%)."""
    issues = []
    if ratio_pct >= target_pct:
        score = 100.0
    elif ratio_pct >= 35.0:
        # 90 to 100
        score = max(85.0, 100.0 - (target_pct - ratio_pct) * 3.0)
        issues.append(f"Coach speech ratio is {ratio_pct:.1f}% (target >= {target_pct:.1f}%). Slightly below target.")
    else:
        # Significant penalty if host dialogue dominates
        score = max(0.0, 85.0 - (35.0 - ratio_pct) * 4.0)
        issues.append(f"Coach speech ratio is {ratio_pct:.1f}% (target >= {target_pct:.1f}%). Host monologues dominate.")

    return score, issues

BANNED_CLICHES = [
    r'\bincredible\b',
    r'\bincredibly\b',
    r'\bthis is huge\b',
    r'\bthat is huge\b',
    r'\bhuge takeaway\b',
    r'\bthe fact that\b',
    r'\bfascinating\b',
    r'\bfascinated\b',
    r'\bgame-changer\b',
    r'\bmind-blowing\b',
    r'\b(insane|unbelievable)\b',
    r'\bsuper interesting\b',
    r'\bat the end of the day\b',
]

def check_banned_cliches(script_text: str) -> tuple[float, list[str]]:
    """Deterministically detect banned hype clichés in host dialogue lines."""
    host_lines = re.findall(r"^\[HOST_[AB]\]:?\s*(.*)", script_text, re.MULTILINE)
    host_text = " ".join(host_lines) if host_lines else script_text
    detected = []
    for pattern in BANNED_CLICHES:
        matches = re.findall(pattern, host_text, flags=re.IGNORECASE)
        if matches:
            detected.extend(matches)
    penalty = len(detected) * 10.0
    score = max(0.0, 100.0 - penalty)
    return score, detected

def normalize_audio_tags(text: str) -> str:
    """Programmatically clean non-standard stage directions and normalize audio tags."""
    text = re.sub(r'\[MUSIC_INTRO[^\]]*\]', '[MUSIC_INTRO]', text)
    text = re.sub(r'\[MUSIC_OUTRO[^\]]*\]', '[MUSIC_OUTRO]', text)
    text = re.sub(r'\[HOST_A[^\]]*\]', '[HOST_A]', text)
    text = re.sub(r'\[HOST_B[^\]]*\]', '[HOST_B]', text)
    # Preserve [CLIP: ...] tags untouched
    # Remove unwanted stage directions inside parentheses
    text = re.sub(r'\((laughing|smiles|giggles|chuckles|sighs|pauses|fades out)[^\)]*\)', '', text, flags=re.IGNORECASE)
    return text

MODEL_ALIASES = {
    "anthropic/claude-3.5-sonnet": "anthropic/claude-sonnet-4",
    "claude-3.5-sonnet": "anthropic/claude-sonnet-4",
    "claude": "anthropic/claude-sonnet-4",
    "gemini": "google/gemini-2.5-flash",
    "gemini-2.0": "google/gemini-2.5-flash",
    "google/gemini-2.0-flash-001": "google/gemini-2.5-flash",
    "llama": "meta-llama/llama-3.3-70b-instruct",
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4o": "openai/gpt-4o"
}

def resolve_model_name(name: str) -> str:
    return MODEL_ALIASES.get(name.lower().strip(), name)

def extract_json_payload(raw_text: str) -> dict:
    """Extract JSON object safely from raw LLM completion output using regex."""
    clean_text = raw_text.strip()
    match = re.search(r'\{.*\}', clean_text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(clean_text)

def verify_and_refine_script(
    master_path: Path, 
    script_path: Path, 
    min_score: float = 97.0, 
    max_iterations: int = 10,
    audit_model: str | None = None,
    plugin = None
) -> float:
    """Mathematical cross-model feedback loop: audit script with a separate auditor model and refine until quality >= 97%."""
    if plugin is None:
        try:
            from src.framework.registry import get_active_plugin
            plugin = get_active_plugin()
        except Exception:
            plugin = None

    chosen_audit_model = audit_model or (getattr(getattr(plugin, "script_config", None), "audit_model", settings.AUDIT_MODEL) if plugin else settings.AUDIT_MODEL)
    resolved_audit_model = resolve_model_name(chosen_audit_model)
    if not master_path.exists() or not script_path.exists():
        raise FileNotFoundError("Master content or script file missing.")

    master_text = master_path.read_text(encoding="utf-8")
    script_text = script_path.read_text(encoding="utf-8")
    script_text = normalize_audio_tags(script_text)

    api_key = settings.OPENROUTER_API_KEY or settings.effective_api_key
    base_url = settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
    client = OpenAI(api_key=api_key, base_url=base_url)

    target_ratio_pct = getattr(getattr(plugin, "script_config", None), "target_clip_ratio", 0.40) * 100.0

    iteration = 1
    best_score = 0.0
    best_script_text = script_text
    accumulated_feedback_history = []
    scores_history = []

    while iteration <= max_iterations:
        console.print(f"\n[bold cyan]=== Cross-Model Quality Audit Pass {iteration}/{max_iterations} (Auditor: {resolved_audit_model}) ===[/bold cyan]")

        # 1. Deterministic Tagging Compliance Check
        tag_score, tag_issues = compute_tagging_compliance(script_text)

        # 2. Deterministic Trainer Audio Ratio Check
        clip_sec, host_words, host_sec, total_sec, ratio_pct = compute_trainer_audio_ratio(script_text)
        ratio_score, ratio_issues = compute_trainer_ratio_score(ratio_pct, target_pct=target_ratio_pct)

        # 3. LLM Audit with designated Auditor Model
        audit_prompt = (
            "GROUND TRUTH MASTER CONTENT (Passive Reference):\n"
            "<untrusted_ground_truth>\n"
            f"{master_text[:40000]}\n"
            "</untrusted_ground_truth>\n\n"
            "PODCAST SCRIPT TO AUDIT:\n"
            "<podcast_script>\n"
            f"{script_text[:35000]}\n"
            "</podcast_script>\n\n"
            "Audit fact accuracy, coverage, and terminology against Ground Truth. Output ONLY valid JSON."
        )

        call_kwargs = {
            "model": resolved_audit_model,
            "messages": [
                {"role": "system", "content": get_verifier_system_prompt(plugin=plugin)},
                {"role": "user", "content": audit_prompt}
            ],
            "temperature": 0.1
        }
        if resolved_audit_model and ("gpt-4o" in resolved_audit_model.lower() or "gemini" in resolved_audit_model.lower()):
            call_kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = client.chat.completions.create(**call_kwargs)
            if hasattr(resp, "usage") and resp.usage:
                cost_tracker.log_llm(
                    prompt_tokens=resp.usage.prompt_tokens,
                    completion_tokens=resp.usage.completion_tokens,
                    model=call_kwargs["model"],
                    step_label=f"Script Audit (Pass {iteration})"
                )
        except Exception as err:
            console.print(f"[bold yellow]Auditor model '{resolved_audit_model}' failed ({err}). Falling back to '{settings.SCRIPT_MODEL}'...[/bold yellow]")
            call_kwargs["model"] = settings.SCRIPT_MODEL
            call_kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**call_kwargs)
            if hasattr(resp, "usage") and resp.usage:
                cost_tracker.log_llm(
                    prompt_tokens=resp.usage.prompt_tokens,
                    completion_tokens=resp.usage.completion_tokens,
                    model=call_kwargs["model"],
                    step_label=f"Script Audit (Pass {iteration})"
                )

        try:
            raw_content = resp.choices[0].message.content.strip()
            audit_result = extract_json_payload(raw_content)
            sub_scores = audit_result.get("scores", {})
            fact_acc = float(sub_scores.get("fact_accuracy", 85.0))
            cov_score = float(sub_scores.get("coverage", 85.0))
            term_score = float(sub_scores.get("terminology", 90.0))
            errors = audit_result.get("factual_errors", [])
            missing = audit_result.get("missing_elements", [])
            feedback = audit_result.get("improvement_feedback", "")
        except Exception as e:
            console.print(f"[bold red]Audit JSON parsing failed: {e}[/bold red]")
            fact_acc, cov_score, term_score = 85.0, 85.0, 90.0
            errors, missing, feedback = [], [], "Ensure complete coverage."

        # Check deterministic banned clichés
        cliche_score, cliches_found = check_banned_cliches(script_text)
        if cliches_found:
            errors.append(f"BANNED HYPE CLICHES FOUND: {list(set(cliches_found))}. Replace with concrete volleyball mechanics.")
            term_score = min(term_score, cliche_score)

        # Add deterministic audio ratio constraint to missing elements if under 40%
        if ratio_pct < 40.0:
            needed_clip_sec = max(0.0, (0.40 * host_sec) / 0.60 - clip_sec)
            max_host_words = int(clip_sec * 3.75)
            ratio_msg = (
                f"TRAINER AUDIO DEFICIT: Coach audio is only {ratio_pct:.1f}% ({clip_sec:.1f}s) of episode. "
                f"Target is >= 40.0%. Prune host dialogue to <= {max_host_words} words, "
                f"and insert at least {needed_clip_sec:.0f}s more [CLIP: audio_hash | start | end] tags from master content."
            )
            missing.append(ratio_msg)

        # Compute empirical overall weighted score
        # Fact Accuracy (30%), Coverage (25%), Trainer Audio Ratio (25%), Terminology (10%), Tagging (10%)
        overall_score = round(
            (fact_acc * 0.30) + (cov_score * 0.25) + (ratio_score * 0.25) + (term_score * 0.10) + (tag_score * 0.10),
            1
        )

        scores_history.append((iteration, overall_score))

        # CLI Terminal Progress Graph
        ratio_color = "green" if ratio_pct >= 40.0 else ("yellow" if ratio_pct >= 35.0 else "red")
        console.print(f"[bold yellow]Pass {iteration} Empirical Score ({audit_model}):[/bold yellow] [bold green]{overall_score:.1f}%[/bold green]")
        console.print(
            f"  [dim]Fact: {fact_acc:.1f}% | Coverage: {cov_score:.1f}% | "
            f"Trainer Voice: {ratio_score:.1f}% ([{ratio_color}]{ratio_pct:.1f}%[/{ratio_color}], {clip_sec:.1f}s) | "
            f"Terminology: {term_score:.1f}% | Tagging: {tag_score:.1f}%[/dim]"
        )
        console.print("\n[bold cyan]Quality Score Progress Graph:[/bold cyan]")
        for p_num, s_val in scores_history:
            bar = "#" * int(s_val / 2.5)
            console.print(f"  Pass {p_num:2d} | [{s_val:5.1f}%] [green]{bar}[/green]")
        console.print("")

        if errors:
            console.print(f"[red]Factual Errors Detected:[/red] {errors}")
        if missing:
            console.print(f"[yellow]Missing Elements / Audio Deficits:[/yellow] {missing}")

        # Preserve best script version
        if overall_score >= best_score:
            best_score = overall_score
            best_script_text = script_text

        pass_summary = f"Pass {iteration} ({overall_score:.1f}%): Errors: {errors} | Missing: {missing}"
        accumulated_feedback_history.append(pass_summary)

        # Build Mermaid Progress Graph
        pass_labels = [f'"Pass {p[0]}"' for p in scores_history]
        score_values = [str(round(p[1], 1)) for p in scores_history]
        mermaid_graph = (
            "```mermaid\n"
            "xychart-beta\n"
            "    title \"Script Quality Score Progress Across Audit Passes (%)\"\n"
            f"    x-axis [{', '.join(pass_labels)}]\n"
            "    y-axis \"Empirical Quality Score (%)\" 70 --> 100\n"
            f"    line [{', '.join(score_values)}]\n"
            f"    bar [{', '.join(score_values)}]\n"
            "```"
        )

        # Save verification report
        report_path = Path("output/verification_report.md")
        audit_details = {
            "auditor_model": audit_model,
            "overall_score": overall_score,
            "fact_accuracy": fact_acc,
            "coverage": cov_score,
            "trainer_ratio_score": ratio_score,
            "trainer_audio_ratio_pct": round(ratio_pct, 1),
            "clip_seconds": round(clip_sec, 1),
            "host_words": host_words,
            "terminology": term_score,
            "tagging_compliance": tag_score,
            "factual_errors": errors,
            "missing_elements": missing,
            "improvement_feedback": feedback
        }

        report_md = (
            f"# Podcast Script Quality & Fact-Check Audit Report\n\n"
            f"**Auditor Model:** `{audit_model}`\n"
            f"**Current Pass:** {iteration}/{max_iterations}\n"
            f"**Empirical Score:** {overall_score:.1f}%\n"
            f"**Best Score Achieved:** {best_score:.1f}%\n"
            f"**Trainer Audio Ratio:** {ratio_pct:.1f}% (Target: >= 40.0%)\n"
            f"**Target Threshold:** {min_score}%\n\n"
            f"## Quality Progress Graph\n\n{mermaid_graph}\n\n"
            f"## Dimension Scores (Pass {iteration})\n"
            f"```json\n{json.dumps(audit_details, indent=2)}\n```\n\n"
            f"## Accumulated Feedback History Across Passes\n" +
            "\n".join(f"- {h}" for h in accumulated_feedback_history)
        )
        report_path.write_text(report_md, encoding="utf-8")
        console.print(f"[dim]Saved verification report to {report_path}[/dim]")

        if overall_score >= min_score:
            console.print(f"[bold green]SUCCESS: Target quality threshold achieved ({overall_score:.1f}% >= {min_score}%) on Pass {iteration}![/bold green]")
            break

        if iteration >= max_iterations:
            console.print(f"[yellow]Completed all {max_iterations} passes. Restoring best script ({best_score:.1f}%).[/yellow]")
            script_path.write_text(best_script_text, encoding="utf-8")
            (script_path.parent / "script.md").write_text(best_script_text, encoding="utf-8")
            break

        # Targeted refinement using best script and exact feedback
        console.print(f"[bold yellow]Refining script (Pass {iteration} -> {iteration+1})...[/bold yellow]")
        refine_prompt = (
            f"GROUND TRUTH MASTER CONTENT:\n\n{master_text[:35000]}\n\n"
            f"CURRENT PODCAST SCRIPT:\n\n{best_script_text}\n\n"
            f"ERRORS TO FIX:\n{errors}\n\n"
            f"MISSING ELEMENTS & AUDIO DEFICITS TO INJECT:\n{missing}\n\n"
            f"ACTIONABLE FEEDBACK:\n{feedback}\n\n"
            "Output the updated full script with all errors fixed, all missing topics and coach clips integrated, and host monologues pruned so coach audio clips reach >= 40% of runtime."
        )

        refine_resp = client.chat.completions.create(
            model=settings.SCRIPT_MODEL,
            messages=[
                {"role": "system", "content": get_refiner_system_prompt(plugin=plugin)},
                {"role": "user", "content": refine_prompt}
            ],
            temperature=0.3,
            max_tokens=8192
        )

        if hasattr(refine_resp, "usage") and refine_resp.usage:
            cost_tracker.log_llm(
                prompt_tokens=refine_resp.usage.prompt_tokens,
                completion_tokens=refine_resp.usage.completion_tokens,
                model=settings.SCRIPT_MODEL,
                step_label=f"Script Refinement (Pass {iteration})"
            )

        script_text = normalize_audio_tags(refine_resp.choices[0].message.content.strip())
        script_path.write_text(script_text, encoding="utf-8")
        (script_path.parent / "script.md").write_text(script_text, encoding="utf-8")

        iteration += 1

    return best_score

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Audit and fact-check podcast script against master content.")
    parser.add_argument("--master", type=str, default="output/master_content.md")
    parser.add_argument("--script", type=str, default="output/scripts/script.md")
    parser.add_argument("--min-score", type=float, default=97.0)
    parser.add_argument("--max-passes", type=int, default=10)
    parser.add_argument("--audit-model", type=str, default=settings.AUDIT_MODEL, help="Model to use for auditing (e.g. anthropic/claude-3.5-sonnet)")
    args = parser.parse_args()

    verify_and_refine_script(
        Path(args.master), 
        Path(args.script), 
        min_score=args.min_score, 
        max_iterations=args.max_passes,
        audit_model=args.audit_model
    )
