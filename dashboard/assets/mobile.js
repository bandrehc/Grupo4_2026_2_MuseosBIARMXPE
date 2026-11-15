// Ajuste de los gráficos Plotly en pantallas angostas (≤700 px): título en varias líneas, barra de color delgada,
// tipografía de ejes más pequeña y leyenda compacta. Es solo presentación: no cambia datos ni callbacks.
(function () {
  var MQ = window.matchMedia("(max-width: 700px)");
  function wrap(t, n) {
    var out = [], line = "";
    t.split(/\s+/).forEach(function (w) {
      if ((line + " " + w).trim().length > n) { out.push(line); line = w; } else { line = (line + " " + w).trim(); }
    });
    if (line) out.push(line);
    return out.join("<br>");
  }
  function ajusta(gd) {
    if (!MQ.matches || !window.Plotly || !gd.layout || gd.layout.meta === "mob") return;  // el marcador vive en el layout: si Dash redibuja, se reaplica
    var L = gd.layout, u = { meta: "mob" };
    var tt = L.title && (L.title.text || (typeof L.title === "string" ? L.title : ""));
    if (tt && tt.indexOf("<br>") < 0) { u["title.text"] = wrap(tt, 34); u["title.font.size"] = 13; u["margin.t"] = 70; }
    if (L.coloraxis && L.coloraxis.showscale !== false) {
      u["coloraxis.colorbar.thickness"] = 8; u["coloraxis.colorbar.len"] = 0.8; u["coloraxis.colorbar.xpad"] = 2;
      u["coloraxis.colorbar.tickfont.size"] = 9; u["coloraxis.colorbar.title.text"] = "";
    }
    if (L.xaxis) { u["xaxis.tickfont.size"] = 10; }
    if (L.yaxis) { u["yaxis.tickfont.size"] = 9.5; u["yaxis.automargin"] = true; }
    if (L.legend) { u["legend.font.size"] = 10; }
    try { window.Plotly.relayout(gd, u); } catch (e) {}
    if (L.map && L.map.zoom) {  // el mapa tarda en estar listo: el zoom se reaplica después
      var z = Math.max(0, L.map.zoom - 1.35);
      [900, 2200].forEach(function (ms, i) { setTimeout(function () { try { window.Plotly.relayout(gd, { "map.zoom": z + 0.001 * (i + 1) }); } catch (e) {} }, ms); });
    }
  }
  function engancha(gd) {  // si Dash redibuja el gráfico (Plotly.react), el layout vuelve al original: se reaplica
    if (gd._mobHook || !gd.on) return;
    gd._mobHook = true;
    gd.on("plotly_afterplot", function () { setTimeout(function () { ajusta(gd); }, 50); });
  }
  function barrido() { document.querySelectorAll(".js-plotly-plot").forEach(function (g) { engancha(g); ajusta(g); }); }
  var t = null;
  new MutationObserver(function () { clearTimeout(t); t = setTimeout(barrido, 350); })
    .observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", function () { setTimeout(barrido, 800); });
})();
