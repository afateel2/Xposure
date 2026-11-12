// Server-safe (no hooks): imported by app/layout.tsx.
const THEME_STORAGE_KEY = "xposure_theme";

/**
 * Inline script injected in <head> by layout.tsx so theme AND language are on
 * <html> before first paint (no flash of the wrong theme or direction).
 */
export const THEME_INIT_SCRIPT = `(function(){try{var d=document.documentElement;var t=localStorage.getItem('${THEME_STORAGE_KEY}');if(t!=='light'&&t!=='dark')t='dark';d.setAttribute('data-theme',t);var l=localStorage.getItem('xposure_lang');if(l==='en'||l==='ar'){d.setAttribute('data-lang',l);d.setAttribute('lang',l);d.setAttribute('dir',l==='ar'?'rtl':'ltr');}}catch(e){}})();`;
