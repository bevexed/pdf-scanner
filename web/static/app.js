let lastFiles = [];

const isDesktop = () => !!window.__DESKTOP__ && window.pywebview && window.pywebview.api;

// 桌面版:应用内预览子窗口(不跳系统浏览器)
async function previewFile(name) {
  const r = await window.pywebview.api.preview(name);
  if (r && r.ok === false && r.error) alert('预览失败: ' + r.error);
}

// 桌面版:单张另存(原生保存对话框)
async function saveFile(name) {
  const r = await window.pywebview.api.save_one(name);
  if (r && r.ok === false && !r.cancelled) alert('导出失败: ' + (r.error || '未知错误'));
}

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
      if (isDesktop()) {
        const fn = fname.replace(/'/g, "\\'");
        op = `<a href="#" onclick="previewFile('${fn}');return false">预览</a>
              <a href="#" onclick="saveFile('${fn}');return false">导出</a>`;
      } else {
        op = `<a href="${r.image}" target="_blank">预览</a>
              <a href="${r.image}" download="${fname}">导出</a>`;
      }
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
  if (isDesktop()) {
    const r = await window.pywebview.api.save_zip(lastFiles);
    if (r && r.ok === false && !r.cancelled) alert('导出失败: ' + (r.error || '未知错误'));
    return;
  }
  const resp = await fetch('/export_zip', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({files: lastFiles})});
  const blob = await resp.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'exports.zip'; a.click();
}
