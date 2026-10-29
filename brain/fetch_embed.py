# -*- coding: utf-8 -*-
"""下载本地句向量模型到 brain/models。不进 git。失败时大脑仍用词向量。"""
from __future__ import print_function

import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(ROOT, "models", "bge-small-zh-v1.5")


def main():
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from huggingface_hub import hf_hub_download

    if not os.path.isdir(DEST):
        os.makedirs(DEST)
    for name in ("onnx/model_quantized.onnx", "tokenizer.json"):
        path = hf_hub_download("Xenova/bge-small-zh-v1.5", name, local_dir=DEST)
        print("got", path, os.path.getsize(path))
    src = os.path.join(DEST, "onnx", "model_quantized.onnx")
    flat = os.path.join(DEST, "model_quantized.onnx")
    if os.path.isfile(src):
        shutil.copyfile(src, flat)
        print("ready", flat, os.path.getsize(flat))


if __name__ == "__main__":
    main()
