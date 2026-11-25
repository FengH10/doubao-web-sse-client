"""Pure Python implementation of the long ``a_bogus`` packet.

This module contains no browser APIs, JavaScript runtime, SDK bundle, or VM.
The implementation follows the wire format recovered from BDMS 1.0.1.20.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Protocol


_SM3_IV = (
    0x7380166F,
    0x4914B2B9,
    0x172442D7,
    0xDA8A0600,
    0xA96F30BC,
    0x163138AA,
    0xE38DEE4D,
    0xB0FB0E4E,
)
_ENV_ALPHABET = "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe"
_OUTPUT_ALPHABET = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
_EPOCH_MS = 1721836800000


class RandomSource(Protocol):
    def randrange(self, stop: int) -> int: ...


@dataclass(frozen=True)
class ABogusOptions:
    user_agent: str
    page_id: int = 26930
    aid: int = 497858
    sdk_version: str = "1.0.1.20-alpha.14"
    now_ms: int | None = None
    ink_ms: int | None = None
    biweekly_index: int | None = None
    env_code: int = 129
    ub_code: int = 14
    env_flags: tuple[int, int, int, int, int] = (0, 0, 0, 0, 79)
    perf: int = 6
    delta: int = 3
    inner_width: int = 0
    inner_height: int = 0
    outer_width: int = 0
    outer_height: int = 0
    avail_width: int = 1440
    avail_height: int = 900
    screen_width: int = 1440
    screen_height: int = 900
    platform: str = "Win32"


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _rol32(value: int, shift: int) -> int:
    shift &= 31
    return _u32((value << shift) | (value >> ((32 - shift) & 31)))


def sm3(data: bytes) -> bytes:
    """Return the GM/T 0004-2012 SM3 digest."""
    message = bytearray(data)
    bit_length = len(message) * 8
    message.append(0x80)
    message.extend(b"\0" * ((56 - len(message)) % 64))
    message.extend(bit_length.to_bytes(8, "big"))
    state = list(_SM3_IV)

    for offset in range(0, len(message), 64):
        block = message[offset : offset + 64]
        words = [int.from_bytes(block[i : i + 4], "big") for i in range(0, 64, 4)]
        for index in range(16, 68):
            mixed = words[index - 16] ^ words[index - 9] ^ _rol32(words[index - 3], 15)
            p1 = mixed ^ _rol32(mixed, 15) ^ _rol32(mixed, 23)
            words.append(_u32(p1 ^ _rol32(words[index - 13], 7) ^ words[index - 6]))
        expanded = [words[i] ^ words[i + 4] for i in range(64)]
        a, b, c, d, e, f, g, h = state
        for index in range(64):
            constant = 0x79CC4519 if index < 16 else 0x7A879D8A
            ss1 = _rol32(_u32(_rol32(a, 12) + e + _rol32(constant, index)), 7)
            ss2 = ss1 ^ _rol32(a, 12)
            if index < 16:
                ff = a ^ b ^ c
                gg = e ^ f ^ g
            else:
                ff = (a & b) | (a & c) | (b & c)
                gg = (e & f) | ((~e) & g)
            tt1 = _u32(ff + d + ss2 + expanded[index])
            tt2 = _u32(gg + h + ss1 + words[index])
            d, c, b, a = c, _rol32(b, 9), a, tt1
            h, g, f = g, _rol32(f, 19), e
            e = tt2 ^ _rol32(tt2, 9) ^ _rol32(tt2, 17)
        state = [_u32(old ^ new) for old, new in zip(state, (a, b, c, d, e, f, g, h))]
    return b"".join(value.to_bytes(4, "big") for value in state)


def _double_sm3(text: str) -> bytes:
    return sm3(sm3(text.encode("utf-8")))


def _js_bytes(text: str) -> list[int]:
    result: list[int] = []
    encoded = text.encode("utf-16-be", errors="surrogatepass")
    for index in range(0, len(encoded), 2):
        high, low = encoded[index], encoded[index + 1]
        result.extend((high, low) if high else (low,))
    return result


def _custom_base64(data: list[int], alphabet: str) -> str:
    output: list[str] = []
    for offset in range(0, len(data), 3):
        chunk = data[offset : offset + 3]
        packed = chunk[0] << 16
        if len(chunk) > 1:
            packed |= chunk[1] << 8
        if len(chunk) > 2:
            packed |= chunk[2]
        output.append(alphabet[(packed >> 18) & 63])
        output.append(alphabet[(packed >> 12) & 63])
        output.append(alphabet[(packed >> 6) & 63] if len(chunk) > 1 else "=")
        output.append(alphabet[packed & 63] if len(chunk) > 2 else "=")
    return "".join(output)


def _stream_cipher(key: list[int], data: list[int]) -> list[int]:
    table = list(range(255, -1, -1))
    cursor = 0
    for index in range(256):
        cursor = (cursor + table[index] * cursor + key[index % len(key)]) & 255
        table[index], table[cursor] = table[cursor], table[index]
    left = right = 0
    result: list[int] = []
    for value in data:
        left = (left + 1) & 255
        right = (right + table[left]) & 255
        table[left], table[right] = table[right], table[left]
        result.append(value ^ table[(table[left] + table[right]) & 255])
    return result


def _version_bytes(version: str) -> list[int]:
    known = {
        "1.0.1.20-alpha.13": [1, 0, 0, 0, 129, 4, 170, 78],
        "1.0.1.20-alpha.14": [1, 0, 0, 0, 129, 4, 170, 84],
    }
    if version in known:
        return known[version]
    raise ValueError(f"unsupported BDMS version: {version}")


def _little_bytes(value: int, width: int) -> list[int]:
    return [(value >> (8 * index)) & 255 for index in range(width)]


def _obfuscate_pair(pair: tuple[int, int], rng: RandomSource) -> list[int]:
    low = rng.randrange(65535) & 255
    high = rng.randrange(40) & 255
    first, second = pair
    return [
        (low & 0xAA) | (first & 0x55),
        (low & 0x55) | (first & 0xAA),
        (high & 0xAA) | (second & 0x55),
        (high & 0x55) | (second & 0xAA),
    ]


def _obfuscate_triplets(data: list[int], rng: RandomSource) -> list[int]:
    output: list[int] = []
    for offset in range(0, len(data), 3):
        chunk = data[offset : offset + 3]
        if len(chunk) < 3:
            output.extend(chunk)
            continue
        noise = rng.randrange(1000) & 255
        first, second, third = chunk
        output.extend(
            (
                (noise & 0x91) | (first & 0x6E),
                (noise & 0x42) | (second & 0xBD),
                (noise & 0x2C) | (third & 0xD3),
                (first & 0x91) | (second & 0x42) | (third & 0x2C),
            )
        )
    return output


def sign_a_bogus(
    query_string: str,
    body: str,
    *,
    options: ABogusOptions,
    rng: RandomSource | None = None,
) -> str:
    """Sign an exact query string and exact serialized request body."""
    random_source = rng or random.SystemRandom()
    now_ms = options.now_ms if options.now_ms is not None else int(time.time() * 1000)
    ink_ms = options.ink_ms if options.ink_ms is not None else now_ms - 1
    biweekly = (
        options.biweekly_index
        if options.biweekly_index is not None
        else (now_ms - _EPOCH_MS) // (14 * 24 * 60 * 60 * 1000)
    )

    query_hash = _double_sm3(query_string + "dhzx")
    body_hash = _double_sm3(body + "dhzx")
    env_key = [(options.env_code >> 8) & 255, options.env_code & 255, options.ub_code & 255]
    env_encoded = _custom_base64(
        _stream_cipher(env_key, _js_bytes(options.user_agent)), _ENV_ALPHABET
    )
    env_hash = sm3(env_encoded.encode("utf-8"))

    time_bytes = _little_bytes(now_ms, 6)
    ink_bytes = _little_bytes(ink_ms, 6)
    aid_bytes = _little_bytes(options.aid, 4)
    page_bytes = _little_bytes(options.page_id, 4)
    env_code_bytes = _little_bytes(options.env_code, 2)
    ub_bytes = _little_bytes(options.ub_code, 4)
    e0, e1, e2, e3, e4 = options.env_flags
    env_bytes = _little_bytes(e4, 2) + [e0 & 255, e1 & 255, e2 & 255, e3 & 255]

    q_marker = 11 if e4 & 2 else (12 if query_hash[3] == 11 else query_hash[3])
    b_marker = 8 if e4 & 4 else (9 if body_hash[4] == 8 else body_hash[4])
    e_marker = 12 if e4 & 8 else (13 if env_hash[5] == 12 else env_hash[5])
    screen = "|".join(
        map(
            str,
            (
                options.inner_width,
                options.inner_height,
                options.outer_width,
                options.outer_height,
                options.avail_width,
                options.avail_height,
                options.screen_width,
                options.screen_height,
                options.platform,
            ),
        )
    )
    screen_bytes = _js_bytes(screen)
    comma_bytes = _js_bytes(f"{(now_ms + 3) & 255},")
    version = _version_bytes(options.sdk_version)

    fields = [
        41, biweekly, options.perf, options.delta, *time_bytes, *env_code_bytes, 3,
        *env_bytes, *ub_bytes, query_hash[9], query_hash[18], q_marker,
        body_hash[10], body_hash[19], b_marker, env_hash[11], env_hash[21], e_marker,
        *ink_bytes, *page_bytes, *aid_bytes, len(screen_bytes) & 255,
        (len(screen_bytes) >> 8) & 255, len(comma_bytes) & 255,
        (len(comma_bytes) >> 8) & 255,
    ]
    checksum = 0
    for value in version + fields:
        checksum ^= value & 255

    packet = [
        time_bytes[5], ub_bytes[0], env_hash[11], ink_bytes[1], aid_bytes[2],
        time_bytes[0], page_bytes[3], ub_bytes[1], env_code_bytes[0], query_hash[18],
        env_bytes[0], 3, q_marker, page_bytes[1], options.delta, query_hash[9],
        ink_bytes[4], ub_bytes[3], time_bytes[1], aid_bytes[0], biweekly, b_marker,
        time_bytes[2], page_bytes[2], e_marker, env_bytes[2], ink_bytes[2],
        ink_bytes[3], options.perf, aid_bytes[1], env_bytes[3], aid_bytes[3],
        env_hash[21], body_hash[10], env_bytes[4], env_bytes[1], time_bytes[4],
        page_bytes[0], body_hash[19], env_bytes[5], ink_bytes[5], ub_bytes[2],
        env_code_bytes[1], 41, ink_bytes[0], time_bytes[3], len(screen_bytes) & 255,
        (len(screen_bytes) >> 8) & 255, len(comma_bytes) & 255,
        (len(comma_bytes) >> 8) & 255,
        *screen_bytes, *comma_bytes, checksum,
    ]
    prefix = _obfuscate_pair((3, 82), random_source)
    encrypted = _stream_cipher([211], version + _obfuscate_triplets(packet, random_source))
    return _custom_base64(prefix + encrypted, _OUTPUT_ALPHABET)

