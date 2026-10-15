/**
 * electron-builder afterPack 钩子：macOS 上补 ad-hoc 签名。
 *
 * 仓库里没有 Developer ID 证书（mac.identity = null ⇒ electron-builder 跳过证书签名，afterSign 不会执行），
 * 但未签名的 .app 在部分系统策略下会直接打不开，所以在这里做临时签名 —— 这**不是** Developer ID，
 * 也不等于 Apple 公证；Gatekeeper 放行仍需用户自行确认来源。
 *
 * 只在 macOS 执行；codesign 失败就抛错中断构建，不吞异常、不产出「看起来成功」的包。
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") return;
  const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", appPath], { stdio: "inherit" });
  execFileSync("codesign", ["--verify", "--deep", "--strict", "--verbose=2", appPath], { stdio: "inherit" });
  console.log(`[packaging] ad-hoc signed: ${appPath}`);
};
