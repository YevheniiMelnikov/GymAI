import hashlib
import re
from pathlib import Path
from typing import ClassVar


class StorageResolver:
    _MD5_TO_SHA: ClassVar[dict[str, str]] = {}

    @staticmethod
    def is_md5_filename(name: str) -> bool:
        return bool(re.match(r"^text_[0-9a-f]{32}\.txt$", name))

    @classmethod
    def map_md5_to_sha_path(cls, md5_name: str, storage_root: Path) -> Path | None:
        md5_match = re.match(r"^text_([0-9a-f]{32})\.txt$", md5_name)
        if not md5_match:
            return None
        md5_digest = md5_match.group(1)
        sha_digest = cls._MD5_TO_SHA.get(md5_digest)
        if sha_digest:
            return storage_root / f"text_{sha_digest}.txt"
        return None

    @classmethod
    async def build_md5_to_sha_index(cls, storage_root: Path) -> None:
        cls._MD5_TO_SHA.clear()
        if not storage_root.exists():
            return
        for path in storage_root.glob("text_*.txt"):
            sha_match = re.match(r"^text_([0-9a-f]{64})\.txt$", path.name)
            if sha_match:
                sha_digest = sha_match.group(1)
                try:
                    content = await path.read_text(encoding="utf-8")
                    md5_digest = hashlib.md5(content.encode("utf-8")).hexdigest()
                    cls._MD5_TO_SHA[md5_digest] = sha_digest
                except Exception:  # noqa: BLE001
                    pass
