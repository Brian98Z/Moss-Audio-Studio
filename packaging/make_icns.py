import argparse
import pathlib
import struct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=pathlib.Path, default=pathlib.Path(__file__).parent / "build")
    args = parser.parse_args()
    build = args.build_dir

    chunks = []
    for ostype, filename in ((b"ic09", "icon-512.png"), (b"ic10", "icon-1024.png")):
        data = (build / filename).read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"{filename} is not a PNG")
        length = len(data) + 8
        chunks.append((ostype, struct.pack(">4sI", ostype, length) + data))

    body = b"".join(chunk for _, chunk in chunks)
    output = struct.pack(">4sI", b"icns", len(body) + 8) + body
    (build / "icon.icns").write_bytes(output)
    print(f"icon.icns: {len(output)} B")
    for ostype, chunk in chunks:
        print(f"{ostype.decode('ascii')} {len(chunk)} B")


if __name__ == "__main__":
    main()
