"""把安装包上传到指定标签的草稿 Release,不改变草稿状态。

发版流水线的最后一步。只认草稿:标签对应的 Release 不存在、或已经不是草稿,就直接失败——
附件与发布说明要人工核对后,再由人把草稿发布出去。(第三方的发布 action 未显式指定时
会把草稿直接发布出去,v0.2.1 就是这样在人工核对前上线的。)只用标准库,便于本地自检。

用法(需要环境变量 GITHUB_TOKEN;GITHUB_REPOSITORY 在流水线上自动提供):
    python scripts/upload_release_assets.py v0.2.1 dist/*.zip dist/*.tar.gz
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UPLOAD_API = "https://uploads.github.com"  # 附件上传不走 api.github.com
TOKEN, REPO = os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"]


def call(method: str, url: str, body: bytes | None = None, content_type: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
               "User-Agent": "patrol-release"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {url} 失败:HTTP {e.code} {e.read().decode('utf-8', errors='replace')[:300]}")


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit("用法: python scripts/upload_release_assets.py <标签> <附件>...")
    tag, files = sys.argv[1], sys.argv[2:]
    release = None
    for _ in range(6):  # 刚建的 Release 可能要过几秒才在列表接口里可见
        releases = call("GET", f"{API}/repos/{REPO}/releases?per_page=100")
        release = next((item for item in releases if item["tag_name"] == tag), None)
        if release:
            break
        time.sleep(3)
    if release is None:
        sys.exit(f"标签 {tag} 还没有对应的 Release:请先建草稿 Release,再推送标签")
    if not release["draft"]:
        sys.exit(f"标签 {tag} 的 Release 已不是草稿,拒绝上传:附件应在上传后、发布前人工核对")
    existing = {asset["name"] for asset in release["assets"]}
    for path in files:
        name = os.path.basename(path)
        if name in existing:
            sys.exit(f"Release 上已有同名附件 {name}:请先删除旧附件再重跑")
        # 接口收的是文件本身的字节(不是 multipart 表单——整段报文会被原样存成附件)
        with open(path, "rb") as f:
            body = f.read()
        query = urllib.parse.urlencode({"name": name})
        asset = call("POST", f"{UPLOAD_API}/repos/{REPO}/releases/{release['id']}/assets?{query}",
                     body, mimetypes.guess_type(name)[0] or "application/octet-stream")
        existing.add(name)
        print(f"已上传 {asset['name']}({asset['size'] / 1048576:.1f} MB)")
    saved = call("GET", f"{API}/repos/{REPO}/releases/{release['id']}")
    print(f"标签 {tag}:草稿={saved['draft']},附件={sorted(a['name'] for a in saved['assets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
