# Windows 安装说明

适用于 Windows 10 或 11 x64。打开 [项目仓库](https://github.com/IrisOnMars/StereoAgentStudio)，点击 **Code → Download ZIP**，或用 Git 克隆。下载源码无需登录。把文件解压到可写目录再运行。

1. 安装 [Python 3.11 x64](https://www.python.org/downloads/release/python-3119/)，安装时保留 Python Launcher。已有 64 位 Python 3.11 可以复用。
2. 首次双击 `setup.cmd`。它会把 Electron、llama.cpp、Qwen 2B 和 Pillow 安装到项目目录，公开模型和安装包按 SHA-256 校验。约下载 **1.75 GB**，另有少量 Python 依赖。
3. 完成后双击 `start.cmd`。选一张 [测试图](../demo_inputs/README.md)，可以先问「描述一下这张图」或试用图片编辑。

下载中断后可以重新运行 `setup.cmd`。支持续传的下载源会接着已有的临时文件下载。下载完成的文件会复用。如果 GitHub 或 Hugging Face 下载较慢，可以用下面的备用链接手动下载再运行安装脚本。

## Qwen 下载链接

两个文件都要下载，保持下表的保存名，放入项目的 `models/`。下表的主下载源固定到项目已核对的版本。

| 配置 | 文件及下载 | 大小 |
| --- | --- | ---: |
| 2B 主模型 | [Qwen3VL-2B-Instruct-Q4_K_M.gguf](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/52d6c8ffea26cc873ac5ad116f8631268d7eb503/Qwen3VL-2B-Instruct-Q4_K_M.gguf) · [魔搭](https://modelscope.cn/models/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/master/Qwen3VL-2B-Instruct-Q4_K_M.gguf) | 1.11 GB |
| 2B 视觉投影 | [mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/52d6c8ffea26cc873ac5ad116f8631268d7eb503/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf) · [魔搭](https://modelscope.cn/models/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/master/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf) | 445 MB |
| 可选 8B 主模型 | [Qwen3-VL-8B-Instruct-Q4_K_M.gguf](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF/resolve/b93a7ee713758252c555be4210c00540df954dc2/Qwen3-VL-8B-Instruct-Q4_K_M.gguf) | 5.03 GB |
| 可选 8B 视觉投影 | [mmproj-F16.gguf](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF/resolve/b93a7ee713758252c555be4210c00540df954dc2/mmproj-F16.gguf)，保存为 `mmproj-Qwen3-VL-8B-Instruct-F16.gguf` | 1.16 GB |

在 PowerShell 里运行 `.\setup.cmd --model 8b` 可以直接安装并选中 8B。以 2B 测试时无需下载这两个可选文件。

软件包也可手动下好再放到项目的 `.setup-downloads/`

- [Electron v45.0.0 Windows x64](https://github.com/electron/electron/releases/download/v45.0.0/electron-v45.0.0-win32-x64.zip) · [同版备用源](https://registry.npmmirror.com/-/binary/electron/v45.0.0/electron-v45.0.0-win32-x64.zip)
- [llama.cpp b11928 Windows x64 Vulkan](https://github.com/ggml-org/llama.cpp/releases/download/b11928/llama-b11928-bin-win-vulkan-x64.zip)

## 开启立体生成

需要支持 CUDA 12.8 的 NVIDIA 显卡和驱动。给安装和模型文件留至少 **15 GB** 可用空间。

1. 从项目负责人拿到组内部署权重 `mono2stereo_runtime_fp16.pt`（**1.73 GB**），放到 `stereo-runtime/assets/weights/mono2stereo_runtime_fp16.pt`。该文件不在仓库中。已有权重可以复用，校验值为 `9005a0edf54c9f412721a79953cd7d17553c119581db098b1b02d2cdd397daae`。
2. 在项目目录的 PowerShell 运行 `.\setup.cmd --stereo`。首次开启会下载约 **5.5 GB** 的公开模型和依赖（不含 Qwen），并检查 CUDA。
3. 启动或重开 Agent。用 `demo_inputs/images/01-forest-cliff.png`，发送「帮我生成右图」，检查补偿右图和红青色差图。

公开立体依赖来自 [Stable Diffusion 2.1 Base FP16](https://huggingface.co/sd2-community/stable-diffusion-2-1-base/tree/4e63672c03103b6c636b8fb4119ba982469b2955)、[Depth Anything V2 Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/03876f8651c73a60fe4c2c48294e09fcb6838fcf/depth_anything_v2_vits.pth)、[Mono2Stereo 上游代码](https://github.com/song2yu/Mono2Stereo/tree/613d41329edfc20452c4085891ab8b4b0901a9b1)和 [PyTorch CUDA 12.8](https://download.pytorch.org/whl/cu128/)。安装清单列出了每个文件的保存位置和校验值。上游公开的 10.39 GB 原始 checkpoint 和组内部署版是不同文件，不能直接改名代替。 [文件清单](../scripts/windows-downloads.json)

仓库里的源码和测试图可以直接下载。`config.json`、模型、运行库、对话数据和日志都保存在各自电脑。
