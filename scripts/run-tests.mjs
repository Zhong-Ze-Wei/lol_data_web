import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const runner = fileURLToPath(new URL('./run-python.mjs', import.meta.url));
const python = spawnSync(process.execPath, [runner, '-m', 'pytest'], { cwd: root, stdio: 'inherit' });
if (python.status !== 0) process.exit(python.status ?? 1);
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const frontend = spawnSync(npm, ['--prefix', 'frontend', 'test'], {
  cwd: root, stdio: 'inherit', shell: process.platform === 'win32'
});
process.exit(frontend.status ?? 1);
