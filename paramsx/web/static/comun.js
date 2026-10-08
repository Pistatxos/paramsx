// Lo que comparten ParamsX y Ajustes: llamadas al servidor, avisos, modal y la navegación.
'use strict';
const $ = id => document.getElementById(id);
// Safari y los gestores de contraseñas proponen correos o contactos en cualquier campo: aquí no hay nada que rellenar
const NOFILL = 'autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" data-1p-ignore data-lpignore="true" data-form-type="other"';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(url, opciones = {}) {
  const r = await fetch(url, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, ...opciones });
  let datos;
  try { datos = await r.json(); } catch { datos = { error: r.status === 403 ? 'Sesión no válida: abre la URL que sale en la terminal.' : `Error ${r.status}` }; }
  if (!r.ok) { const e = new Error(datos.error || `Error ${r.status}`); e.datos = datos; throw e; }
  return datos;
}
const post = (url, datos) => api(url, { method: 'POST', body: JSON.stringify(datos) });

function toast(mensaje, mal) {
  const t = document.createElement('div');
  t.className = 'toast' + (mal ? ' mal' : '');
  t.textContent = mensaje;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), mal ? 7000 : 3500);
}

// ------------------------------------------------ estado compartido (config leída del servidor)
const PX = { estado: null, oyentes: [], pendientes: () => 0 };
async function refrescarEstado() {
  PX.estado = await api('/api/estado');
  PX.oyentes.forEach(f => f(PX.estado));
  return PX.estado;
}
// Config normalizada para usarla en la página (entornos en minúscula, como la terminal)
function cfg() {
  const c = PX.estado && PX.estado.config;
  if (!c) return { entornos: [], perfiles: {}, tags_obligatorias: [], tags_activas: false, perfil_nuevos: '', forzar_securestring: true };
  return { ...c, entornos: (c.entornos || []).map(e => String(e).toLowerCase()) };
}

// ------------------------------------------------ modal (al cerrar, los valores salen también del DOM)
const modal = {
  abierto: () => !$('modal').hidden,
  abrir(html) { $('modalCuerpo').innerHTML = html; $('modal').hidden = false; },
  cerrar() { $('modal').hidden = true; $('modalCuerpo').innerHTML = ''; $('modalCuerpo').onclick = null; },
};
$('modalCerrar').onclick = modal.cerrar;
$('modal').addEventListener('mousedown', e => { if (e.target === $('modal')) modal.cerrar(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.abierto()) modal.cerrar(); });

// ------------------------------------------------ navegación: #/ y #/ajustes
function mostrarVista() {
  const vista = location.hash === '#/ajustes' ? 'ajustes' : 'params';
  $('vParams').hidden = vista !== 'params';
  $('vAjustes').hidden = vista !== 'ajustes';
  document.querySelectorAll('.lateral a').forEach(a => a.classList.toggle('activo', a.dataset.vista === vista));
  document.title = vista === 'ajustes' ? 'Ajustes · ParamsX' : 'ParamsX';
}
window.addEventListener('hashchange', mostrarVista);
mostrarVista();
