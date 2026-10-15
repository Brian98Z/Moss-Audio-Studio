"""Merge HF-style sharded safetensors into one model.safetensors (streaming, low disk/RAM).

Safetensors layout rules the merged file must obey (verified against safetensors 0.8.0):
  * the data section must be perfectly contiguous -- no padding/gaps between tensors
  * the file must end exactly at the last tensor's end -- no trailing bytes
So the merged file is the byte-wise concatenation of each shard's *used* data region,
with each tensor's `data_offsets` shifted by its shard's base. Payloads are streamed and
each shard is deleted as soon as it has been consumed, so peak extra disk = largest shard.

Usage:
  python merge_shards.py <model_dir> [--keep-shards] [--dry-run] [--chunk-mb 64]
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys

CHUNK = 64 << 20


def read_header(path: str):
    """Return (header_dict, data_start, used_payload_bytes)."""
    with open(path, "rb") as f:
        raw = f.read(8)
        if len(raw) != 8:
            raise RuntimeError(f"{path}: too small")
        (hlen,) = struct.unpack("<Q", raw)
        hbytes = f.read(hlen)
        if len(hbytes) != hlen:
            raise RuntimeError(f"{path}: truncated header")
        header = json.loads(hbytes)
    data_start = 8 + hlen
    file_size = os.path.getsize(path)
    used = 0
    for name, info in header.items():
        if name == "__metadata__":
            continue
        used = max(used, int(info["data_offsets"][1]))
    if used > file_size - data_start:
        raise RuntimeError(f"{path}: header claims more data than the file holds")
    return header, data_start, used


def shard_files(model_dir: str):
    names = [
        n
        for n in os.listdir(model_dir)
        if n.startswith("model-") and n.endswith(".safetensors") and "-of-" in n
    ]
    return [os.path.join(model_dir, n) for n in sorted(names)]


def merge(model_dir: str, keep_shards: bool, dry_run: bool, chunk: int) -> int:
    shards = shard_files(model_dir)
    if not shards:
        print(f"no shards found in {model_dir} (already merged?)")
        return 0

    out_path = os.path.join(model_dir, "model.safetensors")
    if os.path.exists(out_path):
        raise RuntimeError(f"{out_path} already exists; refusing to overwrite")

    merged: dict[str, dict] = {}
    metadata = None
    plan = []  # (shard_path, base, used, data_start)
    cursor = 0
    for shard in shards:
        header, data_start, used = read_header(shard)
        if metadata is None and "__metadata__" in header:
            metadata = header["__metadata__"]
        for name, info in header.items():
            if name == "__metadata__":
                continue
            if name in merged:
                raise RuntimeError(f"duplicate tensor {name} across shards")
            start, end = (int(x) for x in info["data_offsets"])
            merged[name] = {
                "dtype": info["dtype"],
                "shape": info["shape"],
                "data_offsets": [cursor + start, cursor + end],
            }
        plan.append((shard, cursor, used, data_start))
        cursor += used

    header: dict = {}
    if metadata:
        header["__metadata__"] = metadata
    header.update(merged)
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    header_bytes += b" " * ((8 - len(header_bytes) % 8) % 8)

    expected = 8 + len(header_bytes) + cursor
    print(
        f"{os.path.basename(model_dir)}: {len(shards)} shards -> {len(merged)} tensors, "
        f"{expected / 1e9:.2f} GB, target {out_path}"
    )
    if dry_run:
        return 0

    written = 0
    with open(out_path, "wb") as out:
        out.write(struct.pack("<Q", len(header_bytes)))
        out.write(header_bytes)
        written = 8 + len(header_bytes)
        for shard, base, used, data_start in plan:
            if written != 8 + len(header_bytes) + base:
                raise RuntimeError("layout drift while writing")
            with open(shard, "rb") as src:
                src.seek(data_start)
                remaining = used
                while remaining:
                    buf = src.read(min(chunk, remaining))
                    if not buf:
                        raise RuntimeError(f"{shard}: short read")
                    out.write(buf)
                    remaining -= len(buf)
                    written += len(buf)
            print(f"  copied {os.path.basename(shard)} ({used / 1e9:.2f} GB)", flush=True)
            if not keep_shards:
                os.remove(shard)
        out.flush()
        os.fsync(out.fileno())

    actual = os.path.getsize(out_path)
    if actual != expected:
        raise RuntimeError(f"size mismatch: {actual} != {expected}")

    from safetensors import safe_open

    with safe_open(out_path, framework="pt") as f:
        got = set(f.keys())
    want = set(merged)
    if got != want:
        raise RuntimeError(f"tensor set mismatch missing={want - got} extra={got - want}")
    print(f"  verified: {len(got)} tensors readable")

    index = os.path.join(model_dir, "model.safetensors.index.json")
    if os.path.exists(index):
        if keep_shards:
            print(f"  kept {os.path.basename(index)} (--keep-shards)")
        else:
            os.remove(index)
            print("  removed model.safetensors.index.json")
    print(f"OK -> {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("--keep-shards", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chunk-mb", type=int, default=64)
    args = ap.parse_args()
    return merge(os.path.abspath(args.model_dir), args.keep_shards, args.dry_run, args.chunk_mb << 20)


if __name__ == "__main__":
    sys.exit(main())
