"""Install the Windows x64 GitHub checkout, with stereo as an optional step."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CACHE = ROOT / ".setup-downloads"
CHECKPOINT = ROOT / "stereo-runtime/assets/weights/mono2stereo_runtime_fp16.pt"
CHECKPOINT_HASH = "9005a0edf54c9f412721a79953cd7d17553c119581db098b1b02d2cdd397daae"


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verified(path, entry):
    return path.is_file() and path.stat().st_size == entry["bytes"] and sha256(path) == entry["sha256"]


def download(path, entry):
    if path.exists():
        if not verified(path, entry):
            raise RuntimeError(f"Existing file failed verification: {path}. Move it aside and try again.")
        print(f"Verified {path.name}", flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    for url in entry["urls"]:
        if not partial.is_file() or partial.stat().st_size != entry["bytes"]:
            print(f"Downloading {path.name} from {url.split('/')[2]}", flush=True)
            result = subprocess.run([
                "curl.exe", "--fail", "--location", "--progress-bar", "--show-error",
                "--user-agent", "Mozilla/5.0", "--header", "Accept-Encoding: identity",
                "--proto", "=https", "--proto-redir", "=https",
                "--connect-timeout", "15", "--speed-limit", "1024", "--speed-time", "30",
                "--max-time", "3600", "--retry", "1", "--continue-at", "-",
                "--output", str(partial), url,
            ], check=False)
            if result.returncode in (33, 36) and partial.is_file():
                # Some mirrors cannot resume; let the next attempt start a new temporary file.
                partial.unlink()
                continue
        if verified(partial, entry):
            partial.replace(path)
            return
        if partial.is_file() and partial.stat().st_size >= entry["bytes"]:
            partial.unlink()
    raise RuntimeError(
        f"Could not download or verify {path.name}. Re-run setup to resume, "
        f"or download one of the links in docs/INSTALL_WINDOWS.md and place it at {path}."
    )


def install_archive(entry):
    folder = ROOT / entry["unpack"]
    marker = folder / entry["marker"]
    if marker.is_file():
        return
    archive = CACHE / entry["path"]
    download(archive, entry)
    root = folder.resolve()
    with zipfile.ZipFile(archive) as contents:
        for item in contents.infolist():
            if not (root / item.filename).resolve().is_relative_to(root):
                raise RuntimeError(f"Archive contains an entry outside its target: {archive.name}")
        contents.extractall(root)
    if not marker.is_file():
        raise RuntimeError(f"{entry['marker']} was not found after extracting {archive.name}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("2b", "8b"), default="2b")
    parser.add_argument("--stereo", action="store_true", help="Install CUDA stereo dependencies and public weights.")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or struct.calcsize("P") != 8:
        raise RuntimeError("Run setup with 64-bit Python 3.11 on Windows x64.")
    if shutil.which("curl.exe") is None:
        raise RuntimeError("Windows curl.exe is required.")
    config_file = ROOT / "config.json"
    example = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else example.copy()
    if (config["python"], config["stereoPython"], config["stereoRoot"]) != (
        example["python"], example["stereoPython"], example["stereoRoot"]
    ):
        raise RuntimeError("Use setup in a fresh GitHub checkout. This directory has a different runtime configured.")
    if args.stereo:
        if not CHECKPOINT.is_file():
            raise RuntimeError(
                f"Place the Mono2Stereo deployment checkpoint at {CHECKPOINT} before running setup.cmd --stereo."
            )
        if CHECKPOINT.stat().st_size != 1732114967 or sha256(CHECKPOINT) != CHECKPOINT_HASH:
            raise RuntimeError("The Mono2Stereo deployment checkpoint failed verification. See docs/INSTALL_WINDOWS.md.")
    downloads = json.loads((SCRIPTS / "windows-downloads.json").read_text(encoding="utf-8"))
    for entry in downloads["desktop"]:
        install_archive(entry)
    for entry in downloads[args.model]:
        download(ROOT / entry["path"], entry)
    if args.stereo:
        for entry in downloads["stereo"]:
            download(ROOT / entry["path"], entry)

    python = ROOT / config["python"]
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(python.parent.parent)
    pip = [str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check"]
    requirements = SCRIPTS / "requirements-stereo-windows.txt"
    stereo_stamp = python.parent.parent / "stereo-requirements.sha256"
    if args.stereo:
        lock = sha256(requirements)
        if not stereo_stamp.is_file() or stereo_stamp.read_text(encoding="ascii").strip() != lock:
            subprocess.run([*pip, "--no-cache-dir", "-r", str(requirements)], check=True)
        subprocess.run([
            str(python), "-IB", "-c",
            "import torch; "
            "print('CUDA available:', torch.cuda.is_available()); "
            "assert torch.cuda.is_available(), 'Install a compatible NVIDIA driver'",
        ], check=True)
        subprocess.run([
            str(python), "-IB", str(ROOT / "stereo-runtime/scripts/run_mono2stereo_tensorrt_image.py"), "--help",
        ], check=True, stdout=subprocess.DEVNULL)
        stereo_stamp.write_text(lock + "\n", encoding="ascii")
        config["stereoEnabled"] = True
    else:
        subprocess.run([*pip, "Pillow==11.3.0"], check=True)

    config["model"] = args.model
    temporary = config_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_file)
    subprocess.run([str(python), "-IB", str(SCRIPTS / "check-env.py")], check=True)
    print("Setup complete. Run start.cmd.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        sys.exit(f"Setup failed: {exc}")
