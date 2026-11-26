#!/usr/bin/env python3
"""Fetch the verified download manifest from the Hugging Face API.

For each model: pull the repo file tree, match the exact GGUF files we want
(single files and multi-part shards), and record path, size (bytes) and the
LFS sha256 (oid). Also records whether the repo is gated (needs HF token).

Output: ~/workspace/strix-halo-models/manifest.json
"""
import json
import os
import sys
import urllib.request

OUT = os.path.expanduser("~/workspace/strix-halo-models/manifest.json")

# model slug -> (display name, HF repo, wanted files)
# wanted: list of ("exact", filename) or ("prefix", dir-prefix) or
# ("contains", substring) matchers, applied to repo file paths.
MODELS = [
    ("qwen3-coder-30b", "Qwen3-Coder-30B-A3B",
     "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
     [("exact", "Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf"),
      ("exact", "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf")]),
    ("qwen3-coder-next-80b", "Qwen3-Coder-Next 80B",
     "Qwen/Qwen3-Coder-Next-GGUF",
     [("prefix", "Qwen3-Coder-Next-Q8_0/"),
      ("prefix", "Qwen3-Coder-Next-Q4_K_M/")]),
    ("qwen3-235b", "Qwen3-235B-A22B",
     "bartowski/Qwen_Qwen3-235B-A22B-Instruct-2507-GGUF",
     [("prefix", "Qwen_Qwen3-235B-A22B-Instruct-2507-Q3_K_M/")]),
    ("qwen3.5-122b", "Qwen3.5-122B-A10B",
     "unsloth/Qwen3.5-122B-A10B-GGUF",
     [("prefix", "Q4_K_M/")]),
    ("gpt-oss-120b", "gpt-oss-120b",
     "ggml-org/gpt-oss-120b-GGUF",
     [("exact", "gpt-oss-120b-MXFP4.gguf")]),
    ("glm-4.7-flash", "GLM-4.7-Flash",
     "bartowski/zai-org_GLM-4.7-Flash-GGUF",
     [("exact", "zai-org_GLM-4.7-Flash-Q6_K_L.gguf")]),
    ("qwen3-30b", "Qwen3-30B-A3B",
     "bartowski/Qwen_Qwen3-30B-A3B-Instruct-2507-GGUF",
     [("exact", "Qwen_Qwen3-30B-A3B-Instruct-2507-Q8_0.gguf")]),
    ("qwen3-32b", "Qwen3-32B",
     "Qwen/Qwen3-32B-GGUF",
     [("exact", "Qwen3-32B-Q8_0.gguf")]),
    ("gemma-3-27b", "Gemma-3-27B-it",
     "unsloth/gemma-3-27b-it-GGUF",
     [("exact", "gemma-3-27b-it-Q8_0.gguf"),
      ("contains", "mmproj")]),
    ("devstral-2", "Devstral-2 123B",
     "unsloth/Devstral-2-123B-Instruct-2512-GGUF",
     [("prefix", "Q4_K_M/")]),
    ("qwen3-vl-32b", "Qwen3-VL-32B",
     "Qwen/Qwen3-VL-32B-Instruct-GGUF",
     [("exact", "Qwen3VL-32B-Instruct-Q8_0.gguf"),
      ("contains", "mmproj")]),
    ("qwen3-8b", "Qwen3-8B",
     "Qwen/Qwen3-8B-GGUF",
     [("exact", "Qwen3-8B-Q8_0.gguf")]),
    ("qwen3-embedding-8b", "Qwen3-Embedding-8B",
     "Qwen/Qwen3-Embedding-8B-GGUF",
     [("exact", "Qwen3-Embedding-8B-Q8_0.gguf")]),
    ("inkling-2-mini", "Inkling-2-Mini",
     "ggml-org/Inkling-2-Mini-GGUF",
     [("exact", "Inkling-2-Mini-Q8_0.gguf"),
      ("contains", "mmproj")]),
    ("ripple-65b", "Ripple-65B-Preview",
     "AtomicChat/Ripple-65B-Preview-GGUF",
     [("contains", "Q8_0")]),
    ("bonsai-2.5-27b", "Bonsai 2.5 27B",
     "prism-ml/Ternary-Bonsai-2.5-27B-GGUF",
     [("exact", "Ternary-Bonsai-2.5-27B-PQ2_0.gguf")]),
    # Halogen 专用模型（.hgn 格式，不跑 llama.cpp，跑 halogen-flash-server）。
    # 注意：下载脚本把文件扁平化存到 <dest>/<slug>/<basename>，tokenizer/
    # 下的 6 个文件会落在模型目录根部，部署 Halogen 前需手动把它们移进
    # tokenizer/ 子目录（见 README）。
    ("halogen-qwen3.8-flash-next", "Qwen 3.8 Flash Next (Halogen)",
     "peonist-ai/halogen-qwen3.8-flash-next",
     [("exact", "qwen38-flash-next-v2.hgn"),
      ("exact", "qwen38-flash-next-ngram.hgn"),
      ("exact", "qwen38-flash-next-drafter-r2-ht4.hgn"),
      ("exact", "qwen38-flash-next-vision.hgn"),
      ("prefix", "tokenizer/")]),
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "manifest-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def match(path, kind, pat):
    if kind == "exact":
        return path == pat
    if kind == "prefix":
        return path.startswith(pat) and path.endswith(".gguf")
    if kind == "contains":
        return pat in path and path.endswith(".gguf")
    return False


def main():
    manifest = {"generated": "2026-11-26", "models": []}
    grand_total = 0
    problems = []
    for slug, name, repo, wanteds in MODELS:
        try:
            meta = get_json("https://huggingface.co/api/models/%s" % repo)
            gated = bool(meta.get("gated"))
        except Exception as e:
            print("META FAIL %s: %s" % (repo, e))
            gated = None
        try:
            tree = get_json(
                "https://huggingface.co/api/models/%s/tree/main?recursive=true" % repo)
        except Exception as e:
            print("TREE FAIL %s: %s" % (repo, e))
            problems.append((slug, "tree fetch failed: %s" % e))
            continue
        if isinstance(tree, dict) and "error" in tree:
            print("TREE ERR %s: %s" % (repo, tree["error"]))
            problems.append((slug, "tree error: %s" % tree["error"]))
            continue
        files_by_path = {}
        for x in tree:
            if x.get("type") == "file" and x.get("path", "").endswith(".gguf"):
                lfs = x.get("lfs") or {}
                files_by_path[x["path"]] = {
                    "size": x.get("size", 0),
                    "sha256": lfs.get("oid"),
                }
        picked = []
        for kind, pat in wanteds:
            hits = [(p, v) for p, v in files_by_path.items()
                    if match(p, kind, pat)]
            if not hits:
                problems.append((slug, "no match for %s %r" % (kind, pat)))
            for p, v in sorted(hits):
                picked.append({"path": p, "size": v["size"],
                               "sha256": v["sha256"]})
        # de-dup (a file could match two patterns)
        seen = set()
        uniq = []
        for f in picked:
            if f["path"] not in seen:
                seen.add(f["path"])
                uniq.append(f)
        total = sum(f["size"] for f in uniq)
        grand_total += total
        missing_sha = [f["path"] for f in uniq if not f["sha256"]]
        if missing_sha:
            problems.append((slug, "missing sha256 for %s" % missing_sha))
        manifest["models"].append({
            "slug": slug, "name": name, "repo": repo, "gated": gated,
            "files": uniq, "size": total,
        })
        print("%-22s %2d files %8.2f GB  gated=%s" % (
            slug, len(uniq), total / 1e9, gated))
        for f in uniq:
            print("    %s  %.2f GB  sha256=%s" % (
                f["path"], f["size"] / 1e9, (f["sha256"] or "?")[:12]))
    manifest["total_size"] = grand_total
    manifest["total_files"] = sum(len(m["files"]) for m in manifest["models"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("TOTAL: %d files, %.2f GB" % (
        manifest["total_files"], grand_total / 1e9))
    if problems:
        print("PROBLEMS:")
        for slug, msg in problems:
            print("  %s: %s" % (slug, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
