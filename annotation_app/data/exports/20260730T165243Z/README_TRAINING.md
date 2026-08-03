# Kraken segmentation training export

This export contains PAGE XML line boundaries and baseline polylines.
Run the command from this export directory inside the Kraken WSL environment:

```bash
"${HOME}/.local/share/tajik-htr/kraken-7.0.3/venv/bin/ketos" --config experiment.yml segtrain
```

`region_class_mapping: []` intentionally trains line baselines only. Rectangle
boundaries remain available to Kraken for line extraction and evaluation.
