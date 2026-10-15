// 把自绘图标 SVG 渲染成「PNG 尺寸集 + 标准 .ico」。
//
// 用法：node render_icons.js [svg] [输出目录]
//   svg      默认 integration/assets/moss-icon/moss-icon.svg
//   输出目录 默认 integration/assets/moss-icon
//
// 产出：
//   icon-<16|24|32|48|64|128|256>.png  —— 每个尺寸都直接从 SVG 原生渲染（不是缩放，小尺寸更锐）
//   moss.ico                          —— 16/24/32/48/64/128 用 DIB（BITMAPINFOHEADER），256 用 PNG
//
// ⚠️ ICO 里只有 256×256 支持 PNG 压缩项；小尺寸必须是 DIB，否则 shell 取 32×32 会渲染出噪点/黑边
//    （本机实测）。DIB 的 alpha 用 32bpp 的 alpha 通道，AND 掩码全 0。
const fs = require('fs');
const path = require('path');
const { Resvg } = require('@resvg/resvg-js');
const { Data } = require('resedit');

const SVG = process.argv[2] || path.join(__dirname, '..', 'assets', 'moss-icon', 'moss-icon.svg');
const OUT = process.argv[3] || path.join(__dirname, '..', 'assets', 'moss-icon');
const SIZES = [16, 24, 32, 48, 64, 128, 256];
const svg = fs.readFileSync(SVG, 'utf8');

function render(size) {
  return new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render();
}

function png(size) {
  fs.writeFileSync(path.join(OUT, `icon-${size}.png`), render(size).asPng());
}

// BITMAPINFOHEADER + BGRA（自下而上）+ AND 掩码（全 0）
function dib(size) {
  const img = render(size);
  const { width, height } = img;
  const px = img.pixels; // RGBA，resvg 给的是预乘 alpha
  const stride = width * 4;
  const maskStride = Math.ceil(width / 8 / 4) * 4;
  const buf = Buffer.alloc(40 + stride * height + maskStride * height);
  buf.writeUInt32LE(40, 0);
  buf.writeInt32LE(width, 4);
  buf.writeInt32LE(height * 2, 8); // XOR + AND 两张位图的高度相加
  buf.writeUInt16LE(1, 12);
  buf.writeUInt16LE(32, 14);
  buf.writeUInt32LE(0, 16); // BI_RGB
  buf.writeUInt32LE(stride * height, 20);
  let p = 40;
  for (let y = height - 1; y >= 0; y--) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const a = px[i + 3];
      // 预乘 → 直通 alpha（避免边缘发暗）
      const f = a === 255 || a === 0 ? 1 : 255 / a;
      buf[p++] = Math.min(255, Math.round(px[i + 2] * f));
      buf[p++] = Math.min(255, Math.round(px[i + 1] * f));
      buf[p++] = Math.min(255, Math.round(px[i] * f));
      buf[p++] = a;
    }
  }
  return buf;
}

const items = [];
for (const size of SIZES) {
  png(size);
  items.push(size === 256
    ? Data.RawIconItem.from(fs.readFileSync(path.join(OUT, 'icon-256.png')), size, size, 32)
    : Data.IconItem.from(size, size, dib(size)));
}
const file = new Data.IconFile();
file.icons = items.map((data, i) => ({ width: SIZES[i], height: SIZES[i], planes: 1, bitCount: 32, data }));
const ico = path.join(OUT, 'moss.ico');
fs.writeFileSync(ico, Buffer.from(file.generate()));

const check = Data.IconFile.from(fs.readFileSync(ico));
console.log(`rendered ${SIZES.length} PNG + ${path.basename(ico)} (${fs.statSync(ico).size} B)`);
for (const it of check.icons) {
  console.log(`  ${it.width}x${it.height} ${it.data.isRaw() ? 'png' : 'dib'} ${Buffer.from(it.data.isRaw() ? it.data.bin : it.data.generate()).length} B`);
}
