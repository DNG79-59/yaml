"""Build the generated localMin configuration from the checked-in template."""
from __future__ import annotations

import base64
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


def main() -> None:
    config = read_yaml(TEMPLATE)
    manual = config.get("proxies", [])
    leaf_nodes = [p for p in manual if str(p.get("name", "")).lower().startswith("leaf")]
    friend_nodes = [p for p in manual if p.get("name") == "HK-ALIYUN"]
    leaf_sub = [p for u in urls(ROOT / "providers-by-one.yaml") for p in fetch(u)]
    airport_sub = [p for u in urls(ROOT / "providers-by-two.yaml") for p in fetch(u)]
    airport_sub = [p for p in airport_sub if not str(p["name"]).lower().startswith("leaf")]

    merged = []
    seen = set()
    for node in leaf_nodes + friend_nodes + leaf_sub + airport_sub:
        if node["name"] not in seen:
            seen.add(node["name"])
            merged.append(node)
    config["proxies"] = merged

    groups = config.get("proxy-groups", [])
    names = {p["name"] for p in merged}
    for group in groups:
        if group.get("name") == "leaf-dialer":
            group["proxies"] = [p["name"] for p in airport_sub + friend_nodes]
        elif isinstance(group.get("proxies"), list):
            group["proxies"] = [p for p in group["proxies"] if p in names or p in {g.get("name") for g in groups} or p in {"DIRECT", "REJECT"}]
    OUTPUT.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"generated {OUTPUT.name}: leaf={len(leaf_sub)} airport={len(airport_sub)} total={len(merged)}")


if __name__ == "__main__":
    main()
