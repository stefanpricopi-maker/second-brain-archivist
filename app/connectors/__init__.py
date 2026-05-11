from app.connectors.base import ArchiveResult, ArchiveSink
from app.connectors.browser_download import BrowserDownloadSink
from app.connectors.obsidian_local import ObsidianVaultSink
from app.connectors.stub import StubArchiveSink

__all__ = [
    "ArchiveResult",
    "ArchiveSink",
    "BrowserDownloadSink",
    "ObsidianVaultSink",
    "StubArchiveSink",
]
