# # cache/base.py
# from abc import ABC, abstractmethod
# from redis.asyncio import Redis
# import orjson
#
# class BaseCache(ABC):
#     _prefix: str = "app"
#     def __init__(self, redis: Redis): self.redis = redis
#
#     def _key(self, k: str) -> str: return f"{self._prefix}:{k}"
#
#     async def _hget(self, key, field):
#         data = await self.redis.hget(self._key(key), field)
#         return orjson.loads(data) if data else None
#
#     async def _hset(self, key, field, obj):
#         await self.redis.hset(self._key(key), field, orjson.dumps(obj))
#
# # cache/profile.py
# class ProfileCache(BaseCache):
#     _key_profiles = "user_profiles"
#
#     async def get(self, tg_id: int) -> Profile:
#         raw = await self._hget(self._key_profiles, tg_id)
#         if not raw or "id" not in raw:
#             raise ProfileNotFoundError(tg_id)
#         return Profile(**raw)
#
#     async def update(self, tg_id: int, **kwargs):
#         allowed = {"language", "status"}
#         patch = {k: v for k, v in kwargs.items() if k in allowed}
#         data = (await self._hget(self._key_profiles, tg_id)) or {}
#         data.update(patch)
#         await self._hset(self._key_profiles, tg_id, data)
#
# # cache/coach.py
# class CoachCache(BaseCache):
#     _key = "coaches"
#     encryptor = Encryptor
#
#     async def get(self, coach_id: int) -> Coach:
#         data = await self._hget(self._key, coach_id)
#         if not data: raise UserServiceError("Coach not found", 404)
#         if pd := data.get("payment_details"):
#             data["payment_details"] = self.encryptor.decrypt(pd)
#         return Coach(**data)
#
#     async def save(self, coach_id: int, **kwargs):
#         if "payment_details" in kwargs:
#             kwargs["payment_details"] = self.encryptor.encrypt(kwargs["payment_details"])
#         await self._hset(self._key, coach_id, kwargs)
