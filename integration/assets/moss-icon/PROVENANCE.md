# 启动器图标资产（自绘 SVG）

- **唯一的矢量源**：`moss-icon.svg`（本项目自绘，512×512）。设计取官方 MOSS 标识的意象
  「斜体几何 M + 环绕轨道 + 圆角蓝底渐变」，但图形是本项目自己画的矢量稿，不直接使用官方位图
  —— 官方头像（`source-460.png`，<https://avatars.githubusercontent.com/u/156300419?s=460&v=4>）
  缩小到 16–48px 会糊成一团、且 32px 走 shell 取图标时有噪点，故仅作设计参考留在本目录。
- **渲染**：`node ..\exe-branding\render_icons.js`（`@resvg/resvg-js` + `resedit`）——
  每个尺寸都从 SVG **原生渲染**（不是缩放），产出：
  - `icon-16/24/32/48/64/128/256.png`：独立 PNG，asar 的窗口图标取 `icon-256.png`。
  - `moss.ico`：**16/24/32/48/64/128 用 DIB（BITMAPINFOHEADER + BGRA 自下而上 + 全 0 AND 掩码），
    256 用 PNG 压缩项**。
- ⚠️ **ICO 项格式是硬约束**：ICO 里只有 256×256 正式支持 PNG 压缩项，小尺寸必须是 DIB。
  早先全部用 PNG 项时，Windows shell 取 32×32 会渲染出噪点/黑边（本机实测）。
- **应用**：
  - exe 图标组 + 版本字段：`node ..\exe-branding\exe_branding.js <源 exe> <目标 exe>`
    （默认就用本目录的 `moss.ico`）。
  - 客户端窗口图标：`integration\apply_launcher_patch.py` 会把 `icon-256.png` 写进
    `app.asar` 的 `resources\icon.png`（main 的 `BrowserWindow` icon 指向它）。
  - 桌面快捷方式 `IconLocation = <exe>,0` ⇒ 自动跟随 exe 图标。
- **改图标**：编辑 `moss-icon.svg` → 跑 `render_icons.js` 重新生成 PNG 集与 `moss.ico` → 用
  `exe_branding.js` 重做 exe（换包流程见 README §六）。若只是替换，Windows 可能仍显示旧图标，
  执行 `ie4uinit.exe -show` 刷新图标缓存。
