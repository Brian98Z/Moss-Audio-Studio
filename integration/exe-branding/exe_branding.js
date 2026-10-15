// 启动器 exe 的「旧品牌字段清理 + 官方图标替换」工具（纯 JS，改的是 PE 资源段，不动代码段）。
//
// 用法：
//   node exe_branding.js <源 exe> <目标 exe> [图标 .ico]
//     默认图标 integration/assets/moss-icon/moss.ico（来源见同目录 PROVENANCE.md）
//
// 做两件事：
//   1. 版本资源（VS_VERSION_INFO）：把品牌/公司/版权字段写成中性值。旧值从 exe 自身读出来仅用于日志，
//      脚本里不保存任何旧标识字面量。
//   2. 图标资源：用 .ico 里的全部项重建图标组（RT_GROUP_ICON + RT_ICON），Windows 资源管理器 /
//      任务栏 / 快捷方式（IconLocation = exe,0）都随之更新。
//
// ⚠️ 图标项格式有讲究：ICO 里 **只有 256×256 支持 PNG 压缩项**，小尺寸必须是 DIB（BITMAPINFOHEADER）。
//    全部用 PNG 项时，shell 取 32×32 会渲染出噪点/黑边（本机实测）。moss.ico 因此是
//    「16/24/32/48/64/128 = DIB + 256 = PNG」的混合布局。
//
// 源 exe 只读；输出写到 <目标 exe>（替换前请先退出客户端——运行中的 exe 被映射，无法覆写）。
const fs = require('fs');
const path = require('path');
const { NtExecutable, NtExecutableResource, Resource, Data } = require('resedit');

const NEUTRAL_NAME = 'MOSS 语音工作台';
const NEW_VALUES = {
  CompanyName: NEUTRAL_NAME,
  FileDescription: NEUTRAL_NAME,
  InternalName: 'MOSS语音工作台',
  LegalCopyright: 'Copyright © 2026',
  ProductName: NEUTRAL_NAME,
};

const [src, dst, iconArg] = process.argv.slice(2);
if (!src || !dst) {
  console.error('usage: node exe_branding.js <src.exe> <dst.exe> [icon.ico]');
  process.exit(2);
}
const iconFile = iconArg || path.join(__dirname, '..', 'assets', 'moss-icon', 'moss.ico');

const exe = NtExecutable.from(fs.readFileSync(src), { ignoreCert: true });
const res = NtExecutableResource.from(exe);

// ---- 1. 版本资源
const viList = Resource.VersionInfo.fromEntries(res.entries);
if (viList.length !== 1) throw new Error(`expected 1 version resource, got ${viList.length}`);
const vi = viList[0];
const langs = vi.getAllLanguagesForStringValues();
if (langs.length !== 1) throw new Error(`expected 1 language, got ${langs.length}`);
const before = vi.getStringValues(langs[0]);
const changed = {};
for (const [key, value] of Object.entries(NEW_VALUES)) {
  if (before[key] !== undefined && before[key] !== value) changed[key] = [before[key], value];
}
vi.setStringValues(langs[0], { ...before, ...NEW_VALUES });
vi.outputToResourceEntries(res.entries);
console.log('version fields rewritten:', JSON.stringify(changed, null, 1));

// ---- 2. 图标资源（用 .ico 的全部项重建图标组）
const parsed = Data.IconFile.from(fs.readFileSync(iconFile));
const icons = parsed.icons.map((item) => item.data);
if (!icons.length) throw new Error(`no icons in ${iconFile}`);
const kinds = parsed.icons.map((i) => `${i.data.isRaw() ? 'png' : 'dib'}${i.width || 256}`);
const groups = Resource.IconGroupEntry.fromEntries(res.entries);
if (!groups.length) throw new Error('no icon group in exe');
for (const group of groups) {
  Resource.IconGroupEntry.replaceIconsForResource(res.entries, group.id, group.lang, icons);
  console.log(`icon group id=${group.id} lang=${group.lang}: ${group.getIconItemsFromEntries(res.entries).length} items -> ${icons.length} (${kinds.join(' ')})`);
}
res.outputResource(exe);
fs.writeFileSync(dst, Buffer.from(exe.generate()));
console.log('written:', dst, fs.statSync(dst).size, 'bytes');
