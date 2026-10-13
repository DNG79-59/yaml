"""雏形合并器：用 yaml 解析合并代替 cat 拼接。用法: python tools/merge.py"""
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config"

def load(name: str) -> dict:
    p = CFG / name
    if not p.exists():
        print(f"[skip] {name} 不存在")
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

def load_proxies_list(p: Path) -> list:
    """兼容两种形态：标准 {proxies: [...]} / 纯列表 / flow 风格一行一个 {...}"""
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict) and isinstance(data.get("proxies"), list):
        return data["proxies"]
    if isinstance(data, list):
        return data
    return []

def main():
    base = load("00-base.yaml")
    dns_doc = load("10-dns.yaml")
    manual = load_proxies_list(CFG / "20-proxies.manual.yaml")

    # 兼容旧文件：新结构还没下载订阅时，先用仓库里已有的 proxies-by-*.yaml
    sub_files = sorted(CFG.glob("20-proxies.sub*.yaml"))
    if not sub_files:
        subs = []
        for legacy in ["proxies-by-one.yaml", "proxies-by-two.yaml"]:
            subs += load_proxies_list(ROOT / legacy)
        print(f"[compat] 用旧 {['proxies-by-one.yaml','proxies-by-two.yaml']} 共 {len(subs)} 个节点")
    else:
        subs = []
        for f in sub_files:
            subs += load_proxies_list(f)
        print(f"[info] config 订阅节点 {len(subs)} 个")

    # 去重：同名只留第一个（旧 cat 会直接重复写入导致 SubMin.yaml:11/88 重复）
    seen, merged, dups = set(), [], []
    for node in manual + subs:
        n = node.get("name") if isinstance(node, dict) else None
        if not n:
            continue
        if n in seen:
            dups.append(n)
            continue
        seen.add(n)
        merged.append(node)
    if dups:
        print(f"[fix] 自动去重 {len(dups)} 个: {sorted(set(dups))}")

    groups = load("30-proxy-groups.yaml").get("proxy-groups", [])
    rules = load("40-rules.yaml").get("rules", [])
    providers = load("41-rule-providers.yaml").get("rule-providers", {})

    out = dict(base)
    if "dns" in dns_doc:
        out["dns"] = dns_doc["dns"]
    out["proxies"] = merged
    out["proxy-groups"] = groups
    out["rules"] = rules
    out["rule-providers"] = providers

    target = ROOT / "SubMin.new.yaml"  # 雏形先写 .new，不覆盖线上 SubMin.yaml
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)
    print(f"[ok] 已生成 {target.name}: proxies={len(merged)} groups={len(groups)} rules={len(rules)}")

if __name__ == "__main__":
    main()
