#!/usr/bin/env bash
set -euo pipefail

expected_device="${1:-any}"
runtime_python="${HOME}/.local/share/tajik-htr/kraken-7.0.3/venv/bin/python"

test -x "${runtime_python}"
"${runtime_python}" - "${expected_device}" <<'PY'
from importlib import metadata, resources
from pathlib import Path
import sys

import PIL
import kraken
import torch
from kraken.configs import SegmentationInferenceConfig
from kraken.tasks import SegmentationTaskModel

if metadata.version("kraken") != "7.0.3":
    raise SystemExit("kraken_version_mismatch")
if metadata.version("pillow") != "12.2.0":
    raise SystemExit("pillow_version_mismatch")
if not Path(resources.files("kraken").joinpath("blla.mlmodel")).is_file():
    raise SystemExit("kraken_blla_model_missing")
if sys.argv[1] == "cuda:0" and not torch.cuda.is_available():
    raise SystemExit("kraken_cuda_unavailable")

print(
    f"kraken={metadata.version('kraken')} "
    f"torch={torch.__version__} "
    f"device={'cuda:0' if torch.cuda.is_available() else 'cpu'}"
)
PY
