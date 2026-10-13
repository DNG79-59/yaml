"""雏形校验器：只做合法性检查，不静默改逻辑。用法: python tools/validate.py [final.yaml]"""
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILTINS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}
GROUP_TYPES = {"select", "url-test", "fallback", "load-balance", "relay"}

errors, warnings = [], []

def load_yaml(p: Path):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        errors.append(f"{p}: YAML 解析失败: {e}")
        return {}

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "SubMin.yaml"
    # 1. 拆分文件都能解析
    parts = sorted((ROOT / "config").glob("*.yaml"))
    if not parts:
        errors.append("config/*.yaml 为空")
    for p in parts:
        load_yaml(p)
    print(f"[check] config 下 {len(parts)} 个文件语法 OK" if not errors else "[check] config 有语法错误")

    if not target.exists():
        # 雏形阶段允许只校验 config，不强制要求产物存在
        print(f"[skip] {target.name} 不存在，跳过引用检查（merge 后会自动检查）")
    else:
        data = load_yaml(target)
        proxies = data.get("proxies") or []
        groups = data.get("proxy-groups") or []
        rules = data.get("rules") or []
        providers = data.get("rule-providers") or {}

        # 2. 节点名唯一
        names = [x.get("name") for x in proxies if isinstance(x, dict)]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            errors.append(f"proxies 存在重名节点: {sorted(dup)} (旧 workflow 的 cat 拼接就会导致这个)")
        else:
            print(f"[check] proxies {len(names)} 个，无重名")

        # 3. 分组名唯一 + 类型合法
        gnames = [g.get("name") for g in groups if isinstance(g, dict)]
        dup_g = {n for n in gnames if gnames.count(n) > 1}
        if dup_g:
            errors.append(f"proxy-groups 存在重名: {sorted(dup_g)}")
        for g in groups:
            if g.get("type") not in GROUP_TYPES:
                errors.append(f"分组 {g.get('name')} type 非法: {g.get('type')}")
        print(f"[check] proxy-groups {len(gnames)} 个")

        known = set(names) | set(gnames) | BUILTINS
        # 4. 分组引用悬空检查（含 include-all/filter 的放行）
        for g in groups:
            if not isinstance(g, dict):
                continue
            refs = g.get("proxies") or []
            if g.get("include-all") or g.get("filter"):
                continue  # 靠订阅节点动态补齐，不做强校验
            for r in refs:
                if r not in known:
                    # 大小写陷阱：Proxy vs PROXY 在你旧配置里同时存在
                    warnings.append(f"分组 {g.get('name')} 引用了未知节点/分组: {r}")

        # 5. rules 引用检查
        for r in rules:
            if not isinstance(r, str):
                continue
            parts_r = [x.strip() for x in r.split(",")]
            if not parts_r:
                continue
            kind = parts_r[0]
            if kind == "RULE-SET":
                if len(parts_r) < 3:
                    errors.append(f"规则格式错误: {r}")
                elif parts_r[1] not in providers:
                    errors.append(f"RULE-SET {parts_r[1]} 在 rule-providers 里找不到 (见 config/41-rule-providers.yaml)")
            elif kind in ("GEOSITE", "GEOIP", "DOMAIN-SET"):
                target_g = parts_r[-2] if parts_r[-1] == "no-resolve" else parts_r[-1]
                if target_g not in known:
                    errors.append(f"规则 {r} 指向的分组 {target_g} 不存在 (你现在的 TaiWan/Japan 就是这种错)")
            elif kind == "MATCH":
                if parts_r[1] not in known:
                    errors.append(f"MATCH {parts_r[1]} 不存在")
        print(f"[check] rules {len(rules)} 条，rule-providers {len(providers)} 个")

    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[error] {e}")
    if errors:
        print(f"\nFAIL: {len(errors)} 个错误，{len(warnings)} 个警告")
        sys.exit(1)
    print(f"\nPASS: 无错误，{len(warnings)} 个警告")

if __name__ == "__main__":
    main()
