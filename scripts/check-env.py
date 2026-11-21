import importlib.util
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
config_path = root / "config.json"
if not config_path.is_file():
    sys.exit("Run setup.cmd first. See docs/INSTALL_WINDOWS.md.")
config = json.loads(config_path.read_text(encoding="utf-8"))
model_files = {
    "2b": ("Qwen3VL-2B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"),
    "8b": ("Qwen3-VL-8B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3-VL-8B-Instruct-F16.gguf"),
}
model, projector = model_files[config["model"]]
checks = {
    "Pillow": bool(importlib.util.find_spec("PIL")),
    "Electron": (root / "node_modules/electron/dist/electron.exe").is_file(),
    "llama.cpp": (root / "runtime/llama/llama-server.exe").is_file(),
    model: (root / "models" / model).is_file(),
    projector: (root / "models" / projector).is_file(),
    "Configured Python": (root / config["python"]).is_file(),
}
if config["stereoEnabled"]:
    stereo = root / config["stereoRoot"]
    checks.update({
        "Mono2Stereo checkpoint": (stereo / "assets/weights/mono2stereo_runtime_fp16.pt").is_file(),
        "SD2 base model": (stereo / "models/mono2stereo/sd2-base-fp16/model_index.json").is_file(),
        "Depth Anything weights": (stereo / "third_party/Mono2Stereo/depth/checkpoints/depth_anything_v2_vits.pth").is_file(),
        "PyTorch package": bool(importlib.util.find_spec("torch")),
    })
for name, ok in checks.items():
    print(("OK   " if ok else "FAIL ") + name)
print("Stereo generation enabled:", config["stereoEnabled"])
sys.exit(0 if all(checks.values()) else 1)
