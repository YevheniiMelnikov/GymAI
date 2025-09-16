from types import SimpleNamespace


from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from cognee.infrastructure.files import utils as file_utils


def test_windows_file_uri(tmp_path, monkeypatch):
    import asyncio

    test_file = tmp_path / "doc.txt"
    test_file.write_text("hello")
    monkeypatch.setattr(
        "cognee.base_config.get_base_config",
        lambda: SimpleNamespace(data_root_directory=str(tmp_path)),
    )
    CogneeConfig._patch_cognee()
    uri = f"file:///C:/Users/test/{test_file.name}"

    async def runner():
        async with file_utils.open_data_file(uri, mode="r") as f:
            return f.read()

    data = asyncio.run(runner())
    assert data == "hello"


def test_windows_bad_uri(tmp_path, monkeypatch):
    import asyncio

    test_file = tmp_path / "doc.txt"
    test_file.write_text("hello")
    monkeypatch.setattr(
        "cognee.base_config.get_base_config",
        lambda: SimpleNamespace(data_root_directory=str(tmp_path)),
    )
    CogneeConfig._patch_cognee()
    uri = f"file://C:\\Users\\test\\{test_file.name}"

    async def runner():
        async with file_utils.open_data_file(uri, mode="r") as f:
            return f.read()

    data = asyncio.run(runner())
    assert data == "hello"
