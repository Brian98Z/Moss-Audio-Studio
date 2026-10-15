"""落盘量化产物中"部分层在旋转基"时的运行时支持。

**为什么需要它**：`quantformats/quanto_ondisk.py --rot-topk k` 会把少数几层的权重按旋转基存盘
（`W_rot = W @ H`，H 为块对角正交 Hadamard）。这样量化误差更小，但**运行时必须对同名层旋转激活**
（`x → H^T x` 的等价形式），否则该层算的就不是原来的函数——本机实测「只转权重不转激活」相对偏差 **0.73（73%）**。

- 名单不在代码里硬编码，读 checkpoint 目录的 `convrot.json`（缺文件即视为普通 checkpoint，不挂钩子）。
- 数值实现与归档 `quantformats/convrot.py` 逐位一致（纯 FWHT + float32 累加；分组宽度须整除输入宽度，
  本模型宽度 4096/12288 都是 64 的倍数，**无需 pad、形状不变**）。
- 开销：FWHT 是 n·log₂n。本模型只转 3 层 ⇒ 约为全量旋转成本的 **0.8%**（每 8 s 音效 +0.1–0.3 s）；
  实测端到端收益 4.684% → 1.483%（int8 基线 → 只转 3 层），而全层旋转只有 2.899%。
- 自检（不需要模型/GPU）：`python server/convrot_runtime.py`
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch
import torch.nn.functional as F

MANIFEST = "convrot.json"


def next_pow2(n: int) -> int:
    if n < 1:
        raise ValueError(f"n must be positive, got {n}")
    return 1 << (n - 1).bit_length()


def fwht(x: torch.Tensor) -> torch.Tensor:
    """Orthonormal fast Walsh-Hadamard transform on the last axis (float32 accumulation)."""
    if x.ndim == 0:
        raise ValueError("fwht requires a tensor with at least one dimension")
    n = x.shape[-1]
    if n < 1 or n & (n - 1):
        raise ValueError(f"fwht last dimension must be a positive power of two, got {n}")
    result = x.to(dtype=torch.float32)
    width = 1
    while width < n:
        blocks = result.reshape(*result.shape[:-1], n // (2 * width), 2, width)
        low, high = blocks[..., 0, :], blocks[..., 1, :]
        result = torch.cat((low + high, low - high), dim=-1).reshape(*result.shape[:-1], n)
        width *= 2
    return result * (1.0 / math.sqrt(n))


def _layout(width: int, group: int) -> tuple[int, int]:
    """(padded_width, group_size)：只在分组无法整除宽度时才 pad（本模型用不到）。"""
    if group > 0 and width % group == 0 and (group & (group - 1)) == 0:
        return width, group
    padded = next_pow2(width)
    if padded % group or (group & (group - 1)):
        raise ValueError(f"group {group} cannot tile padded width {padded}")
    return padded, group


def rotate_activation(x: torch.Tensor, group: int = 64) -> torch.Tensor:
    """与权重同一套块对角 RHT（不改变 dtype：由调用方按需转回）。"""
    if x.ndim < 1:
        raise ValueError("activation must have at least one dimension")
    padded_width, group_size = _layout(x.shape[-1], group)
    padded = F.pad(x.to(torch.float32), (0, padded_width - x.shape[-1]))
    blocks = padded.reshape(*padded.shape[:-1], padded_width // group_size, group_size)
    return fwht(blocks).reshape(*padded.shape[:-1], padded_width)


def load_manifest(ckpt_dir: str | Path) -> dict | None:
    """读 checkpoint 目录的旋转基声明；没有就当普通 checkpoint。"""
    path = Path(ckpt_dir) / MANIFEST
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def install_convrot_hooks(model, ckpt_dir: str | Path, log=print, group: int | None = None) -> int:
    """按 `convrot.json` 给名单里的层挂「激活旋转」前钩子，返回挂上的层数。

    钩子排在既有钩子之前（prepend）：旋转要在 offload 搬运之前发生，否则白搬一趟。
    """
    manifest = load_manifest(ckpt_dir)
    if not manifest:
        return 0
    group = int(group or manifest.get("group", 64))
    layers = list(manifest.get("layers", []))
    done = 0
    for name in layers:
        try:
            module = model.get_submodule(name)
        except AttributeError:
            log(f"convrot: checkpoint 声明的层 {name} 不在模型里，跳过")
            continue

        def pre_hook(_module, args, group=group):
            x = args[0]
            return (rotate_activation(x, group=group).to(x.dtype),) + tuple(args[1:])

        module.register_forward_pre_hook(pre_hook, prepend=True)
        done += 1
    log(f"convrot: 已为 {done}/{len(layers)} 层挂激活旋转钩子（group={group}，名单来自 {Path(ckpt_dir) / MANIFEST}）")
    return done


def self_test() -> int:
    """离线自检：正交性、与权重的等价性、确定性。"""
    torch.manual_seed(0)
    ok = True
    for width, group in ((64, 64), (4096, 64), (1024, 64)):
        x = torch.randn(3, width, dtype=torch.bfloat16)
        rot = rotate_activation(x, group=group)
        if rot.shape != x.shape:
            print(f"  FAIL 形状改变 {tuple(x.shape)} → {tuple(rot.shape)}")
            ok = False
        energy = float(rot.float().pow(2).sum()) / float(x.float().pow(2).sum())
        print(f"  [{width:>5}] 形状保持 {rot.shape == x.shape} · 能量比 {energy:.6f}（正交应为 1）")
        ok &= abs(energy - 1) < 1e-4

    # 端到端等价：W_rot @ (H x) 必须等于 W @ x
    for in_f, out_f in ((64, 64), (4096, 1024)):
        w = torch.randn(out_f, in_f, dtype=torch.float32) * 0.02
        w[0, 0] = 3.0                                     # 造个离群值，贴近真实场景
        w_rot = fwht(w.reshape(out_f, in_f // 64, 64)).reshape(out_f, in_f)
        x = torch.randn(5, in_f, dtype=torch.bfloat16)
        ref = x.float() @ w.T
        got = rotate_activation(x, group=64) @ w_rot.T
        rel = float((got - ref).norm() / ref.norm())
        print(f"  [{out_f}×{in_f}] W_rot@(H x) 与 W@x 相对误差 {rel:.2e} {'PASS' if rel < 1e-4 else 'FAIL'}")
        ok &= rel < 1e-4

    x = torch.randn(2, 128)
    same = torch.equal(rotate_activation(x, 64), rotate_activation(x, 64))
    print(f"  确定性（同输入两次结果逐位相同）: {same}")
    ok &= same

    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="落盘量化产物的旋转基运行时支持")
    ap.add_argument("--self-test", action="store_true", help="离线自检（默认行为）")
    ap.add_argument("--checkpoint", help="检查某 checkpoint 的 convrot.json 并打印名单")
    args = ap.parse_args()
    if args.checkpoint:
        m = load_manifest(args.checkpoint)
        print(json.dumps(m, ensure_ascii=False, indent=1) if m else f"{args.checkpoint} 没有 {MANIFEST}（普通 checkpoint）")
        return 0
    return self_test()


if __name__ == "__main__":
    raise SystemExit(main())
