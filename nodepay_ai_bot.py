import asyncio
import random
import re
import signal
import requests
import json
import time
import uuid
import ssl
from loguru import logger
from websockets_proxy import Proxy, proxy_connect
from fake_useragent import UserAgent

user_agent = UserAgent()
random_user_agent = user_agent.random

nstProxyAppId = "803B577106C250D0"


def add_nstproxy_appid(proxy):
    if "nstproxy." in proxy:
        pattern = r"^(?:[^:]+)://([^:]+):[^@]+@"
        match = re.match(pattern, proxy)
        if match:
            username = match.group(1)
            if "appId" not in username:
                newusername = "{}-appid_{}".format(username, nstProxyAppId)
                proxy = proxy.replace(username, newusername)
                return proxy
    return proxy


async def call_api_info(token):
    return {
        "code": 0,
        "data": {
            "uid": USER_ID,
        }
    }


async def connect_socket_proxy(socks5_proxy, token):
    browser_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, socks5_proxy))
    logger.info(f"Browser: {browser_id}")

    retries = 0

    while True:
        try:
            await asyncio.sleep(1)
            custom_headers = {
                "User-Agent": random_user_agent
            }
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            proxy = Proxy.from_url(socks5_proxy)

            uri = "wss://nw.nodepay.ai:4576/websocket"
            server_hostname = "nw.nodepay.ai"

            async with proxy_connect(uri, proxy=proxy, ssl=ssl_context, server_hostname=server_hostname,
                                     extra_headers=custom_headers) as websocket:
                retries = 0

                async def send_ping(guid, options={}):
                    payload = {
                        "id": guid,
                        "action": "PING",
                        **options,
                    }
                    await websocket.send(json.dumps(payload))
                    logger.debug(payload)

                async def send_pong(guid):
                    payload = {
                        "id": guid,
                        "origin_action": "PONG",
                    }
                    await websocket.send(json.dumps(payload))
                    logger.debug(payload)

                async for message in websocket:
                    data = json.loads(message)

                    if data["action"] == "PONG":
                        await send_pong(data["id"])
                        await asyncio.sleep(5)
                        await send_ping(data["id"])

                    elif data["action"] == "AUTH":
                        api_response = await call_api_info(token)
                        if api_response["code"] == 0 and api_response["data"]["uid"]:
                            user_info = api_response["data"]
                            auth_info = {
                                "user_id": user_info["uid"],
                                "browser_id": browser_id,
                                "user_agent": custom_headers['User-Agent'],
                                "timestamp": int(time.time()),
                                "device_type": "extension",
                                "version": "extension_version",
                                "token": token,
                                "origin_action": "AUTH",
                            }
                            await send_ping(data["id"], auth_info)
                        else:
                            logger.error(f"{browser_id} Failed to authenticate")

        except asyncio.CancelledError:
            break
        except Exception as e:
            retries += 1
            logger.info(f"{browser_id} Retrying {retries} in 30 seconds...")
            await asyncio.sleep(30)


async def shutdown(loop, signal=None):
    if signal:
        logger.info(f"Received exit signal {signal.name}...")

    await asyncio.sleep(2)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("All tasks cancelled, stopping loop")
    loop.stop()


async def fetch_user_id(token):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    response = requests.get("https://api.nodepay.ai/api/network/device-networks?page=0&size=10&active=false",
                            headers=headers)
    response.raise_for_status()
    data = response.json()
    return data['data'][0]['user_id']


async def main():
    # --------------------
    NP_TOKEN = ""
    channelId = ""
    password = ""
    countryList = ["ANY"]
    taskNum = 200
    # --------------------

    socks5_proxy = [
        f"socks5://{channelId}-residential-country_{random.choice(countryList)}-r_120m-s_{random.randint(10000, 99999999)}:{password}@gw-us.nstproxy.io:24125"
        for i in range(taskNum)]

    global USER_ID
    USER_ID = await fetch_user_id(NP_TOKEN)

    loop = asyncio.get_running_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(loop, signal=s)))

    tasks = []
    for proxy in socks5_proxy:
        task = asyncio.create_task(connect_socket_proxy(add_nstproxy_appid(proxy), NP_TOKEN))
        tasks.append(task)

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Program terminated by user.")
