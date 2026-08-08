import asyncio
import json
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

from executor.runner import play_spec


async def run_batch(compilador_dir: Path, output_dir: Path, n: int,
                     concurrency: int = 5, headless: bool = True) -> list[dict]:
    """Runs a compiled spec N times, concurrency-limited, one browser + N contexts —
    no LLM, no confirmation UI. Screenshots stay off by default here (unlike
    dry-run): capturing one per step per run at N=20+ would inflate the very latency
    numbers this is supposed to measure (DESIGN.md's evidence-under-load rule).
    A run that fails never aborts the batch — play_spec always returns, never raises."""
    compilador_dir = Path(compilador_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = yaml.safe_load((compilador_dir / "spec.yaml").read_text(encoding="utf-8"))
    semaphore = asyncio.Semaphore(concurrency)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            async def one(run_number: int) -> dict:
                async with semaphore:
                    context = await browser.new_context()
                    try:
                        page = await context.new_page()
                        run = await play_spec(spec, page, run_number=run_number, output_dir=output_dir)
                    finally:
                        await context.close()
                    path = output_dir / f"run-{run_number:03d}.json"
                    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
                    return run

            runs = await asyncio.gather(*(one(i) for i in range(1, n + 1)))
        finally:
            await browser.close()

    return list(runs)
