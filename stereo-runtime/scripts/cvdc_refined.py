"""Experimental source-detail transfer; never reads a reference right image.

DIS estimates correspondence between the generated right view and the left
input. Forward/backward consistency is a reliability cue, not calibrated
stereo visibility. Defaults are candidates pending independent evaluation.
"""
from __future__ import annotations

import time
import cv2
import numpy as np


def high_pass(image: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    value = image.astype(np.float32) / 255.0
    return value - cv2.GaussianBlur(value, (0, 0), sigma)


def prepare_correspondence(source: np.ndarray, baseline: np.ndarray) -> dict:
    """Target-to-source subpixel map and source-only reliability estimates."""
    if source.shape != baseline.shape or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("source and baseline must be equally sized RGB images")
    started = time.perf_counter()
    src_gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    dst_gray = cv2.cvtColor(baseline, cv2.COLOR_RGB2GRAY)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    backward = dis.calc(dst_gray, src_gray, None)
    forward = dis.calc(src_gray, dst_gray, None)
    height, width = source.shape[:2]
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    map_x, map_y = xx + backward[..., 0], yy + backward[..., 1]
    valid = (map_x >= 1) & (map_x <= width - 2) & (map_y >= 1) & (map_y <= height - 2)
    remap = lambda value: cv2.remap(value, map_x, map_y, cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    returned = remap(forward)
    fb_error = np.linalg.norm(backward + returned, axis=2)
    motion = np.linalg.norm(backward, axis=2)
    # A small motion-dependent allowance accounts for subpixel flow uncertainty.
    fb_scale = 0.75 + 0.05 * motion
    fb_conf = np.exp(-0.5 * (fb_error / fb_scale) ** 2)
    src_f = source.astype(np.float32) / 255.0
    dst_f = baseline.astype(np.float32) / 255.0
    photo_error = np.mean(np.abs(remap(cv2.GaussianBlur(src_f, (0, 0), 1.5)) -
                                 cv2.GaussianBlur(dst_f, (0, 0), 1.5)), axis=2)
    photo_conf = np.exp(-0.5 * (photo_error / 0.06) ** 2)
    mask = valid & (fb_error < 1.5 + 0.05 * motion) & (photo_error < 0.15)
    # Avoid injecting source texture right on correspondence/visibility borders.
    mask = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    confidence = mask.astype(np.float32) * fb_conf * photo_conf
    aligned = remap(high_pass(source))
    baseline_high = high_pass(baseline)
    # Local signed agreement rejects incompatible texture without consulting GT.
    cross = cv2.GaussianBlur(np.sum(aligned * baseline_high, axis=2), (0, 0), 1.5)
    source_energy = cv2.GaussianBlur(np.sum(aligned ** 2, axis=2), (0, 0), 1.5)
    target_energy = cv2.GaussianBlur(np.sum(baseline_high ** 2, axis=2), (0, 0), 1.5)
    correlation = cross / np.sqrt(source_energy * target_energy + 1e-10)
    texture_conf = np.clip((correlation - 0.2) / 0.6, 0.0, 1.0)
    return {"aligned_high": aligned, "source_high": high_pass(source), "baseline_high": baseline_high,
            "confidence": confidence, "texture_confidence": texture_conf,
            "fb_error": fb_error, "photo_error": photo_error,
            "backward_flow": backward, "valid": valid,
            "alignment_seconds": time.perf_counter() - started}


def apply_compensation(baseline: np.ndarray, prepared: dict, strength: float = 0.5,
                       mode: str = "replace", gate: str = "photo") -> np.ndarray:
    """Inject or replace aligned high bands, with a bounded 8/255 correction."""
    if not 0 <= strength <= 1:
        raise ValueError("strength must lie in [0, 1]")
    high = prepared["aligned_high"]
    if mode == "replace":
        correction = high - prepared["baseline_high"]
    elif mode == "add":
        correction = high
    elif mode == "smooth_control":
        correction = -prepared["baseline_high"]
    elif mode == "unaligned_control":
        correction = prepared["source_high"] - prepared["baseline_high"]
    else:
        raise ValueError("unknown compensation mode")
    confidence = prepared["confidence"]
    if gate == "texture":
        confidence = confidence * prepared["texture_confidence"]
    elif gate == "none":
        confidence = prepared["valid"].astype(np.float32)
    elif gate != "photo":
        raise ValueError("gate must be none, photo, or texture")
    delta = np.clip(correction, -8.0 / 255.0, 8.0 / 255.0)
    value = baseline.astype(np.float32) + (255.0 * strength) * confidence[..., None] * delta
    # Round instead of truncating: an all-zero mask must preserve every pixel.
    return np.rint(np.clip(value, 0, 255)).astype(np.uint8)


def refined_cvdc(source: np.ndarray, baseline: np.ndarray, strength: float = 0.5,
                 mode: str = "replace", gate: str = "photo") -> tuple[np.ndarray, dict]:
    prepared = prepare_correspondence(source, baseline)
    result = apply_compensation(baseline, prepared, strength, mode, gate)
    metadata = {"method": "flow_aligned_confidence_limited_cvdc",
                "mode": mode, "gate": gate, "strength": strength,
                "sigma": 1.0, "correction_clip_before_strength": 8.0 / 255.0,
                "alignment_seconds": prepared["alignment_seconds"],
                "confidence_mean": float(prepared["confidence"].mean()),
                "reliable_fraction": float((prepared["confidence"] > 0.25).mean()),
                "reference_right_used": False}
    return result, metadata
