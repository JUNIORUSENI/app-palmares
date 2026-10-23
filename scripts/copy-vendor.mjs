// Copie les bibliothèques JS installées par npm vers static/js (servies par WhiteNoise).
import { copyFileSync, mkdirSync } from 'node:fs';

mkdirSync('static/js', { recursive: true });
copyFileSync('node_modules/htmx.org/dist/htmx.min.js', 'static/js/htmx.min.js');
console.log('static/js/htmx.min.js copié');
