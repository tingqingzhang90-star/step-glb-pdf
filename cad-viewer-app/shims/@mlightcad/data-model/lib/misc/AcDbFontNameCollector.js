/**
 * AcDbFontNameCollector shim
 *
 * Patch for mlightcad publish bug: `@mlightcad/cad-simple-viewer@1.5.9`
 * imports `AcDbFontNameCollector` from `@mlightcad/data-model`, but
 * `data-model@1.12.4` does not export it. This shim provides a minimal
 * compatible implementation so vite dependency optimization can succeed.
 *
 * Usage (from cad-simple-viewer):
 *   new AcDbFontNameCollector({ styles, textStyleVar })
 *     .collect(entities, { getEntityFontInfo, getBlockEntities })
 *
 * `collect` returns a Map<string, { font, bigFont, extendedFont }> whose
 * keys are lower-cased font names. Entities referencing styles by name are
 * resolved through the styles map; INSERT/DIMENSION entities fall back to
 * their block's entities via `getBlockEntities`.
 */

/**
 * Normalize a font file name to a lower-case lookup key without extension.
 * @param {string} font
 * @returns {string}
 */
function normalizeFontName(font) {
  if (!font || typeof font !== 'string') return '';
  let name = font.trim().toLowerCase();
  // Strip directory prefix
  const slash = Math.max(name.lastIndexOf('/'), name.lastIndexOf('\\'));
  if (slash >= 0) name = name.slice(slash + 1);
  // Strip common font extensions
  name = name.replace(/\.(ttf|otf|ttc|shx|shp|pfb|pfm)$/i, '');
  return name;
}

class AcDbFontNameCollector {
  /**
   * @param {object} options
   * @param {Array<{name: string, font?: string, bigFont?: string, extendedFont?: string, standardFlag?: number}>} options.styles
   * @param {string} [options.textStyleVar]
   */
  constructor(options) {
    const opts = options || {};
    this.textStyleVar = opts.textStyleVar || '';
    /** @type {Map<string, {font: string, bigFont: string, extendedFont: string}>} */
    this.styleMap = new Map();
    /** @type {Map<string, {font: string, bigFont: string, extendedFont: string}>} */
    this.styleByName = new Map();
    (opts.styles || []).forEach((style) => {
      const entry = {
        font: style.font || '',
        bigFont: style.bigFont || '',
        extendedFont: style.extendedFont || ''
      };
      if (style.name) {
        this.styleByName.set(style.name, entry);
        this.styleByName.set(style.name.toLowerCase(), entry);
      }
    });
  }

  /**
   * Resolve style entry by style name (case-insensitive).
   * @param {string} styleName
   * @returns {{font: string, bigFont: string, extendedFont: string} | undefined}
   */
  _resolveStyle(styleName) {
    if (!styleName) return undefined;
    if (this.styleByName.has(styleName)) return this.styleByName.get(styleName);
    return this.styleByName.get(String(styleName).toLowerCase());
  }

  /**
   * Add a font name into the result map.
   * @param {Map<string, object>} result
   * @param {string} font
   * @param {string} [bigFont]
   * @param {string} [extendedFont]
   */
  _addFont(result, font, bigFont, extendedFont) {
    const key = normalizeFontName(font);
    if (key && !result.has(key)) {
      result.set(key, { font, bigFont: bigFont || '', extendedFont: extendedFont || '' });
    }
    const bigKey = normalizeFontName(bigFont);
    if (bigKey && !result.has(bigKey)) {
      result.set(bigKey, { font: bigFont, bigFont: '', extendedFont: '' });
    }
  }

  /**
   * Collect all font names referenced by the given entities.
   * @param {Array<any>} entities
   * @param {object} options
   * @param {(entity: any) => {styleName?: string, formattedText?: string, resolveStyle?: boolean, blockName?: string} | null} options.getEntityFontInfo
   * @param {(blockName: string) => Array<any> | undefined} options.getBlockEntities
   * @returns {Map<string, {font: string, bigFont: string, extendedFont: string}>}
   */
  collect(entities, options) {
    const opts = options || {};
    const getEntityFontInfo = opts.getEntityFontInfo || (() => null);
    const getBlockEntities = opts.getBlockEntities || (() => undefined);
    /** @type {Map<string, {font: string, bigFont: string, extendedFont: string}>} */
    const result = new Map();

    // Always include the active text style (TEXTSTYLE sysvar) first.
    if (this.textStyleVar) {
      const entry = this._resolveStyle(this.textStyleVar);
      if (entry) this._addFont(result, entry.font, entry.bigFont, entry.extendedFont);
    }

    const visitedBlocks = new Set();
    const visitEntities = (list) => {
      if (!list || !list.length) return;
      for (const entity of list) {
        let info;
        try {
          info = getEntityFontInfo(entity);
        } catch (_) {
          info = null;
        }
        if (!info) continue;

        if (info.blockName) {
          if (visitedBlocks.has(info.blockName)) continue;
          visitedBlocks.add(info.blockName);
          const blockEntities = getBlockEntities(info.blockName);
          if (blockEntities && blockEntities.length) visitEntities(blockEntities);
          continue;
        }

        if (info.resolveStyle && info.styleName) {
          const entry = this._resolveStyle(info.styleName);
          if (entry) this._addFont(result, entry.font, entry.bigFont, entry.extendedFont);
        }
        // Inline formatted text fonts (\fArial.ttf|...) are not parsed here;
        // cad-simple-viewer's static MText.getFonts handles them separately.
      }
    };

    visitEntities(entities || []);

    // Also collect fonts from all known styles to be safe.
    this.styleByName.forEach((entry) => {
      this._addFont(result, entry.font, entry.bigFont, entry.extendedFont);
    });

    return result;
  }
}

export { AcDbFontNameCollector, normalizeFontName };
//# sourceMappingURL=AcDbFontNameCollector.js.map
