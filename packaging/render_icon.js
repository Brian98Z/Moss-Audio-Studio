const fs = require('fs');
const path = require('path');
const root = __dirname;
const { Resvg } = require(path.join(root, '..', 'integration', 'exe-branding', 'node_modules', '@resvg', 'resvg-js'));

const svgPath = path.join(root, '..', 'integration', 'assets', 'moss-icon', 'moss-icon.svg');
const outDir = path.join(root, 'build');
const svg = fs.readFileSync(svgPath, 'utf8');
fs.mkdirSync(outDir, { recursive: true });

for (const size of [512, 1024]) {
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render().asPng();
  fs.writeFileSync(path.join(outDir, `icon-${size}.png`), png);
  console.log(`icon-${size}.png: ${png.length} B`);
}
