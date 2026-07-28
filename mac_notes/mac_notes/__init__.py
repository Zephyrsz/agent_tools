"""Read and write Apple Notes through macOS automation."""

from .client import AppleScriptRunner, NotesClient, NotesError

__all__ = ["AppleScriptRunner", "NotesClient", "NotesError"]
