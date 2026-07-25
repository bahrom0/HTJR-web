from __future__ import annotations

"""Worker-only local TrOCR + rsLoRA runtime.

The API process may validate manifests, but it must never import or allocate the
model.  This module deliberately imports torch/Transformers/PEFT lazily so the
worker is the only process that owns inference memory.
"""

import gc
import hashlib
import json
import os
import struct
import threading
import time
from dataclasses import dataclass
from math import prod
from pathlib import Path
from typing import Any

from PIL import Image


class TrocrRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TrocrArtifactStatus:
    ready: bool
    code: str
    model_version: str | None = None
    adapter_version: str | None = None
    manifest_sha256: str | None = None
    base_root: Path | None = None
    adapter_root: Path | None = None


@dataclass(frozen=True, slots=True)
class TrocrReadinessEvidence:
    model_version: str
    adapter_version: str
    manifest_sha256: str
    device: str
    dtype: str
    adapter_state_parameter_count: int
    lora_tensor_count: int
    nonzero_lora_parameter_count: int
    warmup_duration_ms: int
    warmup_generated_token_count: int


@dataclass(frozen=True, slots=True)
class TrocrGeneration:
    text: str
    duration_ms: int
    generated_token_count: int
    decoding_steps: int
    mean_token_log_probability: float | None


@dataclass(frozen=True, slots=True)
class _SafeTensorSpec:
    """One validated tensor range inside a local safetensors artifact.

    Windows can reject an mmap of the 1.3 GB base model with WinError 1455
    when the machine's commit/pagefile headroom is constrained.  The worker
    therefore reads the verified artifact one tensor at a time instead of
    mapping the whole file.  This structure is deliberately private: model
    artifacts remain the manifest-backed source of truth.
    """

    name: str
    dtype: str
    shape: tuple[int, ...]
    offset: int
    byte_size: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_artifact(root: Path, relative_path: str, expected_size: int, expected_sha256: str) -> bool:
    candidate = (root / relative_path).resolve()
    try:
        if candidate == root or root not in candidate.parents or candidate.is_symlink() or not candidate.is_file():
            return False
        return candidate.stat().st_size == expected_size and _sha256(candidate).lower() == expected_sha256.lower()
    except OSError:
        return False


def inspect_trocr_artifacts(models_root: Path) -> TrocrArtifactStatus:
    """Validate only local, manifest-backed TrOCR and rsLoRA artifacts."""
    root = models_root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return TrocrArtifactStatus(False, "trocr_artifacts_missing")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        return TrocrArtifactStatus(False, "trocr_manifest_invalid")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return TrocrArtifactStatus(False, "trocr_manifest_invalid")
    models = manifest.get("models")
    if not isinstance(models, dict):
        return TrocrArtifactStatus(False, "trocr_manifest_invalid")
    base = models.get("trocr")
    adapter = models.get("tajik_rslora")
    if not isinstance(base, dict) or not isinstance(adapter, dict):
        return TrocrArtifactStatus(False, "trocr_manifest_invalid")
    model_version = base.get("version")
    adapter_version = adapter.get("version")
    if not isinstance(model_version, str) or not model_version or not isinstance(adapter_version, str) or not adapter_version:
        return TrocrArtifactStatus(False, "trocr_manifest_invalid")
    base_root = (root / "trocr").resolve()
    adapter_root = (root / "tajik_rslora").resolve()
    for group, group_root, expected_prefix in ((base, base_root, "trocr/"), (adapter, adapter_root, "tajik_rslora/")):
        artifacts = group.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            return TrocrArtifactStatus(False, "trocr_manifest_invalid")
        for item in artifacts:
            if not isinstance(item, dict):
                return TrocrArtifactStatus(False, "trocr_manifest_invalid")
            path = item.get("path")
            size = item.get("size_bytes")
            digest = item.get("sha256")
            if (
                not isinstance(path, str)
                or not path.startswith(expected_prefix)
                or not isinstance(size, int)
                or size <= 0
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                return TrocrArtifactStatus(False, "trocr_manifest_invalid")
            relative = path.removeprefix(expected_prefix)
            if not relative or "/" in relative or "\\" in relative or not _safe_artifact(group_root, relative, size, digest):
                return TrocrArtifactStatus(False, "trocr_artifacts_corrupt", model_version, adapter_version)
    try:
        adapter_config = json.loads((adapter_root / "adapter_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return TrocrArtifactStatus(False, "rslora_config_invalid", model_version, adapter_version)
    if adapter_config.get("use_rslora") is not True:
        return TrocrArtifactStatus(False, "rslora_required", model_version, adapter_version)
    return TrocrArtifactStatus(
        True,
        "ready",
        model_version,
        adapter_version,
        hashlib.sha256(manifest_bytes).hexdigest(),
        base_root,
        adapter_root,
    )


_SAFETENSORS_DTYPES = {
    "BOOL": ("bool", 1),
    "U8": ("uint8", 1),
    "I8": ("int8", 1),
    "I16": ("int16", 2),
    "I32": ("int32", 4),
    "I64": ("int64", 8),
    "F16": ("float16", 2),
    "BF16": ("bfloat16", 2),
    "F32": ("float32", 4),
    "F64": ("float64", 8),
}


def _is_windows_pagefile_error(error: BaseException) -> bool:
    """Return true for WinError 1455 anywhere in a chained load exception."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, OSError) and getattr(current, "winerror", None) == 1455:
            return True
        current = current.__cause__ or current.__context__
    return False


def _safetensors_specs(path: Path) -> tuple[int, tuple[_SafeTensorSpec, ...]]:
    """Parse a safetensors header without opening an mmap for its data block."""
    try:
        artifact_size = path.stat().st_size
        with path.open("rb") as source:
            header_size_raw = source.read(8)
            if len(header_size_raw) != 8:
                raise TrocrRuntimeError("trocr_streaming_weights_invalid")
            header_size = struct.unpack("<Q", header_size_raw)[0]
            # The official format puts a JSON header before the data block. A
            # cap makes corrupt local artifacts fail predictably before a
            # process allocates unbounded metadata memory.
            if header_size <= 0 or header_size > 16 * 1024 * 1024 or header_size > artifact_size - 8:
                raise TrocrRuntimeError("trocr_streaming_weights_invalid")
            header_raw = source.read(header_size)
    except TrocrRuntimeError:
        raise
    except OSError as error:
        raise TrocrRuntimeError("trocr_streaming_weights_unreadable") from error

    try:
        header = json.loads(header_raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise TrocrRuntimeError("trocr_streaming_weights_invalid") from error
    if not isinstance(header, dict):
        raise TrocrRuntimeError("trocr_streaming_weights_invalid")

    data_offset = 8 + header_size
    data_size = artifact_size - data_offset
    specs: list[_SafeTensorSpec] = []
    ranges: list[tuple[int, int]] = []
    for name, metadata in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(name, str) or not name or not isinstance(metadata, dict):
            raise TrocrRuntimeError("trocr_streaming_weights_invalid")
        dtype = metadata.get("dtype")
        shape = metadata.get("shape")
        offsets = metadata.get("data_offsets")
        if (
            not isinstance(dtype, str)
            or dtype not in _SAFETENSORS_DTYPES
            or not isinstance(shape, list)
            or not all(isinstance(dimension, int) and dimension >= 0 for dimension in shape)
            or not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(offset, int) and offset >= 0 for offset in offsets)
        ):
            raise TrocrRuntimeError("trocr_streaming_weights_invalid")
        start, end = offsets
        element_count = prod(shape)
        expected_byte_size = element_count * _SAFETENSORS_DTYPES[dtype][1]
        if end < start or end > data_size or end - start != expected_byte_size:
            raise TrocrRuntimeError("trocr_streaming_weights_invalid")
        ranges.append((start, end))
        specs.append(_SafeTensorSpec(name, dtype, tuple(shape), data_offset + start, expected_byte_size))
    if not specs:
        raise TrocrRuntimeError("trocr_streaming_weights_invalid")
    previous_end = 0
    for start, end in sorted(ranges):
        if start < previous_end:
            raise TrocrRuntimeError("trocr_streaming_weights_invalid")
        previous_end = end
    return artifact_size, tuple(specs)


def _read_exactly(source: Any, byte_size: int) -> bytearray:
    payload = bytearray(byte_size)
    view = memoryview(payload)
    written = 0
    while written < byte_size:
        read = source.readinto(view[written:])
        if not isinstance(read, int) or read <= 0:
            raise TrocrRuntimeError("trocr_streaming_weights_unreadable")
        written += read
    return payload


def _stream_safetensors_state(
    path: Path,
    *,
    torch: Any,
    device: Any,
    floating_dtype: Any | None = None,
) -> dict[str, Any]:
    """Load an artifact tensor-by-tensor, retaining only the requested state.

    The returned mapping is intended for the small rsLoRA artifact.  The base
    model is assigned immediately by ``_load_windows_streamed_model`` so it
    never materializes a full Python state dict.
    """
    _artifact_size, specs = _safetensors_specs(path)
    state: dict[str, Any] = {}
    try:
        with path.open("rb") as source:
            for spec in specs:
                source.seek(spec.offset)
                payload = _read_exactly(source, spec.byte_size)
                view = memoryview(payload)
                source_dtype = getattr(torch, _SAFETENSORS_DTYPES[spec.dtype][0])
                raw = torch.frombuffer(view, dtype=source_dtype).reshape(spec.shape)
                target_dtype = floating_dtype if raw.is_floating_point() and floating_dtype is not None else source_dtype
                state[spec.name] = raw.to(device=device, dtype=target_dtype, copy=True)
                del raw, view, payload
    except TrocrRuntimeError:
        raise
    except OSError as error:
        raise TrocrRuntimeError("trocr_streaming_weights_unreadable") from error
    return state


def _assign_model_tensor(model: Any, *, name: str, value: Any, torch: Any) -> None:
    """Replace one meta parameter/buffer without constructing a state dict."""
    target = model
    for part in name.split(".")[:-1]:
        try:
            target = getattr(target, part)
        except AttributeError as error:
            raise TrocrRuntimeError("trocr_streaming_weights_model_mismatch") from error
    leaf = name.rsplit(".", 1)[-1]
    if leaf in target._parameters:
        parameter = target._parameters[leaf]
        requires_grad = bool(parameter.requires_grad) if parameter is not None else False
        target._parameters[leaf] = torch.nn.Parameter(value, requires_grad=requires_grad)
        return
    if leaf in target._buffers:
        target._buffers[leaf] = value
        return
    raise TrocrRuntimeError("trocr_streaming_weights_model_mismatch")


def _load_windows_streamed_model(
    base_root: Path,
    *,
    torch: Any,
    VisionEncoderDecoderModel: Any,
    device: Any,
    dtype: Any,
) -> Any:
    """Build TrOCR on meta and hydrate it from safetensors without mmap.

    This is deliberately Windows-specific.  On other systems the standard
    Transformers loader remains the primary, vendor-supported implementation.
    """
    weights_path = base_root / "model.safetensors"
    _artifact_size, specs = _safetensors_specs(weights_path)
    try:
        config = VisionEncoderDecoderModel.config_class.from_pretrained(base_root, local_files_only=True)
        with torch.device("meta"):
            model = VisionEncoderDecoderModel(config)
        with weights_path.open("rb") as source:
            for spec in specs:
                source.seek(spec.offset)
                payload = _read_exactly(source, spec.byte_size)
                view = memoryview(payload)
                source_dtype = getattr(torch, _SAFETENSORS_DTYPES[spec.dtype][0])
                raw = torch.frombuffer(view, dtype=source_dtype).reshape(spec.shape)
                target_dtype = dtype if raw.is_floating_point() else source_dtype
                value = raw.to(device=device, dtype=target_dtype, copy=True)
                _assign_model_tensor(model, name=spec.name, value=value, torch=torch)
                del value, raw, view, payload
        model.tie_weights()
        unresolved = [name for name, value in model.state_dict(keep_vars=True).items() if value.is_meta]
        if unresolved:
            raise TrocrRuntimeError("trocr_streaming_weights_model_mismatch")
        return model.eval()
    except TrocrRuntimeError:
        raise
    except (OSError, MemoryError) as error:
        if isinstance(error, MemoryError) or _is_windows_pagefile_error(error):
            raise TrocrRuntimeError("trocr_windows_pagefile_exhausted") from error
        raise TrocrRuntimeError("trocr_streaming_weights_unreadable") from error
    except Exception as error:
        raise TrocrRuntimeError("trocr_streaming_weights_model_mismatch") from error


def _runtime_modules() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import torch
        from peft import LoraConfig, inject_adapter_in_model, set_peft_model_state_dict
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    except ImportError as error:
        raise TrocrRuntimeError("trocr_runtime_dependencies_missing") from error
    return torch, LoraConfig, inject_adapter_in_model, set_peft_model_state_dict, (TrOCRProcessor, VisionEncoderDecoderModel)


class TrocrRuntime:
    """A serialized local TrOCR + mandatory rsLoRA runtime for one worker."""

    def __init__(self, models_root: Path, *, device: str = "auto") -> None:
        self.models_root = models_root
        self.requested_device = device
        self._lock = threading.Lock()
        self._model: Any | None = None
        self._processor: Any | None = None
        self._device: Any | None = None
        self._dtype: Any | None = None
        self._evidence: TrocrReadinessEvidence | None = None
        self._pending_evidence: tuple[TrocrArtifactStatus, int, int, int] | None = None

    def artifact_status(self) -> TrocrArtifactStatus:
        return inspect_trocr_artifacts(self.models_root)

    @property
    def evidence(self) -> TrocrReadinessEvidence | None:
        return self._evidence

    def load(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        status = self.artifact_status()
        if not status.ready or status.base_root is None or status.adapter_root is None:
            raise TrocrRuntimeError(status.code)
        torch, LoraConfig, inject_adapter_in_model, set_peft_model_state_dict, transformer_types = _runtime_modules()
        TrOCRProcessor, VisionEncoderDecoderModel = transformer_types
        wants_cuda = self.requested_device == "cuda" or (self.requested_device == "auto" and torch.cuda.is_available())
        if self.requested_device == "cuda" and not torch.cuda.is_available():
            raise TrocrRuntimeError("trocr_cuda_unavailable")
        self._device = torch.device("cuda" if wants_cuda else "cpu")
        # The base model occupies about 1.34 GB in F32.  Windows hosts with a
        # constrained commit/pagefile budget can still fail after avoiding the
        # safetensors mmap if the complete F32 model remains resident.  CPU
        # FP16 is exercised by the local verification path and keeps the
        # model's resident parameter storage roughly half that size.  Other
        # platforms preserve F32 CPU behavior.
        self._dtype = torch.float16 if wants_cuda or os.name == "nt" else torch.float32
        adapter_state = None
        try:
            # The approved adapter manifest does not include merges.txt.  The
            # base artifact does, so the processor is deliberately sourced from
            # the verified base-model copy rather than falling back to network.
            processor = TrOCRProcessor.from_pretrained(status.base_root, local_files_only=True, use_fast=False)
            if os.name == "nt":
                # safetensors.safe_open maps the complete 1.3 GB base file.
                # On Windows this can fail with WinError 1455 before any model
                # tensor is usable.  Hydrate the verified file one tensor at a
                # time into a meta model instead.
                model = _load_windows_streamed_model(
                    status.base_root,
                    torch=torch,
                    VisionEncoderDecoderModel=VisionEncoderDecoderModel,
                    device=self._device,
                    dtype=self._dtype,
                )
            else:
                model = VisionEncoderDecoderModel.from_pretrained(
                    status.base_root,
                    local_files_only=True,
                    low_cpu_mem_usage=True,
                    use_safetensors=True,
                )
            adapter_config = LoraConfig.from_pretrained(status.adapter_root, local_files_only=True)
            if getattr(adapter_config, "use_rslora", False) is not True:
                raise TrocrRuntimeError("rslora_required")
            adapter_state = _stream_safetensors_state(
                status.adapter_root / "adapter_model.safetensors",
                torch=torch,
                device=torch.device("cpu"),
            )
            inject_adapter_in_model(adapter_config, model, low_cpu_mem_usage=False)
            set_peft_model_state_dict(model, adapter_state)
            lora_parameters = [parameter for name, parameter in model.named_parameters() if "lora_" in name]
            if not lora_parameters:
                raise TrocrRuntimeError("rslora_parameters_missing")
            nonzero = sum(int(torch.count_nonzero(parameter.detach()).item()) for parameter in lora_parameters)
            if nonzero == 0:
                raise TrocrRuntimeError("rslora_parameters_zero")
            tokenizer = processor.tokenizer
            for config in (model.config, model.generation_config):
                config.decoder_start_token_id = tokenizer.eos_token_id
                config.pad_token_id = tokenizer.pad_token_id
                config.eos_token_id = tokenizer.eos_token_id
            model.config.use_cache = True
            model.decoder.config.use_cache = True
            # The streaming path has already materialized every tensor on the
            # requested device and dtype.  Avoid a model-wide conversion here:
            # it would temporarily duplicate the full base model and defeat
            # the pagefile-safe loading guarantee.
            if os.name != "nt":
                model = model.to(device=self._device, dtype=self._dtype)
            model = model.eval()
        except TrocrRuntimeError:
            self.close()
            raise
        except (OSError, MemoryError) as error:
            self.close()
            if isinstance(error, MemoryError) or _is_windows_pagefile_error(error):
                raise TrocrRuntimeError("trocr_windows_pagefile_exhausted") from error
            raise TrocrRuntimeError("trocr_model_load_failed") from error
        except Exception as error:
            self.close()
            raise TrocrRuntimeError("trocr_model_load_failed") from error
        adapter_parameter_count = sum(int(parameter.numel()) for parameter in adapter_state.values())
        del adapter_state
        self._model = model
        self._processor = processor
        self._pending_evidence = (status, adapter_parameter_count, len(lora_parameters), nonzero)

    def warmup(self) -> TrocrReadinessEvidence:
        self.load()
        assert self._model is not None and self._processor is not None and self._device is not None and self._dtype is not None
        torch, *_ = _runtime_modules()
        if self._pending_evidence is None:
            raise TrocrRuntimeError("trocr_readiness_evidence_missing")
        status, adapter_parameter_count, lora_tensor_count, nonzero = self._pending_evidence
        started = time.perf_counter()
        sample = Image.new("RGB", (384, 64), "white")
        inputs = pixel_values = generated = None
        try:
            inputs = self._processor(images=sample, return_tensors="pt")
            pixel_values = inputs.pixel_values.to(device=self._device, dtype=self._dtype)
            with self._lock, torch.inference_mode():
                generated = self._model.generate(pixel_values, num_beams=1, max_new_tokens=4)
                if self._device.type == "cuda":
                    torch.cuda.synchronize(self._device)
            token_count = int(generated.shape[-1])
        except Exception as error:
            raise TrocrRuntimeError("trocr_warmup_generate_failed") from error
        finally:
            del inputs, pixel_values, generated
            self._cleanup_memory()
        self._evidence = TrocrReadinessEvidence(
            model_version=status.model_version or "unknown",
            adapter_version=status.adapter_version or "unknown",
            manifest_sha256=status.manifest_sha256 or "",
            device=str(self._device),
            dtype=str(self._dtype).removeprefix("torch."),
            adapter_state_parameter_count=adapter_parameter_count,
            lora_tensor_count=lora_tensor_count,
            nonzero_lora_parameter_count=nonzero,
            warmup_duration_ms=round((time.perf_counter() - started) * 1000),
            warmup_generated_token_count=token_count,
        )
        return self._evidence

    def recognize(self, image: Image.Image, *, num_beams: int, max_new_tokens: int) -> TrocrGeneration:
        if not 1 <= num_beams <= 4 or not 1 <= max_new_tokens <= 256:
            raise TrocrRuntimeError("trocr_generation_settings_invalid")
        self.load()
        assert self._model is not None and self._processor is not None and self._device is not None and self._dtype is not None
        torch, *_ = _runtime_modules()
        started = time.perf_counter()
        inputs = pixel_values = output = None
        try:
            inputs = self._processor(images=image.convert("RGB"), return_tensors="pt")
            pixel_values = inputs.pixel_values.to(device=self._device, dtype=self._dtype)
            with self._lock, torch.inference_mode():
                output = self._model.generate(
                    pixel_values,
                    num_beams=num_beams,
                    max_new_tokens=max_new_tokens,
                    return_dict_in_generate=True,
                    output_scores=True,
                )
                if self._device.type == "cuda":
                    torch.cuda.synchronize(self._device)
            text = self._processor.batch_decode(output.sequences, skip_special_tokens=True)[0].strip()
            mean_token_log_probability = None
            if output.scores:
                try:
                    transition_scores = self._model.compute_transition_scores(
                        output.sequences,
                        output.scores,
                        beam_indices=getattr(output, "beam_indices", None),
                        normalize_logits=True,
                    )
                    generated_scores = transition_scores[0, -len(output.scores):]
                    mean_token_log_probability = float(generated_scores.detach().float().mean().cpu().item())
                except Exception:
                    # The generated text remains valid even when a Transformers
                    # version does not expose transition-score reconstruction.
                    mean_token_log_probability = None
            return TrocrGeneration(
                text=text,
                duration_ms=round((time.perf_counter() - started) * 1000),
                generated_token_count=int(output.sequences.shape[-1]),
                decoding_steps=len(output.scores or ()),
                mean_token_log_probability=mean_token_log_probability,
            )
        except TrocrRuntimeError:
            raise
        except Exception as error:
            raise TrocrRuntimeError("trocr_generate_failed") from error
        finally:
            del inputs, pixel_values, output
            self._cleanup_memory()

    def _cleanup_memory(self) -> None:
        try:
            torch, *_ = _runtime_modules()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except TrocrRuntimeError:
            pass
        gc.collect()

    def close(self) -> None:
        model, self._model = self._model, None
        self._processor = None
        self._evidence = None
        self._pending_evidence = None
        if model is not None:
            del model
        self._cleanup_memory()
