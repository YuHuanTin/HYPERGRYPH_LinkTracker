#!/usr/bin/env python3
"""
将官服下载链接文件转换为 B 服下载链接文件。

规则(按顺序):
  - /1/1/  ->  /2/2/
  - HG.zip  ->  bilibili.zip
  其它字符保持不变。

用法:
    python arknights_hg2b.py <input.txt> [output.txt]
    # output.txt 省略时输出到 <input>-bilibili.txt
"""

import sys
from pathlib import Path


def convert_url(url: str) -> str:
    return url.replace("/1/1/", "/2/2/").replace("HG.zip", "bilibili.zip")


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("用法: python arknights_hg2b.py <input.txt> [output.txt]", file=sys.stderr)
        return 1

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"错误: 输入文件不存在 {input_path}", file=sys.stderr); return 1

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.with_name(f"{input_path.stem}-bilibili{input_path.suffix}")

    lines = input_path.read_text(encoding="utf-8").splitlines()
    converted = [convert_url(line) for line in lines]
    output_path.write_text("\n".join(converted) + "\n", encoding="utf-8")

    print(f"输入: {input_path} ({len(lines)} 行)")
    print(f"输出: {output_path}")
    for orig, new in zip(lines, converted):
        if orig != new: print(f"  {orig}  ->  {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())