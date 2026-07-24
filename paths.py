"""One shared path-traversal guard.

Workspace-relative paths coming from model output (the files tool, run_python,
extract_files) must never escape their run's directory — a symlink or a `../`
sequence would let a hallucinating agent read or clobber the rest of the disk.
This check lived in three separate copies (engine, tools ×2); a fix to one
didn't reach the others. Now there is exactly one implementation to audit.
"""
import os


def safe_join(root: str, rel: str) -> str:
    """Resolve `rel` under `root`, raising ValueError if it escapes.

    Uses realpath on both sides so symlinks can't tunnel out. Returns the
    absolute, real path when it is `root` itself or a descendant of it.
    """
    full = os.path.realpath(os.path.join(root, (rel or "").lstrip("/")))
    real_root = os.path.realpath(root)
    if full != real_root and not full.startswith(real_root + os.sep):
        raise ValueError("path escapes workspace")
    return full
