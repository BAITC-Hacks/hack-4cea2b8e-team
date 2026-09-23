// Сводка получает расчёты сервера; значения и gid не зашиты в страницу.
(() => {
  const root = document.querySelector('#network-summary');
  const content = root.querySelector('[data-summary-content]');
  const status = root.querySelector('[data-summary-status]');
  const refresh = root.querySelector('[data-summary-refresh]');
  const open = document.querySelector('[data-summary-open]');
  const details = root.querySelector('#summary-details');
  const expand = root.querySelector('[data-summary-expand]');
  const compact = root.querySelector('[data-summary-compact]');
  function setExpanded(value) {
    root.classList.toggle('is-expanded', value);
    details.hidden = !value;
    expand.setAttribute('aria-expanded', String(value));
    expand.textContent = value ? 'Свернуть ↓' : 'Подробнее ↑';
  }
  expand.addEventListener('click', () => setExpanded(details.hidden));
  function positionPanel() {
    // Та же ширина боковых карточек, в том числе при масштабе браузера.
    const left = document.querySelector('.panel-top, .panel-legend');
    const right = document.querySelector('.panel-detail, .panel-filters');
    const gap = 12;
    const leftInset = left ? left.getBoundingClientRect().right + gap : 332;
    const rightInset = right ? innerWidth - right.getBoundingClientRect().left + gap : 332;
    const narrow = innerWidth - leftInset - rightInset < 360;
    root.style.left = `${narrow ? 10 : leftInset}px`;
    root.style.right = `${narrow ? 10 : rightInset}px`;
  }
  window.addEventListener('resize', positionPanel);
  root.querySelector('[data-summary-close]').addEventListener('click', () => root.close());
  // Немодальная панель: граф и боковые карточки остаются доступны.
  open.addEventListener('click', () => {
    if (root.open) return;
    positionPanel();
    root.show();
    if (!content.childElementCount && !refresh.disabled) load();
  });
  root.addEventListener('close', () => open.focus());
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && root.open) { root.close(); event.preventDefault(); }
  });
  const labels = {
    coordinator: 'Координирующие узлы', consolidator: 'Точки консолидации',
    distributor: 'Распределители', transit: 'Транзитные узлы',
    terminal: 'Возможные конечные получатели', peripheral: 'Периферия / роль не определена'
  };
  const descriptions = {
    coordinator: 'Принимают от многих и отправляют многим.',
    consolidator: 'Несколько плательщиков; исходящие существенно меньше входящих.',
    distributor: 'Отправляют средства большому числу получателей.',
    transit: 'Видимые входящие и исходящие суммы сопоставимы.',
    terminal: 'Значимые поступления при небольшой сумме исходящих.',
    peripheral: 'Другие правила не сработали либо дальнейшие переводы не видны.'
  };
  const order = ['coordinator', 'consolidator', 'distributor', 'transit', 'terminal', 'peripheral'];
  const fmt = n => Number(n).toLocaleString('ru-RU', {maximumFractionDigits: 2});
  const money = n => `${fmt(n)} ₸`;
  const el = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  function nodeLink(gid) {
    const link = el('a', String(gid), 'summary-node');
    link.href = '#app';
    link.addEventListener('click', event => {
      event.preventDefault();
      root.close();
      window.dispatchEvent(new CustomEvent('summary-select-node', {detail: String(gid)}));
    });
    return link;
  }
  function block(title, note) {
    const section = el('section', undefined, 'summary-block');
    section.append(el('h2', title));
    if (note) section.append(el('p', note, 'summary-note'));
    return section;
  }
  function table(headers, rows) {
    const wrap = el('div', undefined, 'summary-table-wrap');
    const t = el('table');
    const head = el('thead'), hr = el('tr'), body = el('tbody');
    headers.forEach(h => { const th = el('th', h); th.scope = 'col'; hr.append(th); });
    head.append(hr);
    rows.forEach(cells => {
      const tr = el('tr');
      cells.forEach(value => {
        const td = el('td');
        if (value instanceof Node) td.append(value);
        else { td.textContent = value; if (/[₸%]|^\d[\d\s,]*$/.test(value)) td.className = 'summary-number'; }
        tr.append(td);
      });
      body.append(tr);
    });
    t.append(head, body); wrap.append(t);
    return wrap;
  }
  function person(gid, role) {
    const cell = el('div'); cell.append(nodeLink(gid), el('span', labels[role] || role, 'summary-role')); return cell;
  }
  function render(data) {
    const fragment = document.createDocumentFragment(), o = data.overview;
    compact.replaceChildren();
    const totals = el('div', undefined, 'summary-mini-totals');
    for (const [value, label] of [[fmt(o.n_nodes), 'участников'], [fmt(o.n_transactions), 'переводов'], [money(o.sum_kzt), 'сумма переводов']]) {
      const item = el('span'); item.append(el('strong', value), document.createTextNode(` ${label}`)); totals.append(item);
    }
    const chips = el('div', undefined, 'summary-role-chips');
    const short = {coordinator:'Координаторы',consolidator:'Консолидация',distributor:'Распределители',transit:'Транзит',terminal:'Конечные',peripheral:'Периферия'};
    const colors = {coordinator:'#AD51BF',consolidator:'#C98235',distributor:'#2580BB',transit:'#168568',terminal:'#657187',peripheral:'#596878'};
    for (const role of order) {
      const count = data.roles.find(r => r.role === role)?.count || 0;
      const chip = el('span', undefined, 'summary-role-chip');
      const dot = el('i'); dot.style.background = colors[role];
      chip.append(dot, document.createTextNode(`${short[role]} `), el('strong', fmt(count))); chips.append(chip);
    }
    compact.append(totals, chips);
    const period = o.period.from && o.period.to ? `${o.period.from} — ${o.period.to}` : 'нет дат переводов';
    fragment.append(el('p', `Период: ${period}. Вся выгрузка, независимо от выбранного узла и фильтров графа.`, 'summary-note'));
    const kpis = el('div', undefined, 'summary-kpis');
    [[fmt(o.n_nodes), 'участников'], [fmt(o.n_transactions), 'переводов'],
      [fmt(o.n_edges), 'связей отправитель → получатель'], [money(o.sum_kzt), 'сумма всех переводов']].forEach(([value, label]) => {
      const card = el('div', undefined, 'summary-kpi'); card.append(el('strong', value), el('span', label)); kpis.append(card);
    });
    fragment.append(kpis);
    fragment.append(el('p', 'Сумма переводов — не объём уникальных денег: одна сумма могла пройти несколько звеньев. Входящие и исходящие ниже показывают две стороны тех же переводов; складывать их нельзя.', 'summary-help'));
    const roles = block('Кто участвует в сети', 'Роли описывают наблюдаемое поведение. Количество и суммы рассчитаны по всем участникам.');
    const rows = order.map(role => data.roles.find(r => r.role === role)).filter(Boolean);
    roles.append(table(['Роль и поведение', 'Участников', 'Доля', 'Получили', 'Отправили'], rows.map(r => {
      const cell = el('div'); cell.append(el('strong', labels[r.role]), el('span', descriptions[r.role], 'summary-role'));
      return [cell, fmt(r.count), `${fmt(o.n_nodes ? r.count / o.n_nodes * 100 : 0)}%`, money(r.sum_in), money(r.sum_out)];
    })));
    fragment.append(roles);
    const transfers = block('Кто кому перевёл', '10 крупнейших связей по общей сумме за период. Одна строка может объединять несколько переводов. Нажмите gid, чтобы открыть участника на графе.');
    if (data.largest_transfers.length) transfers.append(table(['Отправитель', 'Получатель', 'Сумма', 'Переводов'], data.largest_transfers.map(e =>
      [person(e.src, e.sender_role), person(e.dst, e.receiver_role), money(e.sum_kzt), fmt(e.n_tx)])));
    else transfers.append(el('p', 'В выгрузке нет переводов.', 'summary-empty'));
    fragment.append(transfers);
    const examples = block('Что делали ключевые участники', 'По одному участнику с наибольшим приоритетом в каждой роли. Показаны до трёх крупнейших входящих и исходящих связей; это не полная выписка.');
    const cards = el('div', undefined, 'summary-examples');
    for (const role of order) {
      const n = data.examples.find(item => item.role === role);
      if (!n) continue;
      const card = el('article', undefined, 'summary-card');
      card.append(el('h3', labels[n.role]), nodeLink(n.gid),
        el('p', `Получил ${money(n.sum_in)} от ${fmt(n.n_payers)} плательщиков. Отправил ${money(n.sum_out)}; получателей: ${fmt(n.n_receivers)}.`),
        el('p', n.evidence));
      for (const [title, edges, key] of [['Кто переводил ему', n.incoming, 'src'], ['Кому он переводил', n.outgoing, 'dst']]) {
        card.append(el('h4', title));
        if (!edges.length) { card.append(el('p', 'В выборке таких переводов нет.', 'summary-note')); continue; }
        const list = el('ul');
        for (const e of edges) {
          const li = el('li'); li.append(nodeLink(e[key]), document.createTextNode(` — ${money(e.sum_kzt)} · переводов: ${fmt(e.n_tx)}`)); list.append(li);
        }
        card.append(list);
      }
      cards.append(card);
    }
    examples.append(cards); fragment.append(examples);
    const flows = block('Потоки между ролями', 'Крупнейшие направления по сумме. Это отдельные переводы между группами, а не доказанная последовательность движения одних и тех же денег.');
    if (data.role_flows.length) flows.append(table(['От роли', 'К роли', 'Сумма', 'Переводов'], data.role_flows.slice(0, 10).map(f =>
      [labels[f.sender_role], labels[f.receiver_role], money(f.sum_kzt), fmt(f.n_tx)])));
    else flows.append(el('p', 'Нет потоков для сравнения.', 'summary-empty'));
    fragment.append(flows);
    const limits = block('Как понимать эту сводку');
    limits.append(el('p', `У ${fmt(o.n_truncated)} участников исходящие за границей обхода не видны. Из ${fmt(o.n_seed)} исходных клиентов ${fmt(o.n_seed_without_outgoing)} не имеют видимых исходящих. Полностью изолированных участников: ${fmt(o.n_isolates)}.`));
    const list = el('ul');
    o.limitations.forEach(note => list.append(el('li', note))); limits.append(list);
    limits.append(el('p', '«Периферия» не означает отсутствие активности. Превышение исходящих над входящими не доказывает ошибку или происхождение средств: полный баланс неизвестен.'));
    fragment.append(limits);
    content.replaceChildren(fragment);
  }
  async function load() {
    refresh.disabled = true; status.className = 'summary-note'; status.textContent = 'Загружаем сводку…';
    try {
      const response = await fetch('/api/summary');
      if (!response.ok) throw new Error('HTTP ' + response.status);
      render(await response.json()); status.textContent = 'Сводка всей активной выгрузки. После загрузки нового набора в другой вкладке обновите страницу, чтобы обновить и граф.';
    } catch {
      if (!content.childElementCount) compact.textContent = 'Сводка недоступна. Нажмите «Обновить», чтобы повторить запрос.';
      status.className = 'summary-error';
      status.textContent = content.childElementCount
        ? 'Не удалось обновить данные. Ниже показана предыдущая сводка. Повторите запрос.'
        : 'Не удалось загрузить сводку. Проверьте запуск сервера и нажмите «Обновить».';
    } finally { refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  positionPanel();
  // Сразу видна компактная сводка в нижней свободной области графа.
  root.setAttribute('open', '');
  load();
})();
