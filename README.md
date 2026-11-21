# StereoAgent Studio

A local, professional image workflow agent for the CSIT998 group project. Natural-language requests are translated into bounded tool actions, executed against image versions, and checked by the backend.

**从 GitHub 下载源码的组员**，按 [Windows 安装说明和模型下载链接](docs/INSTALL_WINDOWS.md) 操作。先安装 2B，即可试用聊天和图片编辑。需要生成立体图片时，再安装立体依赖并从组内获取部署权重。

## Start

Double-click **`start.vbs`** (no console) or **`start.cmd`**. The desktop app starts the local model automatically. Closing the window exits the app and stops the model it owns.

For the bundled offline release, extract the whole folder to a writable location on **64-bit Windows 10 or 11**. That release already includes Electron, llama.cpp, Python, Qwen and the CUDA PyTorch models. Install a compatible NVIDIA driver for stereo generation.

Both local Qwen3-VL-2B-Instruct Q4 and Qwen3-VL-8B-Instruct Q4 are available in **Model & workspace**. The ZIP starts with 2B to reduce memory use. The selection is stored in `config.json`.

解压整个文件夹后双击 `start.cmd`。在输入框选图、粘贴或拖入图片，确认缩略图后输入文字并发送，例如「帮我生成右视图，启用细节补偿」。用户消息会同时显示图片和文字。右栏 **Images & Versions** 可选中原图或处理后的版本，输入框会显示下一条消息关联的图片。

也可在右侧选图后点击 **Generate stereo**。在 **Detail compensation** 选择补偿方式。竖图和其他非 7:4 画幅默认等比缩放后补边，也可手动选 **Center crop to 7:4**。结果里的 **Original right** 是同一次生成的无补偿右图，用 **Stereo view** 或预览箭头切换，用 **Export** 下载当前视图。

给组员试用时，可直接从 `demo_inputs/images` 选图。建议先用森林悬崖或山前角色，发送「帮我生成右图」。[测试图说明与来源](demo_inputs/README.md)

## What works in v0.1

- English three-column workspace: conversations, tool execution trace, active-image preview and version history.
- Attach one PNG, JPEG or WebP per message (up to 20 MB) by file picker, paste or drag and drop. The thumbnail stays in the draft until Send. Sent messages reference the saved image, and selecting a version in the inspector uses that image for the next request.
- Local image understanding and structured action planning.
- Current date/time queries read the OS clock in the configured `timeZone` (default `Asia/Shanghai`); general planning also receives a fresh timestamp. This build has no live web search, so current news/weather/prices cannot be verified online.
- Adaptive response depth: explanations can develop a topic, while simple facts and operation acknowledgements remain concise. Assistant paragraphs, lists, emphasis and code are rendered with a sanitised local Markdown pipeline.
- Pixel crop, resize with optional aspect-ratio preservation, clockwise rotation, saturation/brightness/contrast adjustment.
- Every edit produces a new version; select a version, undo, export PNG/JPG/WebP.
- Delete a conversation using the trash button beside its sidebar entry. An in-app confirmation is required. Deleting the last conversation creates a blank workspace. Local image/exported files are retained; running tasks block deletion.
- Open a conversation result, active image or version thumbnail to preview the full-resolution file. Use the wheel or +/− to zoom, **Original size** to reset to 100%, and **Download** to save the displayed image.
- Long conversations and workspace lists scroll independently; the composer and settings remain visible. Polling preserves manually scrolled history.
- Tool validation, explicit failure states, task cancellation, original preservation, persisted sessions/tasks and interrupted-run marking.
- Model start/stop/switch, loopback-only backend, and separate inference lifecycle.

Try these after uploading an image:

```text
左边裁剪掉20px，然后把饱和度提高10%。
Resize the current image to width 150 pixels, preserving aspect ratio.
撤销上一步缩放，回到之前的尺寸。
What is visible in this image? Do not edit it.
Export the current image as JPG.
```

Model-generated plans are fallible. Tool execution checks do not prove semantic correctness; inspect results. The current context uses active-image metadata and recent artifact lineage, rather than replaying unrestricted full conversation history.

## Stereo image generation

- Choose 448×256 or 896×512 pixels per eye. **Fit whole image** keeps the source proportions and adds borders as needed for the 7:4 canvas. **Center crop to 7:4** is also available. Both keep the source version.
- Asking the agent to generate a right view delivers the appearance-aligned compensated right image and a red/cyan anaglyph from the same run. **Generate stereo** in the inspector produces the full set of views. Switching or downloading a view uses the saved output.
- Detail compensation offers **Legacy high-frequency detail compensation** (default), **Appearance-aligned detail compensation**, and **No detail compensation**. Appearance-aligned detail compensation uses horizontal correspondence between the left image and the raw generated right view. Low and mid frequencies use weight 0.5, and the high-frequency difference uses weight 1.0, all scaled by correspondence confidence. It is a still-image option and can change measured disparity.
- The full set can also include **Original right**, a comparison from the same inference. Open any thumbnail and use the on-screen arrows or arrow keys to browse the saved outputs. For a right-view request, both the gallery and the job directory contain only the two requested image files.
- Try “帮我生成右视图” with a photo attached or selected. Select an individual left or right view for further image edits. Combined outputs such as SBS can be previewed and exported.
- The app releases its own chat model before starting stereo inference. The next chat request can load the model again. For a failed run, check the message and `data/stereo/<job-id>/adapter.log`.
- CUDA PyTorch is the default. The development copy also supports a TensorRT mode for compatible engines and hardware. The ZIP uses PyTorch so it can run without those engine files.
- This integration covers still images. Automatic evaluation of stereo quality, visual feedback and recovery, and video workflows are future work.

## Architecture

```text
Electron (isolated web UI)
  -> Node HTTP backend :17863
      -> local Qwen llama.cpp Vulkan :17864
      -> validated JSON action planner
      -> bounded tools -> Python Pillow -> version store
      -> bundled Mono2Stereo image generator
```

- `public/`: interface, CSS, client state/polling.
- `app/main.cjs`: Electron shell, lifecycle and single-instance handling.
- `server/agent.cjs`: prompt, plan validation, sequential execution and persisted traces.
- `server/model.cjs`: private local model process and JSON-schema-constrained responses.
- `server/tools.cjs`, `image_worker.py`: bounded tools and stereo adapter.
- `server/store.cjs`: workspace/artifact persistence in `data/workspace.json`.
- `models/`, `runtime/llama/`: local model and runtime downloads.
- [Windows installation](docs/INSTALL_WINDOWS.md) and [resource provenance](docs/PROVENANCE.md).

## Configuration

`config.json` uses paths relative to the extracted project directory. It specifies model selection, ports and the stereo backend. The backend binds to 127.0.0.1 and uses local models. Keep the extracted folder structure intact.

Model and backend listen on different ports from DesktopPetAgent. They do not share private session state. If a port is occupied, stop the owning app normally; do not kill unrelated processes.

## Verification

From a GitHub checkout after setup, use `.\stereo-runtime\setup-venv\Scripts\python.exe -IB scripts\check-env.py` to check the installed resources. In the full offline copy, the equivalent interpreter is `.\stereo-runtime\python\python.exe`.

With Node.js 24 installed, run `npm.cmd test` for the local backend tests. The desktop runtime from `setup.cmd` does not require a separate Node.js installation.

To use the web version instead of Electron: `npm.cmd run serve`, then open `http://127.0.0.1:17863`. Do not start this alongside the Electron app on the same ports. Stop the terminal server with Ctrl+C.

To build a fresh archive from the development copy, run `.\stereo-runtime\python\python.exe -IB scripts\package-windows.py --output dist\StereoAgentStudio-Windows-x64.zip`. Choose a new filename if it already exists. The ZIP excludes working conversations, local logs, course handouts, Git metadata and prebuilt TensorRT engines.

## Project scope and provenance

The long-term project combines image editing, efficient stereo generation/detail compensation, task planning, feedback checks and output management. Current v0.1 establishes the model and application framework. It is not the completed research contribution or final coursework system.

The GitHub checkout downloads public models and runtimes using the installation manifest. The project reuses the existing individual Mono2Stereo thesis implementation for stereo generation. See [resource provenance](docs/PROVENANCE.md).
