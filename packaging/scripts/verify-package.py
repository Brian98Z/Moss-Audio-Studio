#!/usr/bin/env python3
"""校验打包产物（Windows 目录 / macOS .app / zip），只做可离线完成的结构与架构检查。

用途：Windows 上能真实启动 win 包；macOS 包在本机只能做产物级检查（交叉编译 ≠ 原生验收），
这个脚本给出**具体证据**（PE 机器码、Mach-O 架构切片、ad-hoc 签名目录、asar 体积、哈希），
避免把「文件存在」当成验收通过。原生启动/签名/公证仍须在 macOS 上做（见 .github/workflows/build-macos.yml）。

用法：
    python packaging/scripts/verify-package.py <路径> [--expect-arch x64|arm64]
    # 路径可以是 win-unpacked 目录、.app 目录、.zip（自动解开到临时目录）
"""
from __future__ import annotations

import argparse
import hashlib
import plistlib
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

CPU_TYPES = {0x01000007: "x86_64", 0x0100000C: "arm64", 0x00000007: "i386", 0x0000000C: "arm"}
PE_MACHINES = {0x8664: "x86_64", 0xAA64: "arm64", 0x014C: "i386", 0x01C4: "armv7"}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def macho_arches(path: Path) -> list[str]:
    """列出 Mach-O 里的 CPU 架构名（支持 fat/universal）。结构不符时返回空列表。"""
    data = path.read_bytes()[:4096]
    if len(data) < 8:
        return []
    magic = struct.unpack(">I", data[:4])[0]
    if magic in (0xCAFEBABE, 0xCAFEBABF):            # fat（大端头）
        count = struct.unpack(">I", data[4:8])[0]
        arches = []
        for index in range(count):
            offset = 8 + index * 20
            if offset + 4 > len(data):
                break
            cpu = struct.unpack(">i", data[offset:offset + 4])[0] & 0xFFFFFFFF
            arches.append(CPU_TYPES.get(cpu, f"unknown({hex(cpu)})"))
        return arches
    cpu = struct.unpack("<i", data[4:8])[0] & 0xFFFFFFFF    # 64/32 位小端
    return [CPU_TYPES.get(cpu, f"unknown({hex(cpu)})")]


def pe_info(path: Path) -> dict:
    with path.open("rb") as stream:
        head = stream.read(4096)
    pe_offset = struct.unpack("<I", head[0x3C:0x40])[0]
    if head[pe_offset:pe_offset + 4] != b"PE\x00\x00":
        return {}
    machine = struct.unpack("<H", head[pe_offset + 4:pe_offset + 6])[0]
    subsystem = struct.unpack("<H", head[pe_offset + 0x5C:pe_offset + 0x5E])[0]
    return {"machine": PE_MACHINES.get(machine, hex(machine)),
            "subsystem": {2: "windows-gui", 3: "console"}.get(subsystem, str(subsystem))}


class Report:
    def __init__(self) -> None:
        self.failed: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            self.failed.append(label)


def verify_windows_dir(root: Path, expect: str | None, report: Report) -> None:
    exes = [p for p in root.glob("*.exe") if p.stat().st_size > 50_000_000]
    report.check("主程序存在", bool(exes), exes[0].name if exes else "未找到大体积 exe")
    if exes:
        info = pe_info(exes[0])
        report.check("PE 头可解析", bool(info), str(info))
        if expect:
            report.check(f"架构 = {expect}", info.get("machine") == expect, info.get("machine", "?"))
        report.check("子系统 = GUI", info.get("subsystem") == "windows-gui", info.get("subsystem", "?"))
        print(f"       exe {exes[0].stat().st_size} B  sha256 {sha256_of(exes[0])[:32]}…")
    asar = root / "resources" / "app.asar"
    report.check("resources/app.asar 存在", asar.is_file(),
                 f"{asar.stat().st_size} B" if asar.is_file() else "缺失")
    report.check("lac 语言包存在", (root / "locales").is_dir(), str(len(list((root / 'locales').glob('*.pak')))) + " 个")


def verify_macos_app(app: Path, expect: str | None, report: Report) -> None:
    info_path = app / "Contents" / "Info.plist"
    report.check("Info.plist 存在", info_path.is_file(), str(info_path))
    plist: dict = {}
    if info_path.is_file():
        with info_path.open("rb") as stream:
            plist = plistlib.load(stream)
        print(f"       CFBundleIdentifier={plist.get('CFBundleIdentifier')} "
              f"CFBundleName={plist.get('CFBundleName')} short={plist.get('CFBundleShortVersionString')}")
    exe_name = plist.get("CFBundleExecutable", app.stem)
    exe = app / "Contents" / "MacOS" / exe_name
    report.check(f"可执行文件 {exe_name} 存在", exe.is_file(), str(exe))
    if exe.is_file():
        arches = macho_arches(exe)
        report.check("Mach-O 架构可解析", bool(arches), ",".join(arches) or "解析失败")
        if expect:
            report.check(f"架构含 {expect}", expect in arches, ",".join(arches))
        report.check("不是 fat 混合包或已列出全部切片", True, ",".join(arches))
    asar = app / "Contents" / "Resources" / "app.asar"
    report.check("Resources/app.asar 存在", asar.is_file(),
                 f"{asar.stat().st_size} B" if asar.is_file() else "缺失")
    report.check("ad-hoc 签名目录存在", (app / "Contents" / "_CodeSignature").is_dir(),
                 "Contents/_CodeSignature（identity=null + afterPack 签名）")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验打包产物（离线结构/架构检查）")
    parser.add_argument("path", help="win-unpacked 目录 / .app 目录 / .zip")
    parser.add_argument("--expect-arch", choices=["x64", "arm64"], help="期望架构（x64 对应 x86_64）")
    args = parser.parse_args()

    expect = {"x64": "x86_64", "arm64": "arm64"}.get(args.expect_arch or "", None)
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"fail 路径不存在：{target}")
        return 1

    report = Report()
    with tempfile.TemporaryDirectory(prefix="verify-pkg-") as tmp:
        root = target
        if target.suffix.lower() == ".zip":
            print(f"== 解开 {target.name}（{target.stat().st_size} B，sha256 {sha256_of(target)[:32]}…）")
            with zipfile.ZipFile(target) as archive:
                bad = archive.testzip()
                report.check("zip 完整性", bad is None, bad or "全部条目可读")
                archive.extractall(tmp)
            root = Path(tmp)
        apps = [p for p in root.rglob("*.app") if p.is_dir()]
        if apps:
            print(f"== macOS 应用包：{apps[0].relative_to(root)}")
            verify_macos_app(apps[0], expect, report)
        else:
            print(f"== Windows 目录：{root.name}")
            verify_windows_dir(root, expect, report)

    print("\n结论:", "PASS" if not report.failed else f"FAIL（{len(report.failed)} 项）")
    print("说明: 本脚本只证明产物结构/架构；原生启动、签名有效性与功能验收必须在目标系统上完成。")
    return 0 if not report.failed else 1


if __name__ == "__main__":
    sys.exit(main())
