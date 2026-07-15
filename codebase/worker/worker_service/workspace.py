import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4


class HlsWorkspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def output_directory(self, live_id: UUID, generation: int) -> Path:
        if generation < 1:
            raise ValueError("Worker generation must be greater than zero")
        live_directory = self.root / str(live_id)
        output = live_directory / f"g-{generation}"
        if live_directory.is_symlink() or output.is_symlink():
            raise ValueError("HLS live and generation directories cannot be symlinks")
        try:
            output.relative_to(self.root)
        except ValueError as error:
            raise ValueError("HLS output must remain inside the configured root") from error
        return output

    def prepare(self, live_id: UUID, generation: int) -> Path:
        output = self.output_directory(live_id, generation)
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        return output

    def manifest(self, live_id: UUID, generation: int) -> Path:
        return self.output_directory(live_id, generation) / "index.m3u8"

    def activate(self, live_id: UUID, generation: int) -> Path:
        output = self.output_directory(live_id, generation)
        manifest = output / "index.m3u8"
        if not manifest.is_file() or manifest.stat().st_size == 0:
            raise FileNotFoundError("HLS manifest is not ready")
        temporary_link = output.parent / f".current-{uuid4().hex}"
        current_link = output.parent / "current"
        try:
            os.symlink(output.name, temporary_link, target_is_directory=True)
            os.replace(temporary_link, current_link)
        finally:
            if temporary_link.is_symlink():
                temporary_link.unlink()
        return current_link / "index.m3u8"