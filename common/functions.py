import os

import httpx
import loguru
from aiogram import Bot
from dotenv import load_dotenv

from bot.models import Person

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")


async def api_request(method: str, url: str, data: dict = None) -> tuple:
    logger.info(f"METHOD: {method.upper()} URL: {url} data: {data}")
    try:
        async with httpx.AsyncClient() as client:
            if method == "get":
                response = await client.get(url)
            elif method == "post":
                response = await client.post(url, data=data)
            elif method == "put":
                response = await client.put(url, data=data)
            elif method == "delete":
                response = await client.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return response.status_code, response.json()

    except Exception as e:
        logger.error(e)
        return None, None


async def create_person(data: dict) -> bool:
    url = f"{BACKEND_URL}/persons/"
    status_code, _ = await api_request("post", url, data)
    print(status_code)
    print(_)
    return status_code == 201 if status_code else False


async def get_person(tg_user_id: int) -> Person | None:
    url = f"{BACKEND_URL}/persons/{tg_user_id}/"
    status_code, user_data = await api_request("get", url)
    if "tg_user_id" in user_data:
        return Person.from_dict(user_data)
    else:
        return None


async def edit_person(tg_user_id: int, data: dict) -> bool:
    url = f"{BACKEND_URL}/person/{tg_user_id}/"
    status_code, _ = await api_request("put", url, data)
    return status_code == 200 if status_code else False


async def delete_person(tg_user_id: int) -> bool:
    url = f"{BACKEND_URL}/persons/{tg_user_id}/"
    status_code, _ = await api_request("delete", url)
    return status_code == 404 if status_code else False
