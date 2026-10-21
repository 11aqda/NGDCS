"""客户端非阻塞网络层。

原则（D-007）：
    pygame 主循环里**绝不能阻塞**。所以 socket 设为非阻塞，
    每帧调用一次 poll()：能读多少读多少，读不到就立刻返回。

    poll() 返回“这一帧新收到的完整 Frame 列表”；半包留在 FrameParser 的缓冲区里，
    下一帧继续拼。

本阶段只收不发；第 7 步接输入时再加发送缓冲队列。
"""

from __future__ import annotations

import socket

from protocol.framing import Frame, FrameParser, ProtocolError


class NetworkClient:
    def __init__(self, host: str, port: int) -> None:
        # 建立连接这一次可以阻塞（最多 5 s）；连上后立刻切成非阻塞
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.setblocking(False)

        self.parser = FrameParser()
        self.connected = True
        self.last_error = ""

    def poll(self) -> list[Frame]:
        """非阻塞读一次，返回本次新收到的完整帧。"""
        if not self.connected and not self.parser.buffer:
            return []

        self._read_available()
        return self._parse_available()

    def _read_available(self) -> None:
        while True:
            try:
                data = self.sock.recv(65536)
            except BlockingIOError:
                return  # 当前没有更多数据，正常
            except InterruptedError:
                continue  # 被信号打断，重试
            except OSError as exc:
                self.connected = False
                self.last_error = repr(exc)
                return

            if not data:
                self.connected = False
                self.last_error = "server closed the connection"
                return

            self.parser.feed(data)

    def _parse_available(self) -> list[Frame]:
        frames: list[Frame] = []
        try:
            while True:
                frame = self.parser.next_frame()
                if frame is None:
                    return frames
                frames.append(frame)
        except ProtocolError as exc:
            self.connected = False
            self.last_error = str(exc)
            return frames

    def close(self) -> None:
        self.connected = False
        try:
            self.sock.close()
        except OSError:
            pass
