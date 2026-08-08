#!/usr/bin/env python3
"""
从 launcher.hypergryph.com 拉取 Arknights / Endfield / POPUCOM / 启动器 的最新版本。

策略:
  - 先读本地 links/<game>.json 的 version 字段(忽略 timestamp)
  - 若本地 version 与服务端最新一致,跳过,不调用 API
  - 否则,调用 get_latest_game 时将本地 version 作为 from_version 传入,
    使服务器返回包含 patch 增量包的完整响应
  - B 服(Arknights channel=2 sub_channel=2) 输出到 Arknights-Bilibili.json

环境变量:
  ARKNIGHTS_CHANNELS            默认 "1/1,2/2" (官服 + B 服),多渠道逗号分隔
  ENDFIELD_CHANNELS             默认 "1/1"
  POPUCOM_CHANNELS              默认 "1/1"
  HYPERGRYPH_LAUNCHER_CHANNELS  默认 "1"
  HG_LINK_OUTPUT_DIR            默认 "links"
"""

import json, os, sys
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

BATCH_PROXY_URL = "https://launcher.hypergryph.com/api/proxy/batch_proxy"
LAUNCHER_LATEST_URL = "https://launcher.hypergryph.com/api/launcher/get_latest"
USER_AGENT = "Mozilla/5.0 (Windows NT 6.2; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) QtWebEngine/5.15.8 Chrome/87.0.4280.144 Safari/537.36"
HEADERS = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

GAMES = [
    ("Arknights", "GzD1CpaWgmSq1wew", "ARKNIGHTS_CHANNELS", "1/1,2/2"),
    ("Endfield", "6LL0KJuqHBVz33WK", "ENDFIELD_CHANNELS", "1/1"),
    ("POPUCOM", "Vp2jukCCSUGztqli", "POPUCOM_CHANNELS", "1/1"),
]
LAUNCHER_APPCODE = "abYeZZ16BPluCFyT"
LAUNCHER_ENV_KEY = "HYPERGRYPH_LAUNCHER_CHANNELS"


def http_post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            if resp.status != 200: raise RuntimeError(f"HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        raise RuntimeError(f"POST {url} 失败: {e}") from e


def http_get_json(url: str) -> dict:
    req = request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with request.urlopen(req, timeout=30) as resp:
            if resp.status != 200: raise RuntimeError(f"HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        raise RuntimeError(f"GET {url} 失败: {e}") from e


def parse_channels(env_value: str, default_channel: str = "1") -> list[tuple[str, str]]:
    s = (env_value or "").strip()
    if not s: return [(default_channel, default_channel)]
    out: list[tuple[str, str]] = []
    for item in s.split(","):
        item = item.strip()
        if not item: continue
        if "/" in item:
            c, sc = item.split("/", 1)
            out.append((c.strip(), sc.strip()))
        else:
            out.append((item, default_channel))
    return out or [(default_channel, default_channel)]


def fetch_game(appcode: str, channel: str, sub_channel: str, from_version: str = "") -> dict:
    payload = {"proxy_reqs": [{"kind": "get_latest_game", "get_latest_game_req": {"appcode": appcode, "channel": channel, "sub_channel": sub_channel, "version": from_version, "launcher_appcode": ""}}]}
    return http_post_json(BATCH_PROXY_URL, payload)


def fetch_launcher(channel: str) -> dict:
    return http_get_json(f"{LAUNCHER_LATEST_URL}?appcode={LAUNCHER_APPCODE}&channel={channel}")


def read_local_version(path: Path) -> str | None:
    """仅读取 version,忽略 timestamp。"""
    if not path.exists(): return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    rsp_list = data.get("proxy_rsps") if isinstance(data, dict) else None
    if rsp_list and rsp_list[0]:
        ver = rsp_list[0].get("get_latest_game_rsp", {}).get("version")
        if ver: return ver
    return data.get("version")


def fetch_remote_version(appcode: str, channel: str, sub_channel: str) -> str:
    """只查 version,不写入文件。"""
    rsp = fetch_game(appcode, channel, sub_channel, from_version="")
    return (rsp.get("proxy_rsps") or [{}])[0].get("get_latest_game_rsp", {}).get("version", "")


def out_filename(game_name: str, channel: str, sub_channel: str) -> str:
    if game_name == "Arknights" and channel == "2" and sub_channel == "2":
        return "Arknights-Bilibili.json"
    return f"{game_name}.json"


def write_pretty(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process_game(game_name: str, appcode: str, env_key: str, default_channels: str, output_dir: Path) -> list[str]:
    channels = parse_channels(os.environ.get(env_key, default_channels))
    logs: list[str] = []
    for channel, sub_channel in channels:
        label = f"{game_name}@{channel}/{sub_channel}"
        out_name = out_filename(game_name, channel, sub_channel)
        out_path = output_dir / out_name
        old_ver = read_local_version(out_path)

        try:
            remote_ver = fetch_remote_version(appcode, channel, sub_channel)
        except RuntimeError as e:
            print(f"  [{label}] 失败: {e}", file=sys.stderr); continue

        if not remote_ver:
            print(f"  [{label}] 服务端未返回 version,跳过"); continue
        if remote_ver == old_ver:
            print(f"  [{label}] 无变化 ({old_ver})"); continue

        # 本地不一致:携带本地 version 请求,获取 patch 增量包
        try:
            response = fetch_game(appcode, channel, sub_channel, from_version=old_ver or "")
        except RuntimeError as e:
            print(f"  [{label}] 获取含 patch 的响应失败: {e}", file=sys.stderr); continue
        new_ver = (response.get("proxy_rsps") or [{}])[0].get("get_latest_game_rsp", {}).get("version", "")
        if new_ver != remote_ver:
            print(f"  [{label}] 警告: 含 patch 的响应 version={new_ver} 与纯 latest {remote_ver} 不一致,仍写入")

        write_pretty(out_path, response)
        print(f"  [{label}] {old_ver or 'None'} -> {new_ver or remote_ver}  ({out_name})")
        logs.append(f"{game_name} ({old_ver or 'None'} -> {new_ver or remote_ver})")
    return logs


def process_launcher(output_dir: Path) -> list[str]:
    channels = parse_channels(os.environ.get(LAUNCHER_ENV_KEY, "1"), default_channel="1")
    logs: list[str] = []
    for channel, _ in channels:
        label = f"HypergryphLauncher@{channel}"
        out_path = output_dir / "HypergryphLauncher.json"
        old_ver = read_local_version(out_path)
        try:
            response = fetch_launcher(channel)
        except RuntimeError as e:
            print(f"  [{label}] 失败: {e}", file=sys.stderr); continue
        new_ver = response.get("version", "")
        if not new_ver:
            print(f"  [{label}] 服务端未返回 version"); continue
        if new_ver == old_ver:
            print(f"  [{label}] 无变化 ({old_ver})"); continue
        write_pretty(out_path, response)
        print(f"  [{label}] {old_ver or 'None'} -> {new_ver}")
        logs.append(f"HypergryphLauncher ({old_ver or 'None'} -> {new_ver})")
    return logs


def main() -> int:
    output_dir = Path(os.environ.get("HG_LINK_OUTPUT_DIR", "links")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {output_dir}")

    logs: list[str] = []
    for name, appcode, env_key, default_channels in GAMES:
        print(f"--- {name} ---")
        logs.extend(process_game(name, appcode, env_key, default_channels, output_dir))
    print(f"--- HypergryphLauncher ---")
    logs.extend(process_launcher(output_dir))

    if logs:
        env_file = os.environ.get("GITHUB_ENV")
        if env_file:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"COMMIT_MSG={', '.join(logs)}\n")
        print(f"\n变更: {'; '.join(logs)}")
    else:
        print("\n没有任何变动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())