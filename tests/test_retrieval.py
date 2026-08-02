import json
from pathlib import Path

from footage_search.retrieval import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_MARKER,
    MODEL_REVISION,
    install_model,
    model_is_installed,
)


def test_completed_model_install_never_calls_hugging_face(monkeypatch, tmp_path: Path):
    for filename in MODEL_FILES:
        (tmp_path / filename).write_bytes(b"installed")
    (tmp_path / MODEL_MARKER).write_text(
        json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION}), encoding="utf-8"
    )

    def unexpected_download(**kwargs):
        raise AssertionError("Hugging Face should not be contacted for an installed model")

    monkeypatch.setattr("huggingface_hub.snapshot_download", unexpected_download)
    assert model_is_installed(tmp_path)
    install_model(tmp_path)
