# Resource and implementation provenance

Date: 2026-11-04.

## Copied from DesktopPetAgent

Origin: the local DesktopPetAgent development project. The origin was inspected read-only. Its private settings, conversations, sessions, character assets, CSS, Electron UI and running model service were not copied or modified.

- `models/*.gguf`: local Qwen3-VL-2B-Instruct Q4 + Q8 visual projector and Qwen3-VL-8B-Instruct Q4 + F16 visual projector. These are existing downloaded model resources, not models trained in this project.
- `runtime/llama/`: copied llama.cpp b11928 Windows Vulkan distribution, including its existing dependency licence files. The model service runs on a separate owned port/process.
- `node_modules/`: copied installed dependency tree, including Electron 45 and upstream package licence files. The root lockfile was copied and renamed for this project.
- `server/generation.cjs`: existing repetition-detection helper, originally `app/generation.cjs`.

`resource-manifest.json` records destination file sizes and SHA-256 values for the four models, model server executable and copied helper. It is a local resource inventory, not an independent provenance audit of upstream model contents.

## Newly implemented here

- Professional English three-column workspace and settings UI.
- Local HTTP backend, workspace/artifact/task store, Electron lifecycle.
- Schema-constrained image action planner and checked sequential tool execution.
- Python Pillow worker for imports, transformations and format export.
- Non-destructive version history, undo, task traces, cancellation and explicit errors.
- Bounded stereo adapter with a PyTorch runtime option, linked output versions and format selection without another inference run.
- Backend, UI, model and lifecycle smoke checks; project documentation.

## Existing individual stereo work

`stereo-runtime/` contains selected copies of the existing individual Mono2Stereo thesis implementation. Reused resources include its image CLI, model-loading and warping code, detail compensation, optimized checkpoint, SD2 base components, and Depth Anything V2 Small. The original thesis project now also exposes the optional image postprocess. Its architecture, acceleration, CVDC and prior results predate the group project. The project-level work includes integration, portability, version tracking, output selection and validation. Confirm coursework reuse terms with the supervisors.

The appearance-aligned detail compensation option uses the thesis experiment's appearance-aligned multiband branch (`flow_band`). It reuses the thesis project's correspondence, confidence and frequency reconstruction code, with the recorded 0.5/0.5/1.0 band weights. The app invokes this method from its bundled runtime.

The copied Windows Python 3.10 runtime includes CUDA PyTorch 2.12 nightly (CUDA 12.8) and its image/model dependencies. The share archive uses a selected runtime subset. The development copy contains optional prebuilt TensorRT plans.

## Course documents

Three supplied course PDFs are kept in the local development tree for project context. They are excluded from the GitHub and offline distributions.

## Upstream reference links

- Qwen3-VL: https://github.com/QwenLM/Qwen3-VL
- llama.cpp: https://github.com/ggml-org/llama.cpp
- Electron: https://github.com/electron/electron
- Pillow: https://github.com/python-pillow/Pillow
- Mono2Stereo: https://github.com/song2yu/Mono2Stereo
- Depth Anything V2: https://github.com/DepthAnything/Depth-Anything-V2
- PyTorch: https://github.com/pytorch/pytorch

Check actual model/software/data licence terms before redistribution or deployment. This milestone does not relicense the copied upstream assets or personal thesis work.
The upstream `song2yu/Mono2Stereo` repository did not expose a licence via its GitHub licence endpoint at the time of this build. The linked upstream checkpoint card uses a custom licence label. Verify the licence that applies to both the code and the checkpoint before forwarding the archive. Also retain the applicable notices for the SD2 base weights.
