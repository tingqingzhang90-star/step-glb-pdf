/**
 * Empty shim for @mlightcad/cad-agent-plugin.
 *
 * The real package is an optional peer dependency of @mlightcad/cad-viewer.
 * It is NOT installed in this project. This shim provides stub exports so
 * that:
 *   - Vite's `__vite-optional-peer-dep:` protocol can resolve the
 *     `style.css` subpath (Vite 8.2.1 fails to convert `.css` subpaths
 *     into throw-on-call CJS stubs, unlike `/register` subpaths).
 *   - Any runtime code that does reach the dynamic `import()` will get a
 *     minimal object instead of a thrown module-resolution error.
 *
 * cad-viewer guards all real usage behind feature flags and try/catch
 * blocks, so these stubs will never actually be called in normal DX
 * workflows. If the real plugin is needed later, install it with
 * `npm install @mlightcad/cad-agent-plugin` and delete this shim folder.
 */

const AgentChatPanel = null;
const setAgentPaletteOpener = () => {};
const mergeAgentI18nIntoVueI18n = () => {};
const registerLazyAgentPlugin = () => {};

export {
  AgentChatPanel,
  setAgentPaletteOpener,
  mergeAgentI18nIntoVueI18n,
  registerLazyAgentPlugin
};

export default {
  AgentChatPanel,
  setAgentPaletteOpener,
  mergeAgentI18nIntoVueI18n,
  registerLazyAgentPlugin
};
