from __future__ import annotations


DASHBOARD_CSS = """:root {
  --bg: #0b1015;
  --panel: #121a22;
  --panel-2: #17212b;
  --border: #253442;
  --text: #edf4f8;
  --muted: #91a4b3;
  --accent: #66d9a6;
  --accent-2: #67b7ff;
  --warning: #f4c76b;
  --danger: #ff7f86;
  --good: #65d6a4;
  --shadow: 0 18px 50px rgb(0 0 0 / 20%);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}
button, select { font: inherit; }
button { cursor: pointer; }
button:focus-visible, select:focus-visible {
  outline: 3px solid rgb(103 183 255 / 45%);
  outline-offset: 2px;
}
.shell { min-height: 100vh; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .85rem clamp(1rem, 3vw, 2rem);
  border-bottom: 1px solid var(--border);
  background: rgb(11 16 21 / 94%);
  backdrop-filter: blur(14px);
}
.brand { display: flex; align-items: center; gap: .75rem; min-width: 0; }
.logo {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: linear-gradient(145deg, #20364a, #16382d);
  color: var(--accent);
  font-weight: 800;
}
.brand-copy { min-width: 0; }
.brand-title { font-weight: 750; letter-spacing: -.02em; }
.brand-subtitle { color: var(--muted); font-size: .78rem; margin-top: .08rem; }
.top-actions { display: flex; align-items: center; gap: .65rem; flex-wrap: wrap; }
.site-select {
  min-width: 170px;
  max-width: 260px;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: .58rem .72rem;
}
.icon-button, .primary-button, .soft-button {
  border-radius: 9px;
  border: 1px solid var(--border);
  padding: .58rem .78rem;
  color: var(--text);
  background: var(--panel);
}
.primary-button {
  color: #07120d;
  background: var(--accent);
  border-color: var(--accent);
  font-weight: 700;
}
.soft-button:hover, .icon-button:hover { background: var(--panel-2); }
.layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 0;
  max-width: 1600px;
  margin: 0 auto;
}
.sidebar {
  position: sticky;
  top: 65px;
  height: calc(100vh - 65px);
  padding: 1.25rem .85rem;
  border-right: 1px solid var(--border);
}
.nav-title {
  padding: .3rem .75rem .6rem;
  color: var(--muted);
  font-size: .7rem;
  font-weight: 800;
  letter-spacing: .11em;
  text-transform: uppercase;
}
.nav-button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: .7rem;
  border: 0;
  border-radius: 9px;
  margin: .15rem 0;
  padding: .72rem .78rem;
  color: var(--muted);
  background: transparent;
  text-align: left;
}
.nav-button:hover { color: var(--text); background: var(--panel); }
.nav-button.active {
  color: var(--text);
  background: #17252a;
  box-shadow: inset 3px 0 var(--accent);
}
.nav-icon { width: 1.25rem; text-align: center; color: var(--accent-2); }
.read-only {
  margin: 1.25rem .6rem;
  padding: .75rem;
  border: 1px solid #294b42;
  border-radius: 10px;
  background: #11221d;
  color: #b9ead7;
  font-size: .78rem;
  line-height: 1.4;
}
.content {
  min-width: 0;
  padding: 1.4rem clamp(1rem, 3vw, 2rem) 3rem;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.2rem;
}
.eyebrow {
  color: var(--accent);
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .11em;
  text-transform: uppercase;
}
h1 { margin: .25rem 0 .35rem; font-size: clamp(1.6rem, 3vw, 2.35rem); }
h2 { margin: 0; font-size: 1rem; letter-spacing: -.01em; }
p { margin: 0; }
.muted { color: var(--muted); }
.small { font-size: .78rem; }
.status-row { display: flex; gap: .45rem; flex-wrap: wrap; justify-content: flex-end; }
.pill {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: .38rem .62rem;
  background: var(--panel);
  color: var(--muted);
  font-size: .75rem;
  white-space: nowrap;
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.pill.good .dot { background: var(--good); box-shadow: 0 0 0 4px rgb(101 214 164 / 12%); }
.pill.warn .dot { background: var(--warning); }
.pill.bad .dot { background: var(--danger); }
.view { display: none; }
.view.active { display: block; }
.grid { display: grid; gap: .9rem; }
.metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.two-col { grid-template-columns: minmax(0, 1.65fr) minmax(280px, 1fr); }
.equal-col { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.card {
  min-width: 0;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .7rem;
  margin-bottom: .9rem;
}
.metric {
  position: relative;
  min-height: 118px;
  overflow: hidden;
}
.metric::after {
  content: "";
  position: absolute;
  right: -28px;
  bottom: -38px;
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: rgb(103 183 255 / 6%);
}
.metric-label { color: var(--muted); font-size: .76rem; }
.metric-value {
  margin-top: .42rem;
  font-size: clamp(1.35rem, 2.3vw, 2rem);
  font-weight: 760;
  letter-spacing: -.04em;
}
.metric-detail { margin-top: .38rem; color: var(--muted); font-size: .73rem; }
.good-text { color: var(--good); }
.warn-text { color: var(--warning); }
.bad-text { color: var(--danger); }
.chart-wrap {
  min-height: 250px;
  border-radius: 10px;
  background: #0d141a;
  border: 1px solid #1d2a34;
  padding: .55rem;
}
.chart-wrap svg { display: block; width: 100%; height: 235px; overflow: visible; }
.legend { display: flex; gap: .9rem; flex-wrap: wrap; color: var(--muted); font-size: .72rem; }
.legend-item { display: inline-flex; align-items: center; gap: .35rem; }
.legend-swatch { width: 16px; height: 3px; border-radius: 4px; background: var(--accent); }
.legend-swatch.blue { background: var(--accent-2); }
.legend-swatch.warn { background: var(--warning); }
.attention-list, .action-list, .learning-list { display: grid; gap: .55rem; }
.attention-item, .action-item, .learning-item {
  padding: .72rem .78rem;
  border: 1px solid #263540;
  border-radius: 10px;
  background: #101820;
}
.attention-top, .action-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .6rem;
  margin-bottom: .32rem;
}
.attention-title, .action-title { font-size: .84rem; font-weight: 700; }
.priority {
  border-radius: 999px;
  padding: .2rem .42rem;
  font-size: .65rem;
  font-weight: 800;
  text-transform: uppercase;
}
.priority.high { color: #ffd5d7; background: #451f24; }
.priority.medium { color: #ffe4ae; background: #493a1f; }
.priority.low { color: #beeada; background: #17382e; }
.section-spacer { height: .9rem; }
.kv-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .6rem; }
.kv {
  padding: .65rem;
  border: 1px solid #22313c;
  border-radius: 9px;
  background: #0f171e;
}
.kv-label { color: var(--muted); font-size: .68rem; }
.kv-value { margin-top: .18rem; font-size: .9rem; font-weight: 650; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .78rem; }
th, td { padding: .68rem .6rem; border-bottom: 1px solid #24323c; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 650; }
tr.selected { background: #142721; }
.empty {
  padding: 1.1rem;
  border: 1px dashed #31414e;
  border-radius: 10px;
  color: var(--muted);
  text-align: center;
  font-size: .8rem;
}
.progress {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #0c1318;
  border: 1px solid #24323c;
}
.progress > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}
.raw-controls { display: flex; gap: .55rem; flex-wrap: wrap; margin-bottom: .75rem; }
.raw-output {
  max-height: 540px;
  overflow: auto;
  padding: .9rem;
  border: 1px solid #23323d;
  border-radius: 10px;
  background: #0a0f13;
  color: #c8d7e1;
  font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}
.toast {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 20;
  max-width: 360px;
  padding: .75rem .9rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #18232c;
  box-shadow: var(--shadow);
  opacity: 0;
  transform: translateY(8px);
  pointer-events: none;
  transition: .2s ease;
}
.toast.show { opacity: 1; transform: translateY(0); }
.skeleton {
  border-radius: 7px;
  background: linear-gradient(90deg, #16212a, #21303b, #16212a);
  background-size: 200% 100%;
  animation: shimmer 1.2s linear infinite;
}
@keyframes shimmer { to { background-position: -200% 0; } }
@media (max-width: 1180px) {
  .metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .two-col { grid-template-columns: 1fr; }
}
@media (max-width: 820px) {
  .layout { display: block; }
  .sidebar {
    position: sticky;
    top: 65px;
    z-index: 8;
    height: auto;
    display: flex;
    gap: .35rem;
    overflow-x: auto;
    padding: .55rem .7rem;
    border-right: 0;
    border-bottom: 1px solid var(--border);
    background: rgb(11 16 21 / 96%);
  }
  .nav-title, .read-only { display: none; }
  .nav-button { width: auto; flex: 0 0 auto; margin: 0; padding: .6rem .75rem; }
  .nav-icon { display: none; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .equal-col { grid-template-columns: 1fr; }
  .topbar { align-items: flex-start; }
  .brand-subtitle { display: none; }
  .site-select { min-width: 130px; max-width: 180px; }
}
@media (max-width: 540px) {
  .topbar { padding: .7rem; }
  .top-actions { gap: .4rem; justify-content: flex-end; }
  .site-select { width: 145px; }
  .refresh-label { display: none; }
  .content { padding: 1rem .7rem 2rem; }
  .page-header { display: block; }
  .status-row { justify-content: flex-start; margin-top: .7rem; }
  .metrics { grid-template-columns: 1fr 1fr; gap: .6rem; }
  .metric { min-height: 108px; }
  .kv-grid { grid-template-columns: 1fr; }
}"""
