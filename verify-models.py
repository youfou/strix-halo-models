#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验已完成下载的模型文件 sha256 是否正确。

只校验“已下完”的文件：体积与清单一致、且没有 .aria2 控制文件
（aria2 只有真正下完并校验通过后才删 .aria2）。没下完的（体积不够
或还有 .aria2）、还没开始下的（不存在），都跳过，不算错。

用法：
    python3 verify-models.py [--dest /mnt/llms/models] [--manifest manifest.json]
    python3 verify-models.py --dry-run        # 只汇报，不提示、不删除
    python3 verify-models.py --yes            # 坏文件全部直接删，不逐个问

--dest 不给时，自动读同目录下 runwisp.toml 里 run 命令的 --dest；
读不到就必须用 --dest 指定。

校验出 sha256 不对的文件，默认逐个问是否删除（默认不删）；
体积比清单大的文件也视为坏文件（肯定不对），同样问是否删除。
删掉后重新跑下载脚本即可从断点/从头补下。

退出码：0 = 校验的全部通过；1 = 发现坏文件（无论删没删）；
2 = 用法或配置错误（如目标目录、清单文件不存在）。
"""

import argparse
import hashlib
import json
import os
import re
import sys

CHUNK = 8 * 1024 * 1024  # 每次读 8MB 做 sha256


def file_state(path, expected):
    """返回文件当前状态，与 download-models.py 的口径一致。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "missing"
    if size == expected:
        # 体积满格还不能算完成：多分段乱序写盘时，最后一段一写体积就
        # 接近满格，但中间可能全是空洞；只有 aria2 控制文件也被删掉
        # （aria2 只在真正下完并校验通过后才删）才算完成。
        if os.path.exists(path + ".aria2"):
            return "partial"
        return "done"
    if size > expected:
        return "oversize"
    if os.path.exists(path + ".aria2"):
        return "partial"
    return "partial-noctl"


def read_dest_from_toml(script_dir):
    """从同目录 runwisp.toml 的 run 命令里读 --dest，读不到返回 None。"""
    toml = os.path.join(script_dir, "runwisp.toml")
    try:
        with open(toml, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r'^run\s*=\s*".*?--dest\s+([^"\s]+)', text, re.M)
    return m.group(1) if m else None


def fmt_size(n):
    if n >= 1 << 30:
        return "%.2f GB" % (n / (1 << 30))
    if n >= 1 << 20:
        return "%.1f MB" % (n / (1 << 20))
    return "%d B" % n


def sha256_file(path, size):
    """算文件 sha256。大文件（>1GB）每 2 秒在同一行刷新一次进度。"""
    h = hashlib.sha256()
    done = 0
    last_show = 0.0
    import time
    show_progress = size > (1 << 30)
    with open(path, "rb") as f:
        while True:
            data = f.read(CHUNK)
            if not data:
                break
            h.update(data)
            done += len(data)
            if show_progress:
                now = time.time()
                if now - last_show >= 2.0:
                    last_show = now
                    pct = done * 100.0 / size
                    sys.stdout.write(
                        "\r  已读 %s / %s (%.1f%%)" % (
                            fmt_size(done), fmt_size(size), pct))
                    sys.stdout.flush()
    if show_progress:
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()
    return h.hexdigest()


def ask_yes_no(prompt):
    """问是否删除，默认 No。只认 y/yes（大小写不敏感），其余都当 No。"""
    try:
        ans = input(prompt + " [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="校验已完成下载的模型文件 sha256 是否正确")
    ap.add_argument("--dest", default=None,
                    help="模型根目录（如 /mnt/llms/models），不给则读 runwisp.toml 的 --dest")
    ap.add_argument("--manifest", default=None,
                    help="清单文件，默认同目录下的 manifest.json")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="坏文件全部直接删除，不逐个询问")
    ap.add_argument("--dry-run", action="store_true",
                    help="只汇报结果，不提示、不删除")
    args = ap.parse_args()

    dest = args.dest or read_dest_from_toml(script_dir)
    if not dest:
        print("错误：没找到目标目录。请用 --dest 指定（如 --dest /mnt/llms/models），"
              "或确认同目录下 runwisp.toml 的 run 命令里有 --dest。", file=sys.stderr)
        return 2
    if not os.path.isdir(dest):
        print("错误：目标目录不存在：%s" % dest, file=sys.stderr)
        return 2
    manifest_path = args.manifest or os.path.join(script_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("错误：清单文件不存在：%s" % manifest_path, file=sys.stderr)
        return 2
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        print("错误：清单文件读不了：%s" % e, file=sys.stderr)
        return 2

    models = manifest.get("models", [])
    total = sum(len(m.get("files", [])) for m in models)
    n_ok = 0
    n_bad = 0
    n_skip_missing = 0
    n_skip_partial = 0
    bad = []  # (显示路径, 原因)
    extra = []  # 磁盘上有、清单里没有的文件（只汇报，不处理）

    # 先把清单里所有文件路径记下来，之后用来发现多余文件。
    wanted = set()
    for m in models:
        for f in m.get("files", []):
            wanted.add(os.path.join(dest, m["slug"], f["path"]))

    print("目标目录：%s" % dest)
    print("清单：%s（共 %d 个模型、%d 个文件）" % (
        manifest_path, len(models), total))
    print("只校验已下完的文件（体积与清单一致且无 .aria2）；"
          "没下完、还没下的跳过。")
    print()

    try:
        for m in models:
            slug = m["slug"]
            for f in m.get("files", []):
                rel = os.path.join(slug, f["path"])
                path = os.path.join(dest, rel)
                state = file_state(path, f["size"])
                if state == "missing":
                    n_skip_missing += 1
                    continue
                if state in ("partial", "partial-noctl"):
                    n_skip_partial += 1
                    continue
                if state == "oversize":
                    print("体积异常：%s（实际 %s，清单 %s）" % (
                        rel, fmt_size(os.path.getsize(path)), fmt_size(f["size"])))
                    bad.append((rel, path, "体积比清单大"))
                    n_bad += 1
                    continue
                # state == "done"：真正校验 sha256。
                print("校验 %s（%s）..." % (rel, fmt_size(f["size"])), flush=True)
                try:
                    actual = sha256_file(path, f["size"])
                except OSError as e:
                    print("  读不了，跳过：%s" % e)
                    continue
                if actual == f["sha256"]:
                    print("  通过")
                    n_ok += 1
                else:
                    print("  不匹配！")
                    print("    清单：%s" % f["sha256"])
                    print("    实际：%s" % actual)
                    bad.append((rel, path, "sha256 不匹配"))
                    n_bad += 1
    except KeyboardInterrupt:
        print("\n已中断（Ctrl+C），只汇报已校验的部分，不删除任何文件。")
        print("已通过：%d，坏文件：%d，跳过（未下完）：%d，跳过（未开始）：%d" % (
            n_ok, n_bad, n_skip_partial, n_skip_missing))
        return 1

    # 磁盘上多余的文件（清单里没有）：只汇报，不动。
    for root, _dirs, files in os.walk(dest):
        for name in files:
            if name.endswith(".aria2") or name.startswith("."):
                continue
            p = os.path.join(root, name)
            if p not in wanted:
                extra.append(os.path.relpath(p, dest))

    print()
    print("—— 汇总 ——")
    print("已校验通过：%d" % n_ok)
    print("坏文件：%d" % n_bad)
    print("跳过（还没下完）：%d" % n_skip_partial)
    print("跳过（还没开始下）：%d" % n_skip_missing)
    if extra:
        print("磁盘上多余的文件（清单里没有，只汇报，不处理）：")
        for e in sorted(extra):
            print("  %s" % e)

    if not bad:
        print("全部通过，没有坏文件。")
        return 0

    print()
    print("坏文件清单：")
    for rel, _path, reason in bad:
        print("  %s（%s）" % (rel, reason))

    if args.dry_run:
        print("（--dry-run：只汇报，不删除。）")
        return 1

    deleted = 0
    kept = 0
    for rel, path, reason in bad:
        if args.yes:
            do_delete = True
        else:
            do_delete = ask_yes_no("删除 %s 吗？（%s）" % (rel, reason))
        if do_delete:
            try:
                os.remove(path)
                print("已删除：%s" % rel)
                deleted += 1
            except OSError as e:
                print("删除失败：%s：%s" % (rel, e))
                kept += 1
        else:
            print("保留：%s" % rel)
            kept += 1

    print()
    print("已删除：%d，保留：%d。删掉的文件重新跑下载脚本即可补下。" % (deleted, kept))
    return 1


if __name__ == "__main__":
    sys.exit(main())
