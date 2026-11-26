# Strix Halo 395 模型下载

一次下载 18 个模型（39 个文件，共 948.81GB），给 395 128GB 机器跑 llama.cpp 用。清单（大小、sha256）已逐文件对 Hugging Face 核实，下载完逐个校验。

macOS 和 Ubuntu 都能跑：下载脚本是 Python 3 + aria2c，启动脚本会自动按系统选命令（挂载检查、局域网 IP 显示都是跨平台的）。区别只在装软件的方式和目标盘的挂载点。

## 文件

- `download-models.py`：下载脚本（Python 3 标准库 + aria2c）
- `manifest.json`：下载清单，必须和脚本放同一目录
- `runwisp.toml`：RunWisp 启动配置
- `start-download.sh`：通过 RunWisp 启动 / 停止 / 查看下载

## 准备（macOS）

装好 aria2 和 RunWisp（RunWisp 不在 Homebrew 主仓库，在官方 tap 里）：

```bash
brew install aria2
brew install runwisp/tap/runwisp
```

插上外接 SSD（exFAT，至少留出约 950GB），确认挂载在 `/Volumes/llms`。目标盘不是这个挂载点时，改 `runwisp.toml` 里 `run` 那行的 `--dest` 即可（启动脚本会从那里读）；不想改文件时也可以启动前加 `DOWNLOAD_DEST=/Volumes/你的盘/models` 临时覆盖。

## 准备（Ubuntu）

### 装 aria2 和 RunWisp

```bash
sudo apt update && sudo apt install aria2
```

RunWisp 没有 apt 包，从 GitHub Releases 下 Linux 版（395 是 x86_64，用 linux-x64；去 Releases 页确认一下最新版本号，这里以 v1.11.0 为例）：

```bash
cd /tmp
curl -fsSL -O https://github.com/runwisp/runwisp/releases/download/v1.11.0/runwisp-linux-x64.tar.gz
tar xzf runwisp-linux-x64.tar.gz
sudo install -m 0755 runwisp /usr/local/bin/runwisp
runwisp -v
```

Python 3 是 Ubuntu 预装的，不用另装。

### 格式化磁盘（只在新盘 / 需要重格时做）

**如果这块盘已经在 Mac 上格式化好、里面已经有下载好的模型，整节跳过，直接去挂载。** 下面这些命令会清空整块盘，格错盘数据就没了，千万别对已有数据的盘跑。

先确认是哪块盘。认盘看三点：大小、挂载点、分区结构：

```bash
lsblk -o NAME,SIZE,TYPE,MODEL,MOUNTPOINT
```

- 系统盘：上面挂着 `/` 和 `/boot/efi`，别碰。
- Windows 盘：能看到 100M EFI + 16M 保留分区 + 大容量 C 盘 + 恢复分区，别碰。
- 模型盘：1TB 左右、没有挂载点。Mac 上格好的盘一般是两个分区：一个 200M 左右的 EFI 分区（Mac 格式化时自动建的，不用管）+ 一个约 954G 的 exFAT 数据分区（这才是要挂的）。

设备名分两种写法：SATA/USB 盘是 `/dev/sdX`（分区是 `/dev/sdb1`），NVMe 盘是 `/dev/nvmeXnY`（分区是 `/dev/nvme1n1p2`，注意 `p` 后面的数字才是分区号）。下面命令里的 `/dev/sdb`、`/dev/sdb1` 只是示例，换成你那块盘实际的设备名；NVMe 盘就换成 `/dev/nvme1n1`、`/dev/nvme1n1p2` 这种形式。

装格式化工具，然后建 GPT 分区表 + 一个占满整盘的分区，再格成 exFAT：

```bash
sudo apt install exfatprogs
sudo parted /dev/sdb --script mklabel gpt mkpart primary 0% 100%
sudo mkfs.exfat /dev/sdb1
```

说明：`--script` 让 parted 不经确认直接执行，所以格之前务必先用 `lsblk` 认准盘；`mkpart primary 0% 100%` 是占满整盘的一个分区（百分比写法自动对齐）；`exfatprogs` 提供 `mkfs.exfat`（Ubuntu 24.04 在 Universe 仓库，默认已启用，找不到时先 `sudo add-apt-repository universe`）。exFAT 没有日志，拔盘前务必先卸载（见下面），否则容易丢数据。

### 挂载磁盘

先确认要挂的是哪个分区。Mac 上格好的盘有两个分区：200M 左右的 EFI 分区（不用管）和约 954G 的 exFAT 数据分区（要挂的是这个）。用 `lsblk -f` 看文件系统类型，确认是 exFAT，同时拿到 UUID（比设备名稳，插拔顺序变了也不会认错盘）：

```bash
lsblk -f /dev/nvme1n1p2
```

上面 `/dev/nvme1n1p2` 是 NVMe 盘的例子（1TB 模型盘的第二个分区）；SATA/USB 盘则对应 `/dev/sdb1` 这种形式，换成你实际的设备名。输出里 `FSTYPE` 一列应该是 `exfat`，同时记下 `UUID` 那一串字符，后面写 fstab 要用。

建挂载点并手动挂一次验证（`uid`/`gid` 换成你自己的，`id -u` / `id -g` 查，默认都是 1000）：

```bash
sudo mkdir -p /mnt/llms
sudo mount -o uid=1000,gid=1000,umask=0022 /dev/nvme1n1p2 /mnt/llms
df -h /mnt/llms
touch /mnt/llms/.wtest && rm /mnt/llms/.wtest
```

挂完验证模型都在：

```bash
ls /mnt/llms/models
```

应该能看到之前下好的模型文件夹。`uid`/`gid`/`umask` 不能省：exFAT 不存 Unix 属主，不加这两个参数挂出来的盘是 root 的，普通用户写不进去，下载脚本会报权限错。上面 `df` 确认挂上了、`touch` 确认当前用户能写。

手动挂载重启就没了。想每次开机自动挂，把下面一行加进 `/etc/fstab`（UUID 换成你那块盘的，`uid`/`gid` 换成你自己的）：

```
UUID=XXXX-XXXX /mnt/llms exfat defaults,nofail,uid=1000,gid=1000,umask=0022,x-systemd.device-timeout=10 0 0
```

注意：exFAT 的 UUID 本来就只有 8 位（`XXXX-XXXX` 这种形式），`lsblk -f` 显示的那一小段就是完整的，不是被截断了。exFAT 没有 ext4 那种 36 位的长 UUID，Linux 是拿卷序列号拼出这 8 位来用的，fstab 里直接照抄这一小段就行，别自己补成 36 位。

`nofail` 是关键：盘没插时开机不会卡住（没有它，开机等不到这块盘会进紧急模式）。改完不用重启就能验证：

```bash
sudo systemctl daemon-reload
sudo mount -a
df -h /mnt/llms
```

拔盘前先卸载：

```bash
sudo umount /mnt/llms
```

（桌面版 Ubuntu 插上 exFAT 盘也可能自动挂到 `/media/<用户名>/<卷标>`，但那个挂载点不固定，不适合当下载目标；固定走 `/mnt/llms` + fstab 最稳。）

### 改目标目录

`runwisp.toml` 里 `run` 那行的 `--dest` 改成 Ubuntu 的挂载点：

```
run = "python3 ./download-models.py --dest /mnt/llms/models"
```

或启动前用 `DOWNLOAD_DEST=/mnt/llms/models ./start-download.sh` 临时覆盖（脚本会把它写回 runwisp.toml）。

## 启动

```bash
./start-download.sh
```

脚本会校验配置、拉起 RunWisp daemon（没跑的话）、触发下载，然后立即返回（不占命令行，下载在 daemon 手下后台跑）。进度在 Web UI 看：本机 http://127.0.0.1:9477，局域网另一台设备用 http://<这台机器的局域网 IP>:9477（daemon 默认监听 0.0.0.0，即全部网卡；只想本机访问时 `RUNWISP_HOST=127.0.0.1 ./start-download.sh`）。想在终端里看实时输出用 `./start-download.sh logs`。脚本自己的详细日志在目标盘的 `.logs/` 目录。

RunWisp 自己的数据（数据库、日志、控制 socket）放在 `~/.runwisp`（内置盘），因为 exFAT 不支持 Unix socket；下载本身仍写到外接盘的 `models/`，不受影响。Web UI 的密码：没设 `RUNWISP_PASSWORD` 时每次启动随机生成，用 `runwisp password -c runwisp.toml --data ~/.runwisp` 查看；想固定密码就启动前加 `RUNWISP_PASSWORD=你的密码 ./start-download.sh`。注意：0.0.0.0 会把 Web UI 暴露给整个局域网，务必设一个固定密码（Web UI 能启停任务，不设密码等于把控制权交给局域网里的任何人）；想上 HTTPS 可在 `runwisp.toml` 的 `[daemon]` 里加 `tls = "auto"`（自签证书，浏览器会报证书警告，点继续即可）。

### 环境变量

启动脚本支持下面这些环境变量，不设就用默认值：

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `DOWNLOAD_DEST` | 目标目录（下载到哪） | `runwisp.toml` 里 run 行的 `--dest` |
| `RUNWISP_HOST` | Web UI 监听地址 | `0.0.0.0`（全部网卡） |
| `RUNWISP_PORT` | Web UI 端口 | `9477` |
| `RUNWISP_DATA` | RunWisp 自己的数据目录 | `~/.runwisp` |
| `RUNWISP_PASSWORD` | Web UI 密码 | 不设则每次启动随机生成 |

一次指定多个时，把它们用空格隔开、都写在命令前面，只写需要改的就行，没写的用默认值：

```bash
DOWNLOAD_DEST=/mnt/llms/models RUNWISP_HOST=0.0.0.0 RUNWISP_PORT=9477 RUNWISP_PASSWORD=你的密码 ./start-download.sh
```

注意两点：`DOWNLOAD_DEST` 设了之后脚本会把它写回 `runwisp.toml` 的 `--dest`，下次不加这个变量也会沿用这个目录；`RUNWISP_PASSWORD` 是 RunWisp daemon 自己读的（脚本不直接读），所以必须在启动脚本前设好才生效。

不经过 RunWisp、直接跑也可以：

```bash
python3 download-models.py --dest /Volumes/llms/models   # macOS
python3 download-models.py --dest /mnt/llms/models       # Ubuntu
```

## 停止与续传

```bash
./start-download.sh stop     # 停止，等同于按 Ctrl+C
./start-download.sh status   # 看状态
./start-download.sh logs     # 看实时输出
./start-download.sh restart  # 重启 daemon（改了监听地址/端口后用，
                             # reload 改不了这两个），下载从断点续传
```

随时都能停，重跑自动从断点续传，已下完的文件按大小跳过。启动命令本身不阻塞：它只触发任务就返回，下载在 daemon 手下后台跑；要停必须用 `stop` 或 Web UI。

## 注意事项

- 全程约 24 小时（按 100Mbps 线持续 11MB/s 估算），无人值守：断网、0 速都会自动重试。
- 镜像优先走 ModelScope（37 个文件），Ripple 的 2 个文件走 hf-mirror；某个镜像挂了自动换下一个。
- 跑完会在目标目录生成一份 README.md，列了每个模型和 llama-server 的用法，插到 Ubuntu 上直接用。
- 盘在 macOS 和 Ubuntu 之间换着用没问题（exFAT 通用）：在 Mac 上下到一半，拔盘（先卸载）插到 Ubuntu 上继续跑，断点续传接着下，不用重下。
