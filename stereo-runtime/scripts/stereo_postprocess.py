"""Bounded postprocessing for the selected appearance-aligned multiband method."""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from cvdc_multiband_geometry import multiband_reconstruct, prepare_multiband

DEFAULT_POSTPROCESS = "legacy_high_frequency"
POSTPROCESS_METHODS = (DEFAULT_POSTPROCESS, "appearance_multiband", "baseline")


def postprocess_right(
    source: np.ndarray,
    baseline: np.ndarray,
    method: str,
    legacy_strength: float = 0.5,
    legacy_sigma: float = 1.0,
) -> tuple[np.ndarray, dict[str, Any], np.ndarray | None]:
    if method not in POSTPROCESS_METHODS:
        raise ValueError(f"Unsupported stereo postprocess method: {method}")
    if (
        source.shape != baseline.shape or source.ndim != 3 or source.shape[2] != 3
        or source.dtype != np.uint8 or baseline.dtype != np.uint8
    ):
        raise ValueError("Expected equally sized uint8 RGB images")
    if method == "baseline":
        return baseline.copy(), {
            "method": "baseline",
            "reference_right_used": False,
        }, None
    if method == "legacy_high_frequency":
        from mono2stereo_runtime_utils import add_high_frequency

        return add_high_frequency(
            baseline, source, legacy_strength, sigma=legacy_sigma
        ), {
            "method": "legacy_high_frequency",
            "strength": legacy_strength,
            "sigma": legacy_sigma,
            "reference_right_used": False,
        }, None

    # Match the frozen comparison's OpenCV settings in the image worker.
    cv2.setNumThreads(1)
    prepared = prepare_multiband(source, baseline, disparity=None)
    result = multiband_reconstruct(
        baseline,
        prepared,
        alignment="flow",
        low=0.5,
        mid=0.5,
        high=1.0,
        high_mode="replace",
    )
    confidence = prepared["flow_confidence"]
    return result, {
        "method": "appearance_multiband",
        "method_version": "flow_band_v1",
        "alignment": "horizontal_appearance_correspondence",
        "low_strength": 0.5,
        "mid_strength": 0.5,
        "high_strength": 1.0,
        "high_mode": "replace",
        "confidence_mean": float(confidence.mean()),
        "supported_fraction": float((confidence > 0).mean()),
        "reference_right_used": False,
        "physical_geometry_guaranteed": False,
    }, np.rint(255 * confidence).astype(np.uint8)
