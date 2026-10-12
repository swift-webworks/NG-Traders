/* NG Traders — customer ordering page.
   Speech recognition only turns speech into text (in the browser). The server then finds products,
   checks selling rules and prices the bill. This script never decides a price or a total. */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var cfg = JSON.parse($('#shop-config').textContent);
  var CART_KEY = 'ng_cart_v1';
  var IDEM_KEY = 'ng_idem_v1';

  // ---------------------------------------------------------------- tiny helpers
  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') node.className = attrs[k];
      else if (k === 'text') node.textContent = attrs[k];
      else if (k.indexOf('on') === 0) node.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) node.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid); });
    return node;
  }
  // English line with the Tamil line underneath
  function bi(en, ta, tag) {
    var wrap = el(tag || 'span', {}, [el('span', { text: en })]);
    if (ta) wrap.appendChild(el('span', { class: 'sub ta', text: ta }));
    return wrap;
  }
  function biMsg(m, tag) { return bi(m.en, m.ta, tag); }
  function money(s) { return '₹' + Number(s).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function cookie(name) {
    var m = document.cookie.match('(?:^|; )' + name + '=([^;]*)');
    return m ? decodeURIComponent(m[1]) : '';
  }
  function store(key, val) { try { if (val === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* private mode */ } }
  function load(key) { try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; } }
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var a = new Uint8Array(16); (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }
  function clearNode(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function api(url, data) {
    var opts = { method: data === undefined ? 'GET' : 'POST', headers: { 'Accept': 'application/json' }, credentials: 'same-origin' };
    if (data !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-CSRFToken'] = cookie('csrftoken');
      opts.body = JSON.stringify(data);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    }).catch(function () { return { ok: false, status: 0, json: { error: NET_ERR } }; });
  }
  var NET_ERR = { en: 'Network problem. Please check your internet and try again.', ta: 'இணைய பிரச்சனை. இணைப்பை சரிபார்த்து மீண்டும் முயற்சிக்கவும்.' };
  function errOf(r, fallback) {
    var e = r.json && r.json.error;
    return (e && e.en) ? e : (fallback || NET_ERR);
  }

  // ---------------------------------------------------------------- state
  var cart = (load(CART_KEY) || []).filter(function (l) { return l && l.product_id && l.quantity; });
  var pending = [];
  var bill = null;
  var listening = false;
  var recognition = null;

  var ui = {
    mic: $('#mic-btn'), micLabel: $('#mic-label'), banner: $('#status-banner'), text: $('#speech-text'),
    find: $('#find-btn'), clear: $('#clear-btn'), review: $('#review-section'), reviewList: $('#review-list'),
    billSection: $('#bill-section'), billLines: $('#bill-lines'), billTotals: $('#bill-totals'),
    addMore: $('#add-more-btn'), checkoutBtn: $('#checkout-btn'), checkout: $('#checkout-section'),
    form: $('#checkout-form'), payBox: $('#payment-options'), address: $('#address-group'),
    submit: $('#place-order-btn'), formErrors: $('#form-errors'), checkoutTotal: $('#checkout-total')
  };

  // ---------------------------------------------------------------- banner
  var SYMBOL = { ready: 'ℹ', listening: '🎤', processing: '⏳', ok: '✓', warn: '⚠', error: '✖' };
  function banner(kind, en, ta) {
    clearNode(ui.banner);
    ui.banner.className = 'status-banner ' + (kind === 'ready' || kind === 'processing' ? '' : kind);
    ui.banner.appendChild(el('span', { class: 'sym', 'aria-hidden': 'true', text: SYMBOL[kind] || 'ℹ' }));
    ui.banner.appendChild(bi(en, ta, 'div'));
  }

  // ---------------------------------------------------------------- voice input
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function selectedLang() { var r = $('input[name="lang"]:checked'); return r ? r.value : 'ta-IN'; }

  function setMic(on) {
    listening = on;
    ui.mic.setAttribute('aria-pressed', on ? 'true' : 'false');
    clearNode(ui.micLabel);
    ui.micLabel.appendChild(on ? bi('Tap to stop', 'நிறுத்த தட்டவும்') : bi('Tap to speak', 'பேச தட்டவும்'));
  }

  function startListening() {
    if (!SR) {
      banner('error', 'Voice input is not available in this browser. Please type your order in the box below.',
        'இந்த உலாவியில் குரல் வசதி இல்லை. கீழே உள்ள பெட்டியில் தட்டச்சு செய்யவும்.');
      ui.text.focus();
      return;
    }
    if (listening && recognition) { recognition.stop(); return; }
    var heard = '', failed = false;
    recognition = new SR();
    recognition.lang = selectedLang();
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = function () {
      setMic(true);
      banner('listening', 'Listening… please speak now.', 'கேட்கிறேன்… இப்போது சொல்லுங்கள்.');
    };
    recognition.onresult = function (e) {
      var finalT = '', interim = '';
      for (var i = 0; i < e.results.length; i++) {
        var t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalT += t + ' '; else interim += t;
      }
      heard = (finalT + interim).trim();
      ui.text.value = heard;
    };
    recognition.onerror = function (e) {
      failed = true;
      var code = e && e.error;
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        banner('error', 'The microphone is blocked. Please allow microphone access in your browser settings, or type your order below.',
          'மைக் தடுக்கப்பட்டுள்ளது. உலாவி அமைப்பில் மைக் அனுமதி கொடுக்கவும் அல்லது கீழே தட்டச்சு செய்யவும்.');
        ui.text.focus();
      } else if (code === 'no-speech') {
        banner('warn', 'I did not hear anything. Tap the microphone and try again.', 'எதுவும் கேட்கவில்லை. மைக்கை தட்டி மீண்டும் முயற்சிக்கவும்.');
      } else if (code === 'network') {
        banner('error', NET_ERR.en + ' You can also type your order below.', NET_ERR.ta);
        ui.text.focus();
      } else if (code === 'audio-capture') {
        banner('error', 'No microphone was found on this device. Please type your order below.', 'இந்த சாதனத்தில் மைக் இல்லை. கீழே தட்டச்சு செய்யவும்.');
        ui.text.focus();
      } else if (code === 'language-not-supported') {
        banner('error', 'This language is not supported for voice here. Try the other language button or type your order.',
          'இந்த மொழி இங்கு ஆதரிக்கப்படவில்லை. மற்ற மொழி பொத்தானை அழுத்தவும் அல்லது தட்டச்சு செய்யவும்.');
      } else if (code !== 'aborted') {
        banner('error', 'Something went wrong with voice input. Please try again or type your order.', 'குரல் பதிவில் பிழை. மீண்டும் முயற்சிக்கவும் அல்லது தட்டச்சு செய்யவும்.');
      }
    };
    recognition.onend = function () {
      setMic(false);
      if (heard) {
        banner('processing', 'Finding your items…', 'உங்கள் பொருட்களைத் தேடுகிறேன்…');
        findItems();
      } else if (!failed) {
        banner('warn', 'I did not catch that. Tap the microphone and try again, or type your order below.',
          'புரியவில்லை. மைக்கை தட்டி மீண்டும் சொல்லவும் அல்லது கீழே தட்டச்சு செய்யவும்.');
      }
    };
    try { recognition.start(); } catch (err) {
      setMic(false);
      banner('error', 'Could not start the microphone. Please try again.', 'மைக்கை தொடங்க முடியவில்லை. மீண்டும் முயற்சிக்கவும்.');
    }
  }

  // ---------------------------------------------------------------- parse + review
  var findBusy = false;
  function findItems() {
    var text = ui.text.value.trim();
    if (!text) {
      banner('warn', 'Please say or type your order first. Example: “2 Lux soap, half litre palm oil”.',
        'முதலில் உங்கள் ஆர்டரை சொல்லவும் அல்லது தட்டச்சு செய்யவும். எ.கா: “2 லக்ஸ் சோப்பு, அரை லிட்டர் பாமாயில்”.');
      ui.text.focus();
      return;
    }
    if (findBusy) return;
    findBusy = true; ui.find.disabled = true;
    banner('processing', 'Finding your items…', 'உங்கள் பொருட்களைத் தேடுகிறேன்…');
    api('/api/parse/', { text: text }).then(function (r) {
      findBusy = false; ui.find.disabled = false;
      if (!r.ok) { var e = errOf(r); banner('error', e.en, e.ta); return; }
      if (r.json.empty || !r.json.items.length) {
        banner('warn', 'I could not find any items in that. Please try again, for example “2 Lux soap”.',
          'எந்த பொருளும் கிடைக்கவில்லை. மீண்டும் முயற்சிக்கவும், எ.கா. “2 லக்ஸ் சோப்பு”.');
        return;
      }
      var n = 0;
      r.json.items.forEach(function (it) { it.uid = 'i' + Date.now() + '_' + (n++); });
      pending = pending.concat(r.json.items);
      renderReview();
      var allOk = r.json.items.every(function (i) { return i.status === 'ok'; });
      if (allOk) banner('ok', 'Items found. Please check them below and tap “Add to bill”.', 'பொருட்கள் கிடைத்தன. கீழே சரிபார்த்து “பில்லில் சேர்” அழுத்தவும்.');
      else banner('warn', 'Some items need your help. Please check the highlighted items below.', 'சில பொருட்களுக்கு உங்கள் உதவி தேவை. கீழே குறிக்கப்பட்டவற்றை சரிபார்க்கவும்.');
      ui.review.hidden = false;
      $('#review-title').focus();
      ui.review.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function dropPending(uid) {
    pending = pending.filter(function (p) { return p.uid !== uid; });
    renderReview();
  }

  function priceLine(p) {
    return el('div', { class: 'price' }, [money(p.price) + ' ', el('span', { class: 'text-muted', text: '/ ' + p.unit_en + ' (' + p.unit_ta + ')' })]);
  }
  function nameBlock(p) {
    var d = el('div', { class: 'pname' }, [el('span', { text: p.name_en })]);
    if (p.name_ta) d.appendChild(el('span', { class: 'sub ta', text: p.name_ta }));
    return d;
  }
  function addQty(qtyStr, step, dir) {
    var d = Math.max(0, (String(step).split('.')[1] || '').length, (String(qtyStr).split('.')[1] || '').length);
    var f = Math.pow(10, d);
    var v = Math.round(Number(qtyStr) * f) + dir * Math.round(Number(step) * f);
    return (v / f).toFixed(d).replace(/\.?0+$/, '') || '0';
  }

  // quantity input with +/- (used on review cards and bill rows)
  function qtyControl(p, startVal, onChange) {
    var input = el('input', { class: 'form-control', type: 'text', inputmode: 'decimal', value: startVal || '', 'aria-label': 'Quantity in ' + p.unit_en });
    var minus = el('button', { type: 'button', 'aria-label': 'Decrease quantity', text: '−' });
    var plus = el('button', { type: 'button', 'aria-label': 'Increase quantity', text: '+' });
    function sync() { minus.disabled = !input.value || Number(input.value) - Number(p.step) < Number(p.min_quantity) - 1e-9; }
    minus.addEventListener('click', function () { input.value = addQty(input.value || p.min_quantity, p.step, -1); sync(); if (onChange) onChange(input.value); });
    plus.addEventListener('click', function () { input.value = addQty(input.value || '0', p.step, +1); sync(); if (onChange) onChange(input.value); });
    input.addEventListener('input', sync);
    input.addEventListener('change', function () { if (onChange) onChange(input.value); });
    sync();
    var wrap = el('div', { class: 'qty' }, [minus, input, plus, el('span', { class: 'fw-bold', text: p.unit_en })]);
    wrap.input = input;
    return wrap;
  }

  function errBox() { return el('div', { class: 'field-error', role: 'alert' }); }
  function showErr(box, m) { clearNode(box); if (m) box.appendChild(biMsg(m)); }

  function renderReview() {
    clearNode(ui.reviewList);
    if (!pending.length) { ui.review.hidden = true; return; }
    ui.review.hidden = false;
    pending.forEach(function (item) { ui.reviewList.appendChild(reviewCard(item)); });
  }

  function reviewCard(item) {
    var cls = item.status === 'ok' ? 'ok' : (item.status === 'unavailable' || item.status === 'unknown_product' ? 'bad' : 'needs');
    var card = el('div', { class: 'item-card ' + cls });
    var heard = el('div', { class: 'heard' }, [bi('I heard: “' + item.raw + '”', null)]);
    card.appendChild(heard);
    var err = errBox();

    if (item.product && item.status !== 'ambiguous_product') card.appendChild(nameBlock(item.product));
    if (item.product && item.status !== 'ambiguous_product') card.appendChild(priceLine(item.product));

    if (item.status === 'ok') {
      card.appendChild(el('span', { class: 'tag ok', text: '✓ Ready to add' }));
      var q = qtyControl(item.product, item.quantity);
      card.appendChild(el('div', { class: 'my-2' }, [q]));
      card.appendChild(err);
      card.appendChild(actionRow([
        el('button', { type: 'button', class: 'btn btn-ng', onclick: function () { commitItem(item, q.input.value, err); } }, [bi('Add to bill', 'பில்லில் சேர்')]),
        removeBtn(item)
      ]));
    } else if (item.status === 'unavailable') {
      card.appendChild(el('span', { class: 'tag bad', text: '✖ Not available' }));
      card.appendChild(el('div', { class: 'my-2' }, [biMsg(item.message)]));
      card.appendChild(actionRow([removeBtn(item, 'OK, remove')]));
    } else if (item.status === 'ambiguous_product' || item.status === 'unknown_product') {
      card.appendChild(el('span', { class: 'tag ' + (item.status === 'unknown_product' ? 'bad' : 'needs'), text: item.status === 'unknown_product' ? '✖ Not found' : '? Please choose' }));
      card.appendChild(el('div', { class: 'my-2 fw-bold' }, [biMsg(item.message)]));
      (item.candidates || []).forEach(function (c) { card.appendChild(candidateButton(item, c)); });
      card.appendChild(searchBox(item));
      card.appendChild(actionRow([
        el('button', { type: 'button', class: 'btn btn-ng-outline', onclick: sayAgain }, [bi('Say it again', 'மீண்டும் சொல்')]),
        removeBtn(item)
      ]));
    } else if (item.status === 'conflict') {
      card.appendChild(el('span', { class: 'tag needs', text: '? Please choose one' }));
      card.appendChild(el('div', { class: 'my-2 fw-bold' }, [biMsg(item.message)]));
      (item.options || []).forEach(function (o) {
        card.appendChild(el('button', { type: 'button', class: 'choice-btn', onclick: function () { commitItem(item, o.quantity, err); } },
          [bi(o.label.en, o.label.ta)]));
      });
      card.appendChild(err);
      card.appendChild(customQty(item, err));
      card.appendChild(actionRow([
        el('button', { type: 'button', class: 'btn btn-ng-outline', onclick: sayAgain }, [bi('Say it again', 'மீண்டும் சொல்')]),
        removeBtn(item)
      ]));
    } else { // needs_quantity | needs_unit | unit_mismatch | invalid_rules
      card.appendChild(el('span', { class: 'tag needs', text: '? Please confirm quantity' }));
      card.appendChild(el('div', { class: 'my-2 fw-bold' }, [biMsg(item.message)]));
      var q2 = qtyControl(item.product, item.suggested_quantity || item.product.min_quantity);
      card.appendChild(el('div', { class: 'mb-2' }, [q2]));
      card.appendChild(err);
      card.appendChild(actionRow([
        el('button', { type: 'button', class: 'btn btn-ng', onclick: function () { commitItem(item, q2.input.value, err); } }, [bi('Confirm and add', 'உறுதி செய்து சேர்')]),
        removeBtn(item)
      ]));
    }
    return card;
  }

  function actionRow(buttons) { return el('div', { class: 'd-flex flex-wrap gap-2 mt-2' }, buttons); }
  function removeBtn(item, label) {
    return el('button', { type: 'button', class: 'btn btn-ng-outline', onclick: function () { dropPending(item.uid); } },
      [bi(label || 'Don’t add', label ? null : 'சேர்க்க வேண்டாம்')]);
  }
  function customQty(item, err) {
    var p = item.product;
    var q = qtyControl(p, '');
    return el('div', { class: 'mt-2' }, [el('div', { class: 'fw-bold mb-1' }, [bi('Or type another quantity', 'அல்லது வேறு அளவை உள்ளிடவும்')]), q,
      el('button', { type: 'button', class: 'btn btn-ng-outline btn-sm ms-2', onclick: function () { commitItem(item, q.input.value, err); } }, [bi('Add', 'சேர்')])]);
  }
  function sayAgain() {
    ui.text.value = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
    ui.mic.focus();
  }

  function candidateButton(item, c) {
    var label = el('span', {}, [el('span', { text: c.name_en }), c.name_ta ? el('span', { class: 'sub ta', text: c.name_ta }) : null,
      el('span', { class: 'sub', text: money(c.price) + ' / ' + c.unit_en })]);
    return el('button', { type: 'button', class: 'choice-btn', onclick: function () { chooseProduct(item, c.id); } }, [label]);
  }

  function chooseProduct(item, productId, typedQty) {
    api('/api/resolve/', { product_id: productId, raw: item.raw, product_text: item.product_text, raw_quantities: item.raw_quantities, quantity: typedQty })
      .then(function (r) {
        if (!r.ok) { var e = errOf(r); banner('error', e.en, e.ta); return; }
        var n = r.json.item; n.uid = item.uid;
        pending = pending.map(function (p) { return p.uid === item.uid ? n : p; });
        renderReview();
      });
  }

  function searchBox(item) {
    var out = el('div', { class: 'mt-2' });
    var input = el('input', { class: 'form-control', type: 'search', placeholder: 'Search product name / பொருள் பெயர்', 'aria-label': 'Search product name' });
    var timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      timer = setTimeout(function () {
        if (q.length < 2) { clearNode(out); return; }
        api('/api/products/search/?q=' + encodeURIComponent(q)).then(function (r) {
          clearNode(out);
          if (!r.ok) { return; }
          if (!r.json.products.length) { out.appendChild(el('div', { class: 'text-muted py-2' }, [bi('Nothing found. Please call the shop if you need this item.', 'எதுவும் கிடைக்கவில்லை. இந்த பொருள் வேண்டுமானால் கடையை அழைக்கவும்.')])); return; }
          r.json.products.forEach(function (c) { out.appendChild(candidateButton(item, c)); });
        });
      }, 300);
    });
    return el('div', { class: 'mt-3' }, [el('label', { class: 'form-label' }, [bi('Search by name', 'பெயரால் தேடு')]), input, out]);
  }

  // Add a reviewed item to the cart after the SERVER confirms the quantity is valid.
  function commitItem(item, qtyStr, errNode) {
    var qty = String(qtyStr || '').trim().replace(',', '.');
    if (!qty || isNaN(Number(qty)) || Number(qty) <= 0) {
      showErr(errNode, { en: 'Please enter a quantity greater than zero.', ta: 'பூஜ்ஜியத்தை விட அதிகமான அளவை உள்ளிடவும்.' });
      return;
    }
    var tentative = cart.map(function (l) { return { product_id: l.product_id, quantity: l.quantity }; });
    var found = false;
    tentative.forEach(function (l) {
      if (l.product_id === item.product.id) { l.quantity = sum(l.quantity, qty); found = true; }
    });
    if (!found) tentative.push({ product_id: item.product.id, quantity: qty });
    priceCart(tentative).then(function (r) {
      if (!r.ok) { var e = errOf(r); showErr(errNode, e); return; }
      var line = (r.json.lines || []).filter(function (l) { return l.product_id === item.product.id; })[0];
      if (line && line.errors.length) { showErr(errNode, line.errors[0]); return; }
      cart = tentative; store(CART_KEY, cart);
      pending = pending.filter(function (p) { return p.uid !== item.uid; });
      renderReview();
      applyBill(r.json);
      banner('ok', 'Added to your bill. You can say more items or continue.', 'பில்லில் சேர்க்கப்பட்டது. மேலும் பொருட்களை சொல்லலாம் அல்லது தொடரலாம்.');
      ui.billSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }
  function sum(a, b) { // exact decimal addition without float noise (3 dp max)
    return ((Math.round(Number(a) * 1000) + Math.round(Number(b) * 1000)) / 1000).toString();
  }

  // ---------------------------------------------------------------- bill
  function currentFulfilment() { var r = $('input[name="fulfilment"]:checked'); return r ? r.value : 'PICKUP'; }
  function priceCart(items) { return api('/api/bill/', { items: items, fulfilment: currentFulfilment() }); }

  function refreshBill() {
    if (!cart.length) { bill = null; renderBill(); return Promise.resolve(); }
    return priceCart(cart).then(function (r) {
      if (!r.ok) { var e = errOf(r); banner('error', e.en, e.ta); return; }
      applyBill(r.json);
    });
  }
  function applyBill(b) { bill = b; renderBill(); }

  function setLineQty(productId, qty) {
    cart.forEach(function (l) { if (l.product_id === productId) l.quantity = qty; });
    store(CART_KEY, cart);
    refreshBill();
  }
  function removeLine(productId) {
    cart = cart.filter(function (l) { return l.product_id !== productId; });
    store(CART_KEY, cart);
    refreshBill();
  }

  function renderBill() {
    clearNode(ui.billLines); clearNode(ui.billTotals);
    var has = bill && bill.lines && bill.lines.length;
    ui.billSection.hidden = !has;
    if (!has) { ui.checkout.hidden = true; return; }
    var blocked = !bill.ok;
    bill.lines.forEach(function (l) {
      var row = el('div', { class: 'bill-line' + (l.errors.length ? ' has-error' : '') });
      row.appendChild(el('div', { class: 'no', text: String(l.no) + '.' }));
      var nm = el('div', { class: 'name' }, [el('span', { text: l.name_en }), l.name_ta ? el('span', { class: 'sub ta', text: l.name_ta }) : null]);
      row.appendChild(nm);
      row.appendChild(el('div', { class: 'meta price' }, [money(l.unit_price) + ' per ' + l.unit_en + ' (' + l.unit_ta + ')']));
      var controls = el('div', { class: 'controls' });
      var q = qtyControl({ step: l.step, min_quantity: l.min_quantity, unit_en: l.unit_en }, l.quantity, function (v) {
        var clean = String(v).trim().replace(',', '.');
        if (clean && !isNaN(Number(clean)) && Number(clean) > 0) setLineQty(l.product_id, clean);
      });
      controls.appendChild(q);
      controls.appendChild(el('div', { class: 'line-total price', 'aria-label': 'Line total' }, [l.errors.length ? '—' : money(l.line_total)]));
      controls.appendChild(el('button', { type: 'button', class: 'btn btn-danger-ng btn-sm', 'aria-label': 'Remove ' + l.name_en, onclick: function () { removeLine(l.product_id); } }, [bi('Remove', 'நீக்கு')]));
      row.appendChild(controls);
      if (l.errors.length) {
        var eb = el('div', { class: 'field-error', role: 'alert', style: 'grid-column:1/-1' });
        l.errors.forEach(function (m) { eb.appendChild(biMsg(m, 'div')); });
        row.appendChild(eb);
      }
      ui.billLines.appendChild(row);
    });
    bill.errors.forEach(function (m) { ui.billLines.appendChild(el('div', { class: 'field-error' }, [biMsg(m)])); });

    ui.billTotals.appendChild(totalRow('Subtotal / மொத்தம்', money(bill.subtotal)));
    if (currentFulfilment() === 'DELIVERY') ui.billTotals.appendChild(totalRow('Delivery charge / டெலிவரி கட்டணம்', Number(bill.delivery_charge) === 0 ? 'Free / இலவசம்' : money(bill.delivery_charge)));
    ui.billTotals.appendChild(el('div', { class: 'row-t grand' }, [el('span', { text: 'Total to pay / செலுத்த வேண்டியது' }), el('span', { class: 'price', text: money(bill.total) })]));
    ui.checkoutBtn.disabled = blocked;
    if (ui.checkoutTotal) ui.checkoutTotal.textContent = money(bill.total);
  }
  function totalRow(label, value) { return el('div', { class: 'row-t' }, [el('span', { text: label }), el('span', { class: 'price', text: value })]); }

  // ---------------------------------------------------------------- checkout
  var PAY_LABELS = {
    UPI: ['Pay by UPI', 'UPI மூலம் செலுத்து', 'You will see the shop’s UPI details after you place the order.'],
    CASH_PICKUP: ['Cash when I collect', 'எடுக்கும்போது ரொக்கம்', 'Pay at the shop counter.'],
    COD: ['Cash on delivery', 'டெலிவரியில் ரொக்கம்', 'Pay the delivery person.']
  };
  function renderPayments() {
    clearNode(ui.payBox);
    var methods = (cfg.payment_methods[currentFulfilment()] || []);
    if (!methods.length) {
      ui.payBox.appendChild(el('div', { class: 'status-banner warn' }, [bi('No payment method is available for this option right now. Please call the shop to order.', 'இந்த முறைக்கு தற்போது கட்டண வசதி இல்லை. ஆர்டர் செய்ய கடையை அழைக்கவும்.')]));
      ui.submit.disabled = true;
      return;
    }
    ui.submit.disabled = false;
    methods.forEach(function (m, i) {
      var id = 'pay-' + m;
      var d = el('div', { class: 'choice-card mb-2' }, [
        el('input', { type: 'radio', name: 'payment_method', id: id, value: m, checked: i === 0, required: true }),
        el('label', { for: id }, [bi(PAY_LABELS[m][0], PAY_LABELS[m][1]), el('span', { class: 'sub', text: PAY_LABELS[m][2] })])
      ]);
      ui.payBox.appendChild(d);
    });
  }
  function onFulfilmentChange() {
    ui.address.hidden = currentFulfilment() !== 'DELIVERY';
    $('#delivery-address').required = currentFulfilment() === 'DELIVERY';
    renderPayments();
    refreshBill();
  }

  function formPayload() {
    var pay = $('input[name="payment_method"]:checked');
    return {
      items: cart.map(function (l) { return { product_id: l.product_id, quantity: l.quantity }; }),
      fulfilment: currentFulfilment(),
      payment_method: pay ? pay.value : '',
      customer_name: $('#customer-name').value,
      customer_phone: $('#customer-phone').value,
      delivery_address: $('#delivery-address').value,
      notes: $('#order-notes').value
    };
  }
  // Same key for an identical retry (double tap, flaky network); a new key if anything changed.
  function idempotencyKey(payload) {
    var sig = JSON.stringify(payload), saved = load(IDEM_KEY);
    if (saved && saved.sig === sig) return saved.key;
    var key = uuid();
    store(IDEM_KEY, { sig: sig, key: key });
    return key;
  }

  var submitting = false;
  function submitOrder(ev) {
    ev.preventDefault();
    if (submitting) return;
    clearNode(ui.formErrors);
    document.querySelectorAll('.field-error[data-for]').forEach(function (n) { n.remove(); });
    if (!ui.form.checkValidity()) { ui.form.reportValidity(); return; }
    var payload = formPayload();
    payload.idempotency_key = idempotencyKey(payload);
    submitting = true; ui.submit.disabled = true;
    var original = ui.submit.cloneNode(true);
    clearNode(ui.submit); ui.submit.appendChild(bi('Placing your order… please wait', 'ஆர்டர் செய்கிறோம்… காத்திருக்கவும்'));
    api('/api/order/', payload).then(function (r) {
      if (r.ok && r.json.url) {
        cart = []; store(CART_KEY, null); store(IDEM_KEY, null);
        window.location.href = r.json.url + '?placed=1';
        return;
      }
      submitting = false; ui.submit.disabled = false;
      clearNode(ui.submit); Array.prototype.slice.call(original.childNodes).forEach(function (n) { ui.submit.appendChild(n); });
      var e = r.json && r.json.error;
      if (e && e.fields) {
        Object.keys(e.fields).forEach(function (f) {
          var target = { customer_name: '#customer-name', customer_phone: '#customer-phone', delivery_address: '#delivery-address', payment_method: '#payment-options', fulfilment: '#fulfilment-group' }[f];
          var holder = target && $(target);
          var box = el('div', { class: 'field-error', role: 'alert', 'data-for': f }, [biMsg(e.fields[f])]);
          if (holder && holder.parentNode) holder.parentNode.insertBefore(box, holder.nextSibling); else ui.formErrors.appendChild(box);
        });
        var first = document.querySelector('.field-error[data-for]'); if (first) first.scrollIntoView({ block: 'center' });
      }
      (e && e.general ? e.general : []).forEach(function (m) { ui.formErrors.appendChild(el('div', { class: 'field-error', role: 'alert' }, [biMsg(m)])); });
      if (e && e.bill) { applyBill(e.bill); ui.formErrors.appendChild(el('div', { class: 'field-error' }, [bi('Please fix the items marked in red in your bill, then try again.', 'பில்லில் சிவப்பாக குறிக்கப்பட்ட பொருட்களை சரிசெய்து மீண்டும் முயற்சிக்கவும்.')])); ui.billSection.scrollIntoView(); }
      if (!e || (!e.fields && !e.general)) { var m = errOf(r); ui.formErrors.appendChild(el('div', { class: 'field-error', role: 'alert' }, [bi(m.en, m.ta)])); }
    });
  }

  // ---------------------------------------------------------------- wiring
  ui.mic.addEventListener('click', startListening);
  ui.find.addEventListener('click', findItems);
  ui.clear.addEventListener('click', function () { ui.text.value = ''; ui.text.focus(); banner('ready', 'Ready. Tap the microphone and say your items, or type them.', 'தயார். மைக்கை தட்டி பொருட்களை சொல்லுங்கள் அல்லது தட்டச்சு செய்யுங்கள்.'); });
  ui.text.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) findItems(); });
  ui.addMore.addEventListener('click', function () { ui.checkout.hidden = true; window.scrollTo({ top: 0, behavior: 'smooth' }); ui.mic.focus(); });
  ui.checkoutBtn.addEventListener('click', function () {
    if (!bill || !bill.ok) return;
    ui.checkout.hidden = false;
    onFulfilmentChange();
    $('#checkout-title').focus();
    ui.checkout.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.querySelectorAll('input[name="fulfilment"]').forEach(function (r) { r.addEventListener('change', onFulfilmentChange); });
  ui.form.addEventListener('submit', submitOrder);
  window.addEventListener('beforeunload', function () { if (recognition && listening) recognition.abort(); });

  // delivery option may be switched off by the owner
  if (!cfg.delivery_enabled) { var d = $('#fulfilment-delivery-wrap'); if (d) d.remove(); }

  if (!SR) {
    ui.mic.setAttribute('aria-describedby', 'status-banner');
    banner('warn', 'Voice input is not supported in this browser. You can type your order below (Chrome on Android works best for voice).',
      'இந்த உலாவியில் குரல் வசதி இல்லை. கீழே தட்டச்சு செய்யலாம் (குரலுக்கு Android Chrome சிறந்தது).');
  } else {
    banner('ready', 'Ready. Tap the microphone and say your items.', 'தயார். மைக்கை தட்டி உங்கள் பொருட்களை சொல்லுங்கள்.');
  }
  setMic(false);
  if (cart.length) refreshBill();
})();
