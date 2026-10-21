"""Build the generated localMin configuration from the checked-in template."""
from __future__ import annotations

import base64
import re
import urllib.request
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "localMin.yaml"
OUTPUT = ROOT / "localMin.generated.yaml"


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def parse_subscription(raw: bytes, source: str) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace").strip()
    candidates = [text]
    try:
        candidates.append(base64.b64decode("".join(text.split()) + "===").decode("utf-8"))
    except Exception:
        pass
    for candidate in candidates:
        try:
            data = yaml.safe_load(candidate)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and isinstance(data.get("proxies"), list):
            return [p for p in data["proxies"] if isinstance(p, dict) and p.get("name")]
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict) and p.get("name")]
    raise ValueError(f"无法解析订阅: {source}")


def fetch(url: str) -> list[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": "localMin-builder/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return parse_subscription(response.read(), url)


def urls(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def region(name: str) -> str:
    """Extract a stable geographic bucket from common airport node names."""
    for value in ("香港", "台湾", "日本", "韩国", "新加坡", "美国", "英国", "德国", "法国", "土耳其", "俄罗斯", "澳大利亚", "加拿大"):
        if value in name:
            return value
    parts = [p for p in re.split(r"\s*[|｜-]\s*", name) if p]
    return parts[1] if len(parts) > 1 else "unknown"


def limit_airport_nodes(nodes: list[dict], limit: int = 2) -> list[dict]:
    counts: dict[tuple[str, str], int] = {}
    kept = []
    for node in nodes:
        key = (str(node.get("server", "")), region(str(node["name"])))
        if counts.get(key, 0) >= limit:
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(node)
    return kept


def main() -> None:
    config = read_yaml(TEMPLATE)
    manual = config.get("proxies", [])
    leaf_nodes = [p for p in manual if str(p.get("name", "")).lower().startswith("leaf")]
    friend_nodes = [p for p in manual if p.get("name") == "HK-ALIYUN"]
    leaf_sub = [p for u in urls(ROOT / "providers-by-one.yaml") for p in fetch(u)]
    airport_sub = [p for u in urls(ROOT / "providers-by-two.yaml") for p in fetch(u)]
    airport_sub = [p for p in airport_sub if not str(p["name"]).lower().startswith("leaf")]
    airport_sub = limit_airport_nodes(airport_sub)

    # A dialer-proxy group is resolved to one member for each connection.
    # Create one independent hy2 chain per airport node so a load-balance
    # group can actually spread traffic across all airport links.
    chain_templates = [p for p in leaf_nodes if p.get("name") == "leaf-hy2-IPLC"
                       and p.get("dialer-proxy") == "leaf-dialer"]
    chain_nodes = []
    for template in chain_templates:
        for airport in airport_sub + friend_nodes:
            node = dict(template)
            node["name"] = f"{template['name']} | {airport['name']}"
            node["dialer-proxy"] = airport["name"]
            chain_nodes.append(node)
    if chain_templates:
        leaf_nodes = [p for p in leaf_nodes if p not in chain_templates]

    merged = []
    seen = set()
    for node in leaf_nodes + friend_nodes + leaf_sub + airport_sub + chain_nodes:
        if node["name"] not in seen:
            seen.add(node["name"])
            merged.append(node)
    config["proxies"] = merged

    groups = config.get("proxy-groups", [])
    names = {p["name"] for p in merged}
    if chain_nodes:
        chain_group = next((g for g in groups if g.get("name") == "leaf-hy2-load-balance"), None)
        if chain_group is None:
            chain_group = {"name": "leaf-hy2-load-balance", "type": "load-balance",
                           "strategy": "consistent-hashing",
                           "url": "http://www.gstatic.com/generate_204", "proxies": []}
            groups.insert(0, chain_group)
        chain_group["type"] = "load-balance"
        chain_group["strategy"] = "consistent-hashing"
        chain_group["proxies"] = [p["name"] for p in chain_nodes]
        names.add(chain_group["name"])
    config["proxy-groups"] = groups
    for group in groups:
        if group.get("name") == "leaf-dialer":
            group["proxies"] = [p["name"] for p in airport_sub + friend_nodes]
        elif group.get("name") == "Proxy":
            # Keep every concrete node available as a selectable fallback.
            group["type"] = "select"
            group["proxies"] = (["leaf-hy2-load-balance"] if chain_nodes else []) + [p["name"] for p in merged]
        elif isinstance(group.get("proxies"), list):
            group["proxies"] = [p for p in group["proxies"] if p in names or p in {g.get("name") for g in groups} or p in {"DIRECT", "REJECT"}]
    OUTPUT.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"generated {OUTPUT.name}: leaf={len(leaf_sub)} airport={len(airport_sub)} total={len(merged)}")


if __name__ == "__main__":
    main()
