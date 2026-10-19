// Ownly: small enhancements on top of server-rendered pages. Everything works without them.
(() => {
  const short = (v) => v >= 1e6 ? '$' + (v / 1e6).toFixed(2).replace(/\.00$/, '') + 'M'
                                : '$' + Math.round(v / 1000).toLocaleString('en-US') + 'k';
  const full = (v) => '$' + Math.round(v).toLocaleString('en-US');

  // ---- range meter: likely range, estimate tick, asking price ring
  function drawMeter(meter, low, high, value, ask) {
    const has = Number.isFinite(ask) && ask > 0;
    const lo = Math.min(low, has ? ask : low) * 0.94;
    const hi = Math.max(high, has ? ask : high) * 1.06;
    const pos = (v) => ((v - lo) / (hi - lo)) * 100 + '%';
    const band = meter.querySelector('.est-band');
    band.style.left = pos(low);
    band.style.width = ((high - low) / (hi - lo)) * 100 + '%';
    meter.querySelector('.est-tick').style.left = pos(value);
    const mark = meter.querySelector('.est-ask');
    mark.hidden = !has;
    if (has) mark.style.left = pos(ask);
    meter.hidden = false;
  }
  function compareText(ask, value) {
    const d = ask / value - 1;
    if (Math.abs(d) <= 0.015) return 'Your asking price is in line with the estimate.';
    return 'Your asking price is ' + Math.round(Math.abs(d) * 100) + '% ' + (d > 0 ? 'above' : 'below') + ' the estimate.';
  }

  document.querySelectorAll('[data-meter]').forEach((m) => {
    drawMeter(m, +m.dataset.low, +m.dataset.high, +m.dataset.value, +m.dataset.ask);
    const legend = m.parentElement.querySelector('[data-meter-legend]');
    if (legend) legend.hidden = false;
  });

  // ---- live estimate next to the listing and estimate forms
  const form = document.querySelector('[data-estimate-form]');
  const panel = document.querySelector('[data-estimate-panel]');
  if (form && panel) {
    const FIELDS = ['neighborhood', 'style', 'living_area', 'bedrooms', 'full_baths', 'half_baths', 'basement_area',
      'basement_finished', 'lot_area', 'year_built', 'year_remodeled', 'garage_cars', 'fireplaces', 'overall_quality',
      'overall_condition', 'kitchen_quality', 'exterior_quality', 'central_air', 'latitude', 'longitude'];
    const out = (name) => panel.querySelector('[data-est="' + name + '"]');
    let timer = null, controller = null;

    async function refresh() {
      const params = new URLSearchParams();
      for (const name of FIELDS) {
        const el = form.elements.namedItem(name);
        if (!el) continue;
        if (el.type === 'checkbox') { if (el.checked) params.set(name, '1'); }
        else params.set(name, el.value.replace(/[,$\s]/g, ''));
      }
      if (controller) controller.abort();
      controller = new AbortController();
      let data;
      try {
        const res = await fetch('/api/estimate?' + params.toString(), { signal: controller.signal, headers: { Accept: 'application/json' } });
        data = await res.json();
      } catch (err) {
        if (err.name !== 'AbortError') out('range').textContent = 'The estimate is unavailable right now.';
        return;
      }
      const heading = out('heading');
      if (!data.ok) {
        out('value').textContent = '–';
        out('range').textContent = 'Fill in the home details to see an estimate.';
        out('meter').hidden = true;
        out('compare').hidden = true;
        out('notes').replaceChildren();
        out('basis').textContent = '';
        return;
      }
      if (heading) heading.textContent = 'Ownly estimate, ' + data.quarter;
      out('value').textContent = short(data.value);
      out('range').textContent = 'Likely range ' + short(data.low) + ' – ' + short(data.high);
      const priceEl = form.elements.namedItem('price');
      const ask = priceEl ? parseFloat(priceEl.value.replace(/[,$\s]/g, '')) : NaN;
      drawMeter(out('meter'), data.low, data.high, data.value, ask);
      if (out('legend')) out('legend').hidden = !(ask > 0);
      const compare = out('compare');
      compare.hidden = !(ask > 0);
      if (ask > 0) compare.textContent = compareText(ask, data.value);
      const notes = out('notes');
      notes.replaceChildren(...data.notes.map((n) => { const li = document.createElement('li'); li.textContent = n; return li; }));
      out('basis').textContent = 'Model price in mid-2010 ' + full(data.model_price) + ', times ' + data.factor.toFixed(2) +
        ' for the change in Ames prices since' + (data.projected ? ' (index published through ' + data.latest + ', then the recent trend).' : '.');
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };
    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
    refresh();
  }

  // ---- maps (Leaflet, served from /static/vendor). Tiles: OpenStreetMap's standard server, which is
  // fine for light use and asks for a referrer; a public launch needs its own tile provider.
  // The tile host is also named in the CSP in ownly/__init__.py.
  const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  function baseMap(node, options) {
    const map = L.map(node, Object.assign({ scrollWheelZoom: false }, options));
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19, referrerPolicy: 'strict-origin-when-cross-origin' }).addTo(map);
    return map;
  }
  const homeIcon = () => L.divIcon({ className: 'pin-anchor', html: el('span', 'pin-home'), iconSize: null });

  function popupCard(p) {
    const card = el('a', 'popup-card');
    card.href = p.url;
    if (p.photo) { const img = el('img'); img.src = p.photo; img.alt = ''; card.append(img); }
    const body = el('span', 'popup-body');
    body.append(el('strong', 'popup-price', p.full_price), el('span', 'popup-title', p.title), el('span', 'popup-facts', p.facts),
                el('span', 'popup-place', p.place + (p.exact ? '' : ' · approximate location')));
    if (p.example) body.append(el('span', 'popup-note', 'Example listing'));
    card.append(body);
    return card;
  }

  if (window.L) {
    // Browse: every home in the search as a price tag.
    const pinsData = document.getElementById('map-pins');
    const browseNode = document.querySelector('[data-map="browse"]');
    if (pinsData && browseNode) {
      const pins = JSON.parse(pinsData.textContent);
      const map = baseMap(browseNode);
      const markers = {};
      pins.forEach((p) => {
        const tag = el('span', 'pin' + (p.exact ? '' : ' pin-approx') + (p.status !== 'active' ? ' pin-muted' : ''), p.price);
        const marker = L.marker([p.lat, p.lng], { icon: L.divIcon({ className: 'pin-anchor', html: tag, iconSize: null }),
                                                  title: p.title + ', ' + p.full_price, riseOnHover: true }).addTo(map);
        marker.bindPopup(() => popupCard(p), { closeButton: false, minWidth: 220, maxWidth: 260, offset: [0, -30] });
        markers[p.id] = { marker, tag };
      });
      // Price tags that would overlap shrink to dots (hover or focus shows the price).
      const order = pins.slice().sort((a, b) => (a.status === 'active' ? 0 : 1) - (b.status === 'active' ? 0 : 1) || b.id - a.id);
      function declutter() {
        const placed = [];
        for (const p of order) {
          const { marker, tag } = markers[p.id];
          tag.classList.remove('pin-dot');
          const pt = map.latLngToContainerPoint(marker.getLatLng());
          const w = tag.offsetWidth + 6, h = tag.offsetHeight + 4;
          const box = { l: pt.x - w / 2, r: pt.x + w / 2, t: pt.y - h - 7, b: pt.y };
          if (placed.some((o) => box.l < o.r && box.r > o.l && box.t < o.b && box.b > o.t)) tag.classList.add('pin-dot');
          else placed.push(box);
        }
      }
      map.on('zoomend moveend resize', declutter);
      if (pins.length) map.fitBounds(pins.map((p) => [p.lat, p.lng]), { padding: [48, 48], maxZoom: 15 });
      else map.setView([42.03, -93.64], 12);
      declutter();
      document.querySelectorAll('[data-listing]').forEach((card) => {
        const hit = markers[card.dataset.listing];
        if (!hit) return;
        card.addEventListener('mouseenter', () => { hit.tag.classList.add('is-hot'); hit.marker.setZIndexOffset(1000); });
        card.addEventListener('mouseleave', () => { hit.tag.classList.remove('is-hot'); hit.marker.setZIndexOffset(0); });
      });
    }

    // Listing page: the pin, or the neighborhood as a circle.
    const detailNode = document.querySelector('[data-map="detail"]');
    if (detailNode) {
      const at = [parseFloat(detailNode.dataset.lat), parseFloat(detailNode.dataset.lng)];
      const exact = detailNode.dataset.exact === '1';
      const map = baseMap(detailNode);
      if (exact) L.marker(at, { icon: homeIcon(), keyboard: false }).addTo(map);
      else L.circle(at, { radius: 450, color: '#0e6b50', weight: 1.5, fillColor: '#0e6b50', fillOpacity: 0.08 }).addTo(map);
      map.setView(at, exact ? 16 : 14);
    }

    // Sell and estimate forms: drop a pin, and the neighborhood follows it.
    const picker = document.querySelector('[data-picker]');
    if (picker) {
      const info = JSON.parse(document.getElementById('map-info').textContent);
      const form = picker.closest('form');
      const latIn = form.elements.namedItem('latitude'), lngIn = form.elements.namedItem('longitude');
      const hood = form.elements.namedItem('neighborhood');
      const status = picker.querySelector('[data-pin-status]'), clear = picker.querySelector('[data-pin-clear]');
      const a = info.area;
      const map = baseMap(picker.querySelector('[data-map="picker"]'), {
        maxBounds: [[a.south, a.west], [a.north, a.east]], maxBoundsViscosity: 0.9, minZoom: 12 });
      let marker = null;
      const changed = (node) => node.dispatchEvent(new Event('input', { bubbles: true }));

      async function place(latlng, byUser) {
        if (!marker) {
          marker = L.marker(latlng, { icon: homeIcon(), draggable: true, keyboard: false }).addTo(map);
          marker.on('dragend', () => place(marker.getLatLng(), true));
        } else marker.setLatLng(latlng);
        latIn.value = latlng.lat.toFixed(6);
        lngIn.value = latlng.lng.toFixed(6);
        clear.hidden = false;
        if (!byUser) { status.textContent = 'Pin placed.'; return; }
        status.textContent = 'Finding the neighborhood…';
        try {
          const res = await fetch('/api/neighborhood?lat=' + latIn.value + '&lng=' + lngIn.value);
          const d = await res.json();
          if (!d.ok) { status.textContent = d.error; return; }
          const moved = hood.value !== d.neighborhood;
          hood.value = d.neighborhood;
          status.textContent = (moved ? 'Pin placed. Neighborhood set to ' : 'Pin placed in ') + d.label + '.' +
            (d.covered ? '' : ' Few recorded sales nearby, so the estimate is less certain.');
          if (moved) hood.dispatchEvent(new Event('change', { bubbles: true }));
        } catch (err) {
          status.textContent = 'Pin placed.';
        }
        changed(latIn);
      }
      map.on('click', (e) => place(e.latlng, true));
      clear.addEventListener('click', () => {
        if (marker) { map.removeLayer(marker); marker = null; }
        latIn.value = lngIn.value = '';
        clear.hidden = true;
        status.textContent = 'No pin. Buyers will see the home somewhere in its neighborhood.';
        changed(latIn);
      });
      hood.addEventListener('change', () => { const c = info.centroids[hood.value]; if (c && !marker) map.setView(c, 14); });
      if (latIn.value && lngIn.value) {
        const at = L.latLng(parseFloat(latIn.value), parseFloat(lngIn.value));
        place(at, false);
        map.setView(at, 16);
      } else {
        map.setView(info.centroids[hood.value] || [42.03, -93.64], 14);
      }
    }
  }

  // ---- on phones, start with the filters folded away unless some are set
  const filterBox = document.querySelector('[data-filters]');
  if (filterBox && !filterBox.hasAttribute('data-active') && window.matchMedia('(max-width: 720px)').matches) filterBox.open = false;

  // ---- listing gallery
  document.querySelectorAll('[data-gallery]').forEach((g) => {
    const main = g.querySelector('[data-gallery-main]');
    g.querySelectorAll('.thumb').forEach((t) => t.addEventListener('click', () => {
      main.src = t.dataset.src;
      main.alt = t.dataset.alt;
      g.querySelectorAll('.thumb').forEach((o) => o.removeAttribute('aria-current'));
      t.setAttribute('aria-current', 'true');
    }));
  });

  // ---- photo picker: count and previews
  const picker = document.querySelector('input[type="file"][name="photos"]');
  if (picker) {
    const drop = picker.closest('.drop');
    const count = drop.querySelector('[data-photo-count]');
    const preview = document.querySelector('[data-photo-preview]');
    picker.addEventListener('change', () => {
      const files = [...picker.files];
      count.textContent = files.length ? files.length + ' photo' + (files.length === 1 ? '' : 's') + ' chosen' : 'Choose files or drag them here';
      preview.replaceChildren(...files.slice(0, 8).map((f) => {
        const img = document.createElement('img');
        img.alt = f.name;
        img.src = URL.createObjectURL(f);
        return img;
      }));
    });
    ['dragenter', 'dragover'].forEach((e) => drop.addEventListener(e, () => drop.classList.add('is-over')));
    ['dragleave', 'drop'].forEach((e) => drop.addEventListener(e, () => drop.classList.remove('is-over')));
  }

  // ---- confirm destructive actions
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-confirm]');
    if (el && !window.confirm(el.dataset.confirm)) e.preventDefault();
  });

  // ---- close the account menu when clicking elsewhere
  document.addEventListener('click', (e) => {
    document.querySelectorAll('details.menu[open]').forEach((d) => { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });

  // ---- open a conversation at its latest message
  const reply = document.querySelector('[data-thread] ~ .reply');
  if (reply) reply.scrollIntoView({ block: 'end' });
})();
