# -*- coding: utf-8 -*-
"""本地句向量。模型文件不进 git，缺了就返回 None，调用方改用词向量。"""
from __future__ import print_function

import os

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(ROOT, "models", "bge-small-zh-v1.5")
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
MAX_LEN = 256

_ENCODER = None
_FAILED = False


def model_ready():
    return os.path.isfile(os.path.join(MODEL_DIR, "model_quantized.onnx")) and os.path.isfile(
        os.path.join(MODEL_DIR, "tokenizer.json")
    )


def _load():
    global _ENCODER, _FAILED
    if _ENCODER is not None or _FAILED:
        return _ENCODER
    if not model_ready():
        _FAILED = True
        return None
    try:
        import numpy
        import onnxruntime
        from tokenizers import Tokenizer
    except ImportError:
        _FAILED = True
        return None
    try:
        tokenizer = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        tokenizer.enable_truncation(max_length=MAX_LEN)
        session = onnxruntime.InferenceSession(
            os.path.join(MODEL_DIR, "model_quantized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        _ENCODER = (tokenizer, session, numpy)
        return _ENCODER
    except Exception:
        _FAILED = True
        return None


def embed(text, is_query):
    loaded = _load()
    if loaded is None:
        return None
    tokenizer, session, numpy = loaded
    raw = (QUERY_PREFIX + text) if is_query else (text or "")
    encoded = tokenizer.encode(raw[:4000])
    ids = numpy.array([encoded.ids], dtype=numpy.int64)
    mask = numpy.array([encoded.attention_mask], dtype=numpy.int64)
    types = numpy.zeros_like(ids)
    hidden = session.run(
        None,
        {"input_ids": ids, "attention_mask": mask, "token_type_ids": types},
    )[0]
    # bge 用 CLS，不用平均池化。平均池化会把不相关的句子挤到同一带分数。
    pooled = hidden[:, 0]
    norm = numpy.linalg.norm(pooled, axis=1, keepdims=True)
    pooled = pooled / numpy.clip(norm, 1e-9, None)
    return [float(v) for v in pooled[0]]


def engine_name():
    if embed("测", False) is None:
        return "hash"
    return "bge"
