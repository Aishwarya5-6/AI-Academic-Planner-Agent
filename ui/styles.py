"""Global CSS. Custom surfaces are tinted from `currentColor`, so they follow
Streamlit's light/dark theme without needing to know which one is active."""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..600,0..1,0&display=block');

:root {
  --accent: #4f46e5;
  --accent-2: #7c3aed;
  --surface: color-mix(in srgb, currentColor 3.5%, transparent);
  --surface-strong: color-mix(in srgb, currentColor 7%, transparent);
  --line: color-mix(in srgb, currentColor 11%, transparent);
  --muted: color-mix(in srgb, currentColor 62%, transparent);
  --good: #16a34a; --warn: #d97706; --bad: #dc2626;
}

.block-container { padding-top: 4.2rem; max-width: 1180px; }
h1, h2, h3 { letter-spacing: -0.02em; }

.msr {
  font-family: 'Material Symbols Rounded'; font-weight: 400; font-style: normal;
  font-size: 1.15em; line-height: 1; display: inline-block; vertical-align: -0.18em;
  font-variation-settings: 'FILL' 1, 'wght' 500, 'opsz' 24;
  -webkit-font-smoothing: antialiased; user-select: none;
}

/* ---------- hero ---------- */
.hero {
  position: relative; overflow: hidden; border-radius: 20px; padding: 28px 30px; color: #fff;
  background: radial-gradient(120% 140% at 100% 0%, #a78bfa 0%, transparent 55%),
              linear-gradient(135deg, #4338ca 0%, #6d28d9 55%, #9333ea 100%);
  box-shadow: 0 18px 40px -18px rgba(79, 70, 229, .55);
  display: flex; gap: 28px; align-items: center; justify-content: space-between; flex-wrap: wrap;
}
.hero::after {
  content: ""; position: absolute; inset: auto -60px -80px auto; width: 260px; height: 260px;
  border-radius: 50%; background: rgba(255,255,255,.08);
}
.hero .eyebrow { font-size: .8rem; letter-spacing: .12em; text-transform: uppercase; opacity: .8; font-weight: 600; }
.hero h1 { color: #fff !important; font-size: 2rem; margin: 4px 0 6px; padding: 0; line-height: 1.15; }
.hero p { margin: 0; opacity: .88; font-size: .98rem; }
.hero-stats { display: flex; gap: 14px; position: relative; z-index: 1; flex-wrap: wrap; }
.hero-chip {
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22); backdrop-filter: blur(6px);
  border-radius: 14px; padding: 12px 16px; min-width: 120px;
}
.hero-chip .k { font-size: .74rem; opacity: .8; text-transform: uppercase; letter-spacing: .08em; }
.hero-chip .v { font-size: 1.45rem; font-weight: 700; font-family: 'Plus Jakarta Sans', sans-serif; }

/* ---------- generic cards ---------- */
.card {
  background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px;
}
.section-title {
  display: flex; align-items: center; gap: 8px; font-family: 'Plus Jakarta Sans', sans-serif;
  font-weight: 700; font-size: 1.08rem; margin: 6px 0 10px;
}
.section-title .msr { color: var(--accent); font-size: 1.3em; }
.section-title .sub { font-weight: 500; font-size: .85rem; color: var(--muted); margin-left: auto; }
.muted { color: var(--muted); }

.chip {
  display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 999px;
  font-size: .78rem; font-weight: 600; background: var(--surface-strong); border: 1px solid var(--line);
  white-space: nowrap;
}
.chip.good { color: var(--good); background: color-mix(in srgb, var(--good) 12%, transparent); border-color: transparent; }
.chip.warn { color: var(--warn); background: color-mix(in srgb, var(--warn) 14%, transparent); border-color: transparent; }
.chip.bad  { color: var(--bad);  background: color-mix(in srgb, var(--bad) 12%, transparent);  border-color: transparent; }
.chip.accent { color: #fff; background: linear-gradient(135deg, #4f46e5, #7c3aed); border-color: transparent; }

/* ---------- session card ---------- */
.session { display: flex; gap: 14px; align-items: center; }
.session .bar { width: 5px; align-self: stretch; border-radius: 6px; min-height: 52px; }
.session .icon {
  width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center; flex: none;
}
.session .icon .msr { font-size: 24px; }
.session .subject { font-size: .78rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
.session .topic { font-size: 1.02rem; font-weight: 600; margin: 2px 0 4px; }
.session .meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; font-size: .82rem; }

/* ---------- week strip ---------- */
.week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; }
.day {
  background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 10px 8px 12px;
  text-align: center;
}
.day.today { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.day .dn { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 600; }
.day .dd { font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 1.25rem; }
.day .stack { display: flex; flex-direction: column-reverse; gap: 2px; height: 56px; margin: 6px auto 4px; width: 16px;
  border-radius: 6px; overflow: hidden; background: var(--surface-strong); }
.day .stack span { display: block; width: 100%; }
.day .h { font-size: .78rem; font-weight: 600; }
.day .exam { color: var(--bad); font-size: .7rem; font-weight: 700; }

/* ---------- exam countdown ---------- */
.exams { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
.exam-card { position: relative; overflow: hidden; }
.exam-card .big { font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 2rem; line-height: 1; }
.exam-card .name { font-weight: 600; margin-top: 6px; }
.exam-card .glow { position: absolute; right: -30px; top: -30px; width: 110px; height: 110px; border-radius: 50%; opacity: .16; }

/* ---------- progress ring ---------- */
.ringw { position: relative; width: 92px; height: 92px; flex: none; }
.ringw .ring { position: absolute; inset: 0; border-radius: 50%;
  background: conic-gradient(var(--c) calc(var(--p) * 1%), var(--surface-strong) 0);
  -webkit-mask: radial-gradient(circle at center, transparent 36px, #000 37px);
          mask: radial-gradient(circle at center, transparent 36px, #000 37px); }
.ringw .val { position: absolute; inset: 0; display: grid; place-items: center;
  font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 1.15rem; }
.ring-card { display: flex; gap: 16px; align-items: center; }

.pbar { height: 8px; border-radius: 99px; background: var(--surface-strong); overflow: hidden; }
.pbar > span { display: block; height: 100%; border-radius: 99px; }

/* ---------- plan timeline ---------- */
.tl-day { display: grid; grid-template-columns: 74px 1fr; gap: 14px; padding: 12px 0; border-bottom: 1px dashed var(--line); }
.tl-date .dn { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 600; }
.tl-date .dd { font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 1.5rem; line-height: 1.1; }
.tl-date .mm { font-size: .78rem; color: var(--muted); }
.tl-items { display: flex; flex-direction: column; gap: 6px; }
.tl-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 12px; background: var(--surface);
  border: 1px solid var(--line); }
.tl-item .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.tl-item .t { font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-item .s { color: var(--muted); font-size: .8rem; white-space: nowrap; }
.tl-item.done { opacity: .6; } .tl-item.missed { opacity: .55; text-decoration: line-through; }
.tl-exam { display: flex; align-items: center; gap: 8px; color: var(--bad); font-weight: 700; font-size: .88rem; }

/* ---------- subject card ---------- */
.subj-head { display: flex; align-items: center; gap: 12px; }
.subj-head .badge { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; color: #fff; font-weight: 800;
  font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.05rem; flex: none; }
.subj-head .n { font-weight: 700; font-size: 1.05rem; line-height: 1.2; }
.weak { display: inline-flex; gap: 3px; vertical-align: middle; }
.weak i { width: 8px; height: 8px; border-radius: 2px; background: var(--surface-strong); display: inline-block; }
.topics { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.topics .chip.done { text-decoration: line-through; opacity: .6; }

/* ---------- agents ---------- */
.agents { display: grid; grid-template-columns: repeat(auto-fill, minmax(165px, 1fr)); gap: 10px; }
.intro { display: grid; grid-template-columns: 1.1fr 1fr; gap: 18px; align-items: center; margin-bottom: 14px; }
.intro .big { font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 1.35rem; line-height: 1.25; }
.intro .tools { display: flex; flex-wrap: wrap; gap: 6px; }
.intro .orb { width: 52px; height: 52px; border-radius: 16px; display: grid; place-items: center; color: #fff; margin-bottom: 12px;
  background: linear-gradient(135deg, #4f46e5, #9333ea); box-shadow: 0 10px 24px -10px rgba(124,58,237,.8); }
.intro .orb .msr { font-size: 28px; }
@media (max-width: 760px) { .intro { grid-template-columns: 1fr; } }
.agent .ic { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; color: #fff; margin-bottom: 10px; }
.agent .ic .msr { font-size: 22px; }
.agent .n { font-weight: 700; } .agent .r { font-size: .84rem; color: var(--muted); margin-top: 2px; min-height: 2.4em; }
.agent .last { font-size: .76rem; color: var(--muted); margin-top: 8px; border-top: 1px solid var(--line); padding-top: 8px; }

.feed { display: flex; flex-direction: column; }
.feed-item { display: grid; grid-template-columns: 34px 1fr; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.feed-item .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; color: #fff; }
.feed-item .ic .msr { font-size: 19px; }
.feed-item .who { font-weight: 700; font-size: .86rem; } .feed-item .when { color: var(--muted); font-size: .76rem; margin-left: 6px; font-weight: 500; }
.feed-item .what { font-size: .9rem; margin-top: 2px; }

.empty { text-align: center; padding: 38px 20px; }
.empty .msr { font-size: 46px; color: var(--accent); opacity: .85; }
.empty .t { font-weight: 700; font-size: 1.1rem; margin-top: 8px; }

/* Streamlit widgets polish */
div[data-testid="stMetric"] { background: var(--surface); }
button[kind="primary"] { background: linear-gradient(135deg, #4f46e5, #7c3aed); border: none; }
div[data-testid="stChatMessage"] { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; }
[data-testid="stSidebar"] .brand { display: flex; align-items: center; gap: 10px; margin: 4px 0 14px; }
[data-testid="stSidebar"] .brand .logo { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; color: #fff;
  background: linear-gradient(135deg, #4f46e5, #9333ea); box-shadow: 0 8px 18px -8px rgba(79,70,229,.7); }
[data-testid="stSidebar"] .brand .t { font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 1.1rem; line-height: 1.1; }
[data-testid="stSidebar"] .brand .s { font-size: .74rem; color: var(--muted); }

@media (max-width: 640px) {
  .week { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .hero { padding: 22px 18px; } .hero h1 { font-size: 1.55rem; }
}
</style>
"""
