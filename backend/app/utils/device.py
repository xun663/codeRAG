"""Unified device detection for model inference.

Centralises CUDA / CPU detection so all modules (embedding, reranker, etc.)
use the same logic and can be toggled globally from one place.

Usage::

    from app.utils.device import get_device

    device = get_device()               # "cuda" or "cpu"
    model = SentenceTransformer(..., device=device)
"""
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_device() -> str:
    """Detect the best available compute device.

    Returns ``"cuda"`` when a NVIDIA GPU is available and PyTorch was built
    with CUDA support; ``"cpu"`` otherwise (including Apple MPS — not used
    on this Windows/Linux target, but harmless).

    The result is cached after the first call, so repeated imports are free.
    """
    try:
        import torch

        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            logger.info(
                "CUDA device detected: %s (using cuda)", device_name,
            )
            return "cuda"

        # Apple Metal (not typical for this project, but handled)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("MPS device detected (using mps)")
            return "mps"
    except ImportError:
        logger.debug("torch not installed; falling back to cpu")
    except Exception:
        logger.exception("Device detection error; falling back to cpu")

    logger.info("No GPU detected; using cpu")
    return "cpu"


def is_cuda_available() -> bool:
    """Convenience predicate — shorthand for ``get_device() == "cuda"``."""
    return get_device() == "cuda"
