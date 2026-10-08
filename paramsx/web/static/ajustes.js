// Ajustes: el perfil de AWS y lo del paramsx_config.py (entornos, perfiles, grupos...), en formulario.
// Lo valida y lo guarda el servidor con la misma lógica que la terminal.
(function () {
  'use strict';
  // Cada opción con su ejemplo, para entenderla sin leer nada más
  const POS = { inicio: 'Al inicio · /rds → /dev/rds', final: 'Al final · /api/sta → /api/sta/dev', mixto: 'Donde está el * · /api/*/sta → /api/dev/sta', ninguno: 'Ninguno · /app/clave (igual en todos)' };
  const CASE = { lower: 'minúsculas · dev', upper: 'MAYÚSCULAS · DEV', capitalize: 'Capitalizado · Dev' };
  const CASE_RUTA = { lower: 'minúsculas · /mi-app/clave', upper: 'MAYÚSCULAS · /MI-APP/CLAVE', capitalize: 'Capitalizado · /Mi-app/Clave', ninguno: 'Como se escriba · /Mi-App/clave' };
  let F = null, sucio = false, nombres = null, aws = null, temporizador = null;
  const opciones = (o, v) => Object.entries(o).map(([k, t]) => `<option value="${k}" ${k === v ? 'selected' : ''}>${esc(t)}</option>`).join('');
  const lista = v => v.split(',').map(s => s.trim()).filter(Boolean);

  function desdeEstado(st) {
    const c = st.config;
    F = c ? JSON.parse(JSON.stringify({
      profile_name: c.profile_name || 'default', region_name: c.region_name || '', entornos: c.entornos || [],
      parameter_list: (c.parameter_list || []).filter(e => e && typeof e === 'object').map(e => ({ nombre: e.nombre || '', path: e.path || '', perfil: e.perfil || e.convencion || '' })),
      perfiles: c.perfiles || {}, perfil_nuevos: c.perfil_nuevos || '', fichero_por_ruta: !!c.fichero_por_ruta,
      forzar_securestring: c.forzar_securestring !== false, tags_activas: !!c.tags_activas, obligatorias_vacias: !!c.obligatorias_vacias,
      tags_obligatorias: c.tags_obligatorias || [],
    })) : null;
    sucio = false;
  }

  function pintar() {
    const st = PX.estado;
    $('aFichero').textContent = st.config_path_corto || st.config_path; $('aFichero').parentElement.title = st.config_path;
    const a = $('aAviso');
    a.hidden = !(st.error_lectura || !st.existe);
    a.className = 'aviso' + (st.error_lectura ? ' mal' : '');
    a.innerHTML = st.error_lectura ? `No se puede leer el fichero, así que no se puede guardar desde aquí: ${esc(st.error_lectura)}` : 'Aún no existe: esto es la plantilla. Ajusta tu perfil de AWS y tus grupos y pulsa Guardar para crearlo.';
    $('aGuardar').disabled = !F;
    if (!F) return;

    const perfilesAws = (aws ? aws.perfiles : []).slice();
    if (!perfilesAws.includes(F.profile_name)) perfilesAws.unshift(F.profile_name);
    $('aPerfil').innerHTML = perfilesAws.map(p => `<option ${p === F.profile_name ? 'selected' : ''}>${esc(p)}</option>`).join('');
    $('aRegion').value = F.region_name;
    $('aEntornos').value = F.entornos.join(', ');
    $('aTags').value = F.tags_obligatorias.join(', ');
    $('aSecure').checked = F.forzar_securestring; $('aTagsActivas').checked = F.tags_activas; $('aVacias').checked = F.obligatorias_vacias;
    const nombresPerfil = Object.keys(F.perfiles);
    $('aNuevos').innerHTML = nombresPerfil.map(n => `<option ${n === F.perfil_nuevos ? 'selected' : ''}>${esc(n)}</option>`).join('');

    $('aPerfiles').innerHTML = Object.entries(F.perfiles).map(([n, p]) => `<tr data-perfil><td><input data-k="nombre" data-orig="${esc(n)}" value="${esc(n)}" ${NOFILL}></td><td><select data-k="posicion_entorno">${opciones(POS, p.posicion_entorno)}</select></td><td><select data-k="case_entorno">${opciones(CASE, p.case_entorno || 'lower')}</select></td><td><select data-k="case_ruta">${opciones(CASE_RUTA, p.case_ruta || 'ninguno')}</select></td><td><button type="button" class="quitar" data-quitar title="Quitar">×</button></td></tr>`).join('');

    $('aGrupos').innerHTML = F.parameter_list.map(g => `<tr data-grupo><td><input data-k="nombre" value="${esc(g.nombre)}" placeholder="${esc(g.path.split('/').filter(s => s && s !== '*').pop() || 'nombre')}" ${NOFILL}></td><td><input class="ruta-in" data-k="path" value="${esc(g.path)}" ${NOFILL}></td><td><select data-k="perfil">${nombresPerfil.includes(g.perfil) ? '' : `<option selected>${esc(g.perfil)}</option>`}${nombresPerfil.map(n => `<option ${n === g.perfil ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></td><td><code>…</code></td><td><button type="button" class="quitar" data-quitar title="Quitar">×</button></td></tr>`).join('')
      || '<tr><td colspan="5" class="muted">Sin grupos. La terminal necesita al menos uno; añádelos con «Buscar en la cuenta» o «+ grupo».</td></tr>';
    revisar(0);
  }

  // Del formulario a F (lo valida el servidor)
  function leer() {
    const perfiles = {};
    $('aPerfiles').querySelectorAll('[data-perfil]').forEach(tr => {
      const v = k => tr.querySelector(`[data-k="${k}"]`).value.trim();
      if (v('nombre')) perfiles[v('nombre')] = { posicion_entorno: v('posicion_entorno'), case_entorno: v('case_entorno'), case_ruta: v('case_ruta') };
    });
    const grupos = [...$('aGrupos').querySelectorAll('[data-grupo]')].map(tr => {
      const v = k => tr.querySelector(`[data-k="${k}"]`).value.trim();
      return { nombre: v('nombre'), path: v('path'), perfil: v('perfil') };
    });
    F = { ...F, profile_name: $('aPerfil').value, region_name: $('aRegion').value.trim(), entornos: lista($('aEntornos').value), parameter_list: grupos, perfiles,
      perfil_nuevos: $('aNuevos').value, forzar_securestring: $('aSecure').checked, tags_activas: $('aTagsActivas').checked, obligatorias_vacias: $('aVacias').checked,
      tags_obligatorias: lista($('aTags').value) };
    sucio = true;
    return F;
  }

  // Validación y columna «Resultado» al vuelo, con la lógica del servidor. Solo se tocan los textos: el cursor no se mueve.
  function revisar(espera = 300) {
    clearTimeout(temporizador);
    temporizador = setTimeout(async () => {
      if (!F) return;
      let r;
      try { r = await post('/api/config/revisar', { config: F }); } catch (e) { return mostrarErrores([e.message], []); }
      $('aGrupos').querySelectorAll('[data-grupo] code').forEach((c, i) => {
        const t = r.resultados[i] || ''; c.textContent = t; c.title = t; c.classList.toggle('mal', !t.includes('→'));
      });
      mostrarErrores(r.errores, r.avisos);
    }, espera);
  }
  function mostrarErrores(errores, avisos) {
    const caja = $('aErrores');
    caja.hidden = !errores.length && !avisos.length;
    caja.className = 'errores' + (errores.length ? '' : ' avisos');
    caja.innerHTML = `<ul>${[...errores, ...avisos].map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  }

  const vista = $('vAjustes');
  vista.addEventListener('input', e => {
    if (e.target.id === 'aBuscar' || !F) return;
    leer(); revisar();
  });
  vista.addEventListener('change', e => {
    if (e.target.id === 'aBuscar' || !F) return;
    // Renombrar un perfil se lleva sus grupos y el perfil de los nuevos
    if (e.target.dataset.k === 'nombre' && e.target.dataset.orig !== undefined) {
      const antes = e.target.dataset.orig, ahora = e.target.value.trim();
      if (ahora && antes !== ahora) {
        $('aGrupos').querySelectorAll('[data-k="perfil"]').forEach(s => { if (s.value === antes) { s.insertAdjacentHTML('beforeend', `<option>${esc(ahora)}</option>`); s.value = ahora; } });
        if ($('aNuevos').value === antes) { $('aNuevos').insertAdjacentHTML('beforeend', `<option>${esc(ahora)}</option>`); $('aNuevos').value = ahora; }
      }
    }
    if (e.target.closest('#aPerfiles, #aGrupos')) { leer(); pintar(); }
  });
  vista.addEventListener('click', e => {
    const q = e.target.closest('[data-quitar]'); if (!q) return;
    q.closest('tr').remove(); leer(); pintar();
  });
  $('aPerfilNuevo').onclick = () => {
    leer();
    let n = Object.keys(F.perfiles).length + 1; while (F.perfiles[`perfil${n}`]) n++;
    F.perfiles[`perfil${n}`] = { posicion_entorno: 'inicio', case_entorno: 'lower', case_ruta: 'ninguno' };
    pintar(); const filas = $('aPerfiles').querySelectorAll('[data-k="nombre"]'); filas[filas.length - 1].select();
  };
  $('aGrupoNuevo').onclick = () => {
    leer(); F.parameter_list.push({ nombre: '', path: '/', perfil: F.perfil_nuevos || Object.keys(F.perfiles)[0] || '' });
    pintar(); const filas = $('aGrupos').querySelectorAll('[data-k="path"]'); filas[filas.length - 1].focus();
  };

  $('aProbar').onclick = async () => {
    const res = $('aProbarRes');
    res.className = 'probar-res'; res.textContent = 'Probando…';
    try {
      const r = await post('/api/aws/probar', { profile_name: $('aPerfil').value, region_name: $('aRegion').value.trim() });
      res.innerHTML = `✓ Cuenta <b>${esc(r.account)}</b>`; res.title = r.arn;
    } catch (e) { res.className = 'probar-res error'; res.textContent = e.message; res.title = ''; }
  };

  // ------------------------------------------------ buscar en la cuenta y añadir como grupo
  async function buscar() {
    const q = $('aBuscar').value.trim().toLowerCase(), caja = $('aResultados');
    if (!q) { caja.hidden = true; return; }
    caja.hidden = false;
    if (!nombres) {
      caja.innerHTML = '<p class="muted">Leyendo los nombres de la cuenta…</p>';
      try { nombres = (await api('/api/explorar')).nombres; } catch (e) { caja.innerHTML = `<p class="muted error">${esc(e.message)}</p>`; return; }
    }
    const carpetas = [...new Set(nombres.filter(n => n.toLowerCase().includes(q)).map(n => n.slice(0, n.lastIndexOf('/')) || '/'))].filter(c => c !== '/');
    caja.innerHTML = carpetas.slice(0, 300).map(c => `<div class="resultado"><code title="${esc(c)}">${esc(c)}</code><small>${nombres.filter(n => n.startsWith(c + '/')).length} par</small><button type="button" class="enlace" data-grupo-de="${esc(c)}">Añadir como grupo</button></div>`).join('')
      || '<p class="muted">Ninguna carpeta con eso.</p>';
  }
  $('aBuscar').addEventListener('input', buscar);
  $('aResultados').addEventListener('click', async e => {
    const b = e.target.closest('[data-grupo-de]'); if (!b || !F) return;
    leer();
    let r;
    try { r = await post('/api/grupo-de', { carpeta: b.dataset.grupoDe, entornos: F.entornos, perfiles: F.perfiles }); } catch (err) { return toast(err.message, true); }
    const g = r.grupo;
    if (F.parameter_list.some(x => x.path === g.path && x.perfil === g.perfil)) return toast(`El grupo ${g.path} (${g.perfil}) ya está`);
    if (r.perfil_nuevo) F.perfiles[r.perfil_nuevo[0]] = r.perfil_nuevo[1];
    F.parameter_list.push(g);
    pintar(); toast(`Grupo ${g.path} (${g.perfil}${r.perfil_nuevo ? ', perfil nuevo' : ''}) añadido: revisa y guarda`);
  });

  // ------------------------------------------------ guardar
  $('aGuardar').onclick = async () => {
    leer();
    const c = PX.estado.config || {};
    if ((F.profile_name !== c.profile_name || F.region_name !== c.region_name) && PX.pendientes()
        && !confirm('Cambias de perfil o región y en ParamsX hay cambios sin aplicar: se descartarán. ¿Seguir?')) return;
    $('aEstado').textContent = 'Guardando…';
    try {
      PX.estado = await api('/api/config', { method: 'PUT', body: JSON.stringify({ config: F }) });
      desdeEstado(PX.estado); PX.oyentes.forEach(f => f(PX.estado));
      $('aEstado').textContent = 'Guardado'; toast('Configuración guardada');
    } catch (e) {
      $('aEstado').innerHTML = `<span class="error">${esc(e.message)}</span>`;
      if (e.datos && e.datos.errores) mostrarErrores(e.datos.errores, e.datos.avisos || []);
    }
  };

  PX.oyentes.push(st => {
    const antes = F && `${F.profile_name}|${F.region_name}`;
    if (!sucio) { desdeEstado(st); pintar(); }
    else { $('aEstado').textContent = 'La configuración ha cambiado fuera de este formulario: al guardar se queda lo de aquí.'; }
    if (st.config && antes !== `${st.config.profile_name}|${st.config.region_name}`) { nombres = null; $('aBuscar').value = ''; $('aResultados').hidden = true; }
  });
  api('/api/aws/perfiles').then(r => {
    aws = r;
    $('aRegiones').innerHTML = r.regiones.map(x => `<option value="${esc(x)}"></option>`).join('');
    if (PX.estado && F) { const f = F; pintar(); F = f; }
  }).catch(() => { aws = { perfiles: [], regiones: [] }; });
})();
