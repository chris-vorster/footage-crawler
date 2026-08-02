from __future__ import annotations

import logging
import json
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_ID = "google/siglip2-base-patch16-224"
MODEL_REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
MODEL_DIRECTORY_NAME = f"siglip2-base-patch16-224-{MODEL_REVISION[:8]}"
MODEL_MARKER = ".footage-crawler-model.json"
MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
logger = logging.getLogger(__name__)


def model_is_installed(model_path: Path) -> bool:
    marker = model_path / MODEL_MARKER
    try:
        metadata = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return False
    return (
        metadata == {"model_id": MODEL_ID, "revision": MODEL_REVISION}
        and all((model_path / filename).is_file() for filename in MODEL_FILES)
    )


def install_model(model_path: Path) -> None:
    """Install the pinned snapshot once, then leave startup entirely offline."""
    if model_is_installed(model_path):
        logger.info("Using installed visual model: path=%s", model_path)
        return

    from huggingface_hub import snapshot_download

    started = time.perf_counter()
    model_path.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Installing visual model for first use: id=%s revision=%s path=%s",
        MODEL_ID,
        MODEL_REVISION,
        model_path,
    )
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=model_path,
        allow_patterns=["*.json", "*.safetensors"],
    )
    missing = [filename for filename in MODEL_FILES if not (model_path / filename).is_file()]
    if missing:
        raise RuntimeError(f"Visual model installation is incomplete: missing {', '.join(missing)}")
    (model_path / MODEL_MARKER).write_text(
        json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION}),
        encoding="utf-8",
    )
    logger.info("Visual model installed in %.2fs: path=%s", time.perf_counter() - started, model_path)


class VisualRetriever:
    def __init__(self, model_path: Path, device: str | None = None):
        started = time.perf_counter()
        import torch
        from transformers import AutoModel, AutoProcessor, AutoTokenizer

        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device = device
        self.torch = torch
        self.lock = threading.Lock()
        local_model = str(model_path)
        logger.info("Opening installed model: path=%s device=%s", model_path, device)
        self.processor = AutoProcessor.from_pretrained(local_model, local_files_only=True)
        self.tokenizer = AutoTokenizer.from_pretrained(local_model, local_files_only=True)
        self.model = AutoModel.from_pretrained(local_model, local_files_only=True).to(device).eval()
        logger.info("Model snapshot opened in %.2fs", time.perf_counter() - started)

    @staticmethod
    def _normalise(tensor) -> np.ndarray:
        if hasattr(tensor, "pooler_output"):
            tensor = tensor.pooler_output
        tensor = tensor / tensor.norm(dim=-1, keepdim=True)
        return tensor.detach().float().cpu().numpy()

    def embed_images(self, paths: list[Path]) -> np.ndarray:
        started = time.perf_counter()
        images = []
        for path in paths:
            with Image.open(path) as image:
                images.append(image.convert("RGB"))
        with self.lock, self.torch.inference_mode():
            inputs = self.processor(images=images, return_tensors="pt").to(self.device)
            features = self.model.get_image_features(**inputs)
        embeddings = self._normalise(features)
        logger.debug("Embedded %d images in %.3fs", len(paths), time.perf_counter() - started)
        return embeddings

    def embed_text(self, query: str) -> np.ndarray:
        started = time.perf_counter()
        with self.lock, self.torch.inference_mode():
            inputs = self.tokenizer(
                [query], padding="max_length", max_length=64, truncation=True, return_tensors="pt"
            ).to(self.device)
            features = self.model.get_text_features(**inputs)
        embedding = self._normalise(features)[0]
        logger.info("Encoded search text in %.3fs", time.perf_counter() - started)
        return embedding
