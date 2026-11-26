# 395 模型总表 — Ryzen AI Max+ 395（128GB）可运行模型总览

体积已对 Hugging Face 实测复核；耗时按 100 Mbps（持续约 11 MB/s）换算；评测分中带 `*` 为厂商自报、无独立复核，详见「说明与注意事项」。空白 = 未查到该项得分，不代表 0 分。

使用方法：按推荐 / 场景挑模型。16 个 llama.cpp 模型全下约 716 GB。（2026-11-27 删 MiniMax M2.5 与 Qwen2.5-Coder-32B，见「说明与注意事项」。）Halogen 专用的 Qwen 3.8 Flash Next 另见「Halogen 专用模型」一节，不在评测分表里。

## 可运行模型（16 个）

| 推荐 | 模型名称 | 架构 | 优势场景 | SWE-bench (%) | Aider (%) | LiveCodeBench (%) | GPQA (%) | AIME (%) | 量化 | 体积 (GB) | 预计耗时（分钟） | 预计耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | Qwen3-Coder-Next 80B | MoE | agentic 写码旗舰 | 70.6 | 66.2 | 58.9 | 74.5 | 83.1 | Q8_0 | 84.8 | 128 | 2h08m |
| A | Qwen3.5-122B-A10B | MoE | 长上下文全能 | 72.0 |  | 78.9 | 86.6 |  | Q4_K_M | 76.5 | 115 | 1h55m |
| A | gpt-oss-120b | MoE | 推理 / 工具调用 | 62.4 | 41.8 | 87.8 | 80.1 | 92.5 | MXFP4 | 63.4 | 96 | 1h36m |
| A | Devstral-2 123B | dense | 软件工程 agent | 72.2* |  | 44.8 | 59.4 | 36.7 | Q4_K_M | 74.9 | 113 | 1h53m |
| A | Inkling-2-Mini | MoE | 轻量 agentic / 1M 上下文 | 79.2* |  |  | 86.6 |  | Q8_0 | 27.8 | 42 | 42m |
| A | Ripple-65B-Preview | dense | 终端写码 / 1M 上下文 | 76.5* |  |  | 85.2 | 98.3* | Q8_0 | 68.8 | 104 | 1h44m |
| A | Qwen3-Coder-30B-A3B | MoE | 日常写码主力 | 51.6 | 33.3* | 40.3 | 51.6 | 29.0 | Q8_0 | 32.5 | 49 | 49m |
| A | GLM-4.7-Flash | MoE | 轻量写码 | 59.2* |  | 64.0* | 75.2* | 91.6* | Q6_K_L | 25.0 | 37 | 37m |
| A | Bonsai 2.5 27B | dense | 7GB 的 agentic 写码 | 75.6* |  | 83.0* | 87.7* |  | PQ2_0 | 7.3 | 10 | 10m |
| A | Qwen3-235B-A22B | MoE | 通用旗舰 | 42.0 | 57.3 | 51.8 | 77.5 | 70.3 | Q3_K_M | 107.3 | 162 | 2h42m |
| A | Qwen3-30B-A3B | MoE | 日常通用助手 |  | 35.6 | 43.2 | 70.4 | 61.3 | Q8_0 | 32.5 | 49 | 49m |
| B | Qwen3-32B | dense | dense 推理 | 23.4 | 40.0 | 65.7 | 68.4 | 72.9 | Q8_0 | 34.8 | 52 | 52m |
| B | Gemma-3-27B-it | dense | 多语言 + 视觉 |  | 4.9 | 29.7 | 42.4 | 20.7 | Q8_0 | 28.7 | 43 | 43m |
| B | Qwen3-8B | dense | 快速小模型 |  |  | 57.5 | 62.0 | 67.3 | Q8_0 | 8.7 | 13 | 13m |
| 小众 | Qwen3-VL-32B | dense | 视觉 / OCR / GUI |  |  | 51.4 | 67.1 | 68.3 | Q8_0 | 34.8 | 52 | 52m |
| 小众 | Qwen3-Embedding-8B | dense | 检索 / RAG |  |  |  |  |  | Q8_0 | 8.1 | 12 | 12m |
| 合计 |  |  |  |  |  |  |  |  |  | 716 | 1077 | 17h57m |

注：SWE = SWE-bench，LCB = LiveCodeBench，GPQA 多为 Diamond 口径（个别官方未明确，见说明）。带 `*` 的分数为厂商自报、无独立复核，横向比较时需打折看。

## 装不下的 4 个模型 — 不要浪费时间下载

以下模型即使取最小可用量化也超过 128GB 内存可用范围（或没有 KV cache 余量），不纳入下载清单。

| 模型名称 | 架构 | 最小量化 | 体积 (GB) | SWE-bench (%) | 备注 |
| --- | --- | --- | --- | --- | --- |
| DeepSeek-V3.2 | MoE | IQ1_M | 149.1 | 73.1 | 最小量化已超 128GB |
| Kimi K2.5 | MoE | IQ1_S | 210.3 | 76.8 | K3 更大，466GB |
| Mistral-Large-3 | MoE | IQ1_S | 134.0 | 41.4 | 只超一点，但没留 KV 余量 |
| Llama-4-Maverick | MoE | Q4_K_M | 242.8 | 21.0 | 只有极端 2bit 以下才塞得下，质量损失大 |

## Halogen 专用模型 — Qwen 3.8 Flash Next（不跑 llama.cpp）

此模型不在上面两张表里：它是 Halogen 引擎专用的 `.hgn` 格式，不跑 GGUF、不用 llama.cpp，也没有 SWE-bench / Aider / LiveCodeBench 这套基准分（它的卖点是推理速度和长上下文，不是刷分）。2026-11-27 已加入下载清单（manifest.json），随 16 个 llama.cpp 模型一起下。

| 项目 | 内容 |
| --- | --- |
| 模型 | Qwen 3.8 Flash Next，125B MoE / 6B 激活，Qwen 3.8 这一代 |
| 引擎 | Halogen（闭源容器 `ghcr.io/peonist-ai/halogen-flash-server`，端口 8731，需 ROCm + `/dev/kfd` + `/dev/dri`） |
| 仓库 | `peonist-ai/halogen-qwen3.8-flash-next` |
| 文件（10 个，共 120.30GB） | 主模型 `qwen38-flash-next-v2.hgn` 66.69GB + n-gram 表 `qwen38-flash-next-ngram.hgn` 51.20GB + draft head `qwen38-flash-next-drafter-r2-ht4.hgn` 1.49GB + vision `qwen38-flash-next-vision.hgn` 0.90GB + `tokenizer/` 6 个小文件 |
| 上下文 | 原生 262,144 tokens，YaRN factor 4 可扩到约 1M |
| 实测速度 | Framework 社区同机实测（llama.cpp Vulkan b11344 基线）：prefill 约 7.2k tokens 2,001 t/s（llama.cpp 460）、约 28.8k 为 2,005 t/s（409）；decode 散文 65.8 t/s（31.4）、写代码 100.6 t/s（31.8）、复制类 145.8 t/s（31.7）。但 Sleeping Robots 实测在约 55k 深度上下文的 agent 场景下，调优过的 Nathanw llama.cpp 解码反快 17–70%，「2–4 倍」要打折看 |
| 部署前注意 | 下载脚本扁平化存放，tokenizer/ 的 6 个文件会落在模型目录根部，部署 Halogen 前需手动把它们移进 `tokenizer/` 子目录（命令在 README 的「Halogen 部署前」一节）；不要在下载未完成时移文件，否则会被判定缺失而重下 |

## 说明与注意事项

- **数据来源**：22 个模型逐个核实：官方 GGUF 仓库与推荐量化、Hugging Face 上实测文件大小、SWE-bench / Aider / LiveCodeBench / GPQA / AIME 原始出处得分。拿不到的留空，未编造。体积在成表前又对 HF API 逐个复核过一遍。
- **`*` 的含义**：`*` = 厂商自报、无独立复核。11 月新出的三个（Inkling-2-Mini、Ripple-65B-Preview、Bonsai 2.5 27B）和 GLM-4.7-Flash、Devstral-2 的 SWE 分数都是官方口径，独立榜单跑出来一般更低（例如 Devstral-2 独立跑只有 53.8%，不是 72.2%）。Qwen3-Coder-Next 五项全出自官方技术报告，暂无独立榜单。
- **SWE-bench 注意**：SWE-bench 很看脚手架（harness），同一模型换个 harness 能差 20 个点，不要只盯这一个数横向排名。
- **GPQA 口径**：GPQA 一列里有几个官方只写了 GPQA、没明确 Diamond（Qwen3-Coder-Next、Qwen3-235B-A22B、GLM-4.7-Flash、Qwen3-30B-A3B），按 Diamond 理解会有小出入。
- **2026-11-27 删除的两个模型**：MiniMax M2.5 与 Qwen2.5-Coder-32B 已从本表与下载清单（manifest.json）中移除。MiniMax M2.5 虽 SWE-bench 分数最高（80.2%），但 Q3_K_M 在 128GB 上只能开 8–16K 上下文，满 196K 跑不了，速度也慢，且已被 M2.7 / M3 取代；Qwen2.5-Coder-32B 为老模型，写码角色已被 Qwen3-Coder 系列覆盖。用户决定只往前看，不为情怀保留。两者共 163.94GB，腾出的空间预留给 Halogen 的 Qwen 3.8 Flash Next（约 111GB）。
- **量化取舍**：表中 Qwen 三个写码模型取的是 Q8_0（质量优先）；此前下载脚本用的是 Q4_K_M（速度优先，解码快约一倍）。两个都装得下，下载方案里可按偏好选，或两个都下对比。
- **llama.cpp 版本要求**：Inkling-2-Mini 需 llama.cpp ≥ b12600；Ripple-65B-Preview ≥ b12167；Devstral-2 需 2025-12-12 之后合入 PR #17945 的构建；Qwen3.5-122B-A10B 需支持 qwen35moe 的构建；Bonsai 2.5 27B 的 PQ2_0 需 PrismML 自己的 llama.cpp fork，原版只能跑 Q2_0（7.67GB）。机器到手装 llama.cpp 时再逐个对版本。
- **下载耗时口径**：按 100 Mbps、持续约 11 MB/s 换算。16 个全下合计 716GB（表内口径，单量化）；逐个耗时取整后相加为 1,077 分钟（17h57m，见「可运行模型」表合计行），按总流量直接估算约 18 小时，差异来自逐项取整。下载清单（manifest.json，含 Qwen 三个写码模型的 Q4_K_M 对比版）为 33 个文件、784.87GB。用户现有 2×1TB + 1×2TB SSD，容量足够。
- **硬件前提**：机器：Ryzen AI Max+ 395 + 128GB，日常运行 Ubuntu。gpt-oss-120b 采用 MXFP4 约 63.4GB。此前结论：同配置下 Linux 性能优于 Windows（可用显存更多、RADV Vulkan 后端更快）。
- **下一步**：先在本表圈定要下载的模型，再按圈定清单出具体下载脚本 / 方案。
- **架构（MoE / dense）**：MoE = 混合专家，每 token 只激活一小部分参数（如 Qwen3-Coder-Next 为 80B 总参数 / 3B 激活），同等体积下解码更快，但全部权重仍须驻留内存；dense = 稠密模型，每 token 用全部参数。可运行 16 个中 MoE 8 个、dense 8 个；装不下的 4 个均为 MoE。这也呼应磁盘问题：MoE 每 token 实际读取的权重更少，对存储带宽更不敏感；用户的 SSD 均为 NVMe，模型放哪块盘对运行期性能影响很小。
