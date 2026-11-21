"""Build the offline Windows ZIP from the project's installed runtime."""
import argparse
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path("stereo-runtime")
PYTHON = BUNDLE / "python"
SITE = PYTHON / "Lib/site-packages"
PREFIX = "StereoAgentStudio/"

# Top-level dependencies of the image worker and the PyTorch stereo CLI.
PACKAGES = """
PIL accelerate anyio brotli certifi charset_normalizer click colorama contourpy
cv2 cycler dateutil diffusers exceptiongroup filelock fontTools fsspec h11
hf_xet httpcore httpx huggingface_hub idna imageio jinja2 kiwisolver lazy_loader
lz4 markdown_it markupsafe matplotlib mdurl mpmath networkx numpy numpy.libs
opt_einsum packaging peft psutil pygments pyparsing regex requests rich
safetensors scipy scipy.libs skimage sniffio socks sympy tifffile tokenizers
torch torchgen torchvision tqdm transformers triton typing_extensions urllib3
win32 win32com pywin32_system32 xformers yaml zstandard
""".split()
METADATA = {"pillow", "opencv_python", "opencv_python_headless", "python_dateutil",
            "lazy_loader", "pysocks", "scikit_image", "triton_windows", "pywin32", "pyyaml",
            "brotli", "charset_normalizer"}
NATIVE_DLLS = """
bzip2.dll deflate.dll ffi.dll ffi-7.dll ffi-8.dll freetype.dll lcms2.dll Lerc.dll libbz2.dll
libcrypto-3-x64.dll libexpat.dll libjpeg.dll liblzma.dll libpng16.dll
libsharpyuv.dll libssl-3-x64.dll libwebp.dll libwebpdecoder.dll libwebpdemux.dll
libwebpmux.dll libzstd.dll libiomp5md.dll mkl_rt.2.dll mkl_core.2.dll mkl_def.2.dll
mkl_avx2.2.dll mkl_avx512.2.dll mkl_intel_thread.2.dll mkl_sequential.2.dll
openjp2.dll sqlite3.dll tiff.dll yaml.dll zlib.dll zstd.dll
""".split()
EXCLUDED_DIRS = {".git", ".cache", "__pycache__"}


def files_under(relative):
    source = ROOT / relative
    if source.is_file():
        yield relative
        return
    if not source.is_dir():
        raise FileNotFoundError(source)
    for item in source.rglob("*"):
        parts = item.relative_to(source).parts
        if EXCLUDED_DIRS.intersection(parts):
            continue
        if (item.is_file() and item.name != "direct_url.json"
                and item.suffix.lower() not in {".pyc", ".pdb", ".log", ".ilk"}):
            yield item.relative_to(ROOT)


def runtime_files():
    base = ROOT / PYTHON
    for item in base.iterdir():
        if item.is_file() and (item.suffix == ".dll" or item.name in {"python.exe", "LICENSE_PYTHON.txt"}):
            yield item.relative_to(ROOT)
    yield from files_under(PYTHON / "DLLs")
    for item in (base / "Lib").iterdir():
        if item.name not in {"site-packages", "test", "turtledemo", "ensurepip", "idlelib", "__pycache__"}:
            yield from files_under(item.relative_to(ROOT))
    for name in NATIVE_DLLS:
        file = base / "Library/bin" / name
        if file.is_file():
            yield file.relative_to(ROOT)
    package_keys = {name.lower().replace("-", "_") for name in PACKAGES} | METADATA
    for item in (ROOT / SITE).iterdir():
        name = item.name
        stem = name.removesuffix(".py")
        if (stem in PACKAGES or name == "pywin32.pth"
                or re.fullmatch(r"(?:_brotli|\w+__mypyc)\.cp310-win_amd64\.pyd", name)):
            yield from files_under(item.relative_to(ROOT))
        if name.endswith(".dist-info"):
            distribution = re.sub(r"-[0-9].*$", "", name[:-10]).lower()
            if distribution in package_keys:
                yield from files_under(item.relative_to(ROOT))
    for required in ("PIL", "torch/lib", "diffusers", "transformers"):
        if not (ROOT / SITE / required).is_dir():
            raise FileNotFoundError(ROOT / SITE / required)


def bundle_files():
    for relative in (
        "app", "server", "public", "start.cmd", "start.vbs", "package.json", "README.md",
        "docs/PROVENANCE.md", "docs/resource-manifest.json", "demo_inputs", "models", "runtime/llama",
        "node_modules/electron/dist", "scripts/check-env.py",
        BUNDLE / "assets/weights/mono2stereo_runtime_fp16.pt",
        BUNDLE / "models/mono2stereo/sd2-base-fp16",
        BUNDLE / "scripts/run_mono2stereo_tensorrt_image.py",
        BUNDLE / "scripts/run_mono2stereo_tensorrt_video_gate.py",
        BUNDLE / "scripts/pilot_mono2stereo_condition_adapter.py",
        BUNDLE / "scripts/mono2stereo_runtime_utils.py",
        BUNDLE / "scripts/stereo_postprocess.py",
        BUNDLE / "scripts/cvdc_alignment_v3.py",
        BUNDLE / "scripts/cvdc_refined.py",
        BUNDLE / "scripts/cvdc_visible_fusion.py",
        BUNDLE / "scripts/cvdc_multiband_geometry.py",
        BUNDLE / "third_party/Mono2Stereo/README.md",
        BUNDLE / "third_party/Mono2Stereo/depth/depth_anything_v2",
        BUNDLE / "third_party/Mono2Stereo/depth/checkpoints/depth_anything_v2_vits.pth",
        BUNDLE / "third_party/Mono2Stereo/marigold",
    ):
        yield from files_under(Path(relative))
    yield from runtime_files()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/StereoAgentStudio-Windows-x64.zip")
    args = parser.parse_args()
    archive = args.output.resolve()
    if archive.exists():
        parser.error(f"Output already exists: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config.update(model="2b", autoStartModel=True, stereoEnabled=True, stereoBackend="pytorch",
                  python="stereo-runtime/python/python.exe", stereoRoot="stereo-runtime",
                  stereoPython="stereo-runtime/python/python.exe")
    files = sorted(set(bundle_files()))
    partial = archive.with_suffix(".zip.partial")
    print(f"Writing {len(files):,} files to {archive}", flush=True)
    with zipfile.ZipFile(partial, "x", allowZip64=True) as output:
        output.writestr(PREFIX + "config.json", json.dumps(config, indent=2) + "\n")
        for relative in files:
            file = ROOT / relative
            compression = zipfile.ZIP_DEFLATED if file.stat().st_size < 32 * 1024**2 else zipfile.ZIP_STORED
            output.write(file, PREFIX + relative.as_posix(), compress_type=compression, compresslevel=1)
    partial.rename(archive)
    print(f"Ready: {archive.stat().st_size:,} bytes", flush=True)


if __name__ == "__main__":
    main()
