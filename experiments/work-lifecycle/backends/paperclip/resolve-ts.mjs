// Preserve upstream source imports while executing TypeScript with Node's stripper.
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export async function resolve(specifier, context, nextResolve) {
  if (specifier.endsWith('.js') && specifier.startsWith('.') && context.parentURL) {
    const target = new URL(specifier.slice(0, -3) + '.ts', context.parentURL);
    if (existsSync(fileURLToPath(target))) return nextResolve(target.href, context);
  }
  return nextResolve(specifier, context);
}
