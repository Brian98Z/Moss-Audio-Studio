"""Minimal-diff Electron ASAR reader/writer used to add UI files to the GUI client (read path only;
the launcher patch itself must pack with the official `@electron/asar`).

Layout (little-endian):
  [0:4]   = 4 (pickle tag)
  [4:8]   = header size H (bytes from offset 8 to the start of file data)
  [8:12]  = padded JSON length
  [12:16] = JSON length
  [16:...] JSON header (+ padding), file data starts at 8 + H and is 4-byte aligned.
  Each file entry carries {size, offset, integrity}; identical files may share an offset,
  so the untouched payload is reused verbatim and new blobs are appended at the end.

`roundtrip` must reproduce the source byte-for-byte before any patch is applied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys

BLOCK = 4194304


def _integrity(data: bytes) -> dict:
    blocks = [hashlib.sha256(data[i : i + BLOCK]).hexdigest() for i in range(0, len(data), BLOCK)]
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(data).hexdigest(),
        "blockSize": BLOCK,
        "blocks": blocks,
    }


class Asar:
    def __init__(self, path: str) -> None:
        with open(path, "rb") as f:
            blob = f.read()
        tag, header_size, padded_len, json_len = struct.unpack("<IIII", blob[:16])
        if tag != 4:
            raise RuntimeError(f"unexpected asar header tag {tag}")
        self.path = path
        self.blob = blob
        self.json_len = json_len
        self.padded_len = padded_len
        self.pad_bytes = blob[16 + json_len : 16 + padded_len]
        self.header = json.loads(blob[16 : 16 + json_len].decode("utf-8"))
        self.data_start = 8 + header_size
        # the recorded padded length is rounded to 8, while the JSON in the file is
        # only padded to 4 and header_size counts from offset 8
        if padded_len != json_len + ((-json_len) % 8) or header_size != 8 + json_len + ((-json_len) % 4):
            raise RuntimeError(
                f"unexpected asar header geometry: header={header_size} padded={padded_len} json={json_len}"
            )

    # ---------------------------------------------------------------- helpers
    def entries(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []

        def walk(node: dict, prefix: str) -> None:
            for name, value in node.get("files", {}).items():
                cur = f"{prefix}/{name}"
                if "files" in value:
                    walk(value, cur)
                else:
                    out.append((cur, value))

        walk(self.header, "")
        return out

    def _node(self, path: str) -> dict:
        cur = self.header
        for part in [p for p in path.split("/") if p]:
            cur = cur["files"][part]
        return cur

    def read(self, path: str) -> bytes:
        info = self._node(path)
        off = self.data_start + int(info["offset"])
        return self.blob[off : off + int(info["size"])]

    def _serialize(self) -> bytes:
        return json.dumps(self.header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    # ----------------------------------------------------------------- edits
    def replace(self, path: str, data: bytes) -> None:
        self._node(path)   # raises KeyError when the path is absent
        self._append(path, data)

    def add(self, path: str, data: bytes) -> None:
        node = self.header
        parts = [p for p in path.split("/") if p]
        for part in parts[:-1]:
            node = node.setdefault("files", {}).setdefault(part, {"files": {}})
        node.setdefault("files", {})[parts[-1]] = {}
        self._append(path, data)

    def _append(self, path: str, data: bytes) -> None:
        """Append the payload at the end of the data region, keeping other offsets valid."""
        offset = len(self.blob) - self.data_start
        pad = (-offset) % 4
        self.blob += b"\x00" * pad + data
        node = self._node(path)
        node.clear()
        node.update({"size": len(data), "offset": str(offset + pad), "integrity": _integrity(data)})

    def delete(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        node = self.header
        for part in parts[:-1]:
            node = node["files"][part]
        del node["files"][parts[-1]]

    def write(self, dst: str) -> dict:
        payload = self._serialize()
        body = payload + (b"\x00" * ((4 - len(payload) % 4) % 4))
        padded_field = len(payload) + ((-len(payload)) % 8)
        header_size = 8 + len(body)
        with open(dst, "wb") as out:
            out.write(struct.pack("<IIII", 4, header_size, padded_field, len(payload)))
            out.write(body)
            out.write(self.blob[self.data_start :])
        return {"bytes": os.path.getsize(dst), "files": len(self.entries())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--replace", action="append", default=[], metavar="ASARPATH=FILE")
    ap.add_argument("--add", action="append", default=[], metavar="ASARPATH=FILE")
    ap.add_argument("--delete", action="append", default=[])
    ap.add_argument("--verify-roundtrip", action="store_true")
    args = ap.parse_args()

    a = Asar(args.src)
    if args.verify_roundtrip and not (args.replace or args.add or args.delete):
        a.write(args.dst)
        same = open(args.src, "rb").read() == open(args.dst, "rb").read()
        print("roundtrip byte-identical:", same)
        return 0 if same else 1

    for spec in args.replace:
        path, _, file = spec.partition("=")
        a.replace(path, open(file, "rb").read())
    for spec in args.add:
        path, _, file = spec.partition("=")
        a.add(path, open(file, "rb").read())
    for path in args.delete:
        a.delete(path)
    print("wrote", args.dst, a.write(args.dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
