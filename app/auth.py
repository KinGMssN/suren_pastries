import base64
import hashlib
import hmac
import struct
import time


def verify_totp(secret, code):
    if not secret or not code or not code.isdigit() or len(code) != 6:
        return False
    try:
        key = base64.b32decode(secret.upper(), casefold=True)
    except (ValueError, base64.binascii.Error):
        return False
    counter = int(time.time() // 30)
    for offset in (-1, 0, 1):
        message = struct.pack(">Q", counter + offset)
        digest = hmac.new(key, message, hashlib.sha1).digest()
        start = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[start:start + 4])[0] & 0x7FFFFFFF
        expected = str(value % 1000000).zfill(6)
        if hmac.compare_digest(expected, code):
            return True
    return False