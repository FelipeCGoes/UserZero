import hashlib
import json
import re
from pathlib import Path


def compute_fingerprint(structural_text: str) -> str:
    """Hash of the DOM/accessibility-tree *structure*, text stripped, so two renders
    of the same state (different data, same layout) dedup to one node."""
    stripped = re.sub(r'"[^"]*"', '""', structural_text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:12]


class GraphBuilder:
    """Accumulates graph.json incrementally as the Cartógrafo agent explores, so the
    graph is a side-effect of tool calls rather than something the LLM has to emit
    correctly as one big JSON blob at the end."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self._fingerprint_to_id: dict[str, str] = {}
        self.edges: list[dict] = []

    def record_node(self, node_id: str, url: str, title: str, structural_text: str,
                     screenshot: str | None = None) -> tuple[str, bool]:
        """Returns (actual_id, is_new). If a node with the same structural fingerprint
        already exists, the existing id is returned and no duplicate is created."""
        fingerprint = compute_fingerprint(structural_text)
        existing = self._fingerprint_to_id.get(fingerprint)
        if existing:
            return existing, False

        self.nodes[node_id] = {
            "id": node_id,
            "url": url,
            "title": title,
            "fingerprint": fingerprint,
            "screenshot": screenshot,
        }
        self._fingerprint_to_id[fingerprint] = node_id
        return node_id, True

    def record_edge(self, from_id: str, to_id: str, action: str, selector: str,
                     label: str, api_method: str | None = None, api_path: str | None = None) -> str:
        edge = {
            "from": from_id,
            "to": to_id,
            "action": action,
            "selector": selector,
            "label": label,
        }
        if api_method and api_path:
            edge["api"] = {"method": api_method, "path": api_path}
        self.edges.append(edge)

        warnings = []
        if from_id not in self.nodes:
            warnings.append(f"'{from_id}' was not recorded via record_node yet")
        if to_id not in self.nodes:
            warnings.append(f"'{to_id}' was not recorded via record_node yet")
        return "edge recorded" + (f" (warning: {'; '.join(warnings)})" if warnings else "")

    def to_dict(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": self.edges}

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "graph.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def strip_preamble(text: str) -> str:
    """Models are asked to answer with raw Markdown but often prepend chatty
    commentary ("Here's the map:") anyway. Cut everything before the first heading
    line instead of relying on prompt compliance for a file another agent reads."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            return "\n".join(lines[i:]).strip() + "\n"
    return text.strip() + "\n"


def write_map_md(output_dir: Path, content: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "map.md"
    path.write_text(strip_preamble(content), encoding="utf-8")
    return path
