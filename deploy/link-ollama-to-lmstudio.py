#!/usr/bin/env python3
"""Expose every Ollama model to LM Studio WITHOUT copying it.

There is one model store on this machine: ~/.ollama/models (or $OLLAMA_MODELS).
This walks its manifests and symlinks each model's GGUF weight blob into
~/.lmstudio/models/ollama/<name>-<tag>/<name>-<tag>.gguf. Re-run after pulls;
stale links (blob deleted by `ollama rm`) are removed. Zero extra disk.
"""
import json
import os
import sys

store = os.environ.get("OLLAMA_MODELS", os.path.expanduser("~/.ollama/models"))
dest = os.path.expanduser("~/.lmstudio/models/ollama")
lib = os.path.join(store, "manifests", "registry.ollama.ai", "library")
if not os.path.isdir(lib):
    sys.exit(f"no Ollama manifests at {lib}")

linked = 0
for name in sorted(os.listdir(lib)):
    for tag in sorted(os.listdir(os.path.join(lib, name))):
        with open(os.path.join(lib, name, tag)) as f:
            layers = json.load(f).get("layers", [])
        model = next((l for l in layers if l.get("mediaType") == "application/vnd.ollama.image.model"), None)
        if not model:
            continue
        blob = os.path.join(store, "blobs", model["digest"].replace(":", "-"))
        if not os.path.isfile(blob):
            continue
        slug = f"{name}-{tag}".replace(":", "-")
        os.makedirs(os.path.join(dest, slug), exist_ok=True)
        link = os.path.join(dest, slug, slug + ".gguf")
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(blob, link)
        linked += 1

removed = 0
for root, _dirs, files in os.walk(dest):
    for fn in files:
        p = os.path.join(root, fn)
        if os.path.islink(p) and not os.path.exists(p):
            os.remove(p)
            removed += 1
print(f"linked {linked} models from {store} into {dest}; removed {removed} stale links")
