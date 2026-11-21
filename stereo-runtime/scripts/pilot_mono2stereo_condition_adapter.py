from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageOps
from skimage.metrics import structural_similarity
from torch import nn


PROJECT = Path(__file__).resolve().parents[1]
MONO2STEREO = PROJECT / "third_party" / "Mono2Stereo"
sys.path.insert(0, str(MONO2STEREO))

from depth.depth_anything_v2.dpt import DepthAnythingV2  # noqa: E402
from depth.depth_anything_v2.util.transform import (  # noqa: E402
    MyResize,
    NormalizeImage,
    PrepareForNet,
)
from diffusers import DDIMScheduler, DDPMScheduler  # noqa: E402
from marigold.marigold_pipeline import MarigoldPipeline  # noqa: E402
from torchvision.transforms import Compose  # noqa: E402


FINAL_TEST_SEQUENCES = {"0005", "0011", "0020", "0032", "0045"}


class WarpConditionAdapter(nn.Module):
    """Zero-initialized residual correction for Mono2Stereo's warp latent."""

    def __init__(self, hidden_channels: int = 16) -> None:
        super().__init__()
        self.in_conv = nn.Conv2d(11, hidden_channels, 3, padding=1)
        self.out_conv = nn.Conv2d(hidden_channels, 4, 3, padding=1)
        nn.init.zeros_(self.out_conv.weight)
        nn.init.zeros_(self.out_conv.bias)

    def forward(
        self,
        left_latent: torch.Tensor,
        warp_latent: torch.Tensor,
        reliability: torch.Tensor,
    ) -> torch.Tensor:
        reliability = F.interpolate(
            reliability, size=warp_latent.shape[-2:], mode="area"
        )
        features = torch.cat([left_latent, warp_latent, reliability], dim=1)
        residual = self.out_conv(F.silu(self.in_conv(features)))
        return warp_latent + residual


def image_tensor(path: Path, width: int, height: int, device: torch.device):
    image = Image.open(path).convert("RGB")
    image = ImageOps.fit(
        image, (width, height), method=Image.Resampling.LANCZOS
    )
    array = np.asarray(image, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)
    return image, (tensor * 2.0 - 1.0).to(device)


def depth_tensor(image: Image.Image, device: torch.device) -> torch.Tensor:
    transform = Compose(
        [
            MyResize(
                width=518,
                height=518,
                resize_target=False,
                keep_aspect_ratio=True,
                ensure_multiple_of=14,
                resize_method="lower_bound",
                image_interpolation_method=cv2.INTER_CUBIC,
            ),
            NormalizeImage(
                mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
            ),
            PrepareForNet(),
        ]
    )
    array = np.asarray(image, dtype=np.float32) / 255.0
    transformed = transform({"image": array})["image"]
    return torch.from_numpy(transformed).unsqueeze(0).to(device)


def warp_and_reliability(
    left: torch.Tensor,
    inverse_depth: torch.Tensor,
    viewpoint_scale: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    batch, channels, height, width = left.shape
    inverse_depth = F.interpolate(
        inverse_depth.unsqueeze(1),
        size=(height, width),
        mode="bilinear",
        align_corners=False,
    ).squeeze(1)
    disparity = viewpoint_scale * inverse_depth
    source_x = torch.arange(width, device=left.device).view(1, 1, width)
    source_x = source_x.expand(batch, height, width)
    target_x = (source_x - disparity).to(torch.int64)
    valid = (target_x >= 0) & (target_x < width)

    warped = torch.zeros_like(left)
    counts = torch.zeros((batch, height, width), device=left.device)
    warped_disparity = torch.zeros_like(counts)
    rows = torch.arange(height, device=left.device).view(height, 1).expand(height, width)

    for batch_index in range(batch):
        valid_rows, valid_cols = torch.where(valid[batch_index])
        valid_targets = target_x[batch_index, valid_rows, valid_cols]
        warped[batch_index, :, valid_rows, valid_targets] = left[
            batch_index, :, valid_rows, valid_cols
        ]
        warped_disparity[batch_index, valid_rows, valid_targets] = disparity[
            batch_index, valid_rows, valid_cols
        ]
        flat_targets = (rows * width + target_x[batch_index]).reshape(-1)
        flat_valid = valid[batch_index].reshape(-1)
        counts[batch_index].view(-1).scatter_add_(
            0,
            flat_targets[flat_valid],
            torch.ones_like(flat_targets[flat_valid], dtype=counts.dtype),
        )

    hole = counts.eq(0)
    collision = counts.gt(1)
    left_disp = warped_disparity[:, :, :-1]
    right_disp = warped_disparity[:, :, 1:]
    boundary = (left_disp - right_disp).abs() / (
        left_disp.abs() + right_disp.abs() + 1e-6
    )
    boundary = F.pad(boundary, (1, 0))
    boundary = boundary * (~hole).float()
    reliability = torch.stack(
        [hole.float(), collision.float(), boundary], dim=1
    )
    return warped, reliability


def replace_conv_in(unet: nn.Module) -> None:
    if unet.config["in_channels"] == 12:
        return
    old = unet.conv_in
    weight = old.weight.detach().repeat(1, 3, 1, 1) / 3.0
    new = nn.Conv2d(
        12,
        old.out_channels,
        old.kernel_size,
        stride=old.stride,
        padding=old.padding,
        device=weight.device,
        dtype=weight.dtype,
    )
    new.weight.data.copy_(weight)
    new.bias.data.copy_(old.bias.detach())
    unet.conv_in = new
    unet.config["in_channels"] = 12


def load_checkpoint(unet: nn.Module, path: Path) -> None:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
    state = checkpoint.get("model", checkpoint)
    state = {
        key.removeprefix("module."): value for key, value in state.items()
    }
    unet.load_state_dict(state)


def generate(
    painter: MarigoldPipeline,
    left_latent: torch.Tensor,
    warp_latent: torch.Tensor,
    text_embed: torch.Tensor,
    seed: int,
    steps: int,
) -> torch.Tensor:
    scheduler = DDIMScheduler.from_config(
        painter.scheduler.config, prediction_type="v_prediction"
    )
    scheduler.set_timesteps(steps, device=left_latent.device)
    generator = torch.Generator(device=left_latent.device).manual_seed(seed)
    latent = torch.randn(
        left_latent.shape,
        device=left_latent.device,
        dtype=left_latent.dtype,
        generator=generator,
    )
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        for timestep in scheduler.timesteps:
            model_input = torch.cat([left_latent, warp_latent, latent], dim=1)
            velocity = painter.unet(
                model_input, timestep, encoder_hidden_states=text_embed
            ).sample
            latent = scheduler.step(velocity, timestep, latent).prev_sample
        return painter.decode_right(latent).clamp(-1, 1)


def metrics(prediction: torch.Tensor, target: torch.Tensor, weight=None) -> dict:
    error = (prediction.float() - target.float()).abs().mean(dim=1)
    squared = (prediction.float() - target.float()).pow(2).mean(dim=1)
    gray_prediction = prediction.float().mean(dim=1, keepdim=True)
    gray_target = target.float().mean(dim=1, keepdim=True)
    pred_dx = F.pad(gray_prediction[:, :, :, 1:] - gray_prediction[:, :, :, :-1], (1, 0))
    pred_dy = F.pad(gray_prediction[:, :, 1:, :] - gray_prediction[:, :, :-1, :], (0, 0, 1, 0))
    target_dx = F.pad(gray_target[:, :, :, 1:] - gray_target[:, :, :, :-1], (1, 0))
    target_dy = F.pad(gray_target[:, :, 1:, :] - gray_target[:, :, :-1, :], (0, 0, 1, 0))
    edge_error = (
        torch.sqrt(pred_dx.square() + pred_dy.square() + 1e-12)
        - torch.sqrt(target_dx.square() + target_dy.square() + 1e-12)
    ).abs().squeeze(1)
    if weight is None:
        mae = error.mean()
        mse = squared.mean()
        edge_mae = edge_error.mean()
    else:
        weight = weight.float()
        mae = (error * weight).sum() / weight.sum().clamp_min(1.0)
        mse = (squared * weight).sum() / weight.sum().clamp_min(1.0)
        edge_mae = (edge_error * weight).sum() / weight.sum().clamp_min(1.0)
    psnr = -10.0 * torch.log10(mse.clamp_min(1e-12) / 4.0)
    result = {
        "mae_0_2": float(mae),
        "psnr_db": float(psnr),
        "edge_mae_0_2": float(edge_mae),
    }
    if weight is None:
        prediction_hwc = prediction[0].detach().float().cpu().permute(1, 2, 0).numpy()
        target_hwc = target[0].detach().float().cpu().permute(1, 2, 0).numpy()
        result["ssim"] = float(
            structural_similarity(
                prediction_hwc, target_hwc, channel_axis=2, data_range=2.0
            )
        )
    return result


def save_tensor(path: Path, tensor: torch.Tensor) -> None:
    image = ((tensor[0].detach().float().cpu() + 1.0) * 127.5)
    image = image.clamp(0, 255).byte().permute(1, 2, 0).numpy()
    Image.fromarray(image).save(path)


def load_models(
    device: torch.device,
    checkpoint_path: Path | None = None,
):
    sd2_path = PROJECT / "models" / "mono2stereo" / "sd2-base-fp16"
    scheduler = DDIMScheduler.from_pretrained(
        sd2_path, subfolder="scheduler", local_files_only=True
    )
    scheduler = DDIMScheduler.from_config(
        scheduler.config, prediction_type="v_prediction"
    )
    painter = MarigoldPipeline.from_pretrained(
        sd2_path,
        torch_dtype=torch.float16,
        variant="fp16",
        local_files_only=True,
        scheduler=scheduler,
        scale_invariant=True,
        shift_invariant=True,
    ).to(device)
    replace_conv_in(painter.unet)
    load_checkpoint(
        painter.unet,
        checkpoint_path
        or PROJECT / "assets" / "weights" / "mono2stereo_runtime_fp16.pt",
    )
    painter.unet.requires_grad_(False).eval()
    painter.vae.requires_grad_(False).eval()
    painter.encode_empty_text()
    text_embed = painter.empty_text_embed.detach().to(device)
    painter.text_encoder.to("cpu")

    depth_model = DepthAnythingV2(
        encoder="vits",
        features=64,
        out_channels=[48, 96, 192, 384],
    )
    depth_model.load_state_dict(
        torch.load(
            MONO2STEREO / "depth" / "checkpoints" / "depth_anything_v2_vits.pth",
            map_location="cpu",
            weights_only=True,
        )
    )
    return painter, depth_model.to(device).eval(), text_embed


def prepare_scene(
    scene: Path,
    width: int,
    height: int,
    viewpoint_scale: float,
    painter: MarigoldPipeline,
    depth_model: DepthAnythingV2,
    device: torch.device,
) -> dict:
    left_path = next((scene / "frame_left").glob("*.png"))
    right_path = next((scene / "frame_right").glob("*.png"))
    return prepare_pair(
        left_path,
        right_path,
        scene.name,
        width,
        height,
        viewpoint_scale,
        painter,
        depth_model,
        device,
    )


def prepare_pair(
    left_path: Path,
    right_path: Path,
    scene_name: str,
    width: int,
    height: int,
    viewpoint_scale: float,
    painter: MarigoldPipeline,
    depth_model: DepthAnythingV2,
    device: torch.device,
) -> dict:
    left_image, left = image_tensor(left_path, width, height, device)
    _, target = image_tensor(right_path, width, height, device)
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        inverse_depth = depth_model(depth_tensor(left_image, device))
        warp, reliability = warp_and_reliability(
            left, inverse_depth, viewpoint_scale
        )
        left_latent = painter.encode_rgb(left.half())
        warp_latent = painter.encode_rgb(warp.half())
        target_latent = painter.encode_rgb(target.half())
    return {
        "scene": scene_name,
        "left": left,
        "target": target,
        "warp": warp,
        "reliability": reliability,
        "left_latent": left_latent,
        "warp_latent": warp_latent,
        "target_latent": target_latent,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", default="0006_f0001")
    parser.add_argument("--width", type=int, default=448)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--train-steps", type=int, default=20)
    parser.add_argument("--inference-steps", type=int, default=10)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--viewpoint-scale", type=float, default=4.8)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "outputs" / "mono2stereo_condition_adapter_pilot",
    )
    args = parser.parse_args()

    sequence = args.scene.split("_", 1)[0]
    if sequence in FINAL_TEST_SEQUENCES:
        raise ValueError(f"Final-test sequence is locked: {sequence}")
    if args.width % 8 or args.height % 8:
        raise ValueError("Width and height must be divisible by 8")

    torch.manual_seed(args.seed)
    device = torch.device("cuda")
    scene = PROJECT / "datasets" / "spring_expansion_26x15" / args.scene
    args.output.mkdir(parents=True, exist_ok=True)

    sd2_path = PROJECT / "models" / "mono2stereo" / "sd2-base-fp16"
    painter, depth_model, text_embed = load_models(device)
    prepared = prepare_scene(
        scene,
        args.width,
        args.height,
        args.viewpoint_scale,
        painter,
        depth_model,
        device,
    )
    left = prepared["left"]
    target = prepared["target"]
    warp = prepared["warp"]
    reliability = prepared["reliability"]
    left_latent = prepared["left_latent"]
    warp_latent = prepared["warp_latent"]
    target_latent = prepared["target_latent"]
    depth_model.to("cpu")
    painter.vae.to("cpu")
    del depth_model
    torch.cuda.empty_cache()

    adapter = WarpConditionAdapter().to(device)
    adapter_parameters = sum(parameter.numel() for parameter in adapter.parameters())
    fixed_generator = torch.Generator(device=device).manual_seed(args.seed)
    fixed_noise = torch.randn(
        target_latent.shape,
        device=device,
        dtype=target_latent.dtype,
        generator=fixed_generator,
    )
    fixed_timestep = torch.full((1,), 500, device=device, dtype=torch.long)
    training_scheduler = DDPMScheduler.from_pretrained(
        sd2_path, subfolder="scheduler", local_files_only=True
    )

    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        zero_warp_latent = adapter(left_latent, warp_latent, reliability)
        zero_diff = float((zero_warp_latent - warp_latent).abs().max())

    optimizer = torch.optim.AdamW(adapter.parameters(), lr=args.learning_rate)
    scaler = torch.amp.GradScaler("cuda")
    painter.unet.enable_gradient_checkpointing()
    painter.unet.train()
    losses = []
    torch.cuda.reset_peak_memory_stats()

    for step in range(args.train_steps):
        generator = torch.Generator(device=device).manual_seed(args.seed + step + 1)
        timestep = torch.randint(
            0, training_scheduler.config.num_train_timesteps, (1,),
            generator=generator, device=device,
        )
        noise = torch.randn(
            target_latent.shape,
            generator=generator,
            device=device,
            dtype=target_latent.dtype,
        )
        noisy_target = training_scheduler.add_noise(target_latent, noise, timestep)
        velocity_target = training_scheduler.get_velocity(
            target_latent, noise, timestep
        )
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.float16):
            adapted_warp = adapter(left_latent, warp_latent, reliability)
            model_input = torch.cat(
                [left_latent, adapted_warp, noisy_target], dim=1
            )
            velocity = painter.unet(
                model_input, timestep, encoder_hidden_states=text_embed
            ).sample
            loss = F.mse_loss(velocity.float(), velocity_target.float())
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        losses.append(float(loss.detach()))
        print(f"step={step + 1}/{args.train_steps} loss={losses[-1]:.6f}", flush=True)

    painter.unet.disable_gradient_checkpointing()
    painter.unet.eval()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        noisy_fixed = training_scheduler.add_noise(
            target_latent, fixed_noise, fixed_timestep
        )
        fixed_target = training_scheduler.get_velocity(
            target_latent, fixed_noise, fixed_timestep
        )
        baseline_velocity = painter.unet(
            torch.cat([left_latent, warp_latent, noisy_fixed], dim=1),
            fixed_timestep,
            encoder_hidden_states=text_embed,
        ).sample
        adapted_warp = adapter(left_latent, warp_latent, reliability)
        adapted_velocity = painter.unet(
            torch.cat([left_latent, adapted_warp, noisy_fixed], dim=1),
            fixed_timestep,
            encoder_hidden_states=text_embed,
        ).sample
        fixed_loss_baseline = F.mse_loss(
            baseline_velocity.float(), fixed_target.float()
        )
        fixed_loss_adapted = F.mse_loss(
            adapted_velocity.float(), fixed_target.float()
        )

    painter.vae.to(device)
    baseline = generate(
        painter, left_latent, warp_latent, text_embed, args.seed, args.inference_steps
    )
    adapted = generate(
        painter, left_latent, adapted_warp, text_embed, args.seed, args.inference_steps
    )
    critical_weight = reliability.max(dim=1).values
    summary = {
        "execution_status": "COMPLETED",
        "verification_status": "ANALYZED",
        "scene": args.scene,
        "final_test_sequences_locked": sorted(FINAL_TEST_SEQUENCES),
        "adapter_parameters": adapter_parameters,
        "zero_initialization_max_abs_diff": zero_diff,
        "zero_initialization_equivalence_passed": zero_diff == 0.0,
        "train_losses": losses,
        "fixed_loss": {
            "baseline": float(fixed_loss_baseline),
            "adapted": float(fixed_loss_adapted),
        },
        "metrics": {
            "baseline_full": metrics(baseline, target),
            "adapted_full": metrics(adapted, target),
            "baseline_geometry_weighted": metrics(
                baseline, target, critical_weight
            ),
            "adapted_geometry_weighted": metrics(
                adapted, target, critical_weight
            ),
        },
        "peak_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1),
        "settings": vars(args) | {"output": str(args.output)},
    }
    save_tensor(args.output / "left.png", left)
    save_tensor(args.output / "target_right.png", target)
    save_tensor(args.output / "warp.png", warp)
    save_tensor(args.output / "baseline.png", baseline)
    save_tensor(args.output / "adapted.png", adapted)
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
