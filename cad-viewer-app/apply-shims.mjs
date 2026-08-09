#!/usr/bin/env node
/**
 * apply-shims.mjs
 *
 * Apply local shims into node_modules after `npm install`.
 *
 * Two kinds of shims are supported:
 *   1. New package shims — entire directories under shims/@scope/pkg/
 *      that should be copied verbatim into node_modules/@scope/pkg/.
 *      Used when a package does not exist at all (e.g. cad-agent-plugin).
 *   2. In-place patches — a `patch.json` file inside shims/@scope/pkg/
 *      describing textual edits to apply on the installed package's files.
 *      Used when a package exists but is missing an export (e.g. the
 *      AcDbFontNameCollector export missing from @mlightcad/data-model).
 *
 * Idempotent: running multiple times yields the same result. Safe to run
 * from `postinstall` or manually via `node apply-shims.mjs`.
 *
 * Why this exists:
 *   - @mlightcad/cad-simple-viewer@1.5.9 imports `AcDbFontNameCollector`
 *     from @mlightcad/data-model@1.12.4, but that class was never
 *     exported (publish bug). We provide a minimal implementation.
 *   - @mlightcad/cad-viewer@1.5.9 dynamically imports
 *     `@mlightcad/cad-agent-plugin/style.css` as an optional peer dep.
 *     Vite 8.2.1's `__vite-optional-peer-dep:` protocol fails to convert
 *     `.css` subpaths into throw-on-call CJS stubs (unlike /register
 *     subpaths), so we install an empty shim package to let the protocol
 *     resolve normally.
 */

import { readFile, writeFile, access, mkdir, cp, readdir, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = __dirname;
const SHIMS_DIR = join(ROOT, 'shims');
const NM_DIR = join(ROOT, 'node_modules');

const log = (msg) => console.log(`[apply-shims] ${msg}`);
const warn = (msg) => console.warn(`[apply-shims] WARN: ${msg}`);

async function pathExists(p) {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

/**
 * Recursively copy a directory, creating parents as needed.
 */
async function copyDir(src, dest) {
  await mkdir(dest, { recursive: true });
  await cp(src, dest, { recursive: true });
}

/**
 * Apply a patch.json edit to a target file.
 * Supported edit types:
 *   - "append-line": append a line to end of file (if not already present)
 *   - "replace": replace first occurrence of `find` with `replaceWith`
 */
async function applyPatchEdit(targetFile, edit) {
  let content = await readFile(targetFile, 'utf8');

  if (edit.type === 'append-line') {
    const line = edit.line;
    if (content.includes(line)) {
      log(`  [skip] append-line already present in ${targetFile}`);
      return;
    }
    // Ensure trailing newline before appending.
    const sep = content.endsWith('\n') ? '' : '\n';
    content = content + sep + line + '\n';
    await writeFile(targetFile, content, 'utf8');
    log(`  [done] appended line to ${targetFile}`);
  } else if (edit.type === 'replace') {
    if (!content.includes(edit.find)) {
      // If the replaceWith is already present, treat as already applied.
      if (content.includes(edit.replaceWith)) {
        log(`  [skip] replace already applied in ${targetFile}`);
        return;
      }
      warn(`  [fail] could not find pattern in ${targetFile}: ${edit.find.slice(0, 80)}...`);
      return;
    }
    content = content.replace(edit.find, edit.replaceWith);
    await writeFile(targetFile, content, 'utf8');
    log(`  [done] replaced text in ${targetFile}`);
  } else {
    warn(`  [skip] unknown edit type: ${edit.type}`);
  }
}

/**
 * Apply all shims found under shims/@scope/pkg/.
 *
 * If the shim directory contains a `patch.json`, the patch edits are
 * applied to the installed package's files. All other files in the shim
 * directory are copied verbatim into the installed package, preserving
 * relative paths.
 */
async function applyShimPackage(shimPkgDir, scopeName, pkgName) {
  const targetPkgDir = join(NM_DIR, scopeName, pkgName);

  // Read all entries in the shim dir.
  const entries = await readdir(shimPkgDir);
  const patchFile = entries.find((e) => e === 'patch.json');
  const filesToCopy = entries.filter((e) => e !== 'patch.json');

  // If the target package does not exist at all, copy the whole shim dir
  // as a new package (this is the cad-agent-plugin case).
  if (!(await pathExists(targetPkgDir))) {
    if (filesToCopy.length === 0) {
      warn(`  target ${targetPkgDir} does not exist and no files to copy`);
      return;
    }
    log(`  creating new package at ${targetPkgDir}`);
    await mkdir(targetPkgDir, { recursive: true });
    for (const entry of filesToCopy) {
      const src = join(shimPkgDir, entry);
      const dest = join(targetPkgDir, entry);
      const s = await stat(src);
      if (s.isDirectory()) {
        await copyDir(src, dest);
      } else {
        await mkdir(dirname(dest), { recursive: true });
        await writeFile(dest, await readFile(src), 'utf8');
      }
      log(`  [done] copied ${entry}`);
    }
    return;
  }

  // Target package exists — copy new files and apply patch edits.
  for (const entry of filesToCopy) {
    const src = join(shimPkgDir, entry);
    const dest = join(targetPkgDir, entry);
    const s = await stat(src);
    if (s.isDirectory()) {
      await copyDir(src, dest);
      log(`  [done] copied dir ${entry}/`);
    } else {
      await mkdir(dirname(dest), { recursive: true });
      await writeFile(dest, await readFile(src), 'utf8');
      log(`  [done] copied ${entry}`);
    }
  }

  if (patchFile) {
    const patchPath = join(shimPkgDir, patchFile);
    const patch = JSON.parse(await readFile(patchPath, 'utf8'));
    log(`  applying ${patch.edits.length} patch edit(s) from ${patchFile}`);
    for (const edit of patch.edits) {
      const targetFile = join(targetPkgDir, edit.file);
      if (!(await pathExists(targetFile))) {
        warn(`  [fail] target file not found: ${targetFile}`);
        continue;
      }
      await applyPatchEdit(targetFile, edit);
    }
  }
}

async function main() {
  log(`shims dir: ${SHIMS_DIR}`);
  if (!existsSync(SHIMS_DIR)) {
    log('no shims/ directory found, nothing to do');
    return;
  }
  if (!existsSync(NM_DIR)) {
    warn('node_modules/ not found, run `npm install` first');
    return;
  }

  // Walk shims/@scope/pkg/
  const scopes = await readdir(SHIMS_DIR);
  for (const scopeEntry of scopes) {
    const scopeDir = join(SHIMS_DIR, scopeEntry);
    const s = await stat(scopeDir);
    if (!s.isDirectory()) continue;

    // scopeEntry should be like "@mlightcad"
    const pkgs = await readdir(scopeDir);
    for (const pkgEntry of pkgs) {
      const pkgDir = join(scopeDir, pkgEntry);
      const ps = await stat(pkgDir);
      if (!ps.isDirectory()) continue;

      log(`applying shim: ${scopeEntry}/${pkgEntry}`);
      try {
        await applyShimPackage(pkgDir, scopeEntry, pkgEntry);
      } catch (err) {
        warn(`  failed: ${err.message}`);
      }
    }
  }
  log('done');
}

main().catch((err) => {
  console.error('[apply-shims] fatal:', err);
  process.exit(0); // do not block npm install
});
