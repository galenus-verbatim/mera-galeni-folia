(function() {
  var dataEl = document.getElementById('sorted-data');
  var listEl = document.getElementById('list-titles');
  var selectEl = document.getElementById('selnav');
  if (!dataEl || !listEl || !selectEl) return;

  var DATA = JSON.parse(dataEl.textContent);

  function esc(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderItem(item, sortKey) {
    var li = document.createElement('li');
    li.className = 'list-row text-zinc-900';
    var a = document.createElement('a');
    a.href = '#' + (item.u || '');

    switch (sortKey) {
      case 'titLat':
        a.innerHTML = '<div class="font-bold">[' + esc(item.c) + ']</div><p class="italic list-col-wrap text-zinc-600">' + esc(item.lt || item.t) + '</p>';
        break;
      case 'fichtner':
        a.innerHTML = '<div class="font-bold">[' + esc(item.c) + ']</div><p class="italic list-col-wrap text-zinc-600">' + esc(item.lt) + '</p>';
        break;
      case 'kuehn':
        var pages = (item.kp || '').split('-')[0];
        a.innerHTML = '<div><span class="font-bold">' + esc(item.kv) + '.' + esc(pages) + '</span> [' + esc(item.c) + ' Ficht.]</div><p class="italic list-col-wrap text-zinc-600">' + esc(item.lt) + '</p>';
        break;
      case 'titLatAbbr':
        a.innerHTML = '<div class="italic">' + esc(item.la) + ' <span class="text-zinc-600">[' + esc(item.c) + ']</span></div>';
        break;
      case 'titGrc':
        a.innerHTML = '<div class="italic">' + esc(item.gt) + ' <span class="text-zinc-600">[' + esc(item.c) + ']</span></div>';
        break;
      case 'titFra':
        a.innerHTML = '<div class="italic">' + esc(item.ft) + ' <span class="text-zinc-600">[' + esc(item.c) + ']</span></div>';
        break;
      case 'titEng':
        a.innerHTML = '<div class="italic">' + esc(item.et) + ' <span class="text-zinc-600">[' + esc(item.c) + ']</span></div>';
        break;
      case 'titEngAbbr':
        a.innerHTML = '<div class="italic">' + esc(item.es) + ' <span class="text-zinc-600">[' + esc(item.c) + ']</span></div>';
        break;
    }

    li.appendChild(a);
    return li;
  }

  function renderList(sortKey) {
    listEl.innerHTML = '';
    var items = DATA[sortKey] || [];
    var frag = document.createDocumentFragment();
    for (var i = 0; i < items.length; i++) {
      frag.appendChild(renderItem(items[i], sortKey));
    }
    listEl.appendChild(frag);
  }

  renderList(selectEl.value);

  selectEl.addEventListener('change', function(e) {
    renderList(e.target.value);
  });
})();
