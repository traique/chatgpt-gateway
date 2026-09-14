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
  --ink:#2f241d;--muted:#77685d;--line:rgba(105,72,42,.13);
  --peach:#ffb477;--orange:#ff8a3d;--apricot:#ffd1a8;--cream:#fff8ef;
  --lemongrass:#dce995;--leaf:#77883d;--rose:#ff8f86;--danger:#bd4f45;
  --glass:rgba(255,250,243,.65);--glass-strong:rgba(255,252,247,.82);
  --shadow:0 24px 70px rgba(123,69,29,.14),0 4px 18px rgba(113,70,39,.08);
  --radius-xl:32px;--radius-lg:24px;--radius-md:18px;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text",Inter,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}html{min-height:100%;background:#fff7ed}body{margin:0;min-height:100vh;color:var(--ink);overflow-x:hidden}
body:before,body:after{content:"";position:fixed;z-index:-2;border-radius:50%;filter:blur(12px);opacity:.72;pointer-events:none}
body:before{width:48vw;height:48vw;min-width:420px;min-height:420px;left:-12vw;top:-13vw;background:radial-gradient(circle at 38% 38%,#ffd7ba 0,#ffb96f 38%,rgba(255,185,111,0) 72%)}
body:after{width:52vw;height:52vw;min-width:460px;min-height:460px;right:-16vw;top:28vh;background:radial-gradient(circle at 50% 50%,#e5efa8 0,#f5d791 33%,rgba(245,215,145,0) 72%)}
.bg-orb{position:fixed;z-index:-1;inset:auto auto -28vw 15vw;width:65vw;height:65vw;border-radius:50%;background:radial-gradient(circle,#ffc9b9 0,rgba(255,201,185,.2) 48%,transparent 72%);pointer-events:none}
button,input,select{font:inherit}button{cursor:pointer}.hidden{display:none!important}
.shell{width:min(1480px,100%);margin:0 auto;padding:max(20px,env(safe-area-inset-top)) clamp(16px,3vw,42px) max(32px,env(safe-area-inset-bottom))}
.glass{background:linear-gradient(145deg,rgba(255,255,255,.82),var(--glass));border:1px solid rgba(255,255,255,.82);box-shadow:var(--shadow);backdrop-filter:blur(28px) saturate(155%);-webkit-backdrop-filter:blur(28px) saturate(155%)}
.topbar{position:sticky;top:12px;z-index:20;display:flex;align-items:center;gap:16px;padding:12px 14px 12px 18px;border-radius:24px;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:12px;min-width:0}.brandmark{width:42px;height:42px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(145deg,#ffbd82,#ff8b3f 55%,#dce995);box-shadow:inset 0 1px rgba(255,255,255,.8),0 8px 22px rgba(224,113,44,.22);font-size:20px}.brand h1{font-size:17px;letter-spacing:-.02em;margin:0}.brand small{display:block;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.top-spacer{flex:1}.pill{display:inline-flex;align-items:center;gap:8px;min-height:34px;padding:7px 12px;border:1px solid rgba(122,91,61,.12);border-radius:999px;background:rgba(255,255,255,.58);font-size:12px;font-weight:700;color:#5f5148}.pulse{width:8px;height:8px;border-radius:50%;background:#86a33d;box-shadow:0 0 0 5px rgba(134,163,61,.12)}
.icon-btn{width:40px;height:40px;border:0;border-radius:14px;background:rgba(255,255,255,.62);color:var(--ink);box-shadow:inset 0 0 0 1px rgba(112,79,47,.10)}
.login-wrap{min-height:72vh;display:grid;place-items:center}.login-card{width:min(480px,100%);padding:30px;border-radius:var(--radius-xl);position:relative;overflow:hidden}.login-card:after{content:"";position:absolute;width:180px;height:180px;border-radius:50%;right:-70px;top:-80px;background:linear-gradient(145deg,rgba(255,167,103,.55),rgba(220,233,149,.45));filter:blur(1px)}
.eyebrow{display:flex;align-items:center;gap:8px;color:#9b5e33;text-transform:uppercase;letter-spacing:.12em;font-size:11px;font-weight:850}.login-card h2,.hero h2{font-size:clamp(28px,4vw,48px);line-height:1.02;letter-spacing:-.055em;margin:14px 0 12px}.muted{color:var(--muted);font-size:13px;line-height:1.55}.login-card .muted{font-size:14px}
.field{display:grid;gap:7px;margin-top:14px}.field label{font-size:12px;font-weight:780;color:#66564a;padding-left:3px}.control{width:100%;min-height:48px;border:1px solid rgba(106,75,48,.13);outline:none;border-radius:16px;padding:11px 14px;background:rgba(255,255,255,.68);color:var(--ink);transition:.2s ease;box-shadow:inset 0 1px rgba(255,255,255,.72)}.control:focus{border-color:rgba(255,138,61,.48);box-shadow:0 0 0 4px rgba(255,138,61,.10),inset 0 1px rgba(255,255,255,.8)}.control::placeholder{color:#a99a8e}select.control{appearance:none;background-image:linear-gradient(45deg,transparent 50%,#8d786a 50%),linear-gradient(135deg,#8d786a 50%,transparent 50%);background-position:calc(100% - 18px) 21px,calc(100% - 13px) 21px;background-size:5px 5px,5px 5px;background-repeat:no-repeat;padding-right:34px}
.btn{border:0;min-height:44px;padding:10px 16px;border-radius:15px;font-weight:780;letter-spacing:-.01em;transition:transform .16s ease,box-shadow .16s ease,opacity .16s ease}.btn:hover{transform:translateY(-1px)}.btn:active{transform:translateY(0) scale(.985)}.btn.primary{background:linear-gradient(135deg,#ff9b55,#ff7d36);color:white;box-shadow:0 10px 24px rgba(229,110,39,.22),inset 0 1px rgba(255,255,255,.28)}.btn.soft{background:rgba(255,255,255,.63);color:var(--ink);box-shadow:inset 0 0 0 1px rgba(108,76,49,.1)}.btn.leaf{background:linear-gradient(135deg,#eef5bd,#dce995);color:#4c5b24;box-shadow:inset 0 0 0 1px rgba(95,119,41,.10)}.btn.danger{background:#fff0ed;color:var(--danger);box-shadow:inset 0 0 0 1px rgba(189,79,69,.12)}.btn.small{min-height:34px;padding:7px 11px;border-radius:12px;font-size:12px}.btn.wide{width:100%;margin-top:18px}
.status{margin-top:12px;border-radius:15px;padding:11px 13px;background:rgba(255,255,255,.52);border:1px solid rgba(105,72,42,.08);font-size:12.5px;line-height:1.5;white-space:pre-wrap;color:#6c594b}.status.success{background:rgba(236,245,190,.56);color:#52622a}.status.error{background:rgba(255,230,224,.72);color:#93483f}.status:empty{display:none}
.hero{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(260px,.8fr);gap:18px;margin-bottom:18px}.hero-main,.hero-side{border-radius:var(--radius-xl);padding:clamp(22px,3vw,36px);min-height:250px;position:relative;overflow:hidden}.hero-main:after{content:"";position:absolute;right:-65px;bottom:-90px;width:270px;height:270px;border-radius:50%;background:radial-gradient(circle at 40% 40%,rgba(255,179,113,.68),rgba(255,135,62,.16) 50%,transparent 72%)}.hero-side{background:linear-gradient(145deg,rgba(242,248,203,.76),rgba(255,248,238,.74));display:flex;flex-direction:column;justify-content:space-between}.hero-copy{position:relative;z-index:1;max-width:760px}.hero h2{max-width:780px}.hero-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:22px;position:relative;z-index:1}.metric{display:grid;gap:5px}.metric strong{font-size:38px;letter-spacing:-.06em}.metric span{font-size:12px;color:#68733b;font-weight:760}.route-now{margin-top:18px;padding:13px 14px;border-radius:17px;background:rgba(255,255,255,.5);border:1px solid rgba(107,126,50,.11)}.route-now small{display:block;color:#718041;margin-bottom:4px}.route-now b{font-size:14px}
.bento{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:18px}.tile{grid-column:span 4;border-radius:var(--radius-xl);padding:22px;min-width:0}.tile.span-8{grid-column:span 8}.tile.span-6{grid-column:span 6}.tile.span-12{grid-column:1/-1}.tile h3{font-size:18px;letter-spacing:-.035em;margin:0}.tile-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:16px}.tile-head p{margin:5px 0 0}.kicker{font-size:11px;font-weight:820;text-transform:uppercase;letter-spacing:.1em;color:#b36d3c;margin-bottom:7px}
.provider-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:10px}.provider-card{position:relative;text-align:left;border:1px solid rgba(111,76,45,.09);border-radius:18px;padding:14px;background:rgba(255,255,255,.5);min-height:92px;transition:.18s ease;color:var(--ink)}.provider-card:hover{transform:translateY(-2px);background:rgba(255,255,255,.72)}.provider-card.active{background:linear-gradient(145deg,rgba(255,183,123,.38),rgba(255,255,255,.68));border-color:rgba(255,132,52,.24);box-shadow:0 10px 28px rgba(184,101,44,.09)}.provider-card .provider-name{font-size:13px;font-weight:820;display:block;padding-right:18px}.provider-card .provider-model{display:block;margin-top:7px;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.provider-card .mini-dot{position:absolute;right:13px;top:14px;width:8px;height:8px;border-radius:50%;background:#9eb450}.provider-card .mini-dot.off{background:#d3b7a1}.provider-card .kind{display:inline-block;margin-top:8px;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#9d7254;font-weight:820}
.inline-form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;align-items:end}.model-row{margin-top:14px}.model-row .control{min-height:44px}.model-row .btn{white-space:nowrap}
.custom-layout{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(300px,.9fr);gap:16px}.custom-list{display:grid;gap:10px;align-content:start}.custom-item{padding:15px;border-radius:19px;background:rgba(255,255,255,.48);border:1px solid rgba(104,74,49,.09)}.custom-item-top{display:flex;gap:10px;align-items:flex-start}.custom-item-main{min-width:0;flex:1}.custom-item b{font-size:14px}.custom-item code{display:block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#8c6a52;font-size:10.5px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.custom-item .sub{font-size:11px;color:var(--muted);margin-top:6px}.action-row{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.editor{border-radius:22px;padding:16px;background:linear-gradient(150deg,rgba(255,238,221,.58),rgba(255,255,255,.50));border:1px solid rgba(255,156,81,.12)}.editor-title{display:flex;justify-content:space-between;align-items:center}.editor-title b{font-size:14px}.editor .field{margin-top:11px}.helper{font-size:10.5px;color:#917a69;margin-top:5px;line-height:1.45}
.list{display:grid;gap:9px}.row{display:flex;align-items:center;gap:12px;padding:12px 13px;border-radius:17px;background:rgba(255,255,255,.46);border:1px solid rgba(105,72,42,.07)}.row-main{min-width:0;flex:1}.row-title{font-size:13px;font-weight:800}.row-sub{font-size:10.5px;color:var(--muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.state-dot{width:9px;height:9px;border-radius:50%;background:#91a943;box-shadow:0 0 0 4px rgba(145,169,67,.10);flex:none}.state-dot.off{background:#c5a997;box-shadow:none}.empty{border:1px dashed rgba(103,76,54,.16);border-radius:18px;padding:20px;text-align:center;color:#917e70;font-size:12px;background:rgba(255,255,255,.25)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:10px}.code-box{margin-top:12px;padding:15px;text-align:center;border-radius:18px;background:rgba(255,255,255,.6);font:800 25px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.13em;color:#8d532c}.section-divider{height:1px;background:var(--line);margin:16px 0}.integration-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.integration{padding:15px;border-radius:19px;background:rgba(255,255,255,.43);border:1px solid rgba(104,74,49,.08)}.integration.wide{grid-column:span 2}.integration h4{font-size:13px;margin:0 0 5px}.integration .muted{font-size:11px}.integration .field{margin-top:10px}.integration .control{min-height:42px;border-radius:14px;font-size:12px}.integration .btn{width:100%;margin-top:9px}
details{border-radius:20px;background:rgba(255,255,255,.36);border:1px solid rgba(106,75,48,.08);overflow:hidden}summary{cursor:pointer;list-style:none;padding:14px 16px;font-size:13px;font-weight:820;display:flex;align-items:center;justify-content:space-between}summary::-webkit-details-marker{display:none}details[open] summary{border-bottom:1px solid rgba(106,75,48,.07)}.details-body{padding:14px 16px 16px}.footer{padding:28px 4px 8px;color:#8e7a6b;font-size:11px;text-align:center}
.toast-wrap{position:fixed;z-index:80;right:18px;bottom:18px;display:grid;gap:8px;width:min(360px,calc(100vw - 36px))}.toast{padding:12px 14px;border-radius:16px;background:rgba(54,42,34,.86);color:white;box-shadow:0 15px 40px rgba(61,40,23,.22);backdrop-filter:blur(20px);font-size:12px;animation:toastin .22s ease}.toast.good{background:rgba(77,94,36,.90)}.toast.bad{background:rgba(139,65,56,.92)}@keyframes toastin{from{transform:translateY(8px);opacity:0}to{transform:none;opacity:1}}
@media(max-width:1050px){.tile,.tile.span-8,.tile.span-6{grid-column:span 6}.tile.span-12{grid-column:1/-1}.hero{grid-template-columns:1fr}.hero-side{min-height:180px}.custom-layout{grid-template-columns:1fr}.integration-grid{grid-template-columns:1fr 1fr}}
@media(max-width:720px){.integration.wide{grid-column:auto}.shell{padding-left:12px;padding-right:12px}.topbar{top:8px;border-radius:20px}.topbar .pill{display:none}.brand small{max-width:190px}.hero-main,.hero-side,.tile{border-radius:25px}.hero-main{min-height:280px}.bento{gap:12px}.tile,.tile.span-8,.tile.span-6,.tile.span-12{grid-column:1/-1}.provider-grid{grid-template-columns:1fr 1fr}.integration-grid,.two-col{grid-template-columns:1fr}.inline-form{grid-template-columns:1fr}.inline-form .btn{width:100%}.custom-layout{gap:12px}}
@media(max-width:430px){.provider-grid{grid-template-columns:1fr}.tile{padding:18px}.hero-main,.hero-side{padding:22px}.brand small{max-width:130px}.topbar{padding-left:12px}.custom-item-top{flex-direction:column}.row{align-items:flex-start}.row-actions{width:100%;justify-content:flex-start}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
/* Rendering budget: below-fold bento cards can stay unpainted until needed. */
@supports(content-visibility:auto){.tile{content-visibility:auto;contain-intrinsic-size:420px}}
.mobile-dock{display:none}
#routing-tile,#custom-provider-tile,#client-tile,#chatgpt-tile,#builtins-tile{scroll-margin-top:88px}
@media(hover:none){.btn:hover,.provider-card:hover{transform:none}}
@media(max-width:720px){
  body{background:linear-gradient(160deg,#fff8f0 0,#fff3e5 46%,#f7f8df 100%);padding-bottom:calc(78px + env(safe-area-inset-bottom))}
  body:before,body:after,.bg-orb{display:none}
  .shell{padding-top:max(8px,env(safe-area-inset-top));padding-left:10px;padding-right:10px;padding-bottom:18px}
  .glass{background:rgba(255,251,246,.94);backdrop-filter:none;-webkit-backdrop-filter:none;box-shadow:0 10px 30px rgba(105,67,35,.09),inset 0 0 0 1px rgba(255,255,255,.82)}
  .topbar{top:max(6px,env(safe-area-inset-top));min-height:54px;margin-bottom:10px;padding:8px 10px;border-radius:18px;gap:10px}
  .brand{gap:9px}.brandmark{width:38px;height:38px;border-radius:13px;font-size:18px}.brand h1{font-size:15px}.brand small{display:none}.icon-btn{width:40px;height:40px;border-radius:13px}
  .hero{gap:10px;margin-bottom:10px}.hero-main,.hero-side{border-radius:22px}.hero-main{min-height:0;padding:18px}.hero-main:after{display:none}.hero h2{font-size:30px;line-height:1.02;margin:9px 0 10px}.hero .muted{font-size:12px;line-height:1.45}.hero-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:15px}.hero-actions .btn{width:100%;padding-left:10px;padding-right:10px}
  .hero-side{min-height:0;padding:14px 16px;display:grid;grid-template-columns:minmax(90px,.7fr) minmax(0,1.3fr);align-items:center;gap:12px}.metric strong{font-size:30px}.metric span{font-size:10px}.route-now{margin-top:0;padding:10px 12px;border-radius:15px}.route-now b{font-size:13px}.route-now .muted{font-size:10.5px}
  .bento{gap:10px}.tile,.tile.span-8,.tile.span-6,.tile.span-12{grid-column:1/-1}.tile{padding:16px;border-radius:22px}.tile-head{margin-bottom:13px;gap:9px}.tile-head h3{font-size:17px}.tile-head p{font-size:11.5px;line-height:1.42}.kicker{font-size:9.5px;margin-bottom:5px}
  .control{min-height:50px;border-radius:15px;font-size:16px;padding:11px 13px}.field label{font-size:11.5px}.btn{min-height:48px;border-radius:15px;touch-action:manipulation}.btn.small{min-height:42px;padding:8px 11px}.btn.wide{margin-top:14px}
  .provider-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.provider-card{min-height:86px;padding:12px;border-radius:16px;touch-action:manipulation}.provider-card .provider-name{font-size:12px}.provider-card .provider-model{font-size:10px;margin-top:5px}.provider-card .kind{margin-top:6px}.provider-card .mini-dot{right:11px;top:12px}
  .inline-form,.two-col,.integration-grid,.custom-layout{grid-template-columns:1fr}.custom-layout{gap:10px}.custom-list{gap:8px}.custom-item{padding:13px;border-radius:17px}.custom-item-top{align-items:center}.custom-item code{font-size:10px}.action-row{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.action-row .btn{min-width:0;padding-left:5px;padding-right:5px}.editor{padding:14px;border-radius:19px}
  .row{padding:11px 12px;border-radius:16px;gap:10px;align-items:flex-start}.row-actions{width:100%;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.row-actions .btn{width:100%}.row-sub{white-space:normal;overflow-wrap:anywhere;line-height:1.35}.list{gap:7px}
  .integration{padding:13px;border-radius:17px}.integration.wide{grid-column:auto}.integration .control{font-size:16px}.integration .btn{min-height:46px}.section-divider{margin:14px 0}.code-box{font-size:22px;padding:13px}
  .toast-wrap{right:10px;bottom:calc(80px + env(safe-area-inset-bottom));width:calc(100vw - 20px)}.toast{backdrop-filter:none;border-radius:14px}
  .footer{display:none}
  .mobile-dock{position:fixed;z-index:60;left:10px;right:10px;bottom:max(8px,env(safe-area-inset-bottom));height:60px;padding:5px;display:grid;grid-template-columns:repeat(4,1fr);gap:3px;border-radius:20px;background:rgba(255,250,244,.97);box-shadow:0 10px 35px rgba(88,56,30,.16),inset 0 0 0 1px rgba(121,82,49,.08)}
  .mobile-dock button{border:0;background:transparent;border-radius:15px;color:#77685d;font-size:10px;font-weight:800;letter-spacing:-.01em;display:grid;place-items:center;gap:1px;touch-action:manipulation}.mobile-dock button span{display:block;font-size:17px;line-height:1}.mobile-dock button:active{background:rgba(255,178,112,.18);color:#8f512b}
}
@media(max-width:360px){.provider-grid{grid-template-columns:1fr}.hero-actions{grid-template-columns:1fr}.action-row{grid-template-columns:1fr 1fr}.mobile-dock button{font-size:9px}}
</style>
</head>
<body>
<div class="bg-orb"></div>
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
        <div class="list">
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
          <div class="editor" id="custom-editor">
            <div class="editor-title"><b id="custom-editor-title">Thêm provider</b><button class="btn soft small" onclick="newCustomProvider()">Clear</button></div>
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
        <div class="two-col">
          <div class="field" style="margin-top:0"><label>Tên client</label><input id="client-label" class="control" placeholder="VD: Bot Zalo"></div>
          <div class="field" style="margin-top:0"><label>API key</label><input id="client-key" class="control" placeholder="Để trống để tự sinh"></div>
          <div class="field"><label>Provider</label><select id="client-provider" class="control"></select></div>
          <div class="field"><label>Model</label><input id="client-model" class="control" placeholder="Để trống = mặc định"></div>
        </div>
        <button class="btn leaf wide" onclick="addClient()">＋ Tạo client key</button>
        <div id="client-created" class="status"></div>
        <div class="section-divider"></div>
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
          <div class="integration"><h4>Legacy Generic</h4><div class="muted">Slot OpenAI Compatible cũ để giữ backward compatibility.</div><div class="field"><label>Base URL</label><input id="generic-base-url" class="control" placeholder="https://example.com/v1"></div><div class="field"><label>API key</label><input id="generic-key" class="control" type="password" placeholder="sk-…"></div><div class="field"><label>Model</label><input id="generic-model" class="control" placeholder="model-id"></div><button class="btn soft" onclick="saveGenericConfig()">Lưu</button><div id="generic-status" class="status"></div></div>
          <div class="integration"><h4>OpenRouter</h4><div class="muted">Catalog động, hỗ trợ các model OpenRouter hiện có.</div><div class="field"><label>API key</label><input id="openrouter-key" class="control" type="password" placeholder="sk-or-v1-…"></div><button class="btn soft" onclick="saveOpenRouterKey()">Lưu key</button><div id="openrouter-status" class="status"></div></div>
          <div class="integration"><h4>TokenRouter</h4><div class="muted">OpenAI-compatible và Anthropic Messages native.</div><div class="field"><label>API key</label><input id="tokenrouter-key" class="control" type="password" placeholder="tr_…"></div><button class="btn soft" onclick="saveTokenRouterKey()">Lưu key</button><div id="tokenrouter-status" class="status"></div></div>
          <div class="integration"><h4>NVIDIA NIM</h4><div class="muted">Model catalog được lọc cho chat workloads.</div><div class="field"><label>API key</label><input id="nim-key" class="control" type="password" placeholder="nvapi-…"></div><button class="btn soft" onclick="saveNimKey()">Lưu key</button><div id="nim-status" class="status"></div></div>
          <div class="integration wide"><h4>Notion AI</h4><div class="muted">Đăng nhập bằng browser session hoặc cookie session thủ công.</div><button class="btn leaf" onclick="startNotionBrowserLogin()">Mở browser login</button><div id="notion-browser-status" class="status"></div><details style="margin-top:10px"><summary>Session thủ công <span>⌄</span></summary><div class="details-body"><div class="field" style="margin-top:0"><label>token_v2</label><input id="notion-token-v2" class="control" type="password" placeholder="token_v2"></div><div class="field"><label>notion_user_id</label><input id="notion-user-id" class="control" placeholder="user id"></div><div class="field"><label>notion_users</label><input id="notion-users" class="control" placeholder="notion_users"></div><button class="btn soft wide" onclick="notionLogin()">Lưu session</button><div id="notion-status" class="status"></div></div></details><div class="section-divider"></div><div id="notion-accounts" class="list"><div class="empty">Chưa tải tài khoản Notion.</div></div></div>
        </div>
      </article>
    </section>
    <nav class="mobile-dock" aria-label="Điều hướng nhanh">
      <button type="button" onclick="jumpTo('routing-tile')"><span>⌁</span>Route</button>
      <button type="button" onclick="jumpTo('custom-provider-tile')"><span>＋</span>Provider</button>
      <button type="button" onclick="jumpTo('client-tile')"><span>◇</span>Keys</button>
      <button type="button" onclick="jumpTo('builtins-tile')"><span>•••</span>Kết nối</button>
    </nav>
    <footer class="footer">Gateway Garden · peach / orange / lemongrass liquid glass admin</footer>
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
  $('providers').innerHTML=r.providers.map(p=>`<button class="provider-card ${p.id===r.active_provider?'active':''}" onclick="selectProvider('${esc(p.id)}')"><span class="mini-dot ${p.configured?'':'off'}"></span><span class="provider-name">${esc(p.label)}</span><span class="provider-model">${esc((p.models&&p.models[0])||'model chưa chọn')}</span><span class="kind">${p.kind==='custom'?'custom':'built-in'}</span></button>`).join('');
  const active=r.providers.find(p=>p.id===r.active_provider);renderProviderModels(active?.models||[]);$('model-input').value=r.active_model||'';
  $('hero-active-provider').textContent=active?.label||r.active_provider;$('hero-active-model').textContent=r.active_model?('Override · '+r.active_model):('Default · '+((active?.models||[])[0]||'provider default'));
  status('provider-status',`Đang dùng ${active?.label||r.active_provider}${active&&!active.configured?' · provider chưa cấu hình':''}`);updateClientProviderOptions()
}
async function loadProviders(){
  try{const r=await api('/auth/providers');providersData=r;customProviders=r.providers.filter(p=>p.kind==='custom').map(p=>({id:p.id,name:p.label,base_url:p.base_url||'',model:(p.models||[])[0]||'',configured:p.configured}));renderCustomProviders();renderProviders(r);$('metric-custom').textContent=customProviders.length}catch(e){$('providers').innerHTML=`<div class="empty">${esc(e.message)}</div>`}
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
function newCustomProvider(){
  $('custom-id').value='';$('custom-name').value='';$('custom-base-url').value='';$('custom-api-key').value='';$('custom-model').value='';$('custom-editor-title').textContent='Thêm provider';$('custom-save-button').textContent='Tạo provider';$('custom-key-help').textContent='Bắt buộc khi tạo mới.';status('custom-status','');
}
function editCustomProvider(id){
  const p=customProviders.find(x=>x.id===id);if(!p)return;$('custom-id').value=p.id;$('custom-name').value=p.name;$('custom-base-url').value=p.base_url;$('custom-api-key').value='';$('custom-model').value=p.model;$('custom-editor-title').textContent='Sửa '+p.name;$('custom-save-button').textContent='Lưu thay đổi';$('custom-key-help').textContent='Để trống nếu muốn giữ API key hiện tại.';$('custom-editor').scrollIntoView({behavior:'smooth',block:'center'})
}
function focusNewProvider(){newCustomProvider();$('custom-provider-tile').scrollIntoView({behavior:'smooth',block:'start'});setTimeout(()=>$('custom-name').focus(),350)}
async function saveCustomProvider(){
  const id=$('custom-id').value;const payload={name:$('custom-name').value.trim(),base_url:$('custom-base-url').value.trim(),api_key:$('custom-api-key').value.trim(),model:$('custom-model').value.trim()};
  try{const r=await api(id?('/auth/custom-providers/'+encodeURIComponent(id)):'/auth/custom-providers',{method:'POST',body:JSON.stringify(payload)});customProviders=r.data||[];renderCustomProviders();newCustomProvider();await loadProviders();toast(id?'Đã cập nhật provider':'Đã tạo provider mới')}catch(e){status('custom-status',e.message,'error');toast(e.message,'bad')}
}
async function deleteCustomProvider(id){
  const p=customProviders.find(x=>x.id===id);if(!confirm(`Xóa provider “${p?.name||id}”?`))return;
  try{const r=await api('/auth/custom-providers/'+encodeURIComponent(id),{method:'DELETE'});customProviders=r.data||[];renderCustomProviders();if($('custom-id').value===id)newCustomProvider();await loadProviders();toast('Đã xóa provider')}catch(e){toast(e.message,'bad');status('custom-status',e.message,'error')}
}

async function loadClients(){
  try{const r=await api('/auth/clients');$('clients').innerHTML=r.data.length?r.data.map(c=>`<div class="row"><span class="state-dot ${c.status==='active'?'':'off'}"></span><div class="row-main"><div class="row-title">${esc(c.label)}</div><div class="row-sub">${esc(c.key_masked)} · ${esc(providerLabel(c.provider))}${c.model?' · '+esc(c.model):''}</div></div><div class="row-actions">${c.status==='active'?`<button class="btn soft small" onclick="clientAction('${c.id}','disabled')">Tắt</button>`:`<button class="btn leaf small" onclick="clientAction('${c.id}','active')">Bật</button>`}<button class="btn danger small" onclick="clientAction('${c.id}','delete')">Xóa</button></div></div>`).join(''):'<div class="empty">Chưa có client key.</div>'}catch(e){$('clients').innerHTML=`<div class="empty">${esc(e.message)}</div>`}
}
async function clientAction(id,action){try{if(action==='delete'){if(!confirm('Xóa client key này?'))return;await api('/auth/clients/'+id,{method:'DELETE'})}else await api('/auth/clients/'+id,{method:'POST',body:JSON.stringify({status:action})});await loadClients()}catch(e){status('client-created',e.message,'error')}}
async function addClient(){try{const r=await api('/auth/clients',{method:'POST',body:JSON.stringify({label:$('client-label').value.trim(),key:$('client-key').value.trim(),provider:$('client-provider').value,model:$('client-model').value.trim()})});$('client-key').value='';$('client-model').value='';status('client-created','API key mới: '+r.key,'success');await loadClients();toast('Đã tạo client key')}catch(e){status('client-created',e.message,'error')}}

async function startLogin(){try{const s=await api('/auth/device/start',{method:'POST'});$('code').textContent=s.user_code;$('code').classList.remove('hidden');$('open').classList.remove('hidden');$('open').onclick=()=>window.open(s.verification_url,'_blank','noopener');status('device-status','Mở trang xác nhận và nhập mã. Gateway đang chờ ChatGPT xác nhận…');pollChatGPT(s.login_id,s.interval_seconds)}catch(e){status('device-status',e.message,'error')}}
async function pollChatGPT(id,interval){interval=Math.max(Number(interval)||5,5);for(;;){await pollPause(interval);try{const s=await api('/auth/device/poll',{method:'POST',body:JSON.stringify({login_id:id,label:'ChatGPT'})});if(s.status==='completed'){status('device-status','Đăng nhập ChatGPT thành công.','success');$('code').classList.add('hidden');$('open').classList.add('hidden');await loadAccounts();return}if(s.status==='expired'||s.status==='failed'){status('device-status','Phiên đăng nhập: '+s.status,'error');return}status('device-status','Đang chờ xác nhận đăng nhập…')}catch(e){status('device-status',e.message,'error');return}}}
async function loadAccounts(){try{const r=await api('/auth/accounts');$('accounts').innerHTML=r.data.length?r.data.map(a=>`<div class="row"><span class="state-dot"></span><div class="row-main"><div class="row-title">${esc(a.label)}</div><div class="row-sub">${esc(a.status)}</div></div></div>`).join(''):'<div class="empty">Chưa có tài khoản ChatGPT.</div>'}catch(e){$('accounts').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}

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
async function loadNotionAccounts(){try{const r=await api('/auth/notion/accounts');$('notion-accounts').innerHTML=r.data.length?r.data.map(a=>`<div class="row"><span class="state-dot ${a.status==='active'?'':'off'}"></span><div class="row-main"><div class="row-title">${esc(a.label)}</div><div class="row-sub">${esc(a.space_name||a.space_id)}</div></div>${a.status==='active'?`<button class="btn danger small" onclick="disableNotion('${a.id}')">Tắt</button>`:''}</div>`).join(''):'<div class="empty">Chưa có tài khoản Notion.</div>'}catch(e){$('notion-accounts').innerHTML=`<div class="empty">${esc(e.message)}</div>`}}
async function disableNotion(id){try{await api('/auth/notion/accounts/'+id,{method:'DELETE'});await loadNotionAccounts();await loadProviders()}catch(e){status('notion-status',e.message,'error')}}

async function pollPause(seconds){await new Promise(r=>setTimeout(r,seconds*1000));if(!document.hidden)return;await new Promise(resolve=>{const onVisible=()=>{if(document.hidden)return;document.removeEventListener('visibilitychange',onVisible);resolve()};document.addEventListener('visibilitychange',onVisible)})}
$('model-input').addEventListener('focus',ensureActiveModels);
$('password').addEventListener('keydown',e=>{if(e.key==='Enter')login()});
check();
</script>
</body>
</html>"""
