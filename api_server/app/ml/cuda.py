from __future__ import annotations

from typing import Any


def configure_cuda_inference(torch: Any) -> None:
    """Enable safe CUDA inference fast paths after a worker selects the GPU."""
    if not torch.cuda.is_available():
        return
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cuda.matmul.allow_tf32 = True
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("high")
