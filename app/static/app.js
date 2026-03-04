async function loadVendors() {
  const vendors = await fetch('/api/vendors').then(r => r.json());
  const ul = document.getElementById('vendorList');
  ul.innerHTML = vendors.map(v => `<li>${v.name} - ${v.base_url} - ${v.username || '无用户名'}</li>`).join('');
}

document.getElementById('vendorForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  const res = await fetch('/api/vendors', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const out = await res.json();
  alert(out.message || '添加成功');
  e.target.reset();
  loadVendors();
});

document.getElementById('seedDemo').addEventListener('click', async () => {
  const out = await fetch('/api/seed-demo', { method: 'POST' }).then(r => r.json());
  alert(out.message);
  loadVendors();
});

document.getElementById('queryForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());

  const res = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });

  const resultBody = document.getElementById('resultBody');
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || '查询失败');
    return;
  }

  const out = await res.json();
  resultBody.innerHTML = out.results.map(r => `
    <tr>
      <td>${r.vendor}</td>
      <td>${r.price ?? '-'}</td>
      <td>${r.status}${r.error ? ` (${r.error})` : ''}</td>
      <td><a href="${r.query_url || '#'}" target="_blank">${r.query_url || '-'}</a></td>
    </tr>
  `).join('');
});

loadVendors();
