// Use the existing TypeScript compiler for component tests; no DOM/framework dependency.
import { readFile, access } from 'node:fs/promises';
import ts from 'typescript';
export async function resolve(specifier, context, next) {
  if (specifier.startsWith('.') && context.parentURL?.includes('/src/') && !/\.[a-z]+$/i.test(specifier)) {
    for (const ext of ['.ts', '.tsx']) {
      const url = new URL(specifier + ext, context.parentURL);
      try { await access(url); return {url: url.href, shortCircuit: true}; } catch { /* try next extension */ }
    }
  }
  return next(specifier, context);
}
export async function load(url, context, next) {
  if (/\/src\/.*\.tsx?$/.test(url)) {
    const source = await readFile(new URL(url), 'utf8');
    return {format: 'module', shortCircuit: true, source: ts.transpileModule(source, {
      compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022},
      fileName: new URL(url).pathname,
    }).outputText};
  }
  return next(url, context);
}
