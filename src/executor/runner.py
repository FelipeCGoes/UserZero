import time
from pathlib import Path

ACTIONS = {"goto", "click", "fill", "upload", "wait_for"}
DEFAULT_TIMEOUT_MS = 30_000


async def _perform(page, step: dict) -> None:
    action = step["action"]
    if action == "goto":
        await page.goto(step["url"])
    elif action == "click":
        await page.locator(step["selector"]).click()
    elif action == "fill":
        await page.locator(step["selector"]).fill(step.get("value", ""))
    elif action == "upload":
        await page.locator(step["selector"]).set_input_files(step["file"])
    elif action == "wait_for":
        await page.locator(step["selector"]).wait_for(timeout=step.get("timeout_ms", DEFAULT_TIMEOUT_MS))
    else:
        raise ValueError(f"unknown action {action!r} — v0 actions are {sorted(ACTIONS)}")


async def _read_capture(page, step: dict) -> str | None:
    """Reads the text a step's `capture` is supposed to hold. A capture only has a
    defined read target when either the spec explicitly says `capture.selector`, or
    the step's own action is `wait_for` (in which case what's being waited for IS the
    content). Anything else — e.g. a `click` step with a bare `capture_name` and no
    `capture.selector` — has no declared target: return None rather than guess one,
    so a spec that doesn't say what to read produces a visibly empty capture instead
    of silently-wrong content."""
    capture = step["capture"]
    selector = capture.get("selector")
    if not selector and step["action"] == "wait_for":
        selector = step.get("selector")
    if not selector:
        return None
    return await page.locator(selector).inner_text()


async def play_spec(spec: dict, page, run_number: int, output_dir: Path,
                     capture_screenshots: bool = False) -> dict:
    """Executes one pass of a compiled spec against a live Playwright page — no LLM
    in the loop, deterministic replay of what the Compilador already recorded once.
    Never raises on a step failure: a failed step marks the run 'blocked' and stops
    (there's no Healer built yet to retry into), but this function always returns a
    well-formed run dict, so a batch of N never aborts because one run failed."""
    steps_result = []
    captures = {}
    screenshots = []
    status = "ok"

    for step in spec["steps"]:
        t_start_ms = time.time() * 1000
        ok = True
        error = None
        try:
            await _perform(page, step)
            if "capture" in step:
                captures[step["capture"]["name"]] = await _read_capture(page, step)
        except Exception as exc:  # noqa: BLE001 — a step failure is data, not a crash
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            status = "blocked"
        t_end_ms = time.time() * 1000

        entry = {"id": step["id"], "ok": ok, "t_start_ms": t_start_ms, "t_end_ms": t_end_ms}
        if error:
            entry["error"] = error
        steps_result.append(entry)

        if capture_screenshots:
            name = f"run{run_number:03d}_{step['id']}.png"
            path = output_dir / "screenshots" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(path))
            screenshots.append(f"screenshots/{name}")

        if not ok:
            break

    return {
        "run": run_number,
        "status": status,
        "steps": steps_result,
        "captures": captures,
        "artifacts": {"screenshots": screenshots},
        "heals": [],
    }
