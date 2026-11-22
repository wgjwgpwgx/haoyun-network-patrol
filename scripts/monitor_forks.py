"""fork 与公开扩散监控(维护者工具,只读)

监控三件事:
  1. 谁 fork 了本仓库(列表/星数/最近推送时间);
  2. 每个 fork 相对上游 main 领先哪些提交(谁改了哪里、动了哪些文件);
  3. --search 时扫描 GitHub 公开代码中的特征串扩散(排除本仓库)。

用法:
  python scripts/monitor_forks.py                # fork 列表 + 各 fork 领先提交
  python scripts/monitor_forks.py --search       # 追加公开扩散扫描
  python scripts/monitor_forks.py --json out.json

token 获取顺序: 环境变量 GH_TOKEN > git credential(github.com) > 匿名(限流严格)。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import httpx

UPSTREAM = "wgjwgpwgx/haoyun-network-patrol"
API = "https://api.github.com"
# 公开扩散扫描的特征串:项目独有命名,命中即视为本代码的衍生扩散
SEARCH_MARKERS = ["昊云网络巡检助手", "patrol.desktop.service"]


def _token() -> str | None:
    import os
    import subprocess

    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    try:  # 从 git 凭据管理器取 github.com 的 token(与 push 同源)
        out = subprocess.run(
            ["git", "credential", "fill"], input="protocol=https\nhost=github.com\n",
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        for line in out.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1]
    except Exception:  # noqa: BLE001 - 无凭据则匿名降级
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=UPSTREAM, help="上游 仓库(默认本项目)")
    ap.add_argument("--search", action="store_true", help="追加公开代码扩散扫描")
    ap.add_argument("--json", metavar="FILE", help="同时写机器可读 JSON 报告")
    args = ap.parse_args()

    token = _token()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("[警告] 无 token,匿名访问限流严格", file=sys.stderr)

    with httpx.Client(headers=headers, timeout=30) as c:
        report: dict = {"repo": args.repo, "forks": [], "search": []}

        # ── 1) fork 列表(每页 100,当前规模一页足够;超出时提示) ──
        r = c.get(f"{API}/repos/{args.repo}/forks",
                  params={"per_page": 100, "sort": "newest"})
        r.raise_for_status()
        forks = r.json()
        print(f"== fork 共 {len(forks)} 个 ==")
        if len(forks) == 100:
            print("[提示] 已达单页 100 上限,如有更多请加分页")

        for f in forks:
            item = {"full_name": f["full_name"], "stars": f["stargazers_count"],
                    "pushed_at": f.get("pushed_at", ""), "ahead_commits": [],
                    "license_ok": None}
            line = (f"- {f['full_name']}  ★{f['stargazers_count']}"
                    f"  最近推送 {f.get('pushed_at', '?')[:10]}")

            # ── 2) 领先提交(compare 上游 main...fork main) ──
            try:
                cmp = c.get(f"{API}/repos/{args.repo}/compare/"
                            f"main...{f['owner']['login']}:main")
                if cmp.status_code == 200:
                    data = cmp.json()
                    item["ahead_by"] = data.get("ahead_by", 0)
                    files = [x["filename"] for x in data.get("files", [])]
                    item["ahead_files"] = files
                    line += f"  领先 {data.get('ahead_by', 0)} 提交"
                    for cm in data.get("commits", []):
                        msg = (cm["commit"]["message"] or "").splitlines()[0][:60]
                        author = (cm.get("author") or {}).get("login", "?")
                        item["ahead_commits"].append({"sha": cm["sha"][:7],
                                                      "msg": msg, "author": author})
                        line += f"\n    {cm['sha'][:7]} {msg} ({author})"
                    if files:
                        line += f"\n    改动文件 {len(files)} 个: {', '.join(files[:5])}" \
                               + (" ..." if len(files) > 5 else "")
            except httpx.HTTPError as e:
                line += f"  [compare 失败: {e}]"

            # ── 3) fork 是否保留 MIT 署名 ──
            try:
                lic = c.get(f"{API}/repos/{f['full_name']}/contents/LICENSE")
                if lic.status_code == 404:
                    item["license_ok"] = False
                    line += "\n    [!] LICENSE 缺失(MIT 要求保留,可联系整改)"
                elif lic.status_code == 200:
                    text = base64.b64decode(
                        lic.json().get("content", "")).decode("utf-8", "replace")
                    ok = "昊云" in text or "Haoyun" in text
                    item["license_ok"] = ok
                    if not ok:
                        line += "\n    [!] LICENSE 存在但版权署名被改/删(MIT 违规)"
            except httpx.HTTPError:
                pass

            print(line)
            report["forks"].append(item)

        # ── 4) 公开扩散扫描 ──
        if args.search:
            print("\n== 公开代码扩散扫描 ==")
            for marker in SEARCH_MARKERS:
                try:
                    r = c.get(f"{API}/search/code",
                              params={"per_page": 50,
                                      "q": f'"{marker}" -repo:{args.repo}'})
                    r.raise_for_status()
                    hits = r.json().get("items", [])
                    repos = sorted({h["repository"]["full_name"] for h in hits})
                    print(f'- "{marker}": {len(repos)} 个仓库 {repos}')
                    report["search"].append({"marker": marker, "repos": repos})
                except httpx.HTTPError as e:
                    print(f'- "{marker}": 扫描失败 {e}')
            print("[注] code search 仅覆盖 GitHub 公开可索引代码,建议周期性复查")

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
