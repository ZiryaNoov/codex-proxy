"""Embedded web dashboard for codex-proxy v5.

Pure HTML + CSS + JS, no external dependencies. Served at /dashboard.
Auto-refreshes every 10 seconds. Shows stats, costs, providers, router status.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>codex-proxy dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242837;
    --border: #2e3347;
    --text: #e4e7ef;
    --text2: #8b90a5;
    --accent: #6c63ff;
    --accent2: #4ecdc4;
    --green: #00c853;
    --red: #ff5252;
    --orange: #ffab40;
    --yellow: #ffd740;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; padding: 24px;
  }
  .header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border);
  }
  .header h1 { font-size: 22px; font-weight: 600; }
  .header h1 span { color: var(--accent); }
  .header .meta { font-size: 13px; color: var(--text2); }
  .header .meta .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .header .meta .dot.ok { background: var(--green); }
  .header .meta .dot.err { background: var(--red); }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px;
  }
  .card .label { font-size: 12px; color: var(--text2); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
  .card .value { font-size: 28px; font-weight: 700; }
  .card .value.accent { color: var(--accent); }
  .card .value.green { color: var(--accent2); }
  .card .sub { font-size: 13px; color: var(--text2); margin-top: 4px; }

  .section { margin-bottom: 24px; }
  .section h2 { font-size: 16px; font-weight: 600; margin-bottom: 12px; color: var(--text2); }

  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
  th { color: var(--text2); font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }
  td { color: var(--text); }
  tr:hover td { background: var(--surface2); }

  .bar-container { width: 100%; height: 6px; background: var(--surface2); border-radius: 3px; overflow: hidden; }
  .bar { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
  .bar.green { background: var(--green); }
  .bar.orange { background: var(--orange); }
  .bar.red { background: var(--red); }

  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600;
  }
  .badge.green { background: rgba(0,200,83,0.15); color: var(--green); }
  .badge.red { background: rgba(255,82,82,0.15); color: var(--red); }
  .badge.orange { background: rgba(255,171,64,0.15); color: var(--orange); }
  .badge.blue { background: rgba(108,99,255,0.15); color: var(--accent); }

  .providers-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
  .provider-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .provider-card .name { font-weight: 600; font-size: 15px; margin-bottom: 4px; }
  .provider-card .url { font-size: 12px; color: var(--text2); margin-bottom: 8px; word-break: break-all; }
  .provider-card .models { display: flex; flex-wrap: wrap; gap: 4px; }
  .provider-card .model-tag {
    background: var(--surface2); border: 1px solid var(--border);
    padding: 2px 8px; border-radius: 4px; font-size: 11px; color: var(--text2);
  }

  .router-status { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
  .router-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .router-card .strategy { font-size: 11px; color: var(--accent); text-transform: uppercase; margin-bottom: 4px; }

  .refresh-info { text-align: center; font-size: 12px; color: var(--text2); margin-top: 16px; }
  .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--border);
    border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .empty { text-align: center; padding: 32px; color: var(--text2); font-size: 14px; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1><span>codex</span>-proxy</h1>
    <div class="meta">v<span id="version">—</span></div>
  </div>
  <div class="meta">
    <span class="dot ok" id="status-dot"></span>
    <span id="status-text">connecting…</span>
  </div>
</div>

<!-- Stats cards -->
<div class="grid" id="stats-cards">
  <div class="card"><div class="label">Total Requests</div><div class="value" id="stat-requests">—</div></div>
  <div class="card"><div class="label">Success Rate</div><div class="value green" id="stat-success">—</div></div>
  <div class="card"><div class="label">Uptime</div><div class="value" id="stat-uptime">—</div></div>
  <div class="card"><div class="label">Total Cost</div><div class="value accent" id="stat-cost">$0.00</div></div>
</div>

<!-- Cost by model -->
<div class="section">
  <h2>Cost by Model</h2>
  <div id="cost-table-wrap">
    <table><thead><tr><th>Model</th><th>Requests</th><th>Cost</th><th>Share</th></tr></thead>
    <tbody id="cost-tbody"><tr><td colspan="4" class="empty">Loading…</td></tr></tbody></table>
  </div>
</div>

<!-- Providers -->
<div class="section">
  <h2>Providers</h2>
  <div class="providers-grid" id="providers-grid"></div>
</div>

<!-- Router -->
<div class="section" id="router-section" style="display:none">
  <h2>Smart Router</h2>
  <div class="router-status" id="router-status"></div>
</div>

<div class="refresh-info">
  <span class="spinner" id="spinner"></span>
  Auto-refresh every 10s · Last update: <span id="last-update">—</span>
</div>

<script>
let refreshTimer = null;

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

function formatUptime(seconds) {
  if (seconds < 60) return seconds + 's';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
  return Math.floor(seconds / 86400) + 'd ' + Math.floor((seconds % 86400) / 3600) + 'h';
}

function formatCost(cost) {
  if (cost === 0 || cost === null) return '$0.00';
  if (cost < 0.01) return '$' + cost.toFixed(6);
  if (cost < 1) return '$' + cost.toFixed(4);
  return '$' + cost.toFixed(2);
}

function barColor(pct) {
  if (pct > 80) return 'red';
  if (pct > 50) return 'orange';
  return 'green';
}

async function refresh() {
  try {
    document.getElementById('spinner').style.display = 'inline-block';

    // Fetch all data in parallel
    const [stats, providers, usage] = await Promise.all([
      fetchJSON('/api/stats'),
      fetchJSON('/api/providers'),
      fetchJSON('/api/usage'),
    ]);

    // Version & status
    document.getElementById('version').textContent = stats.version || '?';
    document.getElementById('status-text').textContent = 'running';
    document.getElementById('status-dot').className = 'dot ok';

    // Stats cards
    document.getElementById('stat-requests').textContent = (stats.requests_total || 0).toLocaleString();
    const total = (stats.success_count || 0) + (stats.failure_count || 0);
    const rate = total > 0 ? ((stats.success_count || 0) / total * 100).toFixed(1) + '%' : '—';
    document.getElementById('stat-success').textContent = rate;
    document.getElementById('stat-uptime').textContent = formatUptime(stats.uptime_seconds || 0);

    // Total cost
    const costs = usage.cost_breakdown || [];
    const totalCost = costs.reduce((s, c) => s + (c.total_cost || 0), 0);
    document.getElementById('stat-cost').textContent = formatCost(totalCost);

    // Cost table
    const maxCost = Math.max(...costs.map(c => c.total_cost || 0), 0.001);
    const tbody = document.getElementById('cost-tbody');
    if (costs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">No cost data yet — make some requests!</td></tr>';
    } else {
      tbody.innerHTML = costs.map(c => {
        const pct = ((c.total_cost || 0) / maxCost * 100).toFixed(0);
        return `<tr>
          <td><strong>${esc(c.group_key || '?')}</strong></td>
          <td>${(c.request_count || 0).toLocaleString()}</td>
          <td>${formatCost(c.total_cost || 0)}</td>
          <td><div class="bar-container"><div class="bar ${barColor(pct)}" style="width:${pct}%"></div></div></td>
        </tr>`;
      }).join('');
    }

    // Providers
    const pgrid = document.getElementById('providers-grid');
    pgrid.innerHTML = (providers.providers || []).map(p => `
      <div class="provider-card">
        <div class="name">${esc(p.display_name || p.name)}</div>
        <div class="url">${esc(p.base_url || '')}</div>
        <div class="models">
          ${(p.models || []).map(m => '<span class="model-tag">' + esc(m) + '</span>').join('')}
        </div>
        ${p.has_key_rotation ? '<span class="badge blue" style="margin-top:8px">key rotation</span>' : ''}
      </div>
    `).join('');

    // Router
    const routerData = providers.router;
    const routerSection = document.getElementById('router-section');
    if (routerData) {
      routerSection.style.display = 'block';
      const stratLabel = {'fallback':'Try in order','cost':'Cheapest first','latency':'Fastest first','weighted':'Load balanced'}[routerData.strategy] || routerData.strategy;
      let html = `<div class="router-card">
        <div class="strategy">${esc(routerData.strategy)} — ${stratLabel}</div>
      </div>`;
      for (const [name, info] of Object.entries(routerData.providers || {})) {
        const avg = info.avg_latency_ms;
        const healthy = info.healthy;
        html += `<div class="router-card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <strong>${esc(name)}</strong>
            <span class="badge ${healthy ? 'green' : 'red'}">${healthy ? 'healthy' : 'unhealthy'}</span>
          </div>
          <div style="font-size:13px;color:var(--text2)">
            Avg latency: <span style="color:var(--text)">${avg !== null ? avg + 'ms' : 'no data'}</span><br>
            Error rate: <span style="color:var(--text)">${(info.error_rate * 100).toFixed(1)}%</span>
          </div>
        </div>`;
      }
      document.getElementById('router-status').innerHTML = html;
    } else {
      routerSection.style.display = 'none';
    }

    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

  } catch (e) {
    console.error('Refresh error:', e);
    document.getElementById('status-text').textContent = 'error';
    document.getElementById('status-dot').className = 'dot err';
  } finally {
    document.getElementById('spinner').style.display = 'none';
  }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// Initial load + auto-refresh
refresh();
refreshTimer = setInterval(refresh, 10000);
</script>
</body>
</html>"""
