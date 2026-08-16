"""
FastEmbed ONNX embedding 包装类。
接口兼容 _HashEmbedder：model.encode(texts) → np.ndarray (n, 384)

模型文件位置：~/.cache/fastembed/local_models/bge-small-en-v1.5/
通过 specific_model_path 参数加载，避免联网下载。
"""
import os
from typing import List

import numpy as np

DEFAULT_MODEL_DIR = os.path.expanduser("~/.cache/fastembed/local_models/bge-small-en-v1.5")


class FastEmbedEmbeddings:
    """
    基于 FastEmbed 的 ONNX embedding，接口与 _HashEmbedder 完全兼容。

    FastEmbed 使用 ONNX Runtime 推理，无需 PyTorch。
    模型通过 specific_model_path 从本地加载，无需联网。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5",
                 model_dir: str = DEFAULT_MODEL_DIR):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name, specific_model_path=model_dir)
        self._dim = 384  # bge-small-en-v1.5 固定 384 维

    @property
    def dim(self) -> int:
        return self._dim

    def encode(self, texts: List[str]) -> np.ndarray:
        """
        将文本列表转为 embedding 向量矩阵。

        Args:
            texts: 文本列表

        Returns:
            ndarray of shape (len(texts), dim)
        """
        embeddings = list(self._model.embed(texts))
        return np.stack(embeddings)
