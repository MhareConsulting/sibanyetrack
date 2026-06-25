/**
 * MhareReach · myTrack — Icon System (Vanilla JS)
 * ─────────────────────────────────────────────────
 * Drop-in icon registry for Django templates. Mirrors the React Icon.tsx
 * registry so both stacks stay in sync with identical paths and naming.
 *
 * Usage — HTML string (for innerHTML injection or JS-built UI):
 *   import { iconHtml } from '/static/js/icons.js';
 *   btn.innerHTML = iconHtml('truck', 'w-5 h-5 text-gray-700') + ' Dispatch';
 *
 * Usage — DOM element (for direct appendChild):
 *   import { createIcon } from '/static/js/icons.js';
 *   container.prepend(createIcon('alert-triangle', 'w-4 h-4 text-red-600'));
 *
 * Usage — Django template (CDN / script tag, UMD global):
 *   <script src="{% static 'js/icons.js' %}"></script>
 *   <script>
 *     document.getElementById('btn').prepend(MhareIcons.createIcon('check-circle'));
 *   </script>
 *
 * Extending the registry:
 *   MhareIcons.register('my-custom-icon', '<path d="..."/>');
 */

'use strict';

// ─────────────────────────────────────────────────────────────────────────────
//  REGISTRY
//  Values are raw SVG inner-HTML strings (children only — no <svg> wrapper).
//  All paths are Lucide-compatible: viewBox 0 0 24 24, stroke-based, outline.
// ─────────────────────────────────────────────────────────────────────────────

const ICONS = {

  // ── Fleet & Logistics ───────────────────────────────────────────────────────

  'truck': `
    <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/>
    <path d="M15 18H9"/>
    <path d="M19 18h2a1 1 0 0 0 1-1v-3.28a1 1 0 0 0-.684-.948l-1.923-.641a1 1 0 0 1-.578-.502l-1.539-3.076A1 1 0 0 0 16.38 8H14"/>
    <circle cx="17" cy="18" r="2"/>
    <circle cx="7" cy="18" r="2"/>`,

  'map-pin': `
    <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/>
    <circle cx="12" cy="10" r="3"/>`,

  'route': `
    <circle cx="6" cy="19" r="3"/>
    <path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/>
    <circle cx="18" cy="5" r="3"/>`,

  'navigation': `
    <polygon points="3 11 22 2 13 21 11 13 3 11"/>`,

  'fuel': `
    <path d="M3 22V8l8-6 8 6v14"/>
    <line x1="3" y1="22" x2="21" y2="22"/>
    <rect x="9" y="14" width="6" height="8"/>
    <path d="M21 7.5V12"/>
    <path d="M21 7.5c0-1.38-.56-2-2-2s-2 .62-2 2v5.5"/>
    <path d="M17 12.5h4"/>`,

  // ── Alerts & Status ─────────────────────────────────────────────────────────

  'alert-triangle': `
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
    <path d="M12 9v4"/>
    <path d="M12 17h.01"/>`,

  'alert-circle': `
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="8" x2="12" y2="12"/>
    <line x1="12" y1="16" x2="12.01" y2="16"/>`,

  'bell': `
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
    <path d="M13.73 21a2 2 0 0 1-3.46 0"/>`,

  // ── Compliance & RegTech ────────────────────────────────────────────────────

  'shield-check': `
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    <path d="m9 12 2 2 4-4"/>`,

  'shield': `
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>`,

  'file-text': `
    <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" y1="13" x2="8" y2="13"/>
    <line x1="16" y1="17" x2="8" y2="17"/>
    <line x1="10" y1="9" x2="8" y2="9"/>`,

  'clipboard': `
    <rect x="9" y="2" width="6" height="4" rx="1" ry="1"/>
    <path d="M9 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2h-3"/>`,

  // ── People & Identity ───────────────────────────────────────────────────────

  'user': `
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
    <circle cx="12" cy="7" r="4"/>`,

  'users': `
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>`,

  'user-check': `
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <polyline points="16 11 18 13 22 9"/>`,

  // ── Time & Scheduling ───────────────────────────────────────────────────────

  'clock': `
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 6 12 12 16 14"/>`,

  'calendar': `
    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
    <line x1="16" y1="2" x2="16" y2="6"/>
    <line x1="8" y1="2" x2="8" y2="6"/>
    <line x1="3" y1="10" x2="21" y2="10"/>`,

  // ── UI Controls & Navigation ────────────────────────────────────────────────

  'settings': `
    <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
    <circle cx="12" cy="12" r="3"/>`,

  'more-vertical': `
    <circle cx="12" cy="5" r="1"/>
    <circle cx="12" cy="12" r="1"/>
    <circle cx="12" cy="19" r="1"/>`,

  'more-horizontal': `
    <circle cx="5" cy="12" r="1"/>
    <circle cx="12" cy="12" r="1"/>
    <circle cx="19" cy="12" r="1"/>`,

  'chevron-down': `<polyline points="6 9 12 15 18 9"/>`,
  'chevron-right': `<polyline points="9 18 15 12 9 6"/>`,
  'chevron-left': `<polyline points="15 18 9 12 15 6"/>`,
  'chevron-up': `<polyline points="18 15 12 9 6 15"/>`,

  // ── Actions ─────────────────────────────────────────────────────────────────

  'check-circle': `
    <circle cx="12" cy="12" r="10"/>
    <path d="m9 12 2 2 4-4"/>`,

  'check': `<polyline points="20 6 9 17 4 12"/>`,

  'x': `
    <path d="M18 6 6 18"/>
    <path d="m6 6 12 12"/>`,

  'x-circle': `
    <circle cx="12" cy="12" r="10"/>
    <path d="m15 9-6 6"/>
    <path d="m9 9 6 6"/>`,

  'search': `
    <circle cx="11" cy="11" r="8"/>
    <path d="m21 21-4.35-4.35"/>`,

  'filter': `
    <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>`,

  'refresh-cw': `
    <polyline points="23 4 23 10 17 10"/>
    <polyline points="1 20 1 14 7 14"/>
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>`,

  'download': `
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="7 10 12 15 17 10"/>
    <line x1="12" y1="15" x2="12" y2="3"/>`,

  'upload': `
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="17 8 12 3 7 8"/>
    <line x1="12" y1="3" x2="12" y2="15"/>`,

  'log-out': `
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
    <polyline points="16 17 21 12 16 7"/>
    <line x1="21" y1="12" x2="9" y2="12"/>`,

  // ── Data & Analytics ────────────────────────────────────────────────────────

  'bar-chart': `
    <line x1="18" y1="20" x2="18" y2="10"/>
    <line x1="12" y1="20" x2="12" y2="4"/>
    <line x1="6" y1="20" x2="6" y2="14"/>`,

  'activity': `<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>`,

  'trending-up': `
    <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
    <polyline points="17 6 23 6 23 12"/>`,

  // ── Map & Location ──────────────────────────────────────────────────────────

  'map': `
    <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/>
    <line x1="8" y1="2" x2="8" y2="18"/>
    <line x1="16" y1="6" x2="16" y2="22"/>`,

  'globe': `
    <circle cx="12" cy="12" r="10"/>
    <line x1="2" y1="12" x2="22" y2="12"/>
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>`,

  'crosshair': `
    <circle cx="12" cy="12" r="10"/>
    <line x1="22" y1="12" x2="18" y2="12"/>
    <line x1="6" y1="12" x2="2" y2="12"/>
    <line x1="12" y1="6" x2="12" y2="2"/>
    <line x1="12" y1="22" x2="12" y2="18"/>`,

  // ── Expand / Layout ─────────────────────────────────────────────────────────

  'expand': `
    <polyline points="15 3 21 3 21 9"/>
    <polyline points="9 21 3 21 3 15"/>
    <line x1="21" y1="3" x2="14" y2="10"/>
    <line x1="3" y1="21" x2="10" y2="14"/>`,

  'minimize': `
    <polyline points="4 14 10 14 10 20"/>
    <polyline points="20 10 14 10 14 4"/>
    <line x1="10" y1="14" x2="3" y2="21"/>
    <line x1="21" y1="3" x2="14" y2="10"/>`,
};

// ─────────────────────────────────────────────────────────────────────────────
//  INTERNALS
// ─────────────────────────────────────────────────────────────────────────────

const NS = 'http://www.w3.org/2000/svg';
const FALLBACK_CLASS = 'inline-flex items-center justify-center w-5 h-5 rounded border-2 border-dashed border-gray-300';

function _warn(name) {
  console.warn(
    `%c[MhareReach Icons]%c Unknown icon: "${name}".\nValid names: ${Object.keys(ICONS).sort().join(', ')}`,
    'color:#7c3aed;font-weight:bold', 'color:inherit'
  );
}

// ─────────────────────────────────────────────────────────────────────────────
//  PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Returns a ready-to-inject SVG HTML string.
 *
 * @param {string} name      - Icon name from the registry.
 * @param {string} className - Tailwind/CSS classes for sizing & colour.
 *                             Defaults to 'w-5 h-5'.
 * @param {number} strokeWidth - SVG stroke-width. Defaults to 2.
 * @returns {string}
 *
 * @example
 * el.innerHTML = iconHtml('truck', 'w-5 h-5 text-indigo-600') + ' Dispatch';
 */
export function iconHtml(name, className = 'w-5 h-5', strokeWidth = 2) {
  const inner = ICONS[name];
  if (!inner) {
    _warn(name);
    return `<span class="${FALLBACK_CLASS}" title="[icon: ${name}]" aria-hidden="true"></span>`;
  }
  return (
    `<svg xmlns="${NS}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round" ` +
    `class="${className}" aria-hidden="true">${inner}</svg>`
  );
}

/**
 * Creates and returns a live SVG DOM element (or fallback <span>).
 * Safe to append directly — no innerHTML involved.
 *
 * @param {string} name      - Icon name from the registry.
 * @param {string} className - CSS classes. Defaults to 'w-5 h-5'.
 * @param {number} strokeWidth - SVG stroke-width. Defaults to 2.
 * @returns {SVGSVGElement|HTMLSpanElement}
 *
 * @example
 * const icon = createIcon('alert-triangle', 'w-4 h-4 text-red-600');
 * headerEl.prepend(icon);
 */
export function createIcon(name, className = 'w-5 h-5', strokeWidth = 2) {
  const inner = ICONS[name];
  if (!inner) {
    _warn(name);
    const span = document.createElement('span');
    span.className = FALLBACK_CLASS;
    span.title = `[icon: ${name}]`;
    span.setAttribute('aria-hidden', 'true');
    return span;
  }
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', String(strokeWidth));
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('class', className);
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = inner;
  return svg;
}

/**
 * Registers a custom icon (or overrides an existing one) at runtime.
 *
 * @param {string} name  - Unique icon name.
 * @param {string} paths - SVG child elements as a raw HTML string.
 *
 * @example
 * register('agri-trektor', '<path d="M..."/><circle cx="..." cy="..." r="..."/>');
 */
export function register(name, paths) {
  if (!name || typeof paths !== 'string') {
    console.error('[MhareReach Icons] register(name, paths) — both arguments are required.');
    return;
  }
  ICONS[name] = paths;
}

/** Read-only list of all registered icon names. */
export function iconNames() {
  return Object.keys(ICONS).sort();
}

// ─────────────────────────────────────────────────────────────────────────────
//  UMD-STYLE GLOBAL (for non-module <script> usage in Django templates)
//  e.g.  MhareIcons.createIcon('truck')
// ─────────────────────────────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  window.MhareIcons = { iconHtml, createIcon, register, iconNames };
}
