// 各面板共用顶部导航:固定顶栏 + 当前页高亮
// 用法:页面 <head> 内引入 <script src="/static/panel_nav.js" defer></script>
// 全高页面(100vh)请把根容器高度改为 calc(100vh - var(--panel-nav-offset))
(function () {
  var NAV_H = 44;
  var OFFSET = 60;
  var ITEMS = [
    { label: '装配面板', href: '/' },
    { label: '3D 查看器', href: '/viewer' },
    { label: '模板标注', href: '/editor' },
    { label: '零件导出', href: '/part-export' },
    { label: 'SW 选型对比', href: '/sw-compare' },
    { label: '系列模板看板', href: '/series' }
  ];

  function currentPath() {
    return location.pathname.replace(/\/+$/, '') || '/';
  }

  function build() {
    var style = document.createElement('style');
    style.textContent = [
      ':root{--panel-nav-h:' + NAV_H + 'px;--panel-nav-offset:' + OFFSET + 'px}',
      '.panel-nav{position:fixed;top:0;left:0;right:0;z-index:99999;display:flex;',
      'align-items:center;gap:4px;height:' + NAV_H + 'px;padding:0 14px;',
      'background:#1a2029;border-bottom:1px solid #2d3744;overflow-x:auto;',
      'font-family:-apple-system,"Microsoft YaHei",Segoe UI,Roboto,sans-serif;',
      'font-size:13px;box-sizing:border-box;white-space:nowrap}',
      '.panel-nav::-webkit-scrollbar{height:0}',
      '.panel-nav a{color:#9aa5b1;text-decoration:none;padding:6px 12px;border-radius:6px;',
      'transition:.15s;flex-shrink:0}',
      '.panel-nav a:hover{color:#e4e7eb;background:#222b36}',
      '.panel-nav a.active{color:#fff;background:#3b82f6}',
      'body{padding-top:var(--panel-nav-offset)!important}'
    ].join('');
    document.head.appendChild(style);

    var nav = document.createElement('nav');
    nav.className = 'panel-nav';
    var here = currentPath();
    for (var i = 0; i < ITEMS.length; i++) {
      var a = document.createElement('a');
      a.href = ITEMS[i].href;
      a.textContent = ITEMS[i].label;
      if (ITEMS[i].href === here) a.className = 'active';
      nav.appendChild(a);
    }
    document.body.insertBefore(nav, document.body.firstChild);
  }

  if (document.body) build();
  else document.addEventListener('DOMContentLoaded', build);
})();
