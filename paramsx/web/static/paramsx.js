// ParamsX: cargar un grupo (ruta × entorno), editar todos sus parámetros a la vez, revisar contra AWS, aplicar e historial.
// Los valores solo viven en esta página: no se guardan en ningún sitio (al cerrar la pestaña, desaparecen).
(function () {
  'use strict';
  const TIPOS = ['String', 'StringList', 'SecureString'];
  const S = { grupo: '', entorno: '', ruta: '', items: [], donde: '', account: '' };
  const cuando = v => v ? new Date(v).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' }) : '';
  const quien = u => (u || '').split('/').pop();
  const grupos = () => (PX.estado && PX.estado.grupos) || [];
  const grupoSel = () => grupos()[S.grupo];
  const obligatorias = () => cfg().tags_activas ? (cfg().tags_obligatorias || []) : [];
  const entornoDe = seg => cfg().entornos.find(e => e === String(seg).toLowerCase());
  const claseEntorno = e => !e ? '' : /^prod/.test(e) ? 'prod' : /^(stg|pre|staging|qa|test|uat)/.test(e) ? 'stg' : 'dev';

  // ------------------------------------------------ perfil, región y grupos
  async function pintarDonde() {
    const c = PX.estado && PX.estado.config;
    if (!c) { $('pDonde').textContent = 'Sin configurar · Ajustes'; return; }
    $('pDonde').innerHTML = `<b>${esc(c.profile_name)}</b><span>${esc(c.region_name)}</span><span id="pCuenta">…</span>`;
    try {
      const r = await api('/api/cuenta');
      S.account = r.account;
      $('pCuenta').textContent = r.account;
      $('pDonde').title = `${r.arn}\nCambiar en Ajustes`;
    } catch (e) {
      S.account = '';
      $('pCuenta').innerHTML = '<span class="error">sin credenciales</span>';
      $('pDonde').title = e.message;
    }
  }
  function pintarAviso() {
    const st = PX.estado, a = $('pAviso');
    a.className = 'aviso';
    if (st.error_lectura) { a.classList.add('mal'); a.innerHTML = `No se puede leer la configuración: ${esc(st.error_lectura)}`; }
    else if (!st.existe) a.innerHTML = 'Aún no tienes configuración: ve a <a href="#/ajustes">Ajustes</a>, elige tu perfil de AWS y guarda. Mientras, puedes explorar y escribir rutas.';
    else if (st.errores.length) { a.classList.add('mal'); a.innerHTML = `La configuración tiene ${st.errores.length} ${st.errores.length === 1 ? 'error' : 'errores'}: corrígelos en <a href="#/ajustes">Ajustes</a>.`; }
    else { a.hidden = true; return; }
    a.hidden = false;
  }
  function pintarGrupos() {
    const anterior = grupoSel();
    $('pGrupo').innerHTML = '<option value="">— Ruta libre —</option>' + grupos().map((g, i) => `<option value="${i}">${esc(g.nombre)} · ${esc(g.path)}</option>`).join('');
    const i = anterior ? grupos().findIndex(g => g.path === anterior.path && g.perfil === anterior.perfil) : -1;
    S.grupo = i < 0 ? '' : String(i);
    $('pGrupo').value = S.grupo;
    pintarEntornos();
  }
  function pintarEntornos() {
    const g = grupoSel();
    $('pEntornos').innerHTML = g ? cfg().entornos.map(e => `<button type="button" class="secundario ${e === S.entorno ? 'activo' : ''}" data-entorno="${esc(e)}" ${g.rutas[e] ? `title="${esc(g.rutas[e])}"` : 'disabled title="Revisa este grupo en Ajustes"'}>${esc(e)}</button>`).join('') : '';
  }
  PX.oyentes.push(st => {
    const donde = st.config ? `${st.config.profile_name}|${st.config.region_name}` : '';
    if (donde !== S.donde) {  // otro perfil o región: lo cargado era de otra cuenta
      S.donde = donde; S.items = []; S.carpetas = null; S.ruta = ''; $('pBarra').hidden = true; $('pLista').innerHTML = '';
      $('pEstado').textContent = '';
      pintarDonde();
    }
    pintarAviso(); pintarGrupos();
  });

  $('pGrupo').onchange = () => { S.grupo = $('pGrupo').value; S.entorno = ''; pintarEntornos(); };
  $('pEntornos').addEventListener('click', e => {
    const b = e.target.closest('[data-entorno]'); if (!b || !salirSinGuardar()) return;
    S.entorno = b.dataset.entorno;
    $('pRuta').value = grupoSel().rutas[S.entorno];
    pintarEntornos(); cargar();
  });
  // La ruta escrita a mano (Intro en el buscador): si ya no es la del grupo elegido, deja de ser ese grupo
  function cargarEscrita() {
    if (!salirSinGuardar()) return;
    const g = grupoSel();
    if (!g || $('pRuta').value.trim() !== g.rutas[S.entorno]) { S.grupo = ''; $('pGrupo').value = ''; S.entorno = ''; pintarEntornos(); }
    cargar();
  }
  // ↻ Recargar: vuelve a leer de AWS lo que hay cargado
  $('pEstado').addEventListener('click', e => {
    if (!e.target.closest('[data-recargar]') || !salirSinGuardar()) return;
    $('pRuta').value = S.ruta; S.items = []; cargar();
  });

  // ------------------------------------------------ buscador de rutas (solo nombres, como «Buscar en la cuenta» de Ajustes)
  const B = { activa: -1, lista: [], pidiendo: null };
  // {carpeta: nº de parámetros por debajo}, de todos los niveles; se pide una vez por perfil y región
  async function carpetas() {
    if (S.carpetas) return S.carpetas;
    B.pidiendo = B.pidiendo || api('/api/explorar').then(r => {
      const c = {};
      r.nombres.forEach(n => { const seg = n.split('/').filter(Boolean); for (let i = 1; i < seg.length; i++) { const k = '/' + seg.slice(0, i).join('/'); c[k] = (c[k] || 0) + 1; } });
      S.carpetas = c; return c;
    }).finally(() => { B.pidiendo = null; });
    return B.pidiendo;
  }
  const resaltar = (texto, q) => { const i = texto.toLowerCase().indexOf(q); return i < 0 ? esc(texto) : esc(texto.slice(0, i)) + '<mark>' + esc(texto.slice(i, i + q.length)) + '</mark>' + esc(texto.slice(i + q.length)); };
  function cerrarSugerencias() { $('pSugerencias').hidden = true; $('pRuta').setAttribute('aria-expanded', 'false'); B.activa = -1; }
  function marcarActiva(i) {
    const filas = $('pSugerencias').querySelectorAll('.sug');
    B.activa = Math.max(-1, Math.min(i, filas.length - 1));
    filas.forEach((f, n) => f.classList.toggle('activa', n === B.activa));
    if (filas[B.activa]) filas[B.activa].scrollIntoView({ block: 'nearest' });
  }
  async function sugerir() {
    const q = $('pRuta').value.trim().toLowerCase(), caja = $('pSugerencias');
    if (!q) return cerrarSugerencias();
    caja.hidden = false; $('pRuta').setAttribute('aria-expanded', 'true');
    if (!S.carpetas) caja.innerHTML = '<div class="sug-ayuda">Leyendo las rutas de la cuenta (solo nombres)…</div>';
    let c;
    try { c = await carpetas(); } catch (e) { caja.innerHTML = `<div class="sug-ayuda error">${esc(e.message)}</div>`; return; }
    if ($('pRuta').value.trim().toLowerCase() !== q) return;  // ya se ha escrito otra cosa
    // Primero las que empiezan por lo escrito, luego las más cortas
    B.lista = Object.keys(c).filter(k => k.toLowerCase().includes(q))
      .sort((a, b) => (b.toLowerCase().startsWith(q) - a.toLowerCase().startsWith(q)) || a.split('/').length - b.split('/').length || a.localeCompare(b)).slice(0, 200);
    caja.innerHTML = B.lista.map((k, i) => `<div class="sug" role="option" data-i="${i}"><code>${resaltar(k, q)}</code><span class="exp-n">${c[k]}</span><button type="button" class="secundario sug-grupo" data-grupo-de="${esc(k)}" title="Guardar esta carpeta como grupo (se detecta dónde va el entorno)" tabindex="-1">+ Grupo</button></div>`).join('')
      + `<div class="sug-ayuda">${B.lista.length ? '<kbd>↑</kbd> <kbd>↓</kbd> para elegir · «+ Grupo» la guarda en tus grupos · ' : 'Ninguna carpeta con eso. '}<kbd>Intro</kbd> carga ${B.lista.length ? 'la elegida' : 'la ruta tal cual'}${q.startsWith('/') ? '' : ' (las rutas empiezan por /)'}</div>`;
    marcarActiva(B.lista.length && !q.startsWith('/') ? 0 : -1);
  }
  // «+ Grupo»: guarda la carpeta en la config detectando dónde va el entorno (lo mismo que Explorar y Ajustes)
  async function anadirGrupo(carpeta) {
    try {
      const res = await post('/api/grupos', { carpeta });
      PX.estado = res.estado; PX.oyentes.forEach(f => f(PX.estado));
      toast(`Grupo «${res.grupo.nombre}» añadido: ${res.grupo.path}, perfil ${res.grupo.perfil}${res.perfil_nuevo ? ' (perfil nuevo)' : ''}`);
    } catch (err) { toast(err.message, true); }
  }
  function cargarRuta(ruta) {
    if (!salirSinGuardar()) return;
    $('pRuta').value = ruta; cerrarSugerencias();
    S.grupo = ''; $('pGrupo').value = ''; S.entorno = ''; pintarEntornos(); cargar();
  }
  $('pRuta').addEventListener('input', sugerir);
  $('pRuta').addEventListener('focus', () => { if ($('pRuta').value.trim() && !grupoSel()) sugerir(); });
  $('pRuta').addEventListener('blur', () => setTimeout(cerrarSugerencias, 120));
  $('pRuta').addEventListener('keydown', e => {
    const abierto = !$('pSugerencias').hidden;
    if (e.key === 'ArrowDown' && abierto) { e.preventDefault(); marcarActiva(B.activa + 1); }
    else if (e.key === 'ArrowUp' && abierto) { e.preventDefault(); marcarActiva(B.activa - 1); }
    else if (e.key === 'Escape' && abierto) { e.preventDefault(); e.stopPropagation(); cerrarSugerencias(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (abierto && B.activa >= 0) cargarRuta(B.lista[B.activa]);
      else { cerrarSugerencias(); cargarEscrita(); }
    }
  });
  $('pSugerencias').addEventListener('mousedown', e => {
    const f = e.target.closest('.sug'); if (!f) return;
    e.preventDefault();  // el buscador no pierde el foco
    if (e.target.closest('[data-grupo-de]')) return anadirGrupo(B.lista[+f.dataset.i]);
    cargarRuta(B.lista[+f.dataset.i]);
  });
  $('pSugerencias').addEventListener('mousemove', e => { const f = e.target.closest('.sug'); if (f && +f.dataset.i !== B.activa) marcarActiva(+f.dataset.i); });

  // ------------------------------------------------ cargar y pintar
  async function cargar() {
    const ruta = $('pRuta').value.trim();
    if (!ruta.startsWith('/')) return toast('La ruta empieza por /', true);
    $('pEstado').textContent = `Leyendo ${ruta} de AWS…`; $('pLista').innerHTML = ''; $('pBarra').hidden = true;
    try {
      const r = await post('/api/cargar', { ruta });
      S.ruta = r.ruta;
      S.items = r.parametros.map(p => ({ ...p, tags: p.tags ? { ...p.tags } : null, orig: { ...p, tags: p.tags ? { ...p.tags } : null }, borrar: false, nuevo: false, ver: false }));
      const bloqueados = S.items.filter(p => p.bloqueado).length;
      $('pEstado').innerHTML = `<b>${esc(r.ruta)}</b> · ${S.items.length} par${bloqueados ? ` · 🔒 ${bloqueados} sin permiso` : ''}${r.avisos.map(a => ` · <span class="warn">${esc(a)}</span>`).join('')} · <button type="button" class="enlace" data-recargar title="Volver a leer de AWS">↻ Recargar</button>`;
      $('pBarra').hidden = false; pintar();
    } catch (e) {
      $('pEstado').innerHTML = `<span class="error">${esc(e.message)}</span>`; S.items = []; S.ruta = '';
    }
  }

  const esJson = v => { const t = (v || '').trim(); if (!/^[[{]/.test(t)) return null; try { JSON.parse(t); return true; } catch { return false; } };
  const limpias = t => Object.entries(t || {}).filter(([k, v]) => k && String(v).trim()).sort();
  const tagsIguales = (a, b) => JSON.stringify(limpias(a)) === JSON.stringify(limpias(b));
  function cambios(p) {
    if (p.nuevo) return ['nuevo'];
    if (p.borrar) return ['borrar'];
    const c = [];
    if (p.value !== p.orig.value) c.push('valor');
    if (p.type !== p.orig.type) c.push('tipo');
    if ((p.description || '') !== (p.orig.description || '')) c.push('descripción');
    if (p.tags && !tagsIguales(p.tags, p.orig.tags)) c.push('etiquetas');
    return c;
  }
  const pendientes = () => S.items.filter(p => cambios(p).length);
  PX.pendientes = () => pendientes().length;

  const htmlJson = j => j === true ? 'JSON ✓ <button type="button" class="enlace" data-formatear>Formatear</button>' : j === false ? 'JSON no válido' : '';
  function tarjeta(p, i) {
    const ro = !!p.bloqueado || p.borrar;
    const oculto = p.type === 'SecureString' && !p.ver && !$('pMostrar').checked;
    const tags = p.tags || {};
    const claves = [...new Set([...obligatorias(), ...Object.keys(tags)])];
    const lineas = (p.value || '').split('\n').length;
    const cabecera = `<header>${p.nuevo ? `<input class="nombre-input" data-campo="name" value="${esc(p.name)}" placeholder="/ruta/nombre" ${NOFILL}>` : `<code class="nombre" title="${esc(p.name)}">${esc(p.name)}</code>`}
      <span class="chips">${p.nuevo ? '<span class="chip nuevo">nuevo</span>' : ''}${p.bloqueado ? '<span class="chip">🔒 solo lectura</span>' : ''}${p.version ? `<span class="chip" title="Versión en AWS">v${p.version}</span>` : ''}${p.tier === 'Advanced' ? '<span class="chip" title="Tier Advanced (de pago)">Advanced</span>' : ''}${p.kms_propia ? '<span class="chip" title="Cifrado con una clave KMS propia (se conserva al guardar)">KMS propia</span>' : ''}${p.modified ? `<span class="chip" title="Último cambio">${cuando(p.modified)}${p.user ? ' · ' + esc(quien(p.user)) : ''}</span>` : ''}<span class="cambios"></span></span>
      <span class="param-acciones">${!p.nuevo && !p.bloqueado ? '<button type="button" class="enlace" data-historial>Historial</button>' : ''}${!p.bloqueado ? `<button type="button" class="enlace ${p.borrar ? '' : 'peligro'}" data-borrar>${p.borrar ? 'No borrar' : p.nuevo ? 'Quitar' : 'Borrar'}</button>` : ''}</span></header>`;
    if (p.bloqueado) return `<article class="param bloqueado" data-i="${i}">${cabecera}<p class="bloqueado-motivo">🔒 ${esc(p.bloqueado)}</p></article>`;
    return `<article class="param${p.borrar ? ' borrado' : ''}${p.nuevo ? ' nuevo' : ''}" data-i="${i}">${cabecera}
      <div class="param-cuerpo"><div class="param-campos">
        <div class="fila-desc">
          <label class="campo">Descripción<input data-campo="description" value="${esc(p.description || '')}" maxlength="1024" ${NOFILL} ${ro || p.descripcion_legible === false ? 'disabled' : ''} ${p.descripcion_legible === false ? 'title="Tu rol no puede leer las descripciones (ssm:DescribeParameters)"' : ''}></label>
          <label class="campo">Tipo<select data-campo="type" ${ro ? 'disabled' : ''}>${TIPOS.map(t => `<option ${t === p.type ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
        </div>
        <div class="valor"><div class="valor-cab"><span>Valor</span>${p.type === 'SecureString' ? `<button type="button" class="enlace" data-ver>${oculto ? '👁 Mostrar' : 'Ocultar'}</button>` : ''}<span class="json ${esJson(p.value) === false ? 'mal' : ''}">${htmlJson(esJson(p.value))}</span></div>
          <textarea data-campo="value" rows="${Math.min(12, Math.max(2, lineas))}" ${NOFILL} class="${oculto ? 'oculto' : ''}" ${ro ? 'readonly' : ''}>${esc(p.value ?? '')}</textarea></div>
      </div>
      <div class="tags-col"><div class="tags-cab">Etiquetas${p.tags ? ` <span class="n">${limpias(tags).length}</span>` : ''}${ro || p.tags === null ? '' : '<button type="button" class="enlace" data-tag-nueva>+ etiqueta</button>'}</div>
        <div class="tags">${p.tags === null ? '<span class="muted">Sin permiso para verlas.</span>' : claves.map(k => tagFila(k, tags[k] ?? '', obligatorias().includes(k), ro)).join('') || '<span class="muted">Sin etiquetas.</span>'}</div></div></div></article>`;
  }
  const tagFila = (k, v, obl, ro) => `<span class="tag${obl && !String(v).trim() ? ' falta' : ''}"><input class="tag-k" value="${esc(k)}" ${obl || ro ? 'readonly' : ''} placeholder="Clave" ${NOFILL}><span>=</span><input class="tag-v" value="${esc(v)}" ${ro ? 'disabled' : ''} placeholder="${obl ? 'obligatoria' : 'valor'}" ${NOFILL}>${obl || ro ? '' : '<button type="button" class="enlace" data-tag-quitar title="Quitar">×</button>'}</span>`;

  function pintar() {
    $('pLista').innerHTML = S.items.map(tarjeta).join('') || '<p class="vacio">No hay parámetros en esta ruta. Con «+ Nuevo» puedes crear el primero.</p>';
    S.items.forEach((_, i) => marcar(i)); filtrar(); resumen();
  }
  function marcar(i) {
    const card = $('pLista').querySelector(`[data-i="${i}"]`); if (!card) return;
    const p = S.items[i], c = cambios(p);
    card.classList.toggle('cambiado', !!c.length && !p.nuevo && !p.borrar);
    card.querySelector('.cambios').innerHTML = c.filter(x => x !== 'nuevo' && x !== 'borrar').map(x => `<span class="cambio">${x}</span>`).join('');
  }
  function resumen() {
    const n = pendientes().length;
    $('pResumen').textContent = `${S.items.filter(p => !p.nuevo).length} parámetros${n ? ` · ${n} con cambios` : ''}`;
    $('pRevisar').disabled = !n;
    $('pRevisar').textContent = n ? `Revisar ${n} ${n === 1 ? 'cambio' : 'cambios'}` : 'Revisar cambios';
    $('pDescartar').hidden = !n;
  }
  function filtrar() {
    const q = $('pFiltro').value.trim().toLowerCase();
    $('pLista').querySelectorAll('.param').forEach(card => {
      const p = S.items[card.dataset.i];
      card.hidden = !!q && !p.nuevo && ![p.name, p.description, ...Object.entries(p.tags || {}).flat()].join(' ').toLowerCase().includes(q);
    });
  }
  $('pFiltro').addEventListener('input', filtrar);
  $('pMostrar').addEventListener('change', pintar);

  // ------------------------------------------------ edición (sin repintar la tarjeta: no se pierde el foco)
  function leerTags(card) {
    const t = {};
    card.querySelectorAll('.tag').forEach(f => { const k = f.querySelector('.tag-k').value.trim(); if (k) t[k] = f.querySelector('.tag-v').value; });
    return t;
  }
  $('pLista').addEventListener('input', e => {
    const card = e.target.closest('.param'); if (!card) return;
    const i = +card.dataset.i, p = S.items[i];
    if (e.target.dataset.campo) p[e.target.dataset.campo] = e.target.value;
    if (e.target.closest('.tags')) {
      p.tags = leerTags(card);
      const fila = e.target.closest('.tag');
      fila.classList.toggle('falta', obligatorias().includes(fila.querySelector('.tag-k').value.trim()) && !fila.querySelector('.tag-v').value.trim());
    }
    if (e.target.dataset.campo === 'value') {
      const j = esJson(p.value), el = card.querySelector('.json');
      el.className = `json ${j === false ? 'mal' : ''}`; el.innerHTML = htmlJson(j);
    }
    marcar(i); resumen();
  });
  $('pLista').addEventListener('change', e => {
    if (e.target.dataset.campo !== 'type') return;
    const i = +e.target.closest('.param').dataset.i;
    S.items[i].type = e.target.value; repintarUna(i);
  });
  // Un SecureString oculto se muestra al entrar a editarlo
  $('pLista').addEventListener('focusin', e => {
    if (!e.target.classList.contains('oculto')) return;
    const card = e.target.closest('.param'), p = S.items[+card.dataset.i];
    p.ver = true; e.target.classList.remove('oculto');
    const b = card.querySelector('[data-ver]'); if (b) b.textContent = 'Ocultar';
  });
  // El nombre de uno nuevo, con las mayúsculas del perfil (como la opción 4 de la terminal)
  $('pLista').addEventListener('focusout', async e => {
    if (e.target.dataset.campo !== 'name') return;
    const input = e.target, p = S.items[+input.closest('.param').dataset.i];
    const g = grupoSel();
    try {
      const r = await post('/api/nombre-nuevo', { base: S.ruta, nombre: p.name.trim(), perfil: g ? g.perfil : '' });
      p.name = r.nombre;
      if (document.activeElement !== input) input.value = p.name;
    } catch { /* se valida al revisar */ }
  });
  function repintarUna(i) {
    const card = $('pLista').querySelector(`[data-i="${i}"]`);
    card.outerHTML = tarjeta(S.items[i], i); marcar(i); resumen();
  }
  $('pLista').addEventListener('click', e => {
    const card = e.target.closest('.param'); if (!card) return;
    const i = +card.dataset.i, p = S.items[i];
    if (e.target.closest('[data-ver]')) { p.ver = !p.ver; return repintarUna(i); }
    if (e.target.closest('[data-formatear]')) { try { p.value = JSON.stringify(JSON.parse(p.value), null, 2); } catch { /* no es JSON */ } return repintarUna(i); }
    if (e.target.closest('[data-tag-nueva]')) {
      p.tags = { ...(p.tags || {}) };
      const lista = card.querySelector('.tags');
      lista.querySelector('.muted')?.remove();
      lista.insertAdjacentHTML('beforeend', tagFila('', '', false, false));
      const k = lista.querySelectorAll('.tag-k'); lista.scrollTop = lista.scrollHeight; return k[k.length - 1].focus();
    }
    if (e.target.closest('[data-tag-quitar]')) { e.target.closest('.tag').remove(); p.tags = leerTags(card); marcar(i); return resumen(); }
    if (e.target.closest('[data-borrar]')) {
      if (p.nuevo) { S.items.splice(i, 1); return pintar(); }
      p.borrar = !p.borrar; return repintarUna(i);
    }
    if (e.target.closest('[data-historial]')) historial(i);
  });
  $('pNuevo').onclick = () => {
    if (!S.ruta) return toast('Carga antes un grupo o una ruta.', true);
    const entorno = S.entorno || (S.ruta.split('/').map(entornoDe).find(Boolean) || '');
    const tags = Object.fromEntries(obligatorias().map(k => [k, k === 'Environment' ? entorno : '']));
    S.items.unshift({ name: S.ruta.replace(/\/$/, '') + '/', type: cfg().forzar_securestring === false ? 'String' : 'SecureString', value: '', description: '', tags, nuevo: true, borrar: false, ver: true, orig: null, descripcion_legible: true });
    pintar();
    const input = $('pLista').querySelector('[data-i="0"] [data-campo="name"]');
    if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
  };
  $('pDescartar').onclick = () => {
    if (!confirm('¿Descartar todos los cambios sin aplicar?')) return;
    S.items = S.items.filter(p => !p.nuevo).map(p => ({ ...p, ...p.orig, tags: p.orig.tags ? { ...p.orig.tags } : null, orig: p.orig, borrar: false }));
    pintar();
  };
  function salirSinGuardar() { return !pendientes().length || confirm('Hay cambios sin aplicar en este grupo. ¿Salir y perderlos?'); }
  window.addEventListener('beforeunload', e => { if (pendientes().length) { e.preventDefault(); e.returnValue = ''; } });

  // ------------------------------------------------ revisar y aplicar
  const paraEnviar = () => pendientes().map(p => ({ name: p.name.trim(), accion: p.nuevo ? 'nuevo' : p.borrar ? 'borrar' : 'editar', version: p.orig ? p.orig.version : null,
    value: p.value, description: p.description || '', type: p.type, tags: p.tags }));
  const ETIQUETA = { nuevo: 'Nuevo', editar: 'Modificado', borrar: 'Borrar' };
  $('pRevisar').onclick = async () => {
    const items = paraEnviar();
    modal.abrir('<h2>Revisar cambios</h2><p>Comparando con AWS en este momento…</p>');
    let r;
    try { r = await post('/api/plan', { items }); } catch (e) { return modal.abrir(`<h2>Revisar cambios</h2><p class="error">${esc(e.message)}</p>`); }
    const validos = r.plan.filter(f => !f.errores.length), borrados = validos.filter(f => f.accion === 'borrar').length;
    const conflictos = r.plan.filter(f => f.conflicto).length;
    const frase = `APLICAR EN ${r.account}`;
    modal.abrir(`<h2>Revisar cambios</h2><p>Comparado con lo que hay ahora en AWS, en la cuenta <b>${esc(r.account)}</b> · ${esc(r.region_name)}.${r.plan.length - validos.length ? ` <span class="warn">${r.plan.length - validos.length} no se aplicarán (ver motivo).</span>` : ''}${conflictos ? ' <b class="error">Hay conflictos: recarga el grupo para ver lo que hay ahora.</b>' : ''}</p>
      <div class="plan">${r.plan.map(f => {
        const actual = S.items.find(p => p.name.trim() === f.name) || {};
        return `<div class="plan-fila ${f.errores.length ? 'mal' : ''}"><div>${f.conflicto ? '<span class="pill conflicto">Conflicto</span>' : `<span class="pill ${f.errores.length ? 'mal' : f.accion}">${ETIQUETA[f.accion] || esc(f.accion)}</span>`}<code>${esc(f.name)}</code> ${f.accion === 'editar' ? f.cambios.map(c => `<span class="cambio">${esc(c)}</span>`).join(' ') : ''}</div>
        ${f.errores.map(x => `<small class="error">${esc(x)}</small>`).join('')}${f.avisos.map(x => `<small class="warn">⚠ ${esc(x)}</small>`).join('')}
        ${f.cambios.includes('valor') && f.accion === 'editar' ? `<details><summary>Ver el valor antes y después</summary><div class="diff"><div><small>Ahora en AWS</small><pre>${esc(f.antes ?? '')}</pre></div><div><small>Después</small><pre>${esc(actual.value ?? '')}</pre></div></div></details>` : ''}
        ${f.tags_poner && Object.keys(f.tags_poner).length ? `<small>Etiquetas: ${Object.entries(f.tags_poner).map(([k, v]) => `${esc(k)}=${esc(v)}`).join(', ')}</small>` : ''}${f.tags_quitar && f.tags_quitar.length ? `<small>Quitar etiquetas: ${f.tags_quitar.map(esc).join(', ')}</small>` : ''}</div>`;
      }).join('')}</div>
      ${validos.length ? `<div class="confirmar"><label>Para aplicar, escribe <code>${esc(frase)}</code><input id="pConfirma" ${NOFILL}></label>${borrados ? `<label class="warn">Se van a borrar ${borrados}: escribe <b>${borrados}</b><input id="pBorrados" inputmode="numeric" ${NOFILL}></label>` : ''}
        <div class="acciones"><button type="button" class="primario" id="pAplicar" disabled>Aplicar ${validos.length} ${validos.length === 1 ? 'cambio' : 'cambios'}</button><button type="button" class="secundario" id="pSeguir">Seguir editando</button>${conflictos ? '<button type="button" class="secundario" id="pRecargar">Recargar el grupo</button>' : ''}</div></div>`
      : `<div class="acciones"><button type="button" class="secundario" id="pSeguir">Seguir editando</button>${conflictos ? '<button type="button" class="secundario" id="pRecargar">Recargar el grupo</button>' : ''}</div>`}`);
    $('pSeguir').onclick = modal.cerrar;
    if ($('pRecargar')) $('pRecargar').onclick = () => { if (confirm('Recargar el grupo descarta tus cambios sin aplicar. ¿Seguir?')) { modal.cerrar(); S.items = []; cargar(); } };
    if (!$('pAplicar')) return;
    const listo = () => { $('pAplicar').disabled = $('pConfirma').value.trim() !== frase || (borrados && ($('pBorrados') || {}).value.trim() !== String(borrados)); };
    $('pConfirma').addEventListener('input', listo); if ($('pBorrados')) $('pBorrados').addEventListener('input', listo);
    $('pConfirma').focus();
    $('pAplicar').onclick = async () => {
      $('pAplicar').disabled = true; $('pAplicar').textContent = 'Aplicando…';
      const enviar = items.filter(it => validos.some(v => v.name === it.name));
      try {
        const res = await post('/api/aplicar', { items: enviar, confirmacion: $('pConfirma').value.trim(), borrados: $('pBorrados') ? $('pBorrados').value.trim() : '' });
        const ok = res.resultados.filter(x => x.ok).length, mal = res.resultados.filter(x => !x.ok);
        modal.abrir(`<h2>${mal.length ? 'Aplicado en parte' : 'Aplicado'}</h2><p>${ok} de ${res.resultados.length} cambios hechos en AWS. El grupo se ha vuelto a cargar.</p>${mal.length ? `<div class="plan">${mal.map(x => `<div class="plan-fila mal"><code>${esc(x.name)}</code><small class="error">${esc(x.error)}</small></div>`).join('')}</div>` : ''}<div class="acciones"><button type="button" class="primario" id="pSeguir">Cerrar</button></div>`);
        $('pSeguir').onclick = modal.cerrar;
        S.items = []; S.carpetas = null;  // se recarga de AWS (puede haber rutas nuevas o borradas)
        await cargar();
        toast(mal.length ? `${ok} aplicados, ${mal.length} con error` : `${ok} cambios aplicados`, !!mal.length);
      } catch (e) { $('pAplicar').disabled = false; $('pAplicar').textContent = 'Aplicar'; toast(e.message, true); }
    };
  };

  // ------------------------------------------------ historial (las versiones de AWS)
  async function historial(i) {
    const p = S.items[i];
    modal.abrir(`<h2>Historial</h2><p><code>${esc(p.name)}</code></p><p>Leyendo versiones de AWS…</p>`);
    let r;
    try { r = await post('/api/historial', { nombre: p.name }); } catch (e) { return modal.abrir(`<h2>Historial</h2><p class="error">${esc(e.message)}</p>`); }
    const v = r.versiones;
    modal.abrir(`<h2>Historial · ${v.length} ${v.length === 1 ? 'versión' : 'versiones'}</h2><p><code>${esc(p.name)}</code> · AWS guarda las últimas 100. «Usar esta versión» la pone en el editor: luego revisas y aplicas como siempre.</p>
      <div class="versiones"><ul>${v.map((x, n) => `<li><button type="button" data-version="${n}"><b>v${x.version}</b> ${cuando(x.modified)}<small>${esc(quien(x.user))}${x.labels.length ? ' · ' + x.labels.map(esc).join(', ') : ''}</small></button></li>`).join('')}</ul><div class="version-detalle" id="pVersion"></div></div>`);
    const ver = n => {
      const x = v[n];
      $('pVersion').innerHTML = `<div class="valor-cab"><span>v${x.version} · ${esc(x.type)}${x.description ? ' · ' + esc(x.description) : ''}</span></div>
        <div class="diff"><div><small>Esta versión</small><pre>${esc(x.value)}</pre></div><div><small>En el editor</small><pre>${esc(p.value ?? '')}</pre></div></div>
        <div class="acciones"><button type="button" class="primario" data-usar="${n}" ${x.value === p.value && x.type === p.type && (x.description || '') === (p.description || '') ? 'disabled title="Es lo que ya tienes en el editor"' : ''}>Usar esta versión</button></div>`;
      $('modalCuerpo').querySelectorAll('[data-version]').forEach(b => b.classList.toggle('activo', +b.dataset.version === n));
    };
    $('modalCuerpo').onclick = e => {
      const b = e.target.closest('[data-version]'); if (b) return ver(+b.dataset.version);
      const u = e.target.closest('[data-usar]'); if (!u) return;
      const x = v[+u.dataset.usar];
      Object.assign(p, { value: x.value, type: x.type, ver: true }, p.descripcion_legible === false ? {} : { description: x.description || '' });
      p.borrar = false;
      $('modalCuerpo').onclick = null; modal.cerrar(); repintarUna(i);
      toast(`v${x.version} puesta en el editor: revisa y aplica`);
    };
    if (v.length) ver(0);
  }

  // ------------------------------------------------ explorar (solo nombres): árbol con entornos en color
  $('pExplorar').onclick = async () => {
    modal.abrir('<h2>Explorar</h2><p>Leyendo los nombres (sin valores)…</p>');
    let r;
    try { r = await api('/api/explorar'); } catch (e) { return modal.abrir(`<h2>Explorar</h2><p class="error">${esc(e.message)}</p>`); }
    const arbol = q => {
      const raiz = {};
      r.nombres.filter(n => !q || n.toLowerCase().includes(q)).forEach(n => {
        let nodo = raiz;
        n.split('/').filter(Boolean).slice(0, -1).forEach(x => { nodo[x] = nodo[x] || { _n: 0 }; nodo[x]._n++; nodo = nodo[x]; });
      });
      return raiz;
    };
    const fila = (k, ruta, n, nivel) => {
      const e = entornoDe(k);
      return `<span class="exp-nombre nivel-${Math.min(nivel, 3)}${e ? ' entorno ' + claseEntorno(e) : ''}">${esc(k)}</span><span class="exp-n" title="Parámetros por debajo">${n}</span>
        <span class="exp-acciones"><button type="button" class="secundario" data-ruta="${esc(ruta)}">Cargar</button><button type="button" class="secundario" data-grupo-de="${esc(ruta)}" title="Guardar esta carpeta como grupo (se detecta dónde va el entorno)">+ Grupo</button></span>`;
    };
    const rama = (nodo, ruta, nivel, abierto) => Object.keys(nodo).filter(k => k !== '_n').sort((a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' })).map(k => {
      const r2 = `${ruta}/${k}`, hijos = rama(nodo[k], r2, nivel + 1, abierto);
      return hijos ? `<details class="rama" ${abierto ? 'open' : ''}><summary class="exp-fila">${fila(k, r2, nodo[k]._n, nivel)}</summary><div class="hijos">${hijos}</div></details>`
        : `<div class="exp-fila exp-hoja">${fila(k, r2, nodo[k]._n, nivel)}</div>`;
    }).join('');
    modal.abrir(`<h2>Explorar · ${r.nombres.length} parámetros</h2><p>Solo nombres. «Cargar» abre la carpeta; «+ Grupo» la guarda en tu configuración para elegirla luego con su entorno.${r.limitado ? ' <span class="warn">Hay más de los que se muestran: filtra.</span>' : ''}</p>
      <div class="exp-cab"><input type="search" id="pExpFiltro" placeholder="Filtrar rutas… (p. ej. rds, api)" ${NOFILL}><span class="leyenda">${cfg().entornos.map(e => `<span class="entorno ${claseEntorno(e)}">${esc(e)}</span>`).join('')}</span></div>
      <div class="arbol" id="pArbol">${rama(arbol(''), '', 0, false) || '<p class="muted">No hay parámetros.</p>'}</div>`);
    $('pExpFiltro').addEventListener('input', e => { const q = e.target.value.trim().toLowerCase(); $('pArbol').innerHTML = rama(arbol(q), '', 0, !!q) || '<p class="muted">Ninguna ruta con eso.</p>'; });
    $('pExpFiltro').focus();
    $('pArbol').addEventListener('click', async e => {
      const g = e.target.closest('[data-grupo-de]');
      if (g) { e.preventDefault(); return anadirGrupo(g.dataset.grupoDe); }
      const b = e.target.closest('[data-ruta]'); if (!b) return;
      e.preventDefault(); modal.cerrar(); cargarRuta(b.dataset.ruta);
    });
  };

  refrescarEstado().catch(e => { $('pEstado').innerHTML = `<span class="error">${esc(e.message)}</span>`; });
})();
