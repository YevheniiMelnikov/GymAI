import importlib
import os
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from loguru import logger

from config.app_settings import settings


def _directory_snapshot(path: Path, limit: int = 10) -> tuple[list[str], int]:
    try:
        entries: list[str] = []
        count = 0
        for item in path.iterdir():
            count += 1
            if len(entries) < limit:
                entries.append(item.name)
        return entries, count
    except FileNotFoundError:
        return [], 0
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"cognee_storage_snapshot_failed path={path} detail={exc}")
        return [], 0


def _package_storage_candidates() -> list[Path]:
    try:
        module = importlib.import_module("cognee")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"cognee_package_lookup_failed detail={exc}")
        return []

    module_file = getattr(module, "__file__", None)
    if not module_file:
        return []
    base_dir = Path(module_file).resolve().parent
    names = ("cognee_storage", ".data_storage")
    candidates: list[Path] = []
    seen: set[str] = set()
    for name in names:
        candidate = base_dir / name
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def collect_storage_info(root: Path | None) -> dict[str, Any]:
    package_candidates = _package_storage_candidates()
    package_storage: Path | None = package_candidates[0] if package_candidates else None
    package_exists = False
    package_is_symlink = False
    package_target: str | None = None
    for candidate in package_candidates:
        exists = False
        is_symlink = False
        try:
            exists = candidate.exists()
            is_symlink = candidate.is_symlink()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"cognee_storage_stat_failed path={candidate} detail={exc}")
        if exists or is_symlink:
            package_storage = candidate
            package_exists = exists or is_symlink
            package_is_symlink = is_symlink
            try:
                package_target = str(candidate.resolve(strict=False))
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"cognee_storage_readlink_failed path={candidate} detail={exc}")
            break
    if package_target is None and package_storage is not None:
        try:
            package_target = str(package_storage.resolve(strict=False))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"cognee_storage_resolve_failed path={package_storage} detail={exc}")

    entries_sample: list[str]
    entries_count: int
    if isinstance(root, Path) and root.exists():
        entries_sample, entries_count = _directory_snapshot(root)
    else:
        entries_sample, entries_count = [], 0

    root_exists = root.exists() if isinstance(root, Path) else False
    root_writable = os.access(root, os.W_OK) if isinstance(root, Path) else False

    return {
        "root": str(root) if isinstance(root, Path) else None,
        "root_exists": root_exists,
        "root_writable": root_writable,
        "entries_sample": entries_sample,
        "entries_count": entries_count,
        "package_path": str(package_storage) if package_storage is not None else None,
        "package_exists": package_exists,
        "package_is_symlink": package_is_symlink,
        "package_target": package_target,
        "package_candidates": [str(candidate) for candidate in package_candidates],
    }


def log_storage_details(root: Path) -> None:
    info = collect_storage_info(root)
    logger.debug(
        "cognee_storage prepared path={} exists={} writable={} entries={} sample={} "
        "package_path={} package_exists={} package_is_symlink={} package_target={}",
        info["root"],
        info["root_exists"],
        info["root_writable"],
        info["entries_count"],
        info["entries_sample"],
        info["package_path"],
        info["package_exists"],
        info["package_is_symlink"],
        info["package_target"],
    )


def prepare_storage_root() -> Path:
    storage_candidate = (
        os.environ.get("COGNEE_STORAGE_PATH") or os.environ.get("COGNEE_DATA_ROOT") or settings.COGNEE_STORAGE_PATH
    )
    root = Path(storage_candidate).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for sub in (".cognee_system/databases", ".cognee_system/vectordb"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    os.environ["COGNEE_STORAGE_PATH"] = str(root)
    os.environ["COGNEE_DATA_ROOT"] = str(root)
    log_storage_details(root)
    return root


def _resolve_localfilestorage_class() -> Optional[type[Any]]:
    module_candidates = (
        "cognee.infrastructure.files.storage.LocalFileStorage",
        "cognee.infrastructure.files.storage.local_file_storage",
        "cognee.infrastructure.files.storage",
    )
    for module_path in module_candidates:
        try:
            module = import_module(module_path)
        except Exception:
            continue
        if isinstance(module, ModuleType):
            candidate = getattr(module, "LocalFileStorage", None)
            if isinstance(candidate, type):
                return candidate
    return None


def patch_local_file_storage(root: Path) -> None:
    local_storage_cls = _resolve_localfilestorage_class()
    if local_storage_cls is None:
        logger.warning("LocalFileStorage class not found in Cognee storage module")
        return

    if getattr(local_storage_cls, "_gymbot_storage_patched", False):
        return

    allow_package_storage = os.getenv("COGNEE_ALLOW_PACKAGE_STORAGE", "0") == "1"

    original_open = getattr(local_storage_cls, "open", None)

    if hasattr(local_storage_cls, "storage_path"):
        setattr(local_storage_cls, "storage_path", root)
    if hasattr(local_storage_cls, "STORAGE_PATH"):
        setattr(local_storage_cls, "STORAGE_PATH", str(root))

    package_roots: list[Path] = []
    for candidate in _package_storage_candidates():
        try:
            package_roots.append(candidate.resolve(strict=False))
        except Exception:  # noqa: BLE001
            package_roots.append(candidate)

    def _remap_path(raw_path: Path) -> Path:
        if raw_path.is_absolute():
            try:
                if raw_path.is_relative_to(root):
                    return raw_path
            except ValueError:
                pass
            for package_storage in package_roots:
                try:
                    if raw_path.is_relative_to(package_storage):
                        relative = raw_path.relative_to(package_storage)
                        return (root / relative).resolve()
                except ValueError:
                    continue
            # Fallback for absolute paths outside known roots:
            # We flatten the path to put it directly in 'root'.
            # This handles cases where Cognee uses arbitary paths.
            return (root / raw_path.name).resolve()
        return (root / raw_path).resolve()

    if not callable(original_open):
        logger.info(
            "cognee_storage localfilestorage_no_open class={} storage_path={}",
            local_storage_cls.__name__,
            getattr(local_storage_cls, "storage_path", None) or getattr(local_storage_cls, "STORAGE_PATH", None),
        )
        setattr(local_storage_cls, "_gymbot_storage_patched", True)
        return

    def open_with_project_storage(self: Any, file_path: str, mode: str = "r", **kwargs: Any) -> Any:
        raw_path = Path(file_path)
        # Fix: map absolute paths to root/relative structure
        target_path = _remap_path(raw_path)

        # Check for write modes including '+' based on standard open() logic
        write_mode = any(flag in mode for flag in ("w", "a", "x", "+"))

        # Ensure parent directories exist (crucial for hierarchical datasets)
        if write_mode:
            target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            return target_path.open(mode, **kwargs)
        except FileNotFoundError:
            if allow_package_storage and not write_mode and callable(original_open):
                # If not found in our storage, try falling back to original logic (e.g. package data)
                try:
                    logger.warning("cognee_storage package_fallback file={} root={}", file_path, root)
                    return original_open(self, file_path, mode, **kwargs)
                except Exception:
                    pass
            raise

    setattr(local_storage_cls, "open", open_with_project_storage)

    # Restore storage_path override if getting attributes, but log what we do
    if hasattr(local_storage_cls, "storage_path"):
        setattr(local_storage_cls, "storage_path", root)

    setattr(local_storage_cls, "_gymbot_storage_patched", True)

    logger.info(
        "cognee_storage patched_local_file_storage class={} root={} storage_path={} allow_package_storage={}",
        local_storage_cls.__name__,
        root,
        getattr(local_storage_cls, "storage_path", None),
        allow_package_storage,
    )
