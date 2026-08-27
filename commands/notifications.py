import asyncio
import discord
from discord.ext import commands, tasks
import aiohttp
import traceback
from config import WEBSITE_URL, BOT_API_KEY

# In-memory cache to avoid spamming if the API freezes up
LOCAL_CACHE = set()


def _masked_key_info():
    key = str(BOT_API_KEY or "").strip()
    if not key:
        return "❌ EMPTY / not set"
    return f"length={len(key)}, start='{key[:4]}...', end='...{key[-4:]}'"


class NotificationsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print(f"[NOTIFICATIONS] BOT_API_KEY info: {_masked_key_info()}")
        self.poll_notifications.start()

    def cog_unload(self):
        self.poll_notifications.cancel()

    @tasks.loop(seconds=15)
    async def poll_notifications(self):
        if not WEBSITE_URL or not BOT_API_KEY:
            print("[NOTIFICATIONS] ❌ WEBSITE_URL or BOT_API_KEY is not set, skipping.")
            return

        base_url = WEBSITE_URL.rstrip('/')
        url = f"{base_url}/api/bot-notifications"

        headers = {
            "Authorization": f"Bearer {str(BOT_API_KEY).strip()}",
            "Content-Type": "application/json"
        }

        timeout = aiohttp.ClientTimeout(total=20)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 1. GET REQUEST
                try:
                    async with session.get(f"{url}?limit=10", headers=headers) as response:
                        if response.status != 200:
                            err_text = await response.text()
                            print(f"[NOTIFICATIONS] ❌ GET error ({response.status}): {err_text}")
                            return
                        data = await response.json()
                except asyncio.TimeoutError:
                    print("[NOTIFICATIONS] ⏱️ Timeout on GET request, skipping this cycle.")
                    return

                rows = []
                if isinstance(data, list):
                    rows = data
                elif isinstance(data, dict) and "notifications" in data:
                    rows = data["notifications"]
                elif isinstance(data, dict) and "data" in data:
                    rows = data["data"]
                else:
                    return

                if not rows:
                    return

                processed_ids = []
                for row in rows:
                    row_id = row.get("id")
                    channel_id = row.get("channel_id")
                    message_content = row.get("message")

                    if not row_id or not channel_id or not message_content:
                        continue
                    if row_id in LOCAL_CACHE:
                        continue

                    try:
                        ch_id_int = int(str(channel_id).strip())

                        channel = self.bot.get_channel(ch_id_int)
                        if not channel:
                            channel = await self.bot.fetch_channel(ch_id_int)

                        if channel:
                            await channel.send(message_content)
                            processed_ids.append(row_id)
                            LOCAL_CACHE.add(row_id)

                            if len(LOCAL_CACHE) > 1000:
                                LOCAL_CACHE.clear()

                    except Exception as e:
                        print(f"[NOTIFICATIONS] ❌ Error sending message: {e}")

                # 2. POST REQUEST
                if processed_ids:
                    payload = {"ids": processed_ids}
                    try:
                        async with session.post(url, headers=headers, json=payload) as post_response:
                            if post_response.status not in (200, 204):
                                err_text = await post_response.text()
                                print(f"[NOTIFICATIONS] ❌ API error while acknowledging ({post_response.status}): {err_text}")
                                print(f"[NOTIFICATIONS] ℹ️ Sent key info: {_masked_key_info()}")
                    except asyncio.TimeoutError:
                        print("[NOTIFICATIONS] ⏱️ Timeout on POST (acknowledge) request.")
        except Exception as e:
            print(f"[NOTIFICATIONS POLL ERROR] ❌ System error: {e}")
            traceback.print_exc()

    @poll_notifications.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(NotificationsCog(bot))