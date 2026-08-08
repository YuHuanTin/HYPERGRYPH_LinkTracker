#!/usr/bin/env python3
"""
离线分析工具:从 git 历史提取 Arknights.json 快照,为每个版本生成下载链接列表。

流程:
  1. 扫描 git 历史,提取每次更新时的 links/Arknights.json 到 SNAPSHOT_DIR
     文件命名: <序号>_<完整 commit hash>.json,按旧到新排列
  2. 读取 _index.json,为每个 to_version 在同目录下生成 <版本>.txt
     内含该版本所有 packs 的 URL (每行一个)

运行 -h/--help 查看 CLI 帮助。
"""

import json, re, subprocess, sys
from pathlib import Path

REPO_FILE = "links/Arknights.json"
SNAPSHOT_DIR = Path("scripts/arknights_history")


def convert_url_to_bilibili(url: str) -> str:
    """官服 URL -> B 服 URL:/1/1/ -> /2/2/;HG.zip -> bilibili.zip。"""
    return url.replace("/1/1/", "/2/2/").replace("HG.zip", "bilibili.zip")


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
    return result.stdout


def list_commits(repo: Path, file_path: str) -> list[str]:
    out = run_git(["log", "--pretty=format:%H", "--follow", "--", file_path], repo).strip()
    return [h for h in reversed(out.splitlines()) if h]


def get_commit_meta(repo: Path, commit: str) -> dict:
    sep = "\x01"
    fmt = sep.join(["%H", "%aI", "%cI", "%s"])
    out = run_git(["show", "--no-patch", f"--pretty=format:{fmt}", commit], repo)
    parts = out.split(sep)
    if len(parts) < 4: raise RuntimeError(f"无法解析 commit {commit} 的元数据")
    return {"hash": parts[0], "author_time": parts[1], "commit_time": parts[2], "subject": parts[3]}


def read_file_at_commit(repo: Path, commit: str, file_path: str) -> bytes | None:
    try:
        return subprocess.run(["git", "show", f"{commit}:{file_path}"], cwd=repo, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None


def parse_versions_from_subject(subject: str) -> tuple[str | None, str | None]:
    m = re.search(r"Arknights\s*\(([^)]+)\)", subject, re.IGNORECASE)
    if not m: return None, None
    inner = m.group(1)
    arrow = re.match(r"\s*([^->]+?)\s*->\s*([^->]+?)\s*$", inner)
    if arrow: return arrow.group(1).strip() or None, arrow.group(2).strip() or None
    return None, inner.strip() or None


def extract_snapshot_commits(repo: Path, file_path: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    commits = list_commits(repo, file_path)
    if not commits:
        print(f"未找到影响 {file_path} 的 commit。"); return

    print(f"--- 步骤 1/2: 提取 {len(commits)} 个快照到 {output_dir} ---")
    extracted, skipped, processed = 0, 0, 0
    index: list[dict] = []
    for commit in commits:
        meta = get_commit_meta(repo, commit)
        old_v, new_v = parse_versions_from_subject(meta["subject"])
        content = read_file_at_commit(repo, commit, file_path)
        if content is None:
            print(f"  [{commit[:7]}] 跳过 (文件不存在)"); processed += 1; skipped += 1; continue

        processed += 1
        out_name = f"{processed}_{meta['hash']}.json"
        out_path = output_dir / out_name

        if out_path.exists():
            index.append({"file": out_name, "commit": meta["hash"], "commit_time": meta["commit_time"], "from_version": old_v, "to_version": new_v, "subject": meta["subject"]})
            print(f"  [{commit[:7]}] 已存在,跳过写入: {out_name}"); skipped += 1; continue

        try:
            parsed = json.loads(content.decode("utf-8"))
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pretty = content.decode("utf-8", errors="replace")
        out_path.write_text(pretty + "\n", encoding="utf-8")
        index.append({"file": out_name, "commit": meta["hash"], "commit_time": meta["commit_time"], "from_version": old_v, "to_version": new_v, "subject": meta["subject"]})
        print(f"  [{meta['hash'][:7]}] {old_v or '?'} -> {new_v or '?'}  ->  {out_name}")
        extracted += 1

    (output_dir / "_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"快照提取完成: 写入 {extracted}, 跳过 {skipped}。")


def extract_urls_from_snapshot(snapshot: dict) -> list[str]:
    urls: list[str] = []
    rsp_list = snapshot.get("proxy_rsps", [])
    if not rsp_list: return urls
    pkg = rsp_list[0].get("get_latest_game_rsp", {}).get("pkg") or {}
    for pack in pkg.get("packs") or []:
        url = pack.get("url", "")
        if url: urls.append(url)
    return urls


def generate_full_link_files(output_dir: Path, use_bilibili: bool = False) -> None:
    index_path = output_dir / "_index.json"
    if not index_path.exists():
        print(f"错误: 索引文件不存在 {index_path}", file=sys.stderr); return
    suffix = "-bilibili" if use_bilibili else ""
    label = "B 服" if use_bilibili else "全量"
    print(f"--- 步骤 2/2: 生成{label}版本下载链接 ---")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    written: list[tuple[str, int]] = []
    for entry in index:
        version = entry.get("to_version")
        if not version: continue
        snap_path = output_dir / entry["file"]
        if not snap_path.exists():
            print(f"  [{version}] 警告: 快照不存在 {snap_path}"); continue
        try:
            snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  [{version}] 警告: 解析失败: {e}"); continue
        urls = extract_urls_from_snapshot(snapshot)
        if use_bilibili:
            urls = [convert_url_to_bilibili(u) for u in urls]
        if not urls:
            print(f"  [{version}] 跳过 (无 packs URL)"); continue
        out_name = f"{version}{suffix}.txt"
        (output_dir / out_name).write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"  [{version}] {len(urls)} 个链接 -> {out_name}")
        written.append((version, len(urls)))
    print(f"{label}链接生成完成: {len(written)} 个版本。")


def main() -> int:
    if "-h" in sys.argv or "--help" in sys.argv:
        print(f"""用法:python {Path(__file__).name} [选项]

选项:
  --use-bilibili    只生成 <版本>-bilibili.txt (官服 URL -> B 服 URL)
  -h, --help        显示此帮助

流程:
  1. 提取 git 历史中 links/Arknights.json 的快照到 {SNAPSHOT_DIR}
  2. 为每个 to_version 生成 <版本>.txt (全量 packs URL;--use-bilibili 时改为 B 服)
""")
        return 0

    use_bilibili = "--use-bilibili" in sys.argv

    repo = Path(".").resolve()
    if not (repo / ".git").exists():
        print(f"错误: {repo} 不是 git 仓库", file=sys.stderr); return 1

    extract_snapshot_commits(repo, REPO_FILE, SNAPSHOT_DIR)
    print()
    generate_full_link_files(SNAPSHOT_DIR, use_bilibili=use_bilibili)
    return 0


if __name__ == "__main__":
    sys.exit(main())