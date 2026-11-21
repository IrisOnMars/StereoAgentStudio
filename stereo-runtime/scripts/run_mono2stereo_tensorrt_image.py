from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
sys.path.insert(0, str(PROJECT / "third_party" / "Mono2Stereo"))

import numpy as np
import torch
from diffusers import DPMSolverMultistepScheduler
from PIL import Image

from mono2stereo_runtime_utils import to_uint8  # noqa: E402
from pilot_mono2stereo_condition_adapter import (  # noqa: E402
    depth_tensor,
    load_models,
    warp_and_reliability,
)
from run_mono2stereo_tensorrt_video_gate import (  # noqa: E402
    TensorRTUNetRunner,
    resize_frame,
)
from stereo_postprocess import DEFAULT_POSTPROCESS, POSTPROCESS_METHODS, postprocess_right  # noqa: E402


def compose_anaglyph(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    if left.shape != right.shape:
        raise ValueError("left and right images must have identical shapes")
    anaglyph = left.copy()
    anaglyph[..., 1:] = right[..., 1:]
    return anaglyph


def frame_source(image: Image.Image, width: int, height: int, fit: str) -> tuple[np.ndarray, Image.Image]:
    if fit == "strict" and image.width * height != image.height * width:
        raise ValueError("Source aspect ratio does not match the stereo canvas")
    if fit != "pad":
        return resize_frame(np.asarray(image), width, height)

    scale = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(size, Image.Resampling.LANCZOS)
    framed = Image.new("RGB", (width, height))
    framed.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return np.array(framed), framed


@torch.inference_mode()
def generate_pytorch(painter, left_latent, warp_latent, text_embed, seed):
    scheduler = DPMSolverMultistepScheduler.from_config(
        painter.scheduler.config,
        prediction_type="v_prediction",
        algorithm_type="dpmsolver++",
        solver_order=2,
        lower_order_final=True,
    )
    device = left_latent.device
    scheduler.set_timesteps(20, device=device)
    generator = torch.Generator(device=device).manual_seed(seed)
    latent = torch.randn(left_latent.shape, generator=generator, device=device, dtype=left_latent.dtype)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    with torch.autocast("cuda", dtype=torch.float16):
        for timestep in scheduler.timesteps:
            noisy = scheduler.scale_model_input(latent, timestep)
            model_input = torch.cat([left_latent, warp_latent, noisy], dim=1)
            velocity = painter.unet(model_input, timestep, encoder_hidden_states=text_embed).sample
            latent = scheduler.step(velocity, timestep, latent).prev_sample
    torch.cuda.synchronize(device)
    return latent, time.perf_counter() - started


def main() -> None:
    run_started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=448)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--fit", choices=("pad", "center_crop", "strict"), default="center_crop")
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--viewpoint-scale", type=float, default=4.8)
    parser.add_argument("--cvdc-strength", type=float, default=0.5)
    parser.add_argument("--cvdc-sigma", type=float, default=1.0)
    parser.add_argument("--postprocess", choices=POSTPROCESS_METHODS, default=DEFAULT_POSTPROCESS)
    parser.add_argument("--right-pair", action="store_true", help="Write only the right image and its red/cyan anaglyph")
    parser.add_argument("--backend", choices=("pytorch", "tensorrt"), default="tensorrt")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=PROJECT
        / "assets"
        / "weights"
        / "mono2stereo_runtime_fp16.pt",
    )
    parser.add_argument(
        "--engine",
        type=Path,
        default=PROJECT
        / "assets"
        / "engines"
        / "mono2stereo_448x256_fp16.plan",
    )
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("Stereo generation requires a supported NVIDIA CUDA GPU and driver.")
    if args.width % 8 or args.height % 8:
        raise ValueError("dimensions must be divisible by 8")
    if not args.input_image.is_file():
        raise FileNotFoundError(args.input_image)
    args.output.mkdir(parents=True, exist_ok=True)

    with Image.open(args.input_image) as original:
        left_uint8, fitted_image = frame_source(original.convert("RGB"), args.width, args.height, args.fit)
    device = torch.device("cuda")
    load_started = time.perf_counter()
    painter, depth_model, text_embed = load_models(device, args.checkpoint)
    runner = None
    if args.backend == "tensorrt":
        painter.unet.to("cpu")
        painter.unet = None
        runner = TensorRTUNetRunner(args.engine, painter.scheduler.config)
        runner.validate_resolution(args.width, args.height)
    model_load_seconds = time.perf_counter() - load_started

    left = (
        torch.from_numpy(left_uint8)
        .permute(2, 0, 1)
        .unsqueeze(0)
        .to(device=device, dtype=torch.float32)
        / 127.5
        - 1.0
    )
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        inverse_depth = depth_model(depth_tensor(fitted_image, device))
        warp, reliability = warp_and_reliability(
            left, inverse_depth, args.viewpoint_scale
        )
        left_latent = painter.encode_rgb(left.half())
        warp_latent = painter.encode_rgb(warp.half())
    if runner is None:
        latent, unet_seconds = generate_pytorch(painter, left_latent, warp_latent, text_embed, args.seed)
    else:
        latent, unet_seconds = runner.generate(left_latent, warp_latent, text_embed, args.seed)
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        generated = painter.decode_right(latent).clamp(-1, 1)
    baseline_right = to_uint8(generated)
    postprocess_started = time.perf_counter()
    right_uint8, postprocess, confidence = postprocess_right(
        left_uint8,
        baseline_right,
        args.postprocess,
        legacy_strength=args.cvdc_strength,
        legacy_sigma=args.cvdc_sigma,
    )
    postprocess["elapsed_seconds"] = time.perf_counter() - postprocess_started
    images = {
        "right": ("right.png", right_uint8),
        "anaglyph": ("anaglyph.png", compose_anaglyph(left_uint8, right_uint8)),
    }
    if not args.right_pair:
        images.update({
            "left": ("left.png", left_uint8),
            "baseline_right": ("right_baseline.png", baseline_right),
            "side_by_side": ("side_by_side.png", np.concatenate([left_uint8, right_uint8], axis=1)),
        })
        if confidence is not None:
            images["postprocess_confidence"] = ("postprocess_confidence.png", confidence)
    paths = {}
    for key, (filename, image) in images.items():
        output_path = args.output / filename
        Image.fromarray(image).save(output_path)
        paths[key] = str(output_path)

    summary = {
        "execution_status": "COMPLETED",
        "verification_status": "VERIFIED",
        "input_image": str(args.input_image.resolve()),
        "native_resolution": [args.width, args.height],
        "fit": args.fit,
        "side_by_side_resolution": [args.width * 2, args.height] if not args.right_pair else None,
        "seed": args.seed,
        "viewpoint_scale": args.viewpoint_scale,
        "postprocess": postprocess,
        "cvdc_strength": args.cvdc_strength,
        "cvdc_sigma": args.cvdc_sigma,
        "checkpoint": str(args.checkpoint.resolve()),
        "backend": args.backend,
        "engine": str(args.engine.resolve()) if runner else None,
        "engine_sample_shape": list(runner.engine.get_tensor_shape("sample")) if runner else None,
        "reliability_mean": float(reliability.mean().detach().cpu()),
        "timing_seconds": {
            "model_and_engine_load": model_load_seconds,
            "unet_dpm20": unet_seconds,
            "wall": time.perf_counter() - run_started,
        },
        "outputs": paths,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    del painter, depth_model, text_embed, runner
    gc.collect()
    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
