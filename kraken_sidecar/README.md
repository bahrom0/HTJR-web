# Kraken line-segmentation sidecar

Kraken is officially supported on Linux/macOS. This sidecar keeps it in the
existing Ubuntu WSL2 installation and exposes only two loopback endpoints:

- `GET /health` — loaded model and real warmup evidence;
- `POST /detect` — image bytes in, ordered baseline and boundary polygons out.

The default bundled BLLA model is intentionally used before fine-tuning so its
output can be preserved as the project baseline.

Initial setup from PowerShell:

```powershell
wsl.exe -d Ubuntu -- bash -lc "cd '/mnt/c/Users/bahro/OneDrive/Desktop/HTR App X Server/kraken_sidecar' && bash setup-wsl.sh"
```

The default installs the smaller CPU build, which is sufficient for preserving
the pre-fine-tuning BLLA baseline. Before GPU training, replace the setup
command with:

```powershell
wsl.exe -d Ubuntu -- bash -lc "cd '/mnt/c/Users/bahro/OneDrive/Desktop/HTR App X Server/kraken_sidecar' && KRAKEN_TORCH_FLAVOR=cu128 bash setup-wsl.sh"
```

Normal startup is handled by the root `start.bat` launcher whenever
`api_server/config.toml` contains `CRAFT = false`. The launcher validates the
isolated WSL environment before starting the sidecar. It does not download
packages automatically: if the environment is absent or `CUDA = true` requires
the CUDA build, the launcher prints the exact setup command for the user.
