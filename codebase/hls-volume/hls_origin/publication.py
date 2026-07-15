import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4


class HlsPublication:
    def __init__(
        self,
        root: Path,
        *,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._id_factory = id_factory or uuid4

    def generation_directory(self, live_id: UUID, generation: int) -> Path:
        if generation < 1:
            raise ValueError("HLS generation must be greater than zero")
        live_directory = self._root / str(live_id)
        directory = live_directory / f"g-{generation}"
        if live_directory.is_symlink() or directory.is_symlink():
            raise ValueError("HLS live and generation directories cannot be symlinks")
        try:
            directory.relative_to(self._root)
        except ValueError as error:
            raise ValueError("HLS generation must remain inside the volume") from error
        return directory

    def activate(self, live_id: UUID, generation: int) -> Path:
        generation_directory = self.generation_directory(live_id, generation)
        manifest = generation_directory / "index.m3u8"
        if not manifest.is_file() or manifest.stat().st_size == 0:
            raise FileNotFoundError("HLS generation does not contain a ready manifest")

        live_directory = generation_directory.parent
        live_directory.mkdir(parents=True, exist_ok=True)
        temporary_link = live_directory / f".current-{self._id_factory().hex}"
        current_link = live_directory / "current"
        try:
            os.symlink(
                generation_directory.name,
                temporary_link,
                target_is_directory=True,
            )
            os.replace(temporary_link, current_link)
        finally:
            if temporary_link.is_symlink():
                temporary_link.unlink()
        return current_link / "index.m3u8"