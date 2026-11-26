#!/usr/bin/env python3
"""Minimal Chrome DevTools Protocol client (standard library only).

Used for local browser checks and screenshot capture. It launches the installed
Google Chrome in headless mode, authenticates with an extra HTTP header, and
exposes navigate/evaluate/screenshot helpers.
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class WebSocket:
    def __init__(self, url, timeout=30):
        if not url.startswith("ws://"):
            raise ValueError(f"unsupported url: {url}")
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /{path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            buffer += self.sock.recv(4096)
        if b"101" not in buffer.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket upgrade failed")

    def send(self, payload):
        data = json.dumps(payload).encode()
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, count):
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("websocket closed")
            data += chunk
        return data

    def recv(self):
        first = self._read(2)
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(length)
        if opcode == 0x8:
            raise ConnectionError("websocket closed by peer")
        if opcode == 0x9:
            return self.recv()
        return payload.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Chrome:
    def __init__(self, port=9231, width=1280, height=900, scale=2):
        self.profile = tempfile.mkdtemp(prefix="prk-chrome-")
        self.port = port
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={port}",
             f"--user-data-dir={self.profile}", "--no-first-run",
             "--no-default-browser-check", "--disable-gpu",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self.next_id = 0
        self.events = []
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=2) as resp:
                    targets = json.loads(resp.read())
                page = next(t for t in targets if t.get("type") == "page")
                self.ws = WebSocket(page["webSocketDebuggerUrl"])
                break
            except Exception:
                time.sleep(0.3)
        if not self.ws:
            raise RuntimeError("Chrome did not start")
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Network.enable")
        self.set_viewport(width, height, scale)

    def call(self, method, params=None, timeout=60):
        self.next_id += 1
        ident = self.next_id
        self.ws.send({"id": ident, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = json.loads(self.ws.recv())
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            if "method" in message:
                self.events.append(message)
        raise TimeoutError(method)

    def set_headers(self, headers):
        self.call("Network.setExtraHTTPHeaders", {"headers": headers})

    def set_viewport(self, width, height, scale=2, mobile=False):
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height,
                   "deviceScaleFactor": scale, "mobile": mobile})

    def navigate(self, url, settle=2.5):
        self.events = []
        self.call("Page.navigate", {"url": url})
        deadline = time.time() + 30
        while time.time() < deadline:
            if any(e.get("method") == "Page.loadEventFired" for e in self.events):
                break
            time.sleep(0.1)
        time.sleep(settle)

    def evaluate(self, expression, await_promise=False):
        result = self.call("Runtime.evaluate",
                           {"expression": expression, "returnByValue": True,
                            "awaitPromise": await_promise})
        return result.get("result", {}).get("value")

    def screenshot(self, path, clip=None, full_page=False, scale=1):
        params = {"format": "png"}
        if clip:
            params["clip"] = dict(clip, scale=scale)
            params["captureBeyondViewport"] = True
        elif full_page:
            metrics = self.call("Page.getLayoutMetrics")
            size = metrics["cssContentSize"]
            params["clip"] = {"x": 0, "y": 0, "width": size["width"],
                              "height": size["height"], "scale": scale}
            params["captureBeyondViewport"] = True
        data = self.call("Page.captureScreenshot", params)["data"]
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))
        return path

    def close(self):
        try:
            self.call("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        if self.ws:
            self.ws.close()
        shutil.rmtree(self.profile, ignore_errors=True)
