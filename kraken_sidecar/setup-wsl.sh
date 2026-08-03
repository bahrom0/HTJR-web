#!/usr/bin/env bash
set -euo pipefail

runtime_root="${HOME}/.local/share/tajik-htr/kraken-7.0.3"
bootstrap_root="${HOME}/.cache/tajik-htr/bootstrap"
mkdir -p "${runtime_root}" "${bootstrap_root}"

if ! python3 -m virtualenv --version >/dev/null 2>&1; then
  pip_zip="${bootstrap_root}/pip.pyz"
  if [[ ! -f "${pip_zip}" ]]; then
    python3 - "${pip_zip}" <<'PY'
import pathlib
import sys
import urllib.request

target = pathlib.Path(sys.argv[1])
with urllib.request.urlopen("https://bootstrap.pypa.io/pip/pip.pyz", timeout=60) as response:
    target.write_bytes(response.read())
PY
  fi
  python3 "${pip_zip}" install --user --break-system-packages "virtualenv==20.35.4"
fi

python3 -m virtualenv "${runtime_root}/venv"
torch_flavor="${KRAKEN_TORCH_FLAVOR:-cpu}"
case "${torch_flavor}" in
  cpu)
    torch_index="https://download.pytorch.org/whl/cpu"
    torch_version="2.11.0+cpu"
    torchvision_version="0.26.0+cpu"
    ;;
  cu128)
    torch_index="https://download.pytorch.org/whl/cu128"
    torch_version="2.11.0+cu128"
    torchvision_version="0.26.0+cu128"
    ;;
  *)
    printf 'Unsupported KRAKEN_TORCH_FLAVOR: %s\n' "${torch_flavor}" >&2
    exit 2
    ;;
esac
"${runtime_root}/venv/bin/python" -m pip install \
  --index-url "${torch_index}" \
  "torch==${torch_version}" "torchvision==${torchvision_version}"
"${runtime_root}/venv/bin/python" -m pip install -r "$(dirname "$0")/requirements.txt"
"${runtime_root}/venv/bin/python" -c \
  'from importlib.metadata import version; import PIL, kraken, torch; assert version("kraken") == "7.0.3"; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")'

printf '%s\n' "${runtime_root}/venv/bin/python"
