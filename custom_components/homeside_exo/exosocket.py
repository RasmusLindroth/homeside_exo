"""EXOsocket-protokoll (läsning + inloggning) för Regin ControllerWeb / HomeSide.

Används både av Home Assistant-integrationen och av CLI-testklienten
(exosocket_client.py), som importerar den här filen direkt. Den får därför inte
importera något från Home Assistant eller använda relativa importer.

Endast läsning – modulen skickar aldrig write-anrop.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import struct

import aiohttp

try:  # Python 3.11+
    from asyncio import timeout as _timeout
except ImportError:  # Python 3.10 (äldre HA)
    from async_timeout import timeout as _timeout

VERSION_OFFER = {"method": "versionOffer", "params": {
    "version": 1, "featureLevel": 0, "capabilities": 0}}
VERSION_ACK = {"method": "versionAck", "params": {
    "version": 1, "featureLevel": 0, "capabilities": 0}}
READ_CONTEXT = 42  # valfritt id i läs-intervallet 0..99999

ERR_ACCESS_DENIED = 28


class ExoError(Exception):
    """Allmänt fel vid kommunikation med regulatorn."""


class ExoAuthError(ExoError):
    """Inloggning nekad (fel användare/lösenord eller behörighet)."""


# ---------------------------------------------------------------------------
# Inloggning: samma algoritm som ControllerWeb-klienten (reverse-engineerad ur
# main.min.js -> HandleAuthChallenge). SCRAM-liknande:
#   base = SHA256( user.lower() + "\0" + pass + "\0" )        (8 x 32-bit ord)
#   base[5] ^= clientNonce1 ; base[6] ^= swap(serverNonce) ; base[7] ^= clientNonce2
#   key  = base[0..3] XOR base[4..7]
#   ct   = AES-ECB(key, plaintext=base[4..7])
#   challengeResponse = swap(ct[0])
# Alla nonce-värden skickas på tråden byte-swappade (little-endian "swap").
# ---------------------------------------------------------------------------

def _swap32(x: int) -> int:
    """Byte-swappa ett 32-bitars ord (motsvarar JS Crypto_SwapEnd)."""
    return struct.unpack(">I", struct.pack("<I", x & 0xFFFFFFFF))[0]


def _sha256_words(text: str) -> list[int]:
    d = hashlib.sha256(text.encode("utf-8")).digest()
    return [int.from_bytes(d[i * 4:i * 4 + 4], "big") for i in range(8)]


def _aes_ecb(key_bytes: bytes, plain_bytes: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    enc = Cipher(algorithms.AES(key_bytes), modes.ECB()).encryptor()
    return enc.update(plain_bytes) + enc.finalize()


def _make_authenticate(user: str, password: str, rnd1: int, server_nonce_wire: int) -> dict:
    rnd2 = secrets.randbits(32)
    a = _sha256_words(user.lower() + "\0" + password + "\0")
    a[5] ^= rnd1
    a[6] ^= _swap32(server_nonce_wire)
    a[7] ^= rnd2
    a = [w & 0xFFFFFFFF for w in a]
    key_words = [a[0] ^ a[4], a[1] ^ a[5], a[2] ^ a[6], a[3] ^ a[7]]
    key = b"".join(struct.pack(">I", w) for w in key_words)
    plain = b"".join(struct.pack(">I", a[i]) for i in (4, 5, 6, 7))
    ct = _aes_ecb(key, plain)
    challenge_response = int.from_bytes(ct[0:4], "little")
    return {"user": user, "clientNonce2": _swap32(rnd2),
            "challengeResponse": challenge_response}


def _read_msg(items: list[int], device: int = 0) -> dict:
    return {
        "method": "read",
        "context": READ_CONTEXT,
        "params": {"kind": "indexedPoints",
                   "devices": [{"device": device, "items": items}]},
    }


async def async_get_templates(
    session: aiohttp.ClientSession, host: str, timeout: float = 10.0
) -> list[str]:
    """Namnen på regulatorns applikationsmallar, ur http://<host>/Controllers.json.

    Punktindexen i points.json gäller en specifik mall, så den här används för
    att upptäcka regulatorer med en annan mall.
    """
    try:
        async with _timeout(timeout):
            async with session.get(f"http://{host}/Controllers.json") as resp:
                resp.raise_for_status()
                raw = await resp.read()
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, OSError) as ex:
        raise ExoError(f"Kunde inte läsa Controllers.json: {type(ex).__name__}") from ex
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as ex:
        raise ExoError("Controllers.json är inte giltig JSON") from ex
    if not isinstance(data, dict):
        raise ExoError("Controllers.json har oväntat format")
    return list(data)


async def async_read(
    session: aiohttp.ClientSession,
    host: str,
    items: list[int],
    user: str | None = None,
    password: str | None = None,
    timeout: float = 20.0,
) -> dict[int, tuple[object, object]]:
    """Läs indexed points. Returnerar {index: (value, error)} för alla items.

    Höjer ExoAuthError vid nekad inloggning och ExoError vid övriga fel
    (anslutning, timeout, protokollfel eller ofullständigt svar).
    """
    uri = f"ws://{host}/_EXOsocket/"
    result: dict[int, tuple[object, object]] = {}
    need = set(items)
    try:
        async with _timeout(timeout):
            async with session.ws_connect(uri, protocols=["EXOsocket"]) as ws:
                await ws.send_str(json.dumps(VERSION_OFFER))
                state = "version"   # version -> auth (vid inloggning) -> read
                rnd1 = 0

                async def send_read() -> None:
                    await ws.send_str(json.dumps(_read_msg(items)))

                async for msg in ws:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        m = json.loads(msg.data)
                    except ValueError:
                        continue
                    method = m.get("method")

                    if method == "versionOffer":
                        await ws.send_str(json.dumps(VERSION_ACK))

                    if state == "version" and method in ("versionAck", "versionOffer"):
                        if user:
                            rnd1 = secrets.randbits(32)
                            await ws.send_str(json.dumps(
                                {"method": "getChallenge",
                                 "params": {"clientNonce1": _swap32(rnd1)}}))
                            state = "auth"
                        else:
                            state = "read"
                            await send_read()
                    elif state == "auth" and method == "authChallenge":
                        server_nonce = m.get("params", {}).get("serverNonce")
                        if not isinstance(server_nonce, int):
                            raise ExoError("authChallenge saknar serverNonce")
                        params = _make_authenticate(
                            user, password or "", rnd1, server_nonce)
                        await ws.send_str(json.dumps(
                            {"method": "authenticate", "params": params}))
                    elif state == "auth" and method == "authenticateReply":
                        err = m.get("error")
                        if err:
                            raise ExoAuthError(
                                f"{err.get('message', '?')} ({err.get('code', '?')})")
                        state = "read"
                        await send_read()

                    if method == "update" and m.get("context") == READ_CONTEXT:
                        for dpt in m.get("params", {}).get("devices", []):
                            its = dpt.get("items", [])
                            vals = dpt.get("values", [])
                            errs = dpt.get("errors", [])
                            for i, it in enumerate(its):
                                result[it] = (
                                    vals[i] if i < len(vals) else None,
                                    errs[i] if i < len(errs) else None,
                                )
                        if need.issubset(result):
                            return result
    except ExoError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, OSError) as ex:
        raise ExoError(f"{type(ex).__name__}: {ex}" if str(ex) else type(ex).__name__) from ex

    # Hit kommer vi bara om anslutningen stängdes innan allt var läst.
    missing = len(need - set(result))
    raise ExoError(f"Anslutningen stängdes innan alla punkter lästes ({missing} saknas)")
