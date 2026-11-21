from __future__ import annotations

import cv2
import numpy as np
import torch


def to_uint8(tensor: torch.Tensor) -> np.ndarray:
    array = tensor[0].detach().float().cpu().permute(1, 2, 0).numpy()
    return np.clip((array + 1.0) * 127.5, 0, 255).astype(np.uint8)


def add_high_frequency(
    baseline: np.ndarray,
    detail_source: np.ndarray,
    strength: float,
    sigma: float = 1.0,
) -> np.ndarray:
    baseline_float = baseline.astype(np.float32) / 255.0
    source_float = detail_source.astype(np.float32) / 255.0
    high = source_float - cv2.GaussianBlur(source_float, (0, 0), sigma)
    candidate = baseline_float + strength * high
    return np.clip(candidate * 255.0, 0, 255).astype(np.uint8)
