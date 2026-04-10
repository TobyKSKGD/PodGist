/**
 * afterPack-mac.js
 *
 * electron-builder afterPack hook
 * 在 dmg 生成之前对 .app 做 ad-hoc deep sign
 *
 * 执行时机：.app 已组装完成，dmg 还未生成
 * 这样签名会被打包进 dmg
 */

const { execSync } = require('child_process');
const path = require('path');

exports.default = async function afterPack(context) {
  const appOutDir = context.appOutDir;
  const appName = context.packager.appInfo.productFilename;

  // electron-builder 输出目录中找 PodGist.app
  const { execSync: exec } = require('child_process');
  let appPath = path.join(appOutDir, `${appName}.app`);
  if (!require('fs').existsSync(appPath)) {
    // 尝试其他常见命名
    const possible = require('fs').readdirSync(appOutDir).find(f => f.endsWith('.app'));
    if (possible) {
      appPath = path.join(appOutDir, possible);
    }
  }

  console.log(`[afterPack] .app path: ${appPath}`);

  // ========== Step 1: 检查签名前的二进制状态 ==========
  console.log('[afterPack] === 签名前二进制状态 ===');

  const apiEngine = path.join(appPath, 'Contents/Resources/api/api-engine');
  const ffmpeg = path.join(appPath, 'Contents/Resources/ffmpeg/ffmpeg');
  const ffprobe = path.join(appPath, 'Contents/Resources/ffmpeg/ffprobe');

  for (const bin of [apiEngine, ffmpeg, ffprobe]) {
    if (require('fs').existsSync(bin)) {
      const codeSigned = execSync(`codesign -d "${bin}" 2>&1 || echo UNSIGNED`, { encoding: 'utf8' }).trim();
      console.log(`  ${path.basename(path.dirname(path.dirname(bin)))}/${path.basename(bin)}: ${codeSigned.split('\n')[0]}`);
    }
  }

  // ========== Step 2: Ad-hoc deep sign ==========
  console.log('[afterPack] === 执行 ad-hoc deep sign ===');
  console.log(`  Signing: ${appPath}`);

  try {
    execSync(`codesign --force --deep --sign - "${appPath}"`, {
      stdio: 'inherit',
      shell: true
    });
    console.log('[afterPack] ad-hoc sign 完成');
  } catch (e) {
    console.error('[afterPack] ad-hoc sign 失败:', e.message);
    throw e;
  }

  // ========== Step 3: 验证签名 ==========
  console.log('[afterPack] === 验证签名 ===');
  try {
    const verifyOut = execSync(`codesign --verify --deep --strict "${appPath}" 2>&1`, { encoding: 'utf8' });
    console.log(`  verify pass: ${verifyOut.trim()}`);
  } catch (e) {
    console.error('[afterPack] codesign --verify --deep --strict 失败:', e.message);
    throw new Error(`App 签名验证失败: ${e.message}`);
  }

  // ========== Step 4: codesign -dv ==========
  try {
    const dvOut = execSync(`codesign -dv "${appPath}" 2>&1`, { encoding: 'utf8' });
    console.log('[afterPack] codesign -dv:');
    dvOut.split('\n').forEach(l => console.log('  ' + l));
  } catch (e) {
    console.log('[afterPack] codesign -dv:', e.message);
  }

  console.log('[afterPack] 全部完成，electron-builder 将继续生成 dmg');
};
