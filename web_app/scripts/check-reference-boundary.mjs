import { lstat, readFile, readdir, realpath } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = resolve(webRoot, 'src');
const forbiddenReference = /new[_-]front/i;
const filesToScan = [
  resolve(webRoot, 'package.json'),
  resolve(webRoot, 'package-lock.json'),
  resolve(webRoot, 'tsconfig.json'),
  resolve(webRoot, 'vite.config.ts'),
];
const violations = [];

async function collectSourceFiles(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = resolve(directory, entry.name);
    const entryStats = await lstat(entryPath);

    if (entryStats.isSymbolicLink()) {
      violations.push(`${relative(webRoot, entryPath)} is a symbolic link`);
      continue;
    }
    if (entry.isDirectory()) {
      await collectSourceFiles(entryPath);
      continue;
    }
    if (entry.isFile()) filesToScan.push(entryPath);
  }
}

await collectSourceFiles(sourceRoot);

for (const filePath of filesToScan) {
  const canonicalPath = await realpath(filePath);
  const relativePath = relative(webRoot, canonicalPath);
  if (relativePath.startsWith('..')) {
    violations.push(`${relative(webRoot, filePath)} resolves outside web_app`);
    continue;
  }

  const contents = await readFile(filePath, 'utf8');
  if (forbiddenReference.test(contents)) {
    violations.push(`${relative(webRoot, filePath)} contains a forbidden reference`);
  }
}

if (violations.length > 0) {
  console.error('Reference boundary check failed:');
  for (const violation of violations) console.error(`- ${violation}`);
  process.exit(1);
}

console.log(`Reference boundary is clean (${filesToScan.length} production files checked).`);
