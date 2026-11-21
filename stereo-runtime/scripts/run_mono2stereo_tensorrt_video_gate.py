from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from diffusers import DPMSolverMultistepScheduler
from PIL import Image, ImageOps


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
sys.path.insert(0, str(PROJECT / "third_party" / "Mono2Stereo"))

from mono2stereo_runtime_utils import add_high_frequency, to_uint8  # noqa: E402
from pilot_mono2stereo_condition_adapter import (  # noqa: E402
    depth_tensor,
    load_models,
    warp_and_reliability,
)


def sha256_array(array: np.ndarray) -> str:
    return hashlib.sha256(array.tobytes()).hexdigest()


def read_video_frames(
    video_path: Path, start_frame: int, max_frames: int
) -> tuple[list[int], list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open input video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 15.0
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    indices: list[int] = []
    frames: list[np.ndarray] = []
    frame_index = start_frame
    while max_frames == 0 or len(frames) < max_frames:
        ok, frame = capture.read()
        if not ok:
            break
        indices.append(frame_index)
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        frame_index += 1
    capture.release()
    if not frames:
        raise RuntimeError("Input video contains no frames in the requested range")
    return indices, frames, fps


def resize_frame(frame: np.ndarray, width: int, height: int) -> tuple[np.ndarray, Image.Image]:
    image = ImageOps.fit(
        Image.fromarray(frame).convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
    )
    return np.asarray(image).copy(), image


class TensorRTUNetRunner:
    def __init__(self, engine_path: Path, scheduler_config: dict) -> None:
        sys.path.insert(0, str(PROJECT / "runtime" / "tensorrt_python"))
        import tensorrt as trt

        self.trt = trt
        self.runtime = trt.Runtime(trt.Logger(trt.Logger.WARNING))
        self.engine = self.runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self.engine is None:
            raise RuntimeError(f"Cannot deserialize TensorRT engine: {engine_path}")
        self.context = self.engine.create_execution_context()
        self.scheduler_config = scheduler_config
        self.stream = torch.cuda.Stream()

    def validate_resolution(self, width: int, height: int) -> None:
        expected = (1, 12, height // 8, width // 8)
        actual = tuple(self.engine.get_tensor_shape("sample"))
        if actual != expected:
            raise ValueError(
                f"TensorRT engine expects sample shape {actual}, "
                f"but {width}x{height} requires {expected}"
            )

    def generate(
        self,
        left_latent: torch.Tensor,
        warp_latent: torch.Tensor,
        text_embed: torch.Tensor,
        seed: int,
    ) -> tuple[torch.Tensor, float]:
        scheduler = DPMSolverMultistepScheduler.from_config(
            self.scheduler_config,
            prediction_type="v_prediction",
            algorithm_type="dpmsolver++",
            solver_order=2,
            lower_order_final=True,
        )
        scheduler.set_timesteps(20, device=left_latent.device)
        generator = torch.Generator(device=left_latent.device).manual_seed(seed)
        latent = torch.randn(
            left_latent.shape,
            generator=generator,
            device=left_latent.device,
            dtype=left_latent.dtype,
        )
        velocity = torch.empty_like(latent)
        torch.cuda.synchronize(left_latent.device)
        started = time.perf_counter()
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            for timestep in scheduler.timesteps:
                noisy = scheduler.scale_model_input(latent, timestep)
                model_input = torch.cat(
                    [left_latent, warp_latent, noisy], dim=1
                ).contiguous()
                timestep_input = timestep.reshape(1).to(dtype=torch.int64)
                for name, tensor in (
                    ("sample", model_input),
                    ("timestep", timestep_input),
                    ("encoder_hidden_states", text_embed),
                    ("velocity", velocity),
                ):
                    self.context.set_tensor_address(name, tensor.data_ptr())
                current_stream = torch.cuda.current_stream()
                self.stream.wait_stream(current_stream)
                with torch.cuda.stream(self.stream):
                    ok = self.context.execute_async_v3(self.stream.cuda_stream)
                if not ok:
                    raise RuntimeError("TensorRT execute_async_v3 returned false")
                current_stream.wait_stream(self.stream)
                latent = scheduler.step(velocity, timestep, latent).prev_sample
        torch.cuda.synchronize(left_latent.device)
        return latent, time.perf_counter() - started


def cache_matches(
    metadata_path: Path,
    frame: np.ndarray,
    frame_index: int,
    protocol: dict,
) -> bool:
    image_path = metadata_path.with_suffix(".png")
    if not image_path.is_file() or not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if protocol.get("seed_mode", "fixed") == "increment":
        local_index = protocol["frame_indices"].index(frame_index)
        expected_seed = protocol["seed"] + local_index
    else:
        expected_seed = protocol["seed"]
    expected = {
        "frame_index": frame_index,
        "input_sha256": sha256_array(frame),
        "width": protocol["width"],
        "height": protocol["height"],
        "seed": expected_seed,
        "viewpoint_scale": protocol["viewpoint_scale"],
        "cvdc_strength": protocol["cvdc_strength"],
        "cvdc_sigma": protocol["cvdc_sigma"],
    }
    return all(metadata.get(key) == value for key, value in expected.items())


def write_video(path: Path, frames: list[np.ndarray], fps: float) -> None:
    height, width = frames[0].shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open output video writer: {path}")
    for frame in frames:
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    writer.release()


def verify_video(path: Path, expected_count: int, expected_size: tuple[int, int]) -> dict:
    capture = cv2.VideoCapture(str(path))
    opened = capture.isOpened()
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) if opened else 0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) if opened else 0
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) if opened else 0
    capture.release()
    return {
        "exists": path.is_file(),
        "opened": opened,
        "frame_count": count,
        "width": width,
        "height": height,
        "frame_count_exact": count == expected_count,
        "size_exact": (width, height) == expected_size,
    }


def load_cached_right_frames(
    output: Path, frame_indices: list[int], frames: list[np.ndarray]
) -> tuple[list[np.ndarray], int]:
    cached: list[np.ndarray] = []
    hits = 0
    for frame_index, frame in zip(frame_indices, frames):
        path = output / "frames" / f"frame_{frame_index:06d}.png"
        cached.append(np.asarray(Image.open(path).convert("RGB")))
        hits += 1
    return cached, hits


def main() -> None:
    run_started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument(
        "--max-frames",
        type=int,
        default=8,
        help="number of frames to process; 0 processes all remaining frames",
    )
    parser.add_argument("--width", type=int, default=448)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument(
        "--seed-mode", choices=("fixed", "increment"), default="fixed"
    )
    parser.add_argument("--viewpoint-scale", type=float, default=4.8)
    parser.add_argument("--cvdc-strength", type=float, default=0.5)
    parser.add_argument("--cvdc-sigma", type=float, default=1.0)
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="output FPS override; omitted preserves the source FPS",
    )
    parser.add_argument("--checkpoint", type=Path, default=PROJECT / "assets" / "weights" / "mono2stereo_runtime_fp16.pt")
    parser.add_argument("--engine", type=Path, default=PROJECT / "assets" / "engines" / "mono2stereo_448x256_fp16.plan")
    parser.add_argument("--resume-only", action="store_true")
    args = parser.parse_args()
    if (
        args.start_frame < 0
        or args.max_frames < 0
        or (args.fps is not None and args.fps <= 0)
        or args.width % 8
        or args.height % 8
    ):
        raise ValueError(
            "start-frame/max-frames must be non-negative, FPS must be positive, "
            "and dimensions must be divisible by 8"
        )

    frame_indices, source_frames, source_fps = read_video_frames(
        args.input_video, args.start_frame, args.max_frames
    )
    output_fps = source_fps if args.fps is None else args.fps
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    protocol = {
        "input_video": str(args.input_video.resolve()),
        "start_frame": args.start_frame,
        "max_frames": args.max_frames,
        "frame_indices": frame_indices,
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "seed_mode": args.seed_mode,
        "viewpoint_scale": args.viewpoint_scale,
        "cvdc_strength": args.cvdc_strength,
        "cvdc_sigma": args.cvdc_sigma,
        "source_fps": source_fps,
        "output_fps": output_fps,
        "engine": str(args.engine.resolve()),
    }
    protocol_path = output / "protocol.json"
    protocol_path.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cache_dir = output / "frames"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ready = all(
        cache_matches(
            cache_dir / f"frame_{frame_index:06d}.json",
            frame,
            frame_index,
            protocol,
        )
        for frame_index, frame in zip(frame_indices, source_frames)
    )
    if args.resume_only and not ready:
        raise RuntimeError("--resume-only requested but frame cache is incomplete")

    inference_seconds = 0.0
    frame_processing_seconds = 0.0
    model_load_seconds = 0.0
    inference_count = 0
    cache_hits = 0
    if ready:
        mode = "CACHE_HIT"
        right_frames, cache_hits = load_cached_right_frames(
            output, frame_indices, source_frames
        )
    else:
        mode = "INFERENCE"
        device = torch.device("cuda")
        load_started = time.perf_counter()
        painter, depth_model, text_embed = load_models(device, args.checkpoint)
        painter.unet.to("cpu")
        painter.unet = None
        runner = TensorRTUNetRunner(args.engine, painter.scheduler.config)
        runner.validate_resolution(args.width, args.height)
        model_load_seconds = time.perf_counter() - load_started
        for local_index, (frame_index, source_frame) in enumerate(
            zip(frame_indices, source_frames)
        ):
            metadata_path = cache_dir / f"frame_{frame_index:06d}.json"
            image_path = metadata_path.with_suffix(".png")
            if cache_matches(metadata_path, source_frame, frame_index, protocol):
                cache_hits += 1
                continue
            frame_started = time.perf_counter()
            left_uint8, image = resize_frame(
                source_frame, args.width, args.height
            )
            left = (
                torch.from_numpy(left_uint8)
                .permute(2, 0, 1)
                .unsqueeze(0)
                .to(device=device, dtype=torch.float32)
                / 127.5
                - 1.0
            )
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                inverse_depth = depth_model(depth_tensor(image, device))
                warp, _ = warp_and_reliability(
                    left, inverse_depth, args.viewpoint_scale
                )
                left_latent = painter.encode_rgb(left.half())
                warp_latent = painter.encode_rgb(warp.half())
            frame_seed = (
                args.seed + local_index
                if args.seed_mode == "increment"
                else args.seed
            )
            latent, elapsed = runner.generate(
                left_latent, warp_latent, text_embed, frame_seed
            )
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                generated = painter.decode_right(latent).clamp(-1, 1)
            baseline_right = to_uint8(generated)
            right_uint8 = add_high_frequency(
                baseline_right,
                left_uint8,
                args.cvdc_strength,
                sigma=args.cvdc_sigma,
            )
            Image.fromarray(right_uint8).save(image_path)
            frame_elapsed = time.perf_counter() - frame_started
            metadata = {
                "frame_index": frame_index,
                "input_sha256": sha256_array(source_frame),
                "width": args.width,
                "height": args.height,
                "seed": frame_seed,
                "viewpoint_scale": args.viewpoint_scale,
                "cvdc_strength": args.cvdc_strength,
                "cvdc_sigma": args.cvdc_sigma,
                "unet_seconds": elapsed,
                "frame_processing_seconds": frame_elapsed,
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            inference_seconds += elapsed
            frame_processing_seconds += frame_elapsed
            inference_count += 1
            print(
                f"inferred={inference_count}/{len(frame_indices)} frame={frame_index}",
                flush=True,
            )
        right_frames, _ = load_cached_right_frames(
            output, frame_indices, source_frames
        )
        del painter, depth_model, text_embed, runner
        gc.collect()
        torch.cuda.empty_cache()

    left_frames = [resize_frame(frame, args.width, args.height)[0] for frame in source_frames]
    side_by_side = [np.concatenate([left, right], axis=1) for left, right in zip(left_frames, right_frames)]
    anaglyph = []
    for left, right in zip(left_frames, right_frames):
        merged = left.copy()
        merged[..., 1:] = right[..., 1:]
        anaglyph.append(merged)
    right_path = output / "right.mp4"
    sbs_path = output / "side_by_side.mp4"
    anaglyph_path = output / "anaglyph.mp4"
    write_video(right_path, right_frames, output_fps)
    write_video(sbs_path, side_by_side, output_fps)
    write_video(anaglyph_path, anaglyph, output_fps)
    checks = {
        "frame_count_matches_input": len(right_frames) == len(source_frames),
        "right_video": verify_video(right_path, len(source_frames), (args.width, args.height)),
        "side_by_side_video": verify_video(sbs_path, len(source_frames), (args.width * 2, args.height)),
        "anaglyph_video": verify_video(anaglyph_path, len(source_frames), (args.width, args.height)),
        "cache_complete": all(
            cache_matches(
                cache_dir / f"frame_{frame_index:06d}.json",
                frame,
                frame_index,
                protocol,
            )
            for frame_index, frame in zip(frame_indices, source_frames)
        ),
    }
    checks["all_outputs_valid"] = bool(
        checks["frame_count_matches_input"]
        and checks["cache_complete"]
        and all(
            checks[key]["opened"]
            and checks[key]["frame_count_exact"]
            and checks[key]["size_exact"]
            for key in ("right_video", "side_by_side_video", "anaglyph_video")
        )
    )
    summary = {
        "execution_status": "COMPLETED",
        "verification_status": "VERIFIED" if checks["all_outputs_valid"] else "ANALYZED",
        "mode": mode,
        "frame_count": len(source_frames),
        "frame_indices": frame_indices,
        "source_fps": source_fps,
        "output_fps": output_fps,
        "output_duration_seconds": len(source_frames) / output_fps,
        "cache_hits": cache_hits,
        "inference_frame_count": inference_count,
        "model_and_engine_load_seconds": model_load_seconds,
        "inference_unet_seconds": inference_seconds,
        "mean_unet_seconds_per_inferred_frame": inference_seconds / max(inference_count, 1),
        "inference_frame_processing_seconds": frame_processing_seconds,
        "mean_processing_seconds_per_inferred_frame": frame_processing_seconds
        / max(inference_count, 1),
        "wall_seconds": time.perf_counter() - run_started,
        "outputs": {
            "right": str(right_path),
            "side_by_side": str(sbs_path),
            "anaglyph": str(anaglyph_path),
        },
        "checks": checks,
        "decision": "GO_VIDEO_FRAMEWISE_CACHE" if checks["all_outputs_valid"] else "NO_GO_VIDEO_FRAMEWISE_CACHE",
    }
    summary_path = output / "summary.json"
    if mode == "INFERENCE" and not (output / "initial_summary.json").exists():
        (output / "initial_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if not checks["all_outputs_valid"]:
        raise RuntimeError("Video frame-wise gate failed")


if __name__ == "__main__":
    main()
