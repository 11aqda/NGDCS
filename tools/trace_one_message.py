"""学习用：把一条消息从打包到拆包的全过程打印出来。

这不是系统代码，不影响 server / client；只是让你在 PyCharm 里单步看字节。
运行：
    .venv\\Scripts\\python.exe -X utf8 -m tools.trace_one_message
"""

from protocol.framing import HEADER, pack_frame, recv_frame
from protocol.messages import ECHO


class ChunkedSocket:
    """假 socket：每次 recv 只返回 chunk 个字节，模拟半包。"""

    def __init__(self, data, chunk=3):
        self.data = data
        self.chunk = chunk
        self.calls = 0

    def recv(self, n):
        self.calls += 1
        take = min(n, self.chunk, len(self.data))
        out = self.data[:take]
        self.data = self.data[take:]
        shown = out.hex(" ") if out else "(空)"
        print(f"  第 {self.calls} 次 recv({n}) -> {shown}")
        return out


def show_frame(payload, msg_type=ECHO, seq=1):
    print("=" * 62)
    print(f"原始 payload: {payload!r}  ({len(payload)} B)")

    raw = pack_frame(msg_type, seq, payload)
    print(f"打包后总长: {len(raw)} B  (12 B 帧头 + {len(payload)} B 载荷)")
    print(f"帧头 12 B: {raw[:12].hex(' ')}")
    print(f"载荷   {len(payload)} B: {raw[12:].hex(' ')}")

    magic, version, mtype, mseq, length = HEADER.unpack(raw[:12])
    print(
        f"拆帧头: magic=0x{magic:04X} version={version} "
        f"type=0x{mtype:02X} seq={mseq} length={length}"
    )
    return raw


def main():
    raw = show_frame(b"hi")

    print("\n--- 模拟半包：每次只给 3 B ---")
    sock = ChunkedSocket(raw, chunk=3)
    frame = recv_frame(sock)
    print(
        f"recv_frame 结果: type=0x{frame.msg_type:02X} "
        f"seq={frame.seq} payload={frame.payload!r}"
    )

    print("\n--- 模拟粘包：两条帧连在一起 ---")
    two = pack_frame(ECHO, 1, b"one") + pack_frame(ECHO, 2, b"two")
    sock2 = ChunkedSocket(two, chunk=5)
    first = recv_frame(sock2)
    second = recv_frame(sock2)
    print(f"第一条: seq={first.seq} payload={first.payload!r}")
    print(f"第二条: seq={second.seq} payload={second.payload!r}")


if __name__ == "__main__":
    main()
