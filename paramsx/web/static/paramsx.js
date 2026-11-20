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
  // Un parámetro no puede acabar en «/»: se quitan las barras finales si queda algo más (el servidor hace lo mismo)
  const sinBarraFinal = n => { const t = String(n || '').trim(); return t.replace(/\/+$/, '') || t; };
  const nombreEnvio = p => p.nuevo ? sinBarraFinal(p.name) : p.name.trim();

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
      S.donde = donde; S.items = []; S.carpetas = null; B.enAws = null; S.ruta = ''; $('pBarra').hidden = true; $('pLista').innerHTML = '';
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
    // Un patrón se busca desde su ruta; «buscar en cualquier nivel» lo repite con /**/ delante (p. ej. en cada entorno)
    const otros = e.target.closest('[data-otros-niveles]');
    if (!(otros || e.target.closest('[data-recargar]')) || !salirSinGuardar()) return;
    $('pRuta').value = otros ? '/**' + S.cargada : (S.cargada || S.ruta); S.items = []; cargar();
  });

  // ------------------------------------------------ buscador de rutas (solo nombres, como «Buscar en la cuenta» de Ajustes)
  const B = { activa: -1, lista: [], pidiendo: null };
  // {carpeta: nº de parámetros por debajo}, de todos los niveles; se pide una vez por perfil y región
  async function carpetas() {
    if (S.carpetas) return S.carpetas;
    B.pidiendo = B.pidiendo || api('/api/explorar').then(r => {
      const c = {};
      r.nombres.forEach(n => { const seg = n.split('/').filter(Boolean); for (let i = 1; i < seg.length; i++) { const k = '/' + seg.slice(0, i).join('/'); c[k] = (c[k] || 0) + 1; } });
      S.nombres = new Set(r.nombres); S.limitado = r.limitado;  // los parámetros también se buscan, no solo las carpetas
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
    if (S.limitado && q.length >= 2 && !B.enAws?.has(q)) buscarEnAws(q);
    const orden = (a, b) => (b.toLowerCase().startsWith(q) - a.toLowerCase().startsWith(q)) || a.split('/').length - b.split('/').length || a.localeCompare(b);
    const dirs = Object.keys(c).filter(k => k.toLowerCase().includes(q)).sort(orden).slice(0, 200);
    const params = [...(S.nombres || [])].filter(n => !c[n] && n.toLowerCase().includes(q)).sort(orden).slice(0, 100);  // los parámetros mismos, después
    B.lista = [...dirs, ...params];
    caja.innerHTML = B.lista.map((k, i) => i < dirs.length
      ? `<div class="sug" role="option" data-i="${i}"><code>${resaltar(k, q)}</code><span class="exp-n">${c[k]}</span><button type="button" class="secundario sug-grupo" data-grupo-de="${esc(k)}" title="Guardar esta carpeta como grupo (se detecta dónde va el entorno)" tabindex="-1">+ Grupo</button></div>`
      : `<div class="sug sug-param" role="option" data-i="${i}" title="Parámetro: se carga solo este"><code>${resaltar(k, q)}</code><span class="exp-n">parámetro</span></div>`).join('')
      + `<div class="sug-ayuda">${B.enAws?.get(q) === 'buscando' ? 'Buscando también en AWS… · ' : ''}${B.lista.length ? '<kbd>↑</kbd> <kbd>↓</kbd> para elegir · «+ Grupo» la guarda en tus grupos · ' : 'Ninguna carpeta ni parámetro con eso. '}<kbd>Intro</kbd> carga ${B.lista.length ? 'la elegida' : 'la ruta tal cual (si no existe, los que la llevan en el nombre)'}</div>`;
    marcarActiva(B.lista.length && !q.startsWith('/') ? 0 : -1);
  }
  // Con más parámetros de los que caben en la lista, lo escrito se pide a AWS (distingue mayúsculas: tal cual, en minúsculas y en mayúsculas)
  function buscarEnAws(q) {
    B.enAws = B.enAws || new Map(); B.enAws.set(q, 'buscando');
    clearTimeout(B.espera);
    B.espera = setTimeout(async () => {
      try {
        const vistas = await Promise.all([...new Set([q, q.toLowerCase(), q.toUpperCase()])].map(t => api('/api/explorar?contiene=' + encodeURIComponent(t))));
        vistas.forEach(v => v.nombres.forEach(n => {
          if (S.nombres.has(n)) return; S.nombres.add(n);
          const seg = n.split('/').filter(Boolean); for (let i = 1; i < seg.length; i++) { const k = '/' + seg.slice(0, i).join('/'); S.carpetas[k] = (S.carpetas[k] || 0) + 1; }
        }));
        B.enAws.set(q, 'hecho');
      } catch (e) { B.enAws.delete(q); toast(e.message, true); }
      if ($('pRuta').value.trim().toLowerCase() === q) sugerir();
    }, 400);
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

  // ------------------------------------------------ buscar por valor (cuando no recuerdas el parámetro pero sí el valor)
  // En «Valor», la ruta (o el grupo y el entorno) dice dónde se busca: vacía o «/» es toda la cuenta
  S.modo = 'ruta';
  const RUTA_PH = $('pRuta').placeholder;
  $('pModo').addEventListener('click', e => {
    const b = e.target.closest('[data-modo]'); if (!b) return;
    S.modo = b.dataset.modo;
    $('pModo').querySelectorAll('[data-modo]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    $('pValor').hidden = S.modo !== 'valor';
    $('pRuta').placeholder = S.modo === 'valor' ? 'Dónde: vacío o / es toda la cuenta; o /dev, /prod/mi-app…' : RUTA_PH;
    (S.modo === 'valor' ? $('pValor') : $('pRuta')).focus();
  });
  $('pValor').addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (!$('pValor').value.trim()) return toast('Escribe lo que lleva el valor', true);
    cargarEscrita();
  });
  async function buscarValor() {
    const texto = $('pValor').value, ruta = '/' + $('pRuta').value.trim().replace(/^\/+|\/+$/g, '');
    if (ruta.includes('*')) return toast('Al buscar por valor, la ruta va sin «*»: escribe la carpeta (o nada, para toda la cuenta)', true);
    $('pEstado').textContent = `Leyendo los valores de ${ruta === '/' ? 'toda la cuenta' : ruta} para buscar «${texto}»…`; $('pLista').innerHTML = ''; $('pBarra').hidden = true;
    try {
      const r = await post('/api/buscar-valor', { texto, ruta });
      S.ruta = S.cargada = r.ruta;
      S.items = r.parametros.map(p => ({ ...p, tags: p.tags ? { ...p.tags } : null, orig: { ...p, tags: p.tags ? { ...p.tags } : null }, borrar: false, nuevo: false, ver: false }));
      const n = S.items.length;
      $('pEstado').innerHTML = `Valor con <b>«${esc(r.valor)}»</b> en <b>${r.ruta === '/' ? 'toda la cuenta' : esc(r.ruta)}</b> · ${n} ${n === 1 ? 'parámetro lo lleva' : 'parámetros lo llevan'} (de ${r.leidos} leídos)`
        + (r.otras_mayusculas ? ' · <span class="warn">Ninguno lo lleva tal cual: estos lo llevan con otras mayúsculas</span>' : '')
        + (r.sin_permiso ? ` · 🔒 ${r.sin_permiso} sin permiso para leerlos (no se han mirado)` : '')
        + r.avisos.map(a => ` · <span class="warn">${esc(a)}</span>`).join('') + ' · <button type="button" class="enlace" data-recargar title="Volver a leer de AWS">↻ Recargar</button>';
      $('pBarra').hidden = false; pintar();
    } catch (e) {
      $('pEstado').innerHTML = `<span class="error">${esc(e.message)}</span>`; S.items = []; S.ruta = '';
    }
  }

  // ------------------------------------------------ cargar y pintar
  async function cargar() {
    if (S.modo === 'valor' && $('pValor').value.trim()) return buscarValor();
    let ruta = $('pRuta').value.trim();
    if (!ruta) return toast('Escribe una ruta o el nombre de un parámetro', true);
    if (!ruta.startsWith('/')) $('pRuta').value = ruta = '/' + ruta;  // la barra inicial, sola (uno sin carpeta también se encuentra así)
    $('pEstado').textContent = `Leyendo ${ruta} de AWS…`; $('pLista').innerHTML = ''; $('pBarra').hidden = true;
    try {
      const r = await post('/api/cargar', { ruta });
      S.ruta = r.patron ? (r.patron.split('*')[0].replace(/\/[^/]*$/, '') || '/') : r.ruta;  // con patrón, «+ Nuevo» parte de lo fijo
      S.cargada = r.patron || r.ruta;  // lo que se vuelve a leer con ↻ Recargar
      S.items = r.parametros.map(p => ({ ...p, tags: p.tags ? { ...p.tags } : null, orig: { ...p, tags: p.tags ? { ...p.tags } : null }, borrar: false, nuevo: false, ver: false }));
      const bloqueados = S.items.filter(p => p.bloqueado).length;
      $('pEstado').innerHTML = `${r.patron ? `Patrón <b>«${esc(r.patron)}»</b>${r.cualquier_nivel ? ' en cualquier nivel' : ''} · ${S.items.length} ${S.items.length === 1 ? 'encaja' : 'encajan'}${r.patron && !r.cualquier_nivel && !r.patron.startsWith('/**') ? ` · <button type="button" class="enlace" data-otros-niveles title="Solo se ha buscado desde ${esc(r.patron.split('*')[0].replace(/\/[^/]*$/, '') || '/')}. Con /**/ delante se busca en cualquier nivel (p. ej. en cada entorno).">buscar en cualquier nivel</button>` : ''}` : r.buscado ? `Buscado <b>«${esc(r.buscado)}»</b> · ${S.items.length} ${S.items.length === 1 ? 'parámetro lo lleva' : 'parámetros lo llevan'} en el nombre` : `<b>${esc(r.ruta)}</b> · ${S.items.length} par`}${bloqueados ? ` · 🔒 ${bloqueados} sin permiso` : ''}${r.avisos.map(a => ` · <span class="warn">${esc(a)}</span>`).join('')} · <button type="button" class="enlace" data-recargar title="Volver a leer de AWS">↻ Recargar</button>`;
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
    const cabecera = `<header>${p.bloqueado || p.nuevo ? '' : `<input type="checkbox" class="marca" data-marca ${p.marcado ? 'checked' : ''} aria-label="Marcar ${esc(p.name)}">`}<button type="button" class="plegar" data-plegar aria-expanded="${!!p.abierta}" title="Ver su información">▸</button>${p.nuevo ? `<input class="nombre-input" data-campo="name" value="${esc(p.name)}" placeholder="/ruta/nombre" ${NOFILL}>` : `<code class="nombre" title="${esc(p.name)}">${esc(p.name)}</code><button type="button" class="copiar" data-copiar title="Copiar el nombre" aria-label="Copiar el nombre">⧉</button>${!p.bloqueado && !p.borrar ? '<button type="button" class="copiar renombrar" data-renombrar title="Cambiar el nombre (en SSM: se crea uno nuevo y se borra este)" aria-label="Cambiar el nombre">✎</button>' : ''}`}
      <span class="chips">${p.nuevo ? '<span class="chip nuevo">nuevo</span>' : ''}${p.bloqueado ? '<span class="chip">🔒 solo lectura</span>' : ''}${p.version ? `<span class="chip" title="Versión en AWS">v${p.version}</span>` : ''}${p.tier === 'Advanced' ? '<span class="chip" title="Tier Advanced (de pago)">Advanced</span>' : ''}${p.kms_propia ? '<span class="chip" title="Cifrado con una clave KMS propia (se conserva al guardar)">KMS propia</span>' : ''}${p.modified ? `<span class="chip" title="Último cambio">${cuando(p.modified)}${p.user ? ' · ' + esc(quien(p.user)) : ''}</span>` : ''}<span class="cambios"></span></span>
      <span class="param-acciones">${!p.nuevo && !p.bloqueado ? '<button type="button" class="enlace" data-historial>Historial</button>' : ''}${!p.bloqueado ? `<button type="button" class="enlace ${p.borrar ? '' : 'peligro'}" data-borrar>${p.borrar ? 'No borrar' : p.nuevo ? 'Quitar' : 'Borrar'}</button>` : ''}</span></header>`;
    if (p.bloqueado) return `<article class="param bloqueado${p.abierta ? ' abierta' : ''}" data-i="${i}">${cabecera}<p class="bloqueado-motivo">🔒 ${esc(p.bloqueado)}</p></article>`;
    return `<article class="param${p.marcado ? ' marcado' : ''}${p.borrar ? ' borrado' : ''}${p.nuevo ? ' nuevo' : ''}${p.abierta ? ' abierta' : ''}" data-i="${i}">${cabecera}
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
  // ------------------------------------------------ marcar varios: solo con «☑ Marcar» activado; «Todos» son los que ves (con el filtro)
  S.marcando = false;
  const tarjetaDe = i => $('pLista').querySelector(`[data-i="${i}"]`);
  const marcables = () => [...$('pLista').querySelectorAll('.param:not([hidden])')].map(c => +c.dataset.i).filter(i => S.items[i] && !S.items[i].bloqueado && !S.items[i].nuevo);
  const marcados = () => S.items.map((p, i) => p.marcado ? i : -1).filter(i => i >= 0);
  function ponerMarca(i, v) {
    S.items[i].marcado = v;
    const c = tarjetaDe(i); if (!c) return;
    c.classList.toggle('marcado', v);
    const m = c.querySelector('[data-marca]'); if (m) m.checked = v;
  }
  function pintarMarcas() {
    if (!S.marcando) return;
    const vis = marcables(), m = marcados(), nVis = vis.filter(i => S.items[i].marcado).length;
    $('pTodosN').textContent = vis.length;
    $('pTodos').checked = !!vis.length && nVis === vis.length;
    $('pTodos').indeterminate = nVis > 0 && nVis < vis.length;
    $('pMarcados').textContent = `${m.length} ${m.length === 1 ? 'marcado' : 'marcados'}`;
    const yaBorrar = m.length && m.every(i => S.items[i].borrar);
    $('pBorrarMarcados').disabled = !m.length;
    $('pBorrarMarcados').textContent = !m.length ? '🗑 Borrar marcados' : yaBorrar ? `No borrar ${m.length === 1 ? 'el marcado' : `los ${m.length}`}` : `🗑 Borrar ${m.length === 1 ? 'el marcado' : `los ${m.length}`}`;
  }
  $('pMarcar').onclick = () => {
    S.marcando = !S.marcando;
    $('pMarcar').setAttribute('aria-pressed', String(S.marcando));
    $('pLista').classList.toggle('marcando', S.marcando);
    $('pMarcarBarra').hidden = !S.marcando;
    if (!S.marcando) marcados().forEach(i => ponerMarca(i, false));  // al salir se quitan las marcas (lo marcado para borrar sigue)
    pintarMarcas();
  };
  $('pTodos').onchange = () => { const v = $('pTodos').checked; marcables().forEach(i => ponerMarca(i, v)); pintarMarcas(); };
  // Marca (o desmarca, si ya lo estaban todos) para borrar; se aplica, como siempre, con «Revisar cambios»
  $('pBorrarMarcados').onclick = () => {
    const m = marcados(), borrar = !m.every(i => S.items[i].borrar);
    m.forEach(i => { S.items[i].borrar = borrar; repintarUna(i); });
    pintarMarcas();
  };
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
    pintarMarcas();
  }
  $('pFiltro').addEventListener('input', filtrar);
  // Vista: Listado (por defecto) o Tarjetas (una línea por parámetro: nombre, copiarlo y ▸ para ver su información)
  let vista = 'listado';  // por defecto, el listado
  try { if (localStorage.getItem('paramsx_vista') === 'tarjetas') vista = 'tarjetas'; } catch { /* sin almacenamiento */ }
  const listado = () => vista === 'listado';
  const aplicarVista = () => {
    $('pLista').classList.toggle('modo-listado', listado());
    $('pVista').querySelectorAll('[data-vista]').forEach(b => b.setAttribute('aria-pressed', b.dataset.vista === vista));
  };
  aplicarVista();
  $('pVista').addEventListener('click', e => {
    const b = e.target.closest('[data-vista]'); if (!b) return;
    vista = b.dataset.vista; aplicarVista();
    try { localStorage.setItem('paramsx_vista', vista); } catch { /* sin almacenamiento */ }
  });
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
    p.name = sinBarraFinal(p.name); input.value = p.name;
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
    if (e.target.matches('[data-marca]')) { ponerMarca(i, e.target.checked); return pintarMarcas(); }
    if (e.target.closest('[data-renombrar]')) return pedirNombre(i);
    if (e.target.closest('[data-copiar]')) return navigator.clipboard.writeText(p.name).then(() => toast('Nombre copiado'), () => toast('No se pudo copiar', true));
    // Listado: ▸ (o el nombre) despliega su información
    if (e.target.closest('[data-plegar]') || (listado() && e.target.closest('.nombre'))) {
      p.abierta = !p.abierta; card.classList.toggle('abierta', p.abierta);
      return card.querySelector('[data-plegar]').setAttribute('aria-expanded', p.abierta);
    }
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
    tags.ManagedBy = tags.ManagedBy || 'paramsx';  // quién lo creó; si es obligatoria, ya va rellena
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
  const paraEnviar = () => pendientes().map(p => ({ name: nombreEnvio(p), accion: p.nuevo ? 'nuevo' : p.borrar ? 'borrar' : 'editar', version: p.orig ? p.orig.version : null,
    value: p.value, description: p.description || '', type: p.type, tags: p.tags, ...(p.nuevo && p.de ? { de: p.de } : {}), ...(p.sin_papelera ? { sin_papelera: true } : {}) }));
  const ETIQUETA = { nuevo: 'Nuevo', editar: 'Modificado', borrar: 'Borrar' };
  $('pRevisar').onclick = async () => {
    const items = paraEnviar();
    modal.abrir('<h2>Revisar cambios</h2><p>Comparando con AWS en este momento…</p>');
    let r;
    try { r = await post('/api/plan', { items }); } catch (e) { return modal.abrir(`<h2>Revisar cambios</h2><p class="error">${esc(e.message)}</p>`); }
    const validos = r.plan.filter(f => !f.errores.length), papelera = validos.filter(f => f.papelera).length;
    // dónde quedaría la copia (la fecha la pone el servidor al borrar): /papelera/<fecha>[_<usuario de AWS>]/<nombre>
    const ejemploPapelera = `/papelera/${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}${r.usuario_papelera ? '_' + r.usuario_papelera : ''}/${(validos.find(f => f.papelera) || {}).name?.replace(/^\//, '') || ''}`;
    const conflictos = r.plan.filter(f => f.conflicto).length;
    const frase = `APLICAR EN ${r.account}`;
    modal.abrir(`<h2>Revisar cambios</h2><p>Comparado con lo que hay ahora en AWS, en la cuenta <b>${esc(r.account)}</b> · ${esc(r.region_name)}.${r.plan.length - validos.length ? ` <span class="warn">${r.plan.length - validos.length} no se aplicarán (ver motivo).</span>` : ''}${conflictos ? ' <b class="error">Hay conflictos: recarga el grupo para ver lo que hay ahora.</b>' : ''}</p>
      <div class="plan">${r.plan.map(f => {
        const actual = S.items.find(p => nombreEnvio(p) === f.name) || {};
        return `<div class="plan-fila ${f.errores.length ? 'mal' : ''}"><div>${f.conflicto ? '<span class="pill conflicto">Conflicto</span>' : `<span class="pill ${f.errores.length ? 'mal' : f.accion}">${ETIQUETA[f.accion] || esc(f.accion)}</span>`}<code>${esc(f.name)}</code> ${f.accion === 'editar' ? f.cambios.map(c => `<span class="cambio">${esc(c)}</span>`).join(' ') : ''}</div>
        ${f.errores.map(x => `<small class="error">${esc(x)}</small>`).join('')}${f.avisos.map(x => `<small class="warn">⚠ ${esc(x)}</small>`).join('')}
        ${f.cambios.includes('valor') && f.accion === 'editar' ? `<details><summary>Ver el valor antes y después</summary><div class="diff"><div><small>Ahora en AWS</small><pre>${esc(f.antes ?? '')}</pre></div><div><small>Después</small><pre>${esc(actual.value ?? '')}</pre></div></div></details>` : ''}
        ${f.tags_poner && Object.keys(f.tags_poner).length ? `<small>Etiquetas: ${Object.entries(f.tags_poner).map(([k, v]) => `${esc(k)}=${esc(v)}`).join(', ')}</small>` : ''}${f.tags_quitar && f.tags_quitar.length ? `<small>Quitar etiquetas: ${f.tags_quitar.map(esc).join(', ')}</small>` : ''}</div>`;
      }).join('')}</div>
      ${validos.length ? `<div class="confirmar">${papelera ? `<div class="papelera-caja"><label class="papelera-check"><input type="checkbox" id="pGuardarPapelera"> 🗑 <b>Guardar copia en la papelera</b> antes de borrar${papelera > 1 ? ` (${papelera})` : ''}</label>
          <small>Se guardaría tal cual (valor, tipo, descripción, etiquetas y clave KMS) en el mismo SSM, por ejemplo en <code>${esc(ejemploPapelera)}</code>. Se recupera desde <b>🗑 Papelera</b>.</small></div>` : ''}
        <label class="confirmar-frase"><span>Para aplicar, escribe <code>${esc(frase)}</code></span><input id="pConfirma" ${NOFILL}></label>
        <div class="acciones"><button type="button" class="primario" id="pAplicar" disabled>Aplicar ${validos.length} ${validos.length === 1 ? 'cambio' : 'cambios'}</button><button type="button" class="secundario" id="pSeguir">Seguir editando</button>${conflictos ? '<button type="button" class="secundario" id="pRecargar">Recargar el grupo</button>' : ''}</div></div>`
      : `<div class="acciones"><button type="button" class="secundario" id="pSeguir">Seguir editando</button>${conflictos ? '<button type="button" class="secundario" id="pRecargar">Recargar el grupo</button>' : ''}</div>`}`);
    $('pSeguir').onclick = modal.cerrar;
    if ($('pRecargar')) $('pRecargar').onclick = () => { if (confirm('Recargar el grupo descarta tus cambios sin aplicar. ¿Seguir?')) { modal.cerrar(); S.items = []; cargar(); } };
    if (!$('pAplicar')) return;
    const listo = () => { $('pAplicar').disabled = $('pConfirma').value.trim() !== frase; };
    $('pConfirma').addEventListener('input', listo);
    $('pConfirma').focus();
    $('pAplicar').onclick = async () => {
      $('pAplicar').disabled = true; $('pAplicar').textContent = 'Aplicando…';
      const sinCopia = $('pGuardarPapelera') && !$('pGuardarPapelera').checked;  // casilla de la papelera desmarcada
      const enviar = items.filter(it => validos.some(v => v.name === it.name)).map(it => sinCopia && it.accion === 'borrar' ? { ...it, sin_papelera: true } : it);
      try {
        const res = await post('/api/aplicar', { items: enviar, confirmacion: $('pConfirma').value.trim() });
        const ok = res.resultados.filter(x => x.ok).length, mal = res.resultados.filter(x => !x.ok);
        modal.abrir(`<h2>${mal.length ? 'Aplicado en parte' : 'Aplicado'}</h2><p>${ok} de ${res.resultados.length} cambios hechos en AWS. El grupo se ha vuelto a cargar.</p>${mal.length ? `<div class="plan">${mal.map(x => `<div class="plan-fila mal"><code>${esc(x.name)}</code><small class="error">${esc(x.error)}</small></div>`).join('')}</div>` : ''}<div class="acciones"><button type="button" class="primario" id="pSeguir">Cerrar</button>${mal.some(x => x.sin_copia) ? '<button type="button" class="secundario peligro" id="pSinCopia" title="Se borran sin guardar copia: no se podrán recuperar">Borrarlos sin copia…</button>' : ''}</div>`);
        $('pSeguir').onclick = modal.cerrar;
        const sinCopia = new Set(mal.filter(x => x.sin_copia).map(x => x.name));
        if ($('pSinCopia')) $('pSinCopia').onclick = () => {  // el usuario acepta borrarlos sin copia: quedan marcados, revisa y aplica
          if (!confirm(`¿Borrar ${sinCopia.size} sin guardar copia en la papelera? No se podrán recuperar.`)) return;
          S.items.filter(p => sinCopia.has(p.name)).forEach(p => { p.sin_papelera = true; });
          modal.cerrar(); toast('Marcados para borrar sin copia: revisa y aplica.');
        };
        // Se recarga de AWS (puede haber rutas nuevas o borradas), pero lo que no se aplicó (falló o la revisión lo dejó
        // fuera) se guarda antes y se vuelve a poner, para corregirlo sin escribirlo otra vez
        const hechos = new Set(res.resultados.filter(x => x.ok).map(x => x.name));
        const sinHacer = pendientes().filter(p => !hechos.has(nombreEnvio(p))).map(p => ({ ...p, name: nombreEnvio(p) }));
        const conflictos = new Set([...r.plan.filter(f => f.conflicto).map(f => f.name), ...mal.filter(x => /^Conflicto/.test(x.error)).map(x => x.name)]);
        S.items = []; S.carpetas = null; B.enAws = null;
        await cargar();
        if (sinHacer.length && S.ruta) { reponer(S.items, sinHacer, conflictos); pintar(); }
        toast(mal.length ? `${ok} aplicados, ${mal.length} con error` : `${ok} cambios aplicados`, !!mal.length);
      } catch (e) { $('pAplicar').disabled = false; $('pAplicar').textContent = 'Aplicar'; toast(e.message, true); }
    };
  };

  // Tras aplicar y recargar: pone otra vez sobre lo recién leído de AWS lo que no se aplicó. Los nuevos, arriba y en
  // su orden; en los existentes, lo editado y la marca de borrar. Si era un conflicto, se queda con la versión que se
  // cargó entonces, para que la revisión lo siga marcando y no pise sin avisar el cambio de otro.
  function reponer(items, sinHacer, conflictos) {
    for (const g of [...sinHacer].reverse()) {
      if (g.nuevo) { items.unshift(g); continue; }
      const p = items.find(q => q.name === g.name); if (!p) continue;
      Object.assign(p, { value: g.value, description: g.description, type: g.type, tags: g.tags ? { ...g.tags } : p.tags, borrar: g.borrar, ver: g.ver });
      if (conflictos.has(g.name) && g.orig) p.orig = { ...p.orig, version: g.orig.version };
    }
    return items;
  }

  // ------------------------------------------------ cambiar el nombre (✎): en SSM no se renombra; se crea otro con lo mismo y se borra el viejo
  // Devuelve el motivo si no se puede ('' si se ha puesto en el editor). El nuevo va justo debajo del que sustituye.
  function renombrar(i, nombre) {
    const p = S.items[i], nuevo = sinBarraFinal(nombre);
    if (!nuevo) return 'Escribe el nombre nuevo.';
    if (nuevo === p.name) return 'Es el mismo nombre.';
    if (S.items.some(q => q !== p && nombreEnvio(q) === nuevo)) return 'Ya hay un parámetro con ese nombre.';
    if (p.nuevo) { p.name = nuevo; return ''; }
    if (p.tags === null) return 'No se pueden leer sus etiquetas (falta el permiso ssm:ListTagsForResource): no se renombra para no perderlas.';  // null: no se pudieron leer ({} es que no tiene)
    const copia = { name: nuevo, type: p.type, value: p.value, description: p.description || '', tags: p.tags ? { ...p.tags } : {}, nuevo: true, borrar: false, ver: p.ver, orig: null, descripcion_legible: true, de: p.name };
    Object.assign(p, { value: p.orig.value, type: p.orig.type, description: p.orig.description, tags: p.orig.tags ? { ...p.orig.tags } : null, borrar: true });
    S.items.splice(i + 1, 0, copia);
    return '';
  }
  function pedirNombre(i) {
    const p = S.items[i];
    modal.abrir(`<h2>Cambiar el nombre</h2><p><code>${esc(p.name)}</code></p>
      <label class="campo renombrar-campo">Nombre nuevo<input id="nNombre" value="${esc(p.name)}" ${NOFILL}></label>
      <p class="aviso">⚠ En SSM un parámetro no se renombra: se crea uno nuevo con el mismo valor, tipo, descripción y etiquetas, y se borra el viejo. Lo que lo lea por el nombre viejo dejará de encontrarlo, y su historial de versiones no pasa al nuevo. Si el nuevo no se puede crear, el viejo no se borra.</p>
      <p class="aviso mal" id="nError" hidden></p>
      <div class="acciones"><button type="button" class="primario" id="nSi">Poner en el editor</button><button type="button" class="secundario" id="nNo">Cancelar</button></div>`);
    const campo = $('nNombre'); campo.focus(); campo.setSelectionRange(campo.value.length, campo.value.length);
    if (!p.nuevo && p.tags === null) { $('nError').textContent = 'No se pueden leer sus etiquetas (falta el permiso ssm:ListTagsForResource): no se renombra para no perderlas.'; $('nError').hidden = false; $('nSi').disabled = true; }
    const poner = () => {
      const motivo = renombrar(i, campo.value);
      if (motivo) { $('nError').textContent = motivo; $('nError').hidden = false; return; }
      modal.cerrar(); pintar(); toast('Nombre cambiado en el editor: revisa y aplica.');
    };
    $('nSi').onclick = poner; $('nNo').onclick = () => modal.cerrar();
    campo.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); poner(); } });
  }

  // ------------------------------------------------ reemplazar (buscar y reemplazar en lo que se ve con el filtro)
  // Solo cambia el editor, como si se hubiera escrito a mano; después, «Revisar cambios» como siempre. Un nombre nuevo es
  // crear otro parámetro con lo mismo y borrar el viejo (en SSM no se puede renombrar).
  const escRe = t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const recorte = (t, re) => {  // en valores largos, el trozo de alrededor de la primera coincidencia
    const m = t.search(re); if (t.length <= 90 || m < 0) return t;
    const ini = Math.max(0, m - 35); return (ini ? '…' : '') + t.slice(ini, ini + 90) + (ini + 90 < t.length ? '…' : '');
  };
  const visibles = () => [...$('pLista').querySelectorAll('.param:not([hidden])')].map(c => +c.dataset.i);
  // Dónde actúa «Reemplazar…»: en los marcados si hay (con ☑ Marcar), si no en los que se ven (con el filtro)
  function ambito() {
    const m = S.marcando ? marcados() : [];
    if (m.length) return { idx: m, texto: m.length === 1 ? 'el parámetro marcado' : `los ${m.length} parámetros marcados` };
    const v = visibles();
    return { idx: v, texto: `los ${v.length} parámetros que ves ahora${$('pFiltro').value.trim() ? ' (con el filtro)' : ''}` };
  }
  function coincidencias(buscar, por, donde, mayus) {
    const reT = new RegExp(escRe(buscar), mayus ? '' : 'i'), reG = new RegExp(escRe(buscar), mayus ? 'g' : 'gi'), out = [];
    for (const i of ambito().idx) {
      const p = S.items[i]; if (!p || p.bloqueado || p.borrar) continue;
      const mira = (campo, clave, antes) => {
        if (typeof antes !== 'string' || !reT.test(antes)) return;
        const despues = antes.replace(reG, () => por);
        if (despues === antes) return;  // no cambia nada (y un nombre igual sería crear y borrar el mismo)
        out.push({ i, campo, clave, antes, despues, n: (antes.match(reG) || []).length, reT });
      };
      if (donde.nombre) mira('nombre', '', p.name);
      if (donde.valor) mira('valor', '', p.value);
      if (donde.descripcion && p.descripcion_legible !== false) mira('descripción', '', p.description || '');
      if (donde.etiquetas && p.tags) Object.entries(p.tags).forEach(([k, v]) => mira('etiqueta', k, String(v)));
    }
    return out;
  }
  // ------------------------------------------------ 🏷 Poner etiquetas (en «Reemplazar…»): la misma clave = valor en muchos a la vez
  const ETQ_AWS = /^[\p{L}\p{Z}\p{N}_.:/=+\-@]*$/u;  // lo que AWS admite en claves y valores de etiquetas
  const filaEtq = (k = '', v = '') => `<div class="etq-fila"><input class="e-k" value="${esc(k)}" placeholder="Clave" ${NOFILL}><span>=</span><input class="e-v" value="${esc(v)}" placeholder="Valor" ${NOFILL}><button type="button" class="enlace" data-e-quitar title="Quitar" aria-label="Quitar">×</button></div>`;
  const panelEtiquetas = () => `<div id="ePanel" hidden>
      <div id="eFilas">${(obligatorias().length ? obligatorias() : ['']).map(k => filaEtq(k)).join('')}</div>
      <button type="button" class="enlace" id="eOtra">+ otra etiqueta</button>
      <div class="reemplazar-donde"><span class="reemplazar-et">Dónde</span><span class="pildoras"><label class="pildora"><input type="radio" name="eModo" value="faltan" checked><span>Solo donde falta o está vacía</span></label><label class="pildora"><input type="radio" name="eModo" value="todos"><span>En todos (cambia el valor que tengan)</span></label></span></div>
      <div id="eLista" class="reemplazar-lista"><p class="muted">Escribe la clave y el valor.</p></div>
      <div class="acciones"><button type="button" class="primario" id="ePoner" disabled>Poner en el editor</button><button type="button" class="secundario" id="eNo">Cancelar</button></div></div>`;
  function cambiosEtiquetas(pares, soloFaltan) {
    const out = []; let sinPermiso = 0, sinSitio = 0;
    for (const i of ambito().idx) {
      const p = S.items[i]; if (!p || p.bloqueado || p.borrar) continue;
      if (p.tags === null) { sinPermiso++; continue; }
      const t = p.tags || {}, suyos = [];
      for (const { k, v } of pares) {
        const antes = Object.prototype.hasOwnProperty.call(t, k) ? String(t[k]) : null;
        if ((soloFaltan && (antes || '').trim()) || antes === v) continue;
        suyos.push({ i, k, antes, despues: v });
      }
      if (Object.keys(t).length + suyos.filter(c => c.antes === null).length > 50) { sinSitio++; continue; }  // SSM admite 50
      out.push(...suyos);
    }
    return { out, sinPermiso, sinSitio };
  }
  function montarEtiquetas() {
    let lista = [];
    const pares = () => [...$('eFilas').querySelectorAll('.etq-fila')].map(f => ({ k: f.querySelector('.e-k').value.trim(), v: f.querySelector('.e-v').value.trim() })).filter(x => x.k && x.v);
    const ver = () => {
      const ps = pares(), mal = ps.filter(({ k, v }) => !ETQ_AWS.test(k) || !ETQ_AWS.test(v) || k.length > 128 || v.length > 256 || k.toLowerCase().startsWith('aws:'));
      const repes = ps.map(x => x.k).filter((k, n, a) => a.indexOf(k) !== n);
      const r = mal.length || repes.length || !ps.length ? null : cambiosEtiquetas(ps, $('ePanel').querySelector('[name=eModo]:checked').value === 'faltan');
      lista = r ? r.out : [];
      const notas = r ? [r.sinPermiso && `${r.sinPermiso} sin permiso para ver sus etiquetas`, r.sinSitio && `${r.sinSitio} ya con 50 etiquetas (lo máximo en SSM)`].filter(Boolean) : [];
      $('eLista').innerHTML = !ps.length ? '<p class="muted">Escribe la clave y el valor.</p>'
        : mal.length ? `<p class="error">«${esc(mal[0].k)} = ${esc(mal[0].v)}» no vale: AWS solo admite letras, números, espacios y _ . : / = + - @ (clave hasta 128, valor hasta 256 y sin «aws:» delante).</p>`
        : repes.length ? `<p class="error">La clave «${esc(repes[0])}» está dos veces.</p>`
        : !lista.length ? `<p class="muted">Nada que cambiar: ya la tienen todos${notas.length ? ' · ' + notas.join(' · ') : ''}.</p>`
        : `<p class="reemplazar-cuenta">${lista.length} ${lista.length === 1 ? 'etiqueta' : 'etiquetas'} en ${new Set(lista.map(c => c.i)).size} parámetros · desmarca las que no quieras${notas.length ? ` · <span class="warn">${notas.join(' · ')}: no se tocan</span>` : ''}</p>
          <table class="reemplazar-tabla"><thead><tr><th><input type="checkbox" id="eTodos" checked title="Todas" aria-label="Todas"></th><th>Parámetro</th><th>Etiqueta</th><th>Antes → después</th></tr></thead><tbody>${lista.map((c, n) => `<tr>
          <td><input type="checkbox" data-e="${n}" checked aria-label="Poner esta etiqueta"></td><td><code>${esc(S.items[c.i].name)}</code></td><td><span class="cambio">${esc(c.k)}</span></td>
          <td>${c.antes === null ? '<small class="muted">no la tiene</small>' : c.antes.trim() ? `<span class="reemplazar-antes">${esc(c.antes)}</span>` : '<small class="muted">vacía</small>'}<span class="reemplazar-despues">${esc(c.despues)}</span></td></tr>`).join('')}</tbody></table>`;
      if ($('eTodos')) $('eTodos').addEventListener('change', e => $('eLista').querySelectorAll('[data-e]').forEach(x => { x.checked = e.target.checked; }));
      $('ePoner').disabled = !lista.length;
    };
    $('ePanel').addEventListener('input', ver);
    $('ePanel').addEventListener('change', ver);
    $('ePanel').addEventListener('click', e => {
      if (e.target.closest('[data-e-quitar]')) { e.target.closest('.etq-fila').remove(); if (!$('eFilas').children.length) $('eFilas').insertAdjacentHTML('beforeend', filaEtq()); ver(); }
    });
    $('eOtra').onclick = () => { $('eFilas').insertAdjacentHTML('beforeend', filaEtq()); $('eFilas').lastElementChild.querySelector('.e-k').focus(); };
    $('eNo').onclick = modal.cerrar;
    $('ePoner').onclick = () => {
      const elegidas = lista.filter((_, n) => ($('eLista').querySelector(`[data-e="${n}"]`) || {}).checked);
      for (const c of elegidas) S.items[c.i].tags = { ...(S.items[c.i].tags || {}), [c.k]: c.despues };
      modal.cerrar(); pintar();
      toast(`${elegidas.length} ${elegidas.length === 1 ? 'etiqueta puesta' : 'etiquetas puestas'} en el editor. Revisa y aplica.`);
    };
  }

  $('pReemplazar').onclick = () => {
    if (!S.ruta) return toast('Carga antes un grupo o una ruta.', true);
    modal.abrir(`<h2>Reemplazar</h2><span class="selector-vista r-modo" id="rModo" role="group" aria-label="Qué hacer"><button type="button" data-r-modo="reemplazar" aria-pressed="true">Buscar y reemplazar</button><button type="button" data-r-modo="etiquetas" aria-pressed="false">🏷 Poner etiquetas</button></span>
      <p>En ${ambito().texto}. Solo cambia el editor: después, «Revisar cambios» como siempre.</p>
      <div id="rPanel">
      <div class="reemplazar"><label class="campo">Buscar<input id="rBuscar" ${NOFILL}></label><label class="campo">Reemplazar por<input id="rPor" ${NOFILL}></label></div>
      <div class="reemplazar-donde"><span class="reemplazar-et">Buscar en</span><span class="pildoras">${[['rValor', 'Valores', true], ['rNombre', 'Nombres', false], ['rEtiquetas', 'Etiquetas', false], ['rDesc', 'Descripciones', false]]
        .map(([id, t, on]) => `<label class="pildora"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span>${t}</span></label>`).join('')}</span>
        <label class="pildora sola"><input type="checkbox" id="rMayus"><span>Aa · distinguir mayúsculas</span></label></div>
      <p class="aviso reemplazar-aviso" id="rAvisoNombre" hidden>⚠ En SSM un parámetro no se renombra: se crea uno nuevo con el mismo valor, tipo, descripción y etiquetas, y se borra el viejo. Lo que lo lea por el nombre viejo dejará de encontrarlo, y su historial de versiones no pasa al nuevo. Si el nuevo no se puede crear, el viejo no se borra.</p>
      <div id="rLista" class="reemplazar-lista"><p class="muted">Escribe qué buscar.</p></div>
      <div class="acciones"><button type="button" class="primario" id="rPoner" disabled>Poner en el editor</button><button type="button" class="secundario" id="rNo">Cancelar</button></div></div>
      ${panelEtiquetas()}`);
    let lista = [];
    const donde = () => ({ valor: $('rValor').checked, nombre: $('rNombre').checked, etiquetas: $('rEtiquetas').checked, descripcion: $('rDesc').checked });
    const oculto = c => c.campo === 'valor' && S.items[c.i].type === 'SecureString' && !S.items[c.i].ver && !$('pMostrar').checked;
    const ver = () => {
      const buscar = $('rBuscar').value;
      $('rAvisoNombre').hidden = !$('rNombre').checked;
      lista = buscar ? coincidencias(buscar, $('rPor').value, donde(), $('rMayus').checked) : [];
      const rePor = new RegExp(escRe($('rPor').value) || '^');
      $('rLista').innerHTML = !buscar ? '<p class="muted">Escribe qué buscar.</p>' : !lista.length ? '<p class="muted">Nada que coincida.</p>'
        : `<p class="reemplazar-cuenta">${lista.length} ${lista.length === 1 ? 'cambio' : 'cambios'} en ${new Set(lista.map(c => c.i)).size} parámetros · desmarca los que no quieras</p>
          <table class="reemplazar-tabla"><thead><tr><th><input type="checkbox" id="rTodos" checked title="Todos" aria-label="Todos"></th><th>Parámetro</th><th>Dónde</th><th>Antes → después</th></tr></thead><tbody>${lista.map((c, k) => `<tr>
          <td><input type="checkbox" data-r="${k}" checked aria-label="Aplicar este cambio"></td><td><code>${esc(S.items[c.i].name)}</code></td>
          <td><span class="cambio">${c.campo}${c.clave ? ' · ' + esc(c.clave) : ''}</span>${c.n > 1 ? `<small>${c.n} veces</small>` : ''}</td>
          <td>${oculto(c) ? '<small class="muted">Valor cifrado: marca «Mostrar valores» para verlo</small>'
            : `<span class="reemplazar-antes">${esc(recorte(c.antes, c.reT))}</span><span class="reemplazar-despues">${esc(recorte(c.despues, rePor))}</span>`}</td></tr>`).join('')}</tbody></table>`;
      if ($('rTodos')) $('rTodos').addEventListener('change', e => $('rLista').querySelectorAll('[data-r]').forEach(x => { x.checked = e.target.checked; }));
      $('rPoner').disabled = !lista.length;
    };
    ['rBuscar', 'rPor'].forEach(id => $(id).addEventListener('input', ver));
    ['rValor', 'rNombre', 'rEtiquetas', 'rDesc', 'rMayus'].forEach(id => $(id).addEventListener('change', ver));
    $('rNo').onclick = modal.cerrar; $('rBuscar').focus();
    montarEtiquetas();
    $('rModo').addEventListener('click', e => {
      const b = e.target.closest('[data-r-modo]'); if (!b) return;
      $('rModo').querySelectorAll('[data-r-modo]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      const etq = b.dataset.rModo === 'etiquetas';
      $('rPanel').hidden = etq; $('ePanel').hidden = !etq;
      (etq ? $('ePanel').querySelector('.e-v') || $('ePanel').querySelector('.e-k') : $('rBuscar')).focus();
    });
    $('rPoner').onclick = () => {
      const elegidos = lista.filter((_, k) => ($('rLista').querySelector(`[data-r="${k}"]`) || {}).checked);
      const nombres = elegidos.filter(c => c.campo === 'nombre'), choques = [];
      for (const c of elegidos.filter(c => c.campo !== 'nombre')) {
        const p = S.items[c.i];
        if (c.campo === 'valor') p.value = c.despues;
        else if (c.campo === 'descripción') p.description = c.despues;
        else p.tags = { ...p.tags, [c.clave]: c.despues };
      }
      // Los nombres al final y de abajo arriba: cada nuevo va justo debajo del que sustituye, y el viejo se marca para borrar
      for (const c of nombres.sort((a, b) => b.i - a.i)) { const motivo = renombrar(c.i, c.despues); if (motivo) choques.push(`${S.items[c.i].name} (${motivo.replace(/\.$/, '')})`); }
      modal.cerrar(); pintar();
      toast(`${elegidos.length - choques.length} ${elegidos.length - choques.length === 1 ? 'cambio puesto' : 'cambios puestos'} en el editor${choques.length ? `; ${choques.length} ${choques.length === 1 ? 'nombre no se ha cambiado' : 'nombres no se han cambiado'}: ${choques.join('; ')}` : ''}. Revisa y aplica.`, !!choques.length);
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

  // ------------------------------------------------ papelera: lo borrado desde aquí (copias en /papelera del mismo SSM)
  $('pPapelera').onclick = async () => {
    modal.abrir('<h2>🗑 Papelera</h2><p>Leyendo de AWS…</p>');
    let r;
    try { r = await api('/api/papelera'); } catch (e) { return modal.abrir(`<h2>🗑 Papelera</h2><p class="error">${esc(e.message)}</p>`); }
    const fecha = t => { const d = new Date(t); return isNaN(d) ? esc(t || '') : d.toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' }); };
    modal.abrir(`<h2>🗑 Papelera · ${r.filas.length}</h2>
      <p>Lo que se borra desde ParamsX se guarda antes aquí, tal cual (valor, tipo, descripción, etiquetas y clave KMS), en <code>${esc(r.ruta)}</code> de esta cuenta y región. Sigue cifrado en AWS. <b>Restaurar</b> lo vuelve a crear en su sitio; <b>Borrar para siempre</b> no tiene vuelta atrás.</p>
      ${r.filas.length ? `<label class="papelera-todos"><input type="checkbox" id="ppTodos"> Todos</label>
      <div class="plan papelera-lista">${r.filas.map((f, i) => `<label class="plan-fila"><input type="checkbox" data-pp="${i}"><span><code>${esc(f.original)}</code>
        <small class="muted">${fecha(f.el)}${f.por ? ' · ' + esc(f.por) : ''} · ${esc(f.tipo || '')}${f.sin_etiquetas ? ' · <span class="warn">sin sus etiquetas (no se pudieron leer)</span>' : ''}</small></span></label>`).join('')}</div>
      <label class="campo">Para borrar para siempre, escribe <code>APLICAR EN ${esc(r.account)}</code><input id="ppConfirma" ${NOFILL}></label>
      <div class="acciones"><button type="button" class="primario" id="ppRestaurar" disabled>Restaurar</button><button type="button" class="secundario peligro" id="ppBorrar" disabled>Borrar para siempre</button><button type="button" class="secundario" id="ppNo">Cerrar</button></div>`
      : '<p>Está vacía.</p><div class="acciones"><button type="button" class="secundario" id="ppNo">Cerrar</button></div>'}`);
    $('ppNo').onclick = () => modal.cerrar();
    if (!r.filas.length) return;
    const elegidos = () => [...$('modalCuerpo').querySelectorAll('[data-pp]:checked')].map(c => r.filas[+c.dataset.pp]);
    const marcar = () => { const n = elegidos().length; $('ppRestaurar').disabled = !n; $('ppBorrar').disabled = !n; $('ppRestaurar').textContent = n ? `Restaurar ${n}` : 'Restaurar'; $('ppBorrar').textContent = n ? `Borrar ${n} para siempre` : 'Borrar para siempre'; };
    $('modalCuerpo').onchange = e => { if (e.target.id === 'ppTodos') $('modalCuerpo').querySelectorAll('[data-pp]').forEach(c => { c.checked = e.target.checked; }); marcar(); };
    const hacer = async (accion, extra = {}) => {
      const filas = elegidos();
      try {
        const res = { resultados: [] };  // el servidor admite 200 por petición: en bloques
        for (let k = 0; k < filas.length; k += 200) res.resultados.push(...(await post(`/api/papelera/${accion}`, { nombres: filas.slice(k, k + 200).map(f => f.nombre), ...extra })).resultados);
        const mal = res.resultados.filter(x => !x.ok);
        toast(mal.length ? `${res.resultados.length - mal.length} hechos; ${mal.length} no: ${mal.map(x => x.error).join(' · ')}` : accion === 'restaurar' ? `${filas.length} restaurados en su sitio` : `${filas.length} borrados para siempre`, !!mal.length);
        $('pPapelera').click();  // la papelera, otra vez de AWS
        if (accion === 'restaurar' && S.cargada && !pendientes().length) { S.carpetas = null; B.enAws = null; $('pRuta').value = S.cargada; cargar(); }
      } catch (e) { toast(e.message, true); }
    };
    $('ppRestaurar').onclick = () => confirm(`¿Restaurar ${elegidos().length} en su sitio?`) && hacer('restaurar');
    $('ppBorrar').onclick = () => {
      if (!$('ppConfirma').value.trim()) return toast(`Escribe APLICAR EN ${r.account} para borrar para siempre`, true);
      if (confirm(`¿Borrar para siempre ${elegidos().length}? No se podrán recuperar.`)) hacer('vaciar', { confirmacion: $('ppConfirma').value.trim() });
    };
  };

  // ------------------------------------------------ explorar (solo nombres): árbol con entornos en color
  $('pExplorar').onclick = async () => {
    modal.abrir('<h2>Explorar</h2><p>Leyendo los nombres (sin valores)…</p>');
    let r;
    try { r = await api('/api/explorar'); } catch (e) { return modal.abrir(`<h2>Explorar</h2><p class="error">${esc(e.message)}</p>`); }
    const nombres = new Set(r.nombres);  // con más de los que caben, lo que se filtra se pide también a AWS y se añade aquí
    const arbol = q => {
      const raiz = {};
      [...nombres].filter(n => !q || n.toLowerCase().includes(q)).forEach(n => {
        const seg = n.split('/').filter(Boolean);
        if (seg.length === 1) { raiz[n] = raiz[n] || { _n: 1, _hoja: n }; return; }  // sin carpeta: el parámetro mismo
        let nodo = raiz;
        seg.slice(0, -1).forEach(x => { nodo[x] = nodo[x] || { _n: 0 }; nodo[x]._n++; nodo = nodo[x]; });
      });
      return raiz;
    };
    const fila = (k, ruta, n, nivel, hoja) => {
      const e = entornoDe(k);
      return `<span class="exp-nombre nivel-${Math.min(nivel, 3)}${e ? ' entorno ' + claseEntorno(e) : ''}">${esc(k)}</span><span class="exp-n" title="Parámetros por debajo">${n}</span>
        <span class="exp-acciones"><button type="button" class="secundario" data-ruta="${esc(ruta)}">Cargar</button>${hoja ? '' : `<button type="button" class="secundario" data-grupo-de="${esc(ruta)}" title="Guardar esta carpeta como grupo (se detecta dónde va el entorno)">+ Grupo</button>`}</span>`;
    };
    const rama = (nodo, ruta, nivel, abierto) => Object.keys(nodo).filter(k => k !== '_n' && k !== '_hoja').sort((a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' })).map(k => {
      const r2 = nodo[k]._hoja || `${ruta}/${k}`, hijos = rama(nodo[k], r2, nivel + 1, abierto);
      return hijos ? `<details class="rama" ${abierto ? 'open' : ''}><summary class="exp-fila">${fila(k, r2, nodo[k]._n, nivel, nodo[k]._hoja)}</summary><div class="hijos">${hijos}</div></details>`
        : `<div class="exp-fila exp-hoja">${fila(k, r2, nodo[k]._n, nivel, nodo[k]._hoja)}</div>`;
    }).join('');
    modal.abrir(`<h2>Explorar · ${r.nombres.length} parámetros</h2><p>Solo nombres. «Cargar» abre la carpeta; «+ Grupo» la guarda en tu configuración para elegirla luego con su entorno.${r.limitado ? ' <span class="warn">Hay más de los que se muestran: al filtrar se buscan también en AWS.</span>' : ''}</p>
      <div class="exp-cab"><input type="search" id="pExpFiltro" placeholder="Filtrar rutas… (p. ej. rds, api)" ${NOFILL}><span class="leyenda">${cfg().entornos.map(e => `<span class="entorno ${claseEntorno(e)}">${esc(e)}</span>`).join('')}</span></div>
      <div class="arbol" id="pArbol">${rama(arbol(''), '', 0, false) || '<p class="muted">No hay parámetros.</p>'}</div>`);
    let buscando = false, espera;
    const pintarArbol = () => { const q = $('pExpFiltro').value.trim().toLowerCase(); $('pArbol').innerHTML = rama(arbol(q), '', 0, !!q) || `<p class="muted">${buscando ? 'Buscando en AWS…' : 'Ninguna ruta con eso.'}</p>`; };
    $('pExpFiltro').addEventListener('input', () => {
      pintarArbol();
      const q = $('pExpFiltro').value.trim();
      clearTimeout(espera);
      if (!r.limitado || q.length < 2) return;
      buscando = true; pintarArbol();
      espera = setTimeout(async () => {  // AWS distingue mayúsculas: tal cual, en minúsculas y en mayúsculas
        try {
          const vistas = await Promise.all([...new Set([q, q.toLowerCase(), q.toUpperCase()])].map(t => api('/api/explorar?contiene=' + encodeURIComponent(t))));
          vistas.forEach(v => v.nombres.forEach(n => nombres.add(n)));
        } catch (e) { toast(e.message, true); }
        buscando = false; if ($('pExpFiltro')?.value.trim() === q) pintarArbol();
      }, 400);
    });
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
