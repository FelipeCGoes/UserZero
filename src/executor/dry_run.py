import json
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

from executor.runner import play_spec


async def run_dry(compilador_dir: Path, output_dir: Path, headless: bool = True) -> dict:
    """Runs a compiled spec once for real (n=1, no LLM) and writes dry-run.json —
    deliberately NOT named run-*.json: Judges' batch loader (judges/runner.py)
    globs run-*.json to enumerate production runs, and dry-run output lives in the
    same executor/ folder batch writes into. A dry-run sample must never be silently
    counted as one of the N production runs.
    Returns {"spec": ..., "run": ..., "run_path": ...} — plain data, no printing, no
    confirmation UI. Confirming with a human is the caller's job (compilador owns
    that loop), not this function's."""
    compilador_dir = Path(compilador_dir)
    output_dir = Path(output_dir)
    spec = yaml.safe_load((compilador_dir / "spec.yaml").read_text(encoding="utf-8"))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            run = await play_spec(spec, page, run_number=1, output_dir=output_dir, capture_screenshots=True)
        finally:
            await browser.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    run_path = output_dir / "dry-run.json"
    run_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"spec": spec, "run": run, "run_path": run_path}
