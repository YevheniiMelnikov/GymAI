from types import SimpleNamespace


from ai_coach.cognee_config import CogneeConfig
from cognee.infrastructure.files import utils as file_utils
import asyncio


def test_windows_file_uri(tmp_path, monkeypatch):
    async def runner():
        test_file = tmp_path / "doc.txt"
        test_file.write_text("hello")
        monkeypatch.setattr(
            "cognee.base_config.get_base_config",
            lambda: SimpleNamespace(data_root_directory=str(tmp_path)),
        )
        CogneeConfig._patch_cognee()
        uri = f"file:///C:/Users/test/{test_file.name}"
        async with file_utils.open_data_file(uri, mode="r") as f:
            data = f.read()
        assert data == "hello"

    asyncio.run(runner())


def test_windows_bad_uri(tmp_path, monkeypatch):
    async def runner():
        test_file = tmp_path / "doc.txt"
        test_file.write_text("hello")
        monkeypatch.setattr(
            "cognee.base_config.get_base_config",
            lambda: SimpleNamespace(data_root_directory=str(tmp_path)),
        )
        CogneeConfig._patch_cognee()
        uri = f"file://C:\\Users\\test\\{test_file.name}"
        async with file_utils.open_data_file(uri, mode="r") as f:
            data = f.read()
        assert data == "hello"

    asyncio.run(runner())
