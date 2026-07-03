let lastFiles = [];

async function doImport() {
  const f = document.getElementById('pdf').files[0];
  if (!f) return alert('请选择 PDF');
  const fd = new FormData(); fd.append('file', f);
  await fetch('/import', {method: 'POST', body: fd});
  pollProgress();
}

function pollProgress() {
  const p = document.getElementById('progress');
  const timer = setInterval(async () => {
    const s = await (await fetch('/progress')).json();
    if (s.state === 'parsing') p.textContent = `解析中 ${s.done}/${s.total} 页…`;
    else if (s.state === 'done') { p.innerHTML = `已入库 <b>${s.tickets}</b> 票 ${s.message||''}`; clearInterval(timer); }
    else if (s.state === 'error') { p.textContent = '出错: ' + s.message; clearInterval(timer); }
  }, 800);
}

async function doQuery() {
  const mode = document.querySelector('input[name=mode]:checked').value;
  const awbs = document.getElementById('awbs').value.split('\n').map(x=>x.trim()).filter(Boolean);
  const res = await (await fetch('/query', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({awbs, mode})})).json();
  const tb = document.querySelector('#table tbody'); tb.innerHTML = ''; lastFiles = [];
  for (const r of res) {
    const tr = document.createElement('tr');
    let op = '';
    if (r.image) {
      const fname = r.image.split('/').pop();
      op = `<a href="${r.image}" target="_blank">预览</a>
            <a href="${r.image}" download="${fname}">导出</a>`;
      lastFiles.push(fname);
    } else if (r.status === '打码不完整') {
      op = '<span class="warn">需人工处理</span>';
    }
    const cls = (r.status === '打码不完整') ? ' class="warn"' : '';
    tr.innerHTML = `<td>${r.awb}</td><td>${r.invoice_no||'-'}</td>
      <td>${r.page ?? '-'}</td><td${cls}>${r.status}</td><td>${op}</td>`;
    tb.appendChild(tr);
  }
}

async function exportZip() {
  if (!lastFiles.length) return alert('无可导出结果');
  const resp = await fetch('/export_zip', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({files: lastFiles})});
  const blob = await resp.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'exports.zip'; a.click();
}
