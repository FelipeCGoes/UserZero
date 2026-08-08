# UserZero
## Overview

This project is a implementation of a synthetic test pipeline for AI-driven flows.
It executes a declared flow, records run artifacts, and evaluates those runs with a set of judges.

The repository currently contains:
- a small browser/agent exploration component under `src/cartografo`
- a judge runner under `src/judges`
- result aggregation under `src/veredito`
- fixtures under `fixture/`

This README is incomplete and reflects the existing code and fixture structure.

## Key concepts

### Spec files



### Judges

The judge pipeline reads a spec and a directory of runs, then produces `judgments.json`.
- Deterministic judges are offline/scripted and require no LLM.
- The `grounding` judge is the only LLM-powered judge in this implementation.

## How to run judges

From `src/`, use the judge CLI:

```powershell
python -m judges.cli --spec ../fixture/spec.yaml --runs-dir ../fixture/runs --out ../fixture/out/judgments.json
```

For grounding-only fixtures:

```powershell
python -m judges.cli --spec ../fixture/spec_grounding.yaml --runs-dir ../fixture/runs_grounding --out ../fixture/out/judgments_grounding.json
```

### Grounding and environment variables

If the spec contains a `grounding` contract, the CLI loads LLM settings from environment variables:
- `FEATHERLESS_BASE_URL`
- `FEATHERLESS_API_KEY`
- `MODEL`

The other judge types run deterministically and do not require these variables.

## Repository structure

- `src/cartografo/`: Cartógrafo agent and browser exploration helpers
- `src/common/`: shared utilities such as LLM client creation
- `src/judges/`: judge implementations and runner
- `src/veredito/`: aggregation and reporting logic
- `fixture/`: sample specs, runs, sources, and output fixtures

## Current behavior

- `fixture/spec.yaml` is a full flow fixture with multiple contracts and two captures (`report_text`, `report_text_v2`).
- `fixture/runs/` contains a larger set of run records used by the deterministic judges.
- `fixture/spec_grounding.yaml` is a simplified flow for grounding evaluation only.
- `fixture/runs_grounding/` contains the matching grounding-only runs.
- `fixture/sources/empresa_fonte.txt` is the source text used for grounding verification.

## Notes

- `spec.yaml` files declare which judge checks to apply and with what parameters; they do not implement judge logic.
- The judge runner is designed to be rerunnable: it reads existing `run-*.json` files and evaluates them without replaying the browser.
- This README is intentionally partial and based on the current codebase state.
