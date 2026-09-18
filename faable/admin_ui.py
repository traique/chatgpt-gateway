"""Self-contained admin console UI.

The interface intentionally has no build step or external assets so the gateway
can still be deployed as a small Python service. Visual language: soft liquid
 glass, bento layout, peach/orange/lemongrass accents, and large touch targets.
"""

ADMIN_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f7b46a">
<title>Gateway Garden · Admin</title>
<style>
:root{
  color-scheme:light;
  --ink:#2d241e;--muted:#796a5e;--line:rgba(101,73,49,.12);
  --peach:#ffb77d;--orange:#ff873d;--orange-deep:#e86d25;--cream:#fff8ef;
  --lemongrass:#e2ee9f;--leaf:#667b31;--danger:#b94f45;
  --glass:rgba(255,252,248,.76);--glass-solid:rgba(255,252,248,.96);
  --shadow:0 14px 40px rgba(103,66,36,.10),0 2px 8px rgba(103,66,36,.05);
  --radius-xl:26px;--radius-lg:20px;--radius-md:15px;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",Inter,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html{min-height:100%;background:#fff7ed;scroll-behavior:smooth}
body{margin:0;min-height:100vh;color:var(--ink);overflow-x:hidden;background:
  radial-gradient(circle at 8% -8%,rgba(255,173,105,.28),transparent 32rem),
  radial-gradient(circle at 92% 32%,rgba(226,238,159,.25),transparent 34rem),
  linear-gradient(160deg,#fff9f2 0,#fff5ea 50%,#faf8e8 100%)}
button,input,select{font:inherit}button{cursor:pointer}.hidden{display:none!important}
.shell{width:min(1320px,100%);margin:0 auto;padding:max(14px,env(safe-area-inset-top)) clamp(14px,2.3vw,30px) max(28px,env(safe-area-inset-bottom))}
.glass{background:linear-gradient(145deg,rgba(255,255,255,.86),var(--glass));border:1px solid rgba(255,255,255,.88);box-shadow:var(--shadow);backdrop-filter:blur(18px) saturate(135%);-webkit-backdrop-filter:blur(18px) saturate(135%)}
.topbar{position:sticky;top:10px;z-index:50;display:flex;align-items:center;gap:12px;padding:9px 11px 9px 13px;border-radius:20px;margin-bottom:12px}
.brand{display:flex;align-items:center;gap:10px;min-width:0}.brandmark{width:38px;height:38px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,#ffc08a,#ff8a41 58%,#dce991);box-shadow:inset 0 1px rgba(255,255,255,.75),0 7px 18px rgba(224,113,44,.18);font-size:18px}.brand h1{font-size:15px;letter-spacing:-.025em;margin:0}.brand small{display:block;color:var(--muted);font-size:10.5px;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.top-spacer{flex:1}.pill{display:inline-flex;align-items:center;gap:7px;min-height:31px;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.62);font-size:10.5px;font-weight:750;color:#62554c}.pulse{width:7px;height:7px;border-radius:50%;background:#8aa63e;box-shadow:0 0 0 4px rgba(138,166,62,.11)}
.icon-btn{width:36px;height:36px;border:0;border-radius:12px;background:rgba(255,255,255,.68);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
.mobile-dock{display:none}
.login-wrap{min-height:72vh;display:grid;place-items:center}.login-card{width:min(450px,100%);padding:28px;border-radius:var(--radius-xl)}
.eyebrow{display:flex;align-items:center;gap:7px;color:#a55f31;text-transform:uppercase;letter-spacing:.115em;font-size:9.5px;font-weight:850}.login-card h2,.hero h2{line-height:1.02;letter-spacing:-.05em;margin:10px 0 9px}.login-card h2{font-size:clamp(28px,4vw,42px)}
.muted{color:var(--muted);font-size:12px;line-height:1.48}.login-card .muted{font-size:13px}
.field{display:grid;gap:6px;margin-top:12px}.field label{font-size:10.5px;font-weight:780;color:#66564a;padding-left:2px}.control{width:100%;min-height:44px;border:1px solid rgba(106,75,48,.13);outline:none;border-radius:14px;padding:10px 12px;background:rgba(255,255,255,.76);color:var(--ink);transition:border-color .15s ease,box-shadow .15s ease;box-shadow:inset 0 1px rgba(255,255,255,.72)}.control:focus{border-color:rgba(255,132,56,.48);box-shadow:0 0 0 3px rgba(255,132,56,.09),inset 0 1px rgba(255,255,255,.8)}.control::placeholder{color:#a99a8e}select.control{appearance:none;background-image:linear-gradient(45deg,transparent 50%,#8d786a 50%),linear-gradient(135deg,#8d786a 50%,transparent 50%);background-position:calc(100% - 17px) 19px,calc(100% - 12px) 19px;background-size:5px 5px,5px 5px;background-repeat:no-repeat;padding-right:32px}
.btn{border:0;min-height:40px;padding:9px 14px;border-radius:13px;font-weight:780;font-size:12px;letter-spacing:-.01em;transition:transform .14s ease,box-shadow .14s ease,opacity .14s ease}.btn:hover{transform:translateY(-1px)}.btn:active{transform:translateY(0) scale(.985)}.btn.primary{background:linear-gradient(135deg,#ff9f5b,#ff7d36);color:white;box-shadow:0 8px 19px rgba(229,110,39,.19),inset 0 1px rgba(255,255,255,.28)}.btn.soft{background:rgba(255,255,255,.72);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}.btn.leaf{background:linear-gradient(135deg,#eef5bb,#dce991);color:#4c5b24;box-shadow:inset 0 0 0 1px rgba(95,119,41,.10)}.btn.danger{background:#fff0ed;color:var(--danger);box-shadow:inset 0 0 0 1px rgba(189,79,69,.11)}.btn.small{min-height:32px;padding:6px 10px;border-radius:10px;font-size:10.5px}.btn.wide{width:100%;margin-top:14px}
.status{margin-top:10px;border-radius:13px;padding:9px 11px;background:rgba(255,255,255,.52);border:1px solid rgba(105,72,42,.08);font-size:10.5px;line-height:1.45;white-space:pre-wrap;color:#6c594b}.status.success{background:rgba(236,245,190,.58);color:#52622a}.status.error{background:rgba(255,230,224,.76);color:#93483f}.status:empty{display:none}
.hero{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(260px,.75fr);gap:12px;margin-bottom:12px}.hero-main,.hero-side{border-radius:var(--radius-xl);padding:22px;position:relative;overflow:hidden}.hero-main{min-height:175px}.hero-main:after{content:"";position:absolute;right:-45px;bottom:-92px;width:230px;height:230px;border-radius:50%;background:radial-gradient(circle at 40% 40%,rgba(255,180,119,.58),rgba(255,135,62,.10) 52%,transparent 73%)}.hero-copy{position:relative;z-index:1;max-width:720px}.hero h2{font-size:clamp(32px,4vw,44px);max-width:650px}.hero-main .muted{max-width:700px}.hero-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px;position:relative;z-index:1}.hero-side{background:linear-gradient(145deg,rgba(242,248,203,.76),rgba(255,248,238,.77));display:grid;grid-template-rows:auto 1fr;gap:12px}.metric{display:flex;align-items:baseline;justify-content:space-between;gap:12px}.metric strong{font-size:34px;letter-spacing:-.055em}.metric span{font-size:10px;color:#68733b;font-weight:760}.route-now{align-self:end;padding:11px 12px;border-radius:15px;background:rgba(255,255,255,.54);border:1px solid rgba(107,126,50,.10)}.route-now small{display:block;color:#718041;font-size:9.5px;margin-bottom:3px}.route-now b{font-size:12.5px}.route-now .muted{font-size:10px;margin-top:2px}
.bento{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px}.tile{grid-column:span 4;border-radius:var(--radius-xl);padding:18px;min-width:0}.tile.span-8{grid-column:span 8}.tile.span-6{grid-column:span 6}.tile.span-12{grid-column:1/-1}.tile h3{font-size:16px;letter-spacing:-.03em;margin:0}.tile-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:13px}.tile-head p{margin:4px 0 0}.kicker{font-size:9px;font-weight:840;text-transform:uppercase;letter-spacing:.1em;color:#ad693b;margin-bottom:5px}
.provider-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}.provider-card{position:relative;text-align:left;border:1px solid rgba(111,76,45,.09);border-radius:15px;padding:11px 12px;background:rgba(255,255,255,.54);min-height:76px;transition:.15s ease;color:var(--ink)}.provider-card:hover{transform:translateY(-1px);background:rgba(255,255,255,.78)}.provider-card.active{background:linear-gradient(145deg,rgba(255,183,123,.34),rgba(255,255,255,.76));border-color:rgba(255,132,52,.25);box-shadow:0 7px 20px rgba(184,101,44,.08)}.provider-card .provider-name{font-size:11.5px;font-weight:820;display:block;padding-right:16px}.provider-card .provider-model{display:block;margin-top:5px;color:var(--muted);font-size:9.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.provider-card .mini-dot{position:absolute;right:11px;top:12px;width:7px;height:7px;border-radius:50%;background:#93ad43}.provider-card .mini-dot.off{background:#d0b49e}.provider-card .kind{display:inline-block;margin-top:6px;font-size:8px;letter-spacing:.075em;text-transform:uppercase;color:#9a7155;font-weight:820}.health-pill{display:inline-flex;align-items:center;gap:4px;margin-top:6px;margin-left:5px;padding:2px 6px;border-radius:999px;font-size:8px;font-weight:850;background:rgba(145,169,67,.12);color:#61752d}.health-pill.bad{background:rgba(166,77,63,.10);color:#995749}.health-pill.warn{background:rgba(205,148,61,.13);color:#936828}.secret-line{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}.secret-line.hidden-secret{letter-spacing:.08em}
.inline-form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end}.model-row{margin-top:12px}.model-row .control{min-height:42px}.model-row .btn{white-space:nowrap}
.custom-layout{display:grid;gap:12px}.custom-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:8px;align-content:start}.custom-item{padding:13px;border-radius:16px;background:rgba(255,255,255,.52);border:1px solid rgba(104,74,49,.09)}.custom-item-top{display:flex;gap:9px;align-items:flex-start}.custom-item-main{min-width:0;flex:1}.custom-item b{font-size:12px}.custom-item code{display:block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#8c6a52;font-size:9.5px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.custom-item .sub{font-size:10px;color:var(--muted);margin-top:5px}.action-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.editor{max-width:760px;border-radius:18px;padding:15px;background:linear-gradient(150deg,rgba(255,238,221,.62),rgba(255,255,255,.54));border:1px solid rgba(255,156,81,.13)}.editor-title{display:flex;justify-content:space-between;align-items:center;gap:12px}.editor-title b{font-size:12.5px}.editor .field{margin-top:10px}.helper{font-size:9.5px;color:#917a69;margin-top:4px;line-height:1.42}
.list{display:grid;gap:7px}.row{display:flex;align-items:center;gap:10px;padding:10px 11px;border-radius:14px;background:rgba(255,255,255,.49);border:1px solid rgba(105,72,42,.07)}.row-main{min-width:0;flex:1}.row-title{font-size:11.5px;font-weight:800}.row-sub{font-size:9.5px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row-actions{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}.state-dot{width:8px;height:8px;border-radius:50%;background:#91a943;box-shadow:0 0 0 3px rgba(145,169,67,.10);flex:none}.state-dot.off{background:#c5a997;box-shadow:none}.empty{border:1px dashed rgba(103,76,54,.15);border-radius:15px;padding:15px;text-align:center;color:#917e70;font-size:10.5px;background:rgba(255,255,255,.24)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:9px}.code-box{margin-top:10px;padding:13px;text-align:center;border-radius:15px;background:rgba(255,255,255,.62);font:800 22px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.13em;color:#8d532c}.section-divider{height:1px;background:var(--line);margin:13px 0}
details{border-radius:16px;background:rgba(255,255,255,.38);border:1px solid rgba(106,75,48,.08);overflow:hidden}summary{cursor:pointer;list-style:none;padding:11px 13px;font-size:11.5px;font-weight:820;display:flex;align-items:center;justify-content:space-between;gap:10px}summary::-webkit-details-marker{display:none}details[open]>summary{border-bottom:1px solid rgba(106,75,48,.07)}.details-body{padding:12px 13px 13px}
.client-create{margin-bottom:12px}.client-create>summary{background:rgba(237,245,185,.35);color:#536328}.client-create .two-col .field:first-child,.client-create .two-col .field:nth-child(2){margin-top:0}
.integration-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.integration{border-radius:16px;background:rgba(255,255,255,.46);border:1px solid rgba(104,74,49,.08);overflow:hidden}.integration>summary{padding:12px 13px}.integration-summary{min-width:0}.integration-summary h4{font-size:11.5px;margin:0}.integration-summary .muted{font-size:9.5px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.integration-chevron{font-size:13px;color:#907560;transition:transform .15s ease}.integration[open] .integration-chevron{transform:rotate(180deg)}.integration-body{padding:0 13px 13px}.integration .field{margin-top:9px}.integration .control{min-height:40px;border-radius:12px;font-size:11px}.integration .btn{width:100%;margin-top:8px}.integration-body details{margin-top:9px}.integration-body .status{margin-bottom:0}
.surface-list .row{padding:9px 10px}.surface-list .row-title{font-size:10.5px}.surface-list .row-sub{font-size:9px}
.toast-wrap{position:fixed;z-index:90;right:15px;bottom:15px;display:grid;gap:7px;width:min(340px,calc(100vw - 30px))}.toast{padding:11px 13px;border-radius:14px;background:rgba(54,42,34,.91);color:white;box-shadow:0 12px 32px rgba(61,40,23,.20);font-size:11px;animation:toastin .18s ease}.toast.good{background:rgba(77,94,36,.93)}.toast.bad{background:rgba(139,65,56,.94)}@keyframes toastin{from{transform:translateY(6px);opacity:0}to{transform:none;opacity:1}}
.footer{padding:20px 4px 4px;color:#8e7a6b;font-size:9.5px;text-align:center}
#routing-tile,#custom-provider-tile,#client-tile,#chatgpt-tile,#builtins-tile{scroll-margin-top:82px}
@media(max-width:980px){.hero{grid-template-columns:1fr}.hero-side{grid-template-columns:140px minmax(0,1fr);grid-template-rows:1fr;align-items:center}.route-now{align-self:auto}.tile,.tile.span-8,.tile.span-6{grid-column:span 6}.tile.span-12{grid-column:1/-1}.integration-grid{grid-template-columns:1fr 1fr}}
@media(max-width:720px){
  html{scroll-behavior:auto}body{background:linear-gradient(160deg,#fff8f0 0,#fff3e7 55%,#f8f8e6 100%)}
  .shell{padding-top:max(7px,env(safe-area-inset-top));padding-left:9px;padding-right:9px;padding-bottom:max(18px,env(safe-area-inset-bottom))}
  .glass{background:rgba(255,252,248,.965);backdrop-filter:none;-webkit-backdrop-filter:none;box-shadow:0 7px 22px rgba(105,67,35,.075),inset 0 0 0 1px rgba(255,255,255,.86)}
  .topbar{top:max(5px,env(safe-area-inset-top));min-height:52px;margin-bottom:7px;padding:7px 9px;border-radius:17px;gap:8px}.topbar .pill{display:none}.brand{gap:8px}.brandmark{width:36px;height:36px;border-radius:12px;font-size:17px}.brand h1{font-size:14px}.brand small{display:none}.icon-btn{width:36px;height:36px;border-radius:12px}
  .mobile-dock{position:sticky;top:calc(max(5px,env(safe-area-inset-top)) + 58px);z-index:45;display:grid;grid-template-columns:repeat(4,1fr);gap:3px;padding:4px;margin:0 0 8px;border-radius:15px;background:rgba(255,250,244,.96);border:1px solid rgba(255,255,255,.9);box-shadow:0 6px 18px rgba(88,56,30,.08)}
  .mobile-dock button{border:0;min-height:38px;padding:4px 2px;background:transparent;border-radius:11px;color:#77685d;font-size:9px;font-weight:800;display:flex;align-items:center;justify-content:center;gap:4px}.mobile-dock button span{font-size:13px}.mobile-dock button:active{background:rgba(255,178,112,.17);color:#8f512b}
  .hero{grid-template-columns:1fr;gap:8px;margin-bottom:8px}.hero-main,.hero-side{border-radius:20px}.hero-main{min-height:0;padding:17px}.hero-main:after{display:none}.hero h2{font-size:28px;margin:8px 0 8px}.hero-main .muted{font-size:11px;line-height:1.42}.hero-actions{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:13px}.hero-actions .btn{width:100%;padding-left:8px;padding-right:8px}
  .hero-side{padding:11px 13px;display:grid;grid-template-columns:100px minmax(0,1fr);grid-template-rows:1fr;align-items:center;gap:10px}.metric{display:grid;gap:2px}.metric strong{font-size:27px}.metric span{font-size:8.5px}.route-now{padding:9px 10px;border-radius:13px}.route-now b{font-size:11px}.route-now .muted{font-size:9px}
  .bento{gap:8px}.tile,.tile.span-8,.tile.span-6,.tile.span-12{grid-column:1/-1}.tile{padding:14px;border-radius:20px}.tile-head{margin-bottom:11px;gap:8px}.tile-head h3{font-size:15px}.tile-head p{font-size:10.5px;line-height:1.38}.kicker{font-size:8px;margin-bottom:4px}
  .control{min-height:48px;border-radius:13px;font-size:16px;padding:10px 12px}.field label{font-size:10.5px}.btn{min-height:44px;border-radius:13px;font-size:11.5px;touch-action:manipulation}.btn.small{min-height:36px;padding:7px 9px;font-size:10px}.btn.wide{margin-top:12px}
  .provider-grid{grid-template-columns:1fr;gap:6px}.provider-card{min-height:60px;padding:10px 11px;border-radius:14px}.provider-card .provider-name{font-size:11.5px}.provider-card .provider-model{font-size:9.5px;margin-top:4px;padding-right:74px}.provider-card .kind{position:absolute;right:10px;bottom:10px;margin:0;padding:3px 6px;border-radius:999px;background:rgba(255,242,230,.78)}.provider-card .mini-dot{right:11px;top:11px}
  .inline-form,.two-col,.integration-grid{grid-template-columns:1fr}.inline-form{gap:7px}.inline-form .btn{width:100%}.model-row{margin-top:10px}
  .custom-list{grid-template-columns:1fr;gap:7px}.custom-item{padding:11px;border-radius:14px}.custom-item b{font-size:11.5px}.action-row{display:grid;grid-template-columns:1.25fr .8fr .8fr;gap:5px}.action-row .btn{min-width:0;padding-left:5px;padding-right:5px}.editor{max-width:none;padding:13px;border-radius:16px}.editor .field{margin-top:9px}
  .row{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:start;padding:10px;border-radius:14px;gap:9px}.row-actions{grid-column:2;justify-content:flex-start}.row-sub{white-space:normal;overflow-wrap:anywhere;line-height:1.32}.list{gap:6px}
  .client-create{margin-bottom:10px}.client-create>summary{min-height:43px;padding:10px 12px}.client-create .two-col{gap:0}.client-create .field{margin-top:9px}
  .integration-grid{gap:6px}.integration{border-radius:14px}.integration>summary{padding:11px 12px}.integration-summary h4{font-size:11px}.integration-summary .muted{font-size:9px;max-width:250px}.integration-body{padding:0 12px 12px}.integration .control{font-size:16px;min-height:47px}.integration .btn{min-height:43px}
  .section-divider{margin:11px 0}.code-box{font-size:20px;padding:12px}.status{font-size:10px}.toast-wrap{right:9px;bottom:max(9px,env(safe-area-inset-bottom));width:calc(100vw - 18px)}.footer{display:none}
  #routing-tile,#custom-provider-tile,#client-tile,#chatgpt-tile,#builtins-tile{scroll-margin-top:112px}
}
@media(max-width:360px){.hero-actions{grid-template-columns:1fr}.action-row{grid-template-columns:1fr 1fr}.action-row .btn:first-child{grid-column:1/-1}.mobile-dock button{font-size:8.5px}.provider-card .provider-model{padding-right:66px}}
@media(hover:none){.btn:hover,.provider-card:hover{transform:none}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
</style>
</head>
<body>
<div class="toast-wrap" id="toasts"></div>
<main class="shell">
  <header class="topbar glass">
    <div class="brand"><div class="brandmark">✦</div><div><h1>Gateway Garden</h1><small>OpenAI-compatible routing console</small></div></div>
    <div class="top-spacer"></div>
    <div class="pill" id="session-pill"><span class="pulse"></span> Admin console</div>
    <button id="logout-button" class="icon-btn hidden" onclick="logout()" title="Đăng xuất">↗</button>
  </header>

  <section id="login-card" class="login-wrap">
    <div class="login-card glass">
      <div class="eyebrow">✦ Liquid gateway</div>
      <h2>Chào bạn quay lại.</h2>
      <p class="muted">Quản lý routing, provider động, client key và phiên đăng nhập từ một bảng điều khiển.</p>
      <div class="field"><label>Tên đăng nhập</label><input id="username" class="control" autocomplete="username" placeholder="admin"></div>
      <div class="field"><label>Mật khẩu</label><input id="password" class="control" type="password" autocomplete="current-password" placeholder="••••••••"></div>
      <button class="btn primary wide" onclick="login()">Mở bảng điều khiển</button>
      <div id="login-status" class="status hidden"></div>
    </div>
  </section>

  <section id="dashboard" class="hidden">
    <nav class="mobile-dock" aria-label="Điều hướng nhanh">
      <button type="button" onclick="jumpTo('routing-tile')"><span>⌁</span>Route</button>
      <button type="button" onclick="jumpTo('custom-provider-tile')"><span>＋</span>Provider</button>
      <button type="button" onclick="jumpTo('client-tile')"><span>◇</span>Keys</button>
      <button type="button" onclick="jumpTo('builtins-tile')"><span>•••</span>Kết nối</button>
    </nav>
    <section class="hero">
      <div class="hero-main glass">
        <div class="hero-copy">
          <div class="eyebrow">Gateway orchestration</div>
          <h2>Một gateway.<br>Nhiều upstream.</h2>
          <p class="muted">Thêm provider OpenAI-compatible chỉ bằng tên, Base URL, API key và model. Không cần tạo adapter Python riêng cho từng dịch vụ.</p>
          <div class="hero-actions">
            <button class="btn primary" onclick="focusNewProvider()">＋ Thêm provider</button>
            <button class="btn soft" onclick="refreshDashboard()">↻ Làm mới</button>
          </div>
        </div>
      </div>
      <div class="hero-side glass">
        <div class="metric"><span>Custom providers</span><strong id="metric-custom">0</strong></div>
        <div class="route-now"><small>Đang route qua</small><b id="hero-active-provider">Đang tải…</b><div class="muted" id="hero-active-model">Model mặc định</div></div>
      </div>
    </section>

    <section class="bento">
      <article class="tile span-8 glass" id="routing-tile">
        <div class="tile-head"><div><div class="kicker">01 · Routing</div><h3>Provider & model mặc định</h3><p class="muted">Dùng cho master key. Client key riêng có thể override routing.</p></div><button class="btn soft small" onclick="loadProviders()">↻</button></div>
        <div id="providers" class="provider-grid"><div class="empty">Đang tải provider…</div></div>
        <div class="model-row inline-form">
          <div><div class="field" style="margin-top:0"><label>Model override</label><input id="model-input" class="control" list="model-options" placeholder="Để trống = model mặc định của provider"></div><datalist id="model-options"></datalist></div>
          <button class="btn leaf" onclick="applyModel()">Áp dụng model</button>
        </div>
        <div id="provider-status" class="status"></div>
      </article>

      <article class="tile glass">
        <div class="tile-head"><div><div class="kicker">02 · Health</div><h3>Gateway surface</h3><p class="muted">Các endpoint client có thể dùng.</p></div></div>
        <div class="list surface-list">
          <div class="row"><span class="state-dot"></span><div class="row-main"><div class="row-title">Chat Completions</div><div class="row-sub">/v1/chat/completions</div></div></div>
          <div class="row"><span class="state-dot"></span><div class="row-main"><div class="row-title">Responses</div><div class="row-sub">/v1/responses</div></div></div>
          <div class="row"><span class="state-dot"></span><div class="row-main"><div class="row-title">Anthropic bridge</div><div class="row-sub">/v1/messages</div></div></div>
          <div class="row"><span class="state-dot"></span><div class="row-main"><div class="row-title">Model catalog</div><div class="row-sub">/v1/models</div></div></div>
        </div>
      </article>

      <article class="tile span-12 glass" id="custom-provider-tile">
        <div class="tile-head"><div><div class="kicker">03 · Dynamic registry</div><h3>Custom OpenAI-compatible providers</h3><p class="muted">Tạo bao nhiêu provider cũng được. API key được mã hóa trước khi lưu database.</p></div><button class="btn primary small" onclick="newCustomProvider()">＋ Provider mới</button></div>
        <div class="custom-layout">
          <div id="custom-providers" class="custom-list"><div class="empty">Chưa có custom provider.</div></div>
          <div class="editor hidden" id="custom-editor">
            <div class="editor-title"><b id="custom-editor-title">Thêm provider</b><button class="btn soft small" onclick="closeCustomProviderEditor()">Đóng</button></div>
            <input id="custom-id" type="hidden">
            <div class="field"><label>Tên hiển thị</label><input id="custom-name" class="control" placeholder="VD: DeepSeek Private"></div>
            <div class="field"><label>Base URL</label><input id="custom-base-url" class="control" placeholder="https://api.example.com/v1" autocomplete="off" spellcheck="false"><div class="helper">Gateway tự nối <code>/chat/completions</code> hoặc <code>/responses</code>.</div></div>
            <div class="field"><label>API key</label><input id="custom-api-key" class="control" type="password" placeholder="sk-…" autocomplete="new-password" spellcheck="false"><div id="custom-key-help" class="helper">Bắt buộc khi tạo mới.</div></div>
            <div class="field"><label>Model</label><input id="custom-model" class="control" placeholder="model-id" autocomplete="off" spellcheck="false"></div>
            <button class="btn primary wide" onclick="saveCustomProvider()" id="custom-save-button">Tạo provider</button>
            <div id="custom-status" class="status"></div>
          </div>
        </div>
      </article>

      <article class="tile span-6 glass" id="client-tile">
        <div class="tile-head"><div><div class="kicker">04 · Access</div><h3>Client keys</h3><p class="muted">Mỗi client có thể pin provider và model riêng.</p></div><button class="btn soft small" onclick="loadClients()">↻</button></div>
        <details class="client-create" id="client-create-details">
          <summary><span>＋ Tạo client key mới</span><span>⌄</span></summary>
          <div class="details-body">
            <div class="two-col">
              <div class="field"><label>Tên client</label><input id="client-label" class="control" placeholder="VD: Bot Zalo"></div>
              <div class="field"><label>API key</label><input id="client-key" class="control" placeholder="Để trống để tự sinh"></div>
              <div class="field"><label>Provider</label><select id="client-provider" class="control"></select></div>
              <div class="field"><label>Model</label><input id="client-model" class="control" placeholder="Để trống = mặc định"></div>
            </div>
            <button class="btn leaf wide" onclick="addClient()">Tạo client key</button>
            <div id="client-created" class="status"></div>
          </div>
        </details>
        <div id="clients" class="list"><div class="empty">Chưa tải client.</div></div>
      </article>

      <article class="tile span-6 glass" id="chatgpt-tile">
        <div class="tile-head"><div><div class="kicker">05 · ChatGPT</div><h3>Device login</h3><p class="muted">Lưu refresh token mã hóa; không cần dán access token thủ công.</p></div><button class="btn soft small" onclick="loadAccounts()">↻</button></div>
        <button class="btn primary" onclick="startLogin()">Đăng nhập ChatGPT</button>
        <div id="device-status" class="status"></div>
        <div id="code" class="code-box hidden"></div>
        <button id="open" class="btn soft wide hidden">Mở trang xác nhận</button>
        <div class="section-divider"></div>
        <div id="accounts" class="list"><div class="empty">Chưa tải tài khoản.</div></div>
      </article>

      <article class="tile span-12 glass" id="builtins-tile">
        <div class="tile-head"><div><div class="kicker">06 · Built-ins</div><h3>Provider tích hợp sẵn</h3><p class="muted">Các connector cũ vẫn giữ nguyên. Custom registry là lớp bổ sung, không thay thế chúng.</p></div></div>
        <div class="integration-grid">
          <details class="integration">
            <summary><div class="integration-summary"><h4>Legacy Generic</h4><div class="muted">OpenAI Compatible cũ · backward compatibility</div></div><span class="integration-chevron">⌄</span></summary>
            <div class="integration-body"><div class="field"><label>Base URL</label><input id="generic-base-url" class="control" placeholder="https://example.com/v1"></div><div class="field"><label>API key</label><input id="generic-key" class="control" type="password" placeholder="sk-…"></div><div class="field"><label>Model</label><input id="generic-model" class="control" placeholder="model-id"></div><button class="btn soft" onclick="saveGenericConfig()">Lưu cấu hình</button><div id="generic-status" class="status"></div></div>
          </details>
          <details class="integration">
            <summary><div class="integration-summary"><h4>OpenRouter</h4><div class="muted">Catalog model động</div></div><span class="integration-chevron">⌄</span></summary>
            <div class="integration-body"><div class="field"><label>API key</label><input id="openrouter-key" class="control" type="password" placeholder="sk-or-v1-…"></div><button class="btn soft" onclick="saveOpenRouterKey()">Lưu API key</button><div id="openrouter-status" class="status"></div></div>
          </details>
          <details class="integration">
            <summary><div class="integration-summary"><h4>TokenRouter</h4><div class="muted">OpenAI + Anthropic Messages</div></div><span class="integration-chevron">⌄</span></summary>
            <div class="integration-body"><div class="field"><label>API key</label><input id="tokenrouter-key" class="control" type="password" placeholder="tr_…"></div><button class="btn soft" onclick="saveTokenRouterKey()">Lưu API key</button><div id="tokenrouter-status" class="status"></div></div>
          </details>
          <details class="integration">
            <summary><div class="integration-summary"><h4>NVIDIA NIM</h4><div class="muted">Chat model catalog</div></div><span class="integration-chevron">⌄</span></summary>
            <div class="integration-body"><div class="field"><label>API key</label><input id="nim-key" class="control" type="password" placeholder="nvapi-…"></div><button class="btn soft" onclick="saveNimKey()">Lưu API key</button><div id="nim-status" class="status"></div></div>
          </details>
          <details class="integration">
            <summary><div class="integration-summary"><h4>Notion AI</h4><div class="muted">Browser login hoặc session thủ công</div></div><span class="integration-chevron">⌄</span></summary>
            <div class="integration-body"><button class="btn leaf" onclick="startNotionBrowserLogin()">Mở browser login</button><div id="notion-browser-status" class="status"></div><details><summary>Session thủ công <span>⌄</span></summary><div class="details-body"><div class="field" style="margin-top:0"><label>token_v2</label><input id="notion-token-v2" class="control" type="password" placeholder="token_v2"></div><div class="field"><label>notion_user_id</label><input id="notion-user-id" class="control" placeholder="user id"></div><div class="field"><label>notion_users</label><input id="notion-users" class="control" placeholder="notion_users"></div><button class="btn soft wide" onclick="notionLogin()">Lưu session</button><div id="notion-status" class="status"></div></div></details><div class="section-divider"></div><div id="notion-accounts" class="list"><div class="empty">Chưa tải tài khoản Notion.</div></div></div>
          </details>
        </div>
      </article>
    </section>
    <footer class="footer">Gateway Garden · lightweight liquid admin</footer>
  </section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ADMIN_API=location.pathname.startsWith('/admin')?'/admin-api':'/auth';
let providersData=null, customProviders=[], providerModelSeq=0, lazyObserver=null;
const lazyLoaded=new Set(), providerCatalogLoaded=new Set();

function toast(message,type='good'){
  const el=document.createElement('div');el.className='toast '+(type==='bad'?'bad':'good');el.textContent=message;$('toasts').appendChild(el);setTimeout(()=>el.remove(),4200)
}
function status(id,message,type=''){
  const el=$(id);if(!el)return;el.textContent=message||'';el.classList.remove('hidden','success','error');if(type)el.classList.add(type)
}
async function api(path,options={}){
  if(path.startsWith('/auth/'))path=ADMIN_API+path.slice(5);
  const r=await fetch(path,{...options,headers:{'content-type':'application/json',...(options.headers||{})}});
  const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(b.detail||b.error?.message||('HTTP '+r.status));return b
}
function showDashboard(){
  lazyLoaded.clear();$('login-card').classList.add('hidden');$('dashboard').classList.remove('hidden');$('logout-button').classList.remove('hidden');loadAll();setupLazySections()
}
function showLogin(){
  $('login-card').classList.remove('hidden');$('dashboard').classList.add('hidden');$('logout-button').classList.add('hidden');if(lazyObserver)lazyObserver.disconnect()
}
async function check(){try{const r=await api('/auth/me');r.authenticated?showDashboard():showLogin()}catch{showLogin()}}
async function login(){try{await api('/auth/login',{method:'POST',body:JSON.stringify({username:$('username').value.trim(),password:$('password').value})});$('password').value='';showDashboard()}catch(e){status('login-status',e.message,'error')}}
async function logout(){try{await api('/auth/logout',{method:'POST'})}finally{showLogin()}}
async function loadAll(){await loadProviders()}
async function refreshDashboard(){const tasks=[loadProviders()];if(lazyLoaded.has('client-tile'))tasks.push(loadClients());if(lazyLoaded.has('chatgpt-tile'))tasks.push(loadAccounts());if(lazyLoaded.has('builtins-tile'))tasks.push(loadBuiltins());await Promise.allSettled(tasks);toast('Đã làm mới phần đang dùng')}
function loadBuiltins(){return Promise.allSettled([loadNotionAccounts(),loadGenericStatus(),loadOpenRouterStatus(),loadTokenRouterStatus(),loadNimStatus()])}
function runLazy(id,loader){if(lazyLoaded.has(id))return;lazyLoaded.add(id);Promise.resolve(loader()).catch(()=>lazyLoaded.delete(id))}
function setupLazySections(){
  if(lazyObserver)lazyObserver.disconnect();
  const sections=[['client-tile',loadClients],['chatgpt-tile',loadAccounts],['builtins-tile',loadBuiltins]];
  if(!('IntersectionObserver' in window)){sections.forEach(([id,loader])=>runLazy(id,loader));return}
  lazyObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(!entry.isIntersecting)return;const pair=sections.find(([id])=>id===entry.target.id);if(pair){runLazy(pair[0],pair[1]);lazyObserver.unobserve(entry.target)}}),{rootMargin:'240px 0px'});
  sections.forEach(([id])=>{const el=$(id);if(el)lazyObserver.observe(el)})
}
function jumpTo(id){const el=$(id);if(!el)return;el.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});if(id==='client-tile')runLazy(id,loadClients);else if(id==='chatgpt-tile')runLazy(id,loadAccounts);else if(id==='builtins-tile')runLazy(id,loadBuiltins)}

function providerById(id){return providersData?.providers?.find(p=>p.id===id)}
function providerLabel(id){return providerById(id)?.label||id}
function updateClientProviderOptions(){
  const select=$('client-provider');if(!select||!providersData)return;const current=select.value;
  select.innerHTML=providersData.providers.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}${p.configured?'':' · chưa cấu hình'}</option>`).join('');
  if([...select.options].some(o=>o.value===current))select.value=current
}
function renderProviderModels(models){$('model-options').innerHTML=(models||[]).map(m=>`<option value="${esc(m)}"></option>`).join('')}
function renderProviders(r){
  $('providers').innerHTML=r.providers.map(p=>{const h=p.health||{status:p.configured?'ok':'unconfigured'};const hc=h.status==='ok'?'':(h.status==='degraded'?'warn':'bad');const label=h.status==='ok'?'OK':(h.status==='degraded'?'Cảnh báo':(h.status==='unconfigured'?'Chưa cấu hình':'Lỗi'));return `<button class="provider-card ${p.id===r.active_provider?'active':''}" onclick="selectProvider('${esc(p.id)}')" title="${esc(h.detail||'')}"><span class="mini-dot ${h.status==='ok'?'':'off'}"></span><span class="provider-name">${esc(p.label)}</span><span class="provider-model">${esc((p.models&&p.models[0])||'model chưa chọn')}</span><span class="kind">${p.kind==='custom'?'custom':'built-in'}</span><span class="health-pill ${hc}">${label}</span></button>`}).join('');
  const active=r.providers.find(p=>p.id===r.active_provider);renderProviderModels(active?.models||[]);$('model-input').value=r.active_model||'';
  $('hero-active-provider').textContent=active?.label||r.active_provider;$('hero-active-model').textContent=r.active_model?('Override · '+r.active_model):('Default · '+((active?.models||[])[0]||'provider default'));
  status('provider-status',`Đang dùng ${active?.label||r.active_provider}${active&&!active.configured?' · provider chưa cấu hình':''}`);updateClientProviderOptions()
}
async function loadProviders(){
  try{const [r,h]=await Promise.all([api('/auth/providers'),api('/auth/providers/health').catch(()=>({data:[]}))]);const healthMap=new Map((h.data||[]).map(x=>[x.id,x]));r.providers.forEach(p=>p.health=healthMap.get(p.id)||{status:p.configured?'ok':'unconfigured',detail:p.configured?'Configured':'Not configured'});providersData=r;customProviders=r.providers.filter(p=>p.kind==='custom').map(p=>({id:p.id,name:p.label,base_url:p.base_url||'',model:(p.models||[])[0]||'',configured:p.configured,health:p.health}));renderCustomProviders();renderProviders(r);$('metric-custom').textContent=customProviders.length}catch(e){$('providers').innerHTML=`<div class="empty">${esc(e.message)}</div>`}
}
async function loadProviderModels(provider,seq){try{const r=await api('/auth/providers/'+encodeURIComponent(provider)+'/models');if(seq!==providerModelSeq||!providersData||providersData.active_provider!==provider)return;const active=providerById(provider);if(active)active.models=Array.isArray(r.models)?r.models:[];renderProviderModels(active?.models||[]);renderProviders(providersData)}catch{providerCatalogLoaded.delete(provider)}}
async function ensureActiveModels(){if(!providersData)return;const provider=providersData.active_provider;if(providerCatalogLoaded.has(provider))return;providerCatalogLoaded.add(provider);const seq=++providerModelSeq;await loadProviderModels(provider,seq)}
async function selectProvider(id){try{await api('/auth/providers/select',{method:'POST',body:JSON.stringify({provider:id})});providerCatalogLoaded.delete(id);await loadProviders();toast('Đã chuyển provider sang '+providerLabel(id))}catch(e){status('provider-status',e.message,'error');toast(e.message,'bad')}}
async function applyModel(){if(!providersData)return;try{await api('/auth/providers/select',{method:'POST',body:JSON.stringify({provider:providersData.active_provider,model:$('model-input').value.trim()})});await loadProviders();toast('Đã cập nhật model mặc định')}catch(e){status('provider-status',e.message,'error')}}

function renderCustomProviders(){
  $('metric-custom').textContent=customProviders.length;
  $('custom-providers').innerHTML=customProviders.length?customProviders.map(p=>`<div class="custom-item"><div class="custom-item-top"><span class="state-dot"></span><div class="custom-item-main"><b>${esc(p.name)}</b><code>${esc(p.base_url)}</code><div class="sub">Model · ${esc(p.model)}</div></div></div><div class="action-row"><button class="btn leaf small" onclick="selectProvider('${esc(p.id)}')">Dùng provider</button><button class="btn soft small" onclick="editCustomProvider('${esc(p.id)}')">Sửa</button><button class="btn danger small" onclick="deleteCustomProvider('${esc(p.id)}')">Xóa</button></div></div>`).join(''):'<div class="empty">Chưa có custom provider. Tạo provider đầu tiên ở form bên cạnh.</div>'
}
async function loadCustomProviders(){try{const r=await api('/auth/custom-providers');customProviders=r.data||[];renderCustomProviders()}catch(e){$('custom-providers').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}
function newCustomProvider(openEditor=true){
  $('custom-id').value='';$('custom-name').value='';$('custom-base-url').value='';$('custom-api-key').value='';$('custom-model').value='';$('custom-editor-title').textContent='Thêm provider';$('custom-save-button').textContent='Tạo provider';$('custom-key-help').textContent='Bắt buộc khi tạo mới.';status('custom-status','');
  if(openEditor){$('custom-editor').classList.remove('hidden');requestAnimationFrame(()=>$('custom-name').focus({preventScroll:true}))}
}
function closeCustomProviderEditor(){$('custom-editor').classList.add('hidden');status('custom-status','')}
function editCustomProvider(id){
  const p=customProviders.find(x=>x.id===id);if(!p)return;$('custom-editor').classList.remove('hidden');$('custom-id').value=p.id;$('custom-name').value=p.name;$('custom-base-url').value=p.base_url;$('custom-api-key').value='';$('custom-model').value=p.model;$('custom-editor-title').textContent='Sửa '+p.name;$('custom-save-button').textContent='Lưu thay đổi';$('custom-key-help').textContent='Để trống nếu muốn giữ API key hiện tại.';$('custom-editor').scrollIntoView({behavior:'smooth',block:'center'})
}
function focusNewProvider(){$('custom-provider-tile').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});newCustomProvider(true)}
async function saveCustomProvider(){
  const id=$('custom-id').value;const payload={name:$('custom-name').value.trim(),base_url:$('custom-base-url').value.trim(),api_key:$('custom-api-key').value.trim(),model:$('custom-model').value.trim()};
  try{const r=await api(id?('/auth/custom-providers/'+encodeURIComponent(id)):'/auth/custom-providers',{method:'POST',body:JSON.stringify(payload)});customProviders=r.data||[];renderCustomProviders();newCustomProvider(false);closeCustomProviderEditor();await loadProviders();toast(id?'Đã cập nhật provider':'Đã tạo provider mới')}catch(e){status('custom-status',e.message,'error');toast(e.message,'bad')}
}
async function deleteCustomProvider(id){
  const p=customProviders.find(x=>x.id===id);if(!confirm(`Xóa provider “${p?.name||id}”?`))return;
  try{const r=await api('/auth/custom-providers/'+encodeURIComponent(id),{method:'DELETE'});customProviders=r.data||[];renderCustomProviders();if($('custom-id').value===id){newCustomProvider(false);closeCustomProviderEditor();}await loadProviders();toast('Đã xóa provider')}catch(e){toast(e.message,'bad');status('custom-status',e.message,'error')}
}

async function loadClients(){
  try{const r=await api('/auth/clients');$('clients').innerHTML=r.data.length?r.data.map(c=>`<div class="row"><span class="state-dot ${c.status==='active'?'':'off'}"></span><div class="row-main"><div class="row-title">${esc(c.label)}</div><div class="row-sub"><span id="key-${c.id}" class="secret-line hidden-secret" data-masked="${esc(c.key_masked)}">${esc(c.key_masked)}</span> · ${esc(providerLabel(c.provider))}${c.model?' · '+esc(c.model):''}</div></div><div class="row-actions"><button class="btn soft small" onclick="toggleClientKey('${c.id}',this)">Xem</button><button class="btn leaf small" onclick="copyClientKey('${c.id}')">Copy</button>${c.status==='active'?`<button class="btn soft small" onclick="clientAction('${c.id}','disabled')">Tắt</button>`:`<button class="btn leaf small" onclick="clientAction('${c.id}','active')">Bật</button>`}<button class="btn danger small" onclick="clientAction('${c.id}','delete')">Xóa</button></div></div>`).join(''):'<div class="empty">Chưa có client key.</div>'}catch(e){$('clients').innerHTML=`<div class="empty">${esc(e.message)}</div>`}
}
async function copyText(value){try{await navigator.clipboard.writeText(value)}catch{const ta=document.createElement('textarea');ta.value=value;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}}
async function fetchClientKey(id){const r=await api('/auth/clients/'+encodeURIComponent(id)+'/secret',{cache:'no-store'});return r.key}
async function toggleClientKey(id,button){const el=$('key-'+id);if(!el)return;if(!el.classList.contains('hidden-secret')){el.textContent=el.dataset.masked||'••••••••••••••••';el.classList.add('hidden-secret');button.textContent='Xem';return}try{button.disabled=true;const key=await fetchClientKey(id);el.textContent=key;el.classList.remove('hidden-secret');button.textContent='Ẩn'}catch(e){toast(e.message,'bad')}finally{button.disabled=false}}
async function copyClientKey(id){try{const key=await fetchClientKey(id);await copyText(key);toast('Đã copy client key')}catch(e){toast(e.message,'bad')}}
async function clientAction(id,action){try{if(action==='delete'){if(!confirm('Xóa client key này?'))return;await api('/auth/clients/'+id,{method:'DELETE'})}else await api('/auth/clients/'+id,{method:'POST',body:JSON.stringify({status:action})});await loadClients()}catch(e){status('client-created',e.message,'error')}}
async function addClient(){try{const r=await api('/auth/clients',{method:'POST',body:JSON.stringify({label:$('client-label').value.trim(),key:$('client-key').value.trim(),provider:$('client-provider').value,model:$('client-model').value.trim()})});$('client-key').value='';$('client-model').value='';$('client-label').value='';status('client-created','API key mới: '+r.key,'success');await loadClients();toast('Đã tạo client key')}catch(e){status('client-created',e.message,'error')}}

async function startLogin(){try{const s=await api('/auth/device/start',{method:'POST'});$('code').textContent=s.user_code;$('code').classList.remove('hidden');$('open').classList.remove('hidden');$('open').onclick=()=>window.open(s.verification_url,'_blank','noopener');status('device-status','Mở trang xác nhận và nhập mã. Gateway đang chờ ChatGPT xác nhận…');pollChatGPT(s.login_id,s.interval_seconds)}catch(e){status('device-status',e.message,'error')}}
async function pollChatGPT(id,interval){interval=Math.max(Number(interval)||5,5);for(;;){await pollPause(interval);try{const s=await api('/auth/device/poll',{method:'POST',body:JSON.stringify({login_id:id,label:'ChatGPT'})});if(s.status==='completed'){status('device-status','Đăng nhập ChatGPT thành công.','success');$('code').classList.add('hidden');$('open').classList.add('hidden');await loadAccounts();return}if(s.status==='expired'||s.status==='failed'){status('device-status','Phiên đăng nhập: '+s.status,'error');return}status('device-status','Đang chờ xác nhận đăng nhập…')}catch(e){status('device-status',e.message,'error');return}}}
function accountHealthLabel(a){return {healthy:'Khỏe',expiring:'Sắp hết hạn',expired:'Hết hạn',error:'Lỗi',disabled:'Đã tắt'}[a.health]||a.health}
function formatExpiry(ms){try{return new Date(ms).toLocaleString('vi-VN')}catch{return ''}}
async function accountAction(id,action){try{if(action==='delete'){if(!confirm('Xóa hẳn tài khoản ChatGPT này?'))return;await api('/auth/accounts/'+id,{method:'DELETE'})}else await api('/auth/accounts/'+id,{method:'POST',body:JSON.stringify({status:action})});await loadAccounts();await loadProviders()}catch(e){status('device-status',e.message,'error');toast(e.message,'bad')}}
async function loadAccounts(){try{const r=await api('/auth/accounts');$('accounts').innerHTML=r.data.length?r.data.map(a=>{const bad=['expired','error','disabled'].includes(a.health);const warn=a.health==='expiring';return `<div class="row"><span class="state-dot ${bad?'off':''}"></span><div class="row-main"><div class="row-title">${esc(a.label)} <span class="health-pill ${bad?'bad':(warn?'warn':'')}">${esc(accountHealthLabel(a))}</span></div><div class="row-sub">Hết hạn: ${esc(formatExpiry(a.expires_at))}${a.last_error?' · '+esc(a.last_error):''}</div></div><div class="row-actions">${a.status==='active'&&a.health!=='expired'?`<button class="btn soft small" onclick="accountAction('${a.id}','disabled')">Tắt</button>`:''}${a.status!=='active'?`<button class="btn leaf small" onclick="accountAction('${a.id}','active')">Bật</button>`:''}${a.health==='expired'||a.status!=='active'?`<button class="btn danger small" onclick="accountAction('${a.id}','delete')">Xóa</button>`:''}</div></div>`}).join(''):'<div class="empty">Chưa có tài khoản ChatGPT.</div>'}catch(e){$('accounts').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}

async function saveGenericConfig(){try{const baseUrl=$('generic-base-url').value.trim(),apiKey=$('generic-key').value.trim(),model=$('generic-model').value.trim();await api('/auth/generic/config',{method:'POST',body:JSON.stringify({base_url:baseUrl,api_key:apiKey,model})});$('generic-key').value='';status('generic-status','Đã lưu · '+baseUrl+' · '+model,'success');await loadProviders()}catch(e){status('generic-status',e.message,'error')}}
async function loadGenericStatus(){try{const r=await api('/auth/generic/config');if(r.base_url)$('generic-base-url').value=r.base_url;if(r.model)$('generic-model').value=r.model;if(r.configured)status('generic-status','Đã cấu hình · '+r.model,'success')}catch{}}
async function saveOpenRouterKey(){try{await api('/auth/openrouter/key',{method:'POST',body:JSON.stringify({api_key:$('openrouter-key').value.trim()})});$('openrouter-key').value='';status('openrouter-status','Đã lưu API key.','success');await loadProviders()}catch(e){status('openrouter-status',e.message,'error')}}
async function loadOpenRouterStatus(){try{const r=await api('/auth/openrouter/key');if(r.configured)status('openrouter-status','Đã cấu hình.','success')}catch{}}
async function saveTokenRouterKey(){try{await api('/auth/tokenrouter/key',{method:'POST',body:JSON.stringify({api_key:$('tokenrouter-key').value.trim()})});$('tokenrouter-key').value='';status('tokenrouter-status','Đã lưu API key.','success');await loadProviders()}catch(e){status('tokenrouter-status',e.message,'error')}}
async function loadTokenRouterStatus(){try{const r=await api('/auth/tokenrouter/key');if(r.configured)status('tokenrouter-status','Đã cấu hình · '+r.base_url,'success')}catch{}}
async function saveNimKey(){try{await api('/auth/nim/key',{method:'POST',body:JSON.stringify({api_key:$('nim-key').value.trim()})});$('nim-key').value='';status('nim-status','Đã lưu API key.','success');await loadProviders()}catch(e){status('nim-status',e.message,'error')}}
async function loadNimStatus(){try{const r=await api('/auth/nim/key');if(r.configured)status('nim-status','Đã cấu hình.','success')}catch{}}

async function startNotionBrowserLogin(){try{const s=await api('/auth/notion/browser/start',{method:'POST',body:JSON.stringify({})});status('notion-browser-status','Chrome/Edge đã được mở trên máy chạy gateway. Đang chờ đăng nhập…');pollNotionBrowserLogin(s.login_id,s.interval_seconds||2)}catch(e){status('notion-browser-status',e.message,'error')}}
async function pollNotionBrowserLogin(id,interval){interval=Math.max(Number(interval)||3,3);for(;;){await pollPause(interval);try{const s=await api('/auth/notion/browser/poll',{method:'POST',body:JSON.stringify({login_id:id})});if(s.status==='completed'){status('notion-browser-status','Đăng nhập Notion thành công.','success');await loadNotionAccounts();await loadProviders();return}if(s.status==='failed'||s.status==='expired'){status('notion-browser-status',s.error||('Phiên đăng nhập: '+s.status),'error');return}status('notion-browser-status','Đang chờ bạn đăng nhập Notion…')}catch(e){status('notion-browser-status',e.message,'error');return}}}
async function notionLogin(){const token=$('notion-token-v2').value.trim(),userId=$('notion-user-id').value.trim(),notionUsers=$('notion-users').value.trim();if(!token){status('notion-status','Hãy nhập token_v2.','error');return}try{await api('/auth/notion/login',{method:'POST',body:JSON.stringify({token_v2:token,notion_user_id:userId,notion_users:notionUsers})});$('notion-token-v2').value='';$('notion-user-id').value='';$('notion-users').value='';status('notion-status','Đã lưu Notion session.','success');await loadNotionAccounts();await loadProviders()}catch(e){status('notion-status',e.message,'error')}}
function notionHealthLabel(a){return {healthy:'Khỏe',error:'Lỗi',disabled:'Đã tắt'}[a.health]||a.health}
async function loadNotionAccounts(){try{const r=await api('/auth/notion/accounts');$('notion-accounts').innerHTML=r.data.length?r.data.map(a=>{const bad=['error','disabled'].includes(a.health);return `<div class="row"><span class="state-dot ${bad?'off':''}"></span><div class="row-main"><div class="row-title">${esc(a.label)} <span class="health-pill ${bad?'bad':''}">${esc(notionHealthLabel(a))}</span></div><div class="row-sub">${esc(a.space_name||a.space_id)}${a.last_error?' · '+esc(a.last_error):''}</div></div><div class="row-actions"><button class="btn soft small" onclick="notionAccountAction('${a.id}','health')">Kiểm tra</button>${a.status==='active'?`<button class="btn soft small" onclick="notionAccountAction('${a.id}','disabled')">Tắt</button>`:`<button class="btn leaf small" onclick="notionAccountAction('${a.id}','active')">Bật</button>`}${a.status!=='active'||a.health==='error'?`<button class="btn danger small" onclick="notionAccountAction('${a.id}','delete')">Xóa</button>`:''}</div></div>`}).join(''):'<div class="empty">Chưa có tài khoản Notion.</div>'}catch(e){$('notion-accounts').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}
async function notionAccountAction(id,action){try{if(action==='delete'){if(!confirm('Xóa hẳn tài khoản Notion này?'))return;await api('/auth/notion/accounts/'+id,{method:'DELETE'})}else if(action==='health'){const r=await api('/auth/notion/accounts/'+id+'/health',{method:'POST'});toast(r.health?.status==='ok'?'Notion account đang khỏe':(r.health?.detail||'Notion account có lỗi'),r.health?.status==='ok'?'good':'bad')}else await api('/auth/notion/accounts/'+id,{method:'POST',body:JSON.stringify({status:action})});await loadNotionAccounts();await loadProviders()}catch(e){status('notion-status',e.message,'error');toast(e.message,'bad')}}

async function pollPause(seconds){await new Promise(r=>setTimeout(r,seconds*1000));if(!document.hidden)return;await new Promise(resolve=>{const onVisible=()=>{if(document.hidden)return;document.removeEventListener('visibilitychange',onVisible);resolve()};document.addEventListener('visibilitychange',onVisible)})}
$('model-input').addEventListener('focus',ensureActiveModels);
$('password').addEventListener('keydown',e=>{if(e.key==='Enter')login()});
check();
</script>
</body>
</html>"""
