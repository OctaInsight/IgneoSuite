"""Interactive 3-D scatter drawn on a plain HTML canvas (no WebGL needed).

Drag to rotate, scroll or pinch to zoom, double-click to reset, hover for the sample, click a legend entry
to hide or show a cluster, 'Turn' starts a slow automatic rotation, 'Save PNG' downloads the current view.
"""
from __future__ import annotations
import json
import numpy as np
import streamlit.components.v1 as components

_HTML = r"""
<div id="wrap" style="position:relative;font-family:'Source Sans Pro',Arial,sans-serif;color:#0b0b0b;user-select:none">
  <div style="display:flex;gap:8px;align-items:center;margin:0 0 6px 0;flex-wrap:wrap">
    <b style="font-size:14px">__TITLE__</b>
    <span style="flex:1"></span>
    <button id="spin" class="b">⟳ Turn</button>
    <button id="reset" class="b">Reset view</button>
    <button id="save" class="b">⬇ Save PNG</button>
  </div>
  <canvas id="c" style="width:100%;height:__H__px;border:1px solid #e4e3df;border-radius:6px;background:#fbfaf8;
          cursor:grab;touch-action:none"></canvas>
  <div id="legend" style="position:absolute;top:44px;right:10px;background:rgba(255,255,255,.92);
       border:1px solid #e4e3df;border-radius:6px;padding:6px 8px;font-size:13px"></div>
  <div id="tip" style="position:absolute;pointer-events:none;display:none;background:#2a78d6;color:#fff;
       padding:5px 8px;border-radius:4px;font-size:12px;line-height:1.35;white-space:nowrap"></div>
  <div style="font-size:12px;color:#52514e;margin-top:4px">Drag to rotate · scroll or pinch to zoom ·
       double-click to reset · hover for the sample · click a cluster in the legend to hide or show it</div>
</div>
<style>.b{font:13px 'Source Sans Pro',Arial,sans-serif;padding:4px 10px;border:1px solid #c9c7c1;border-radius:6px;
background:#fff;cursor:pointer}.b:hover{border-color:#2a78d6;color:#2a78d6}</style>
<script>
const D = __DATA__;
const cv = document.getElementById('c'), ctx = cv.getContext('2d'), tip = document.getElementById('tip');
const n = D.x.length, AX = D.axes;
// centre and scale the cloud
let cx=0,cy=0,cz=0; for(let i=0;i<n;i++){cx+=D.x[i];cy+=D.y[i];cz+=D.z[i];} cx/=n;cy/=n;cz/=n;
let R=0; for(let i=0;i<n;i++){R=Math.max(R,Math.hypot(D.x[i]-cx,D.y[i]-cy,D.z[i]-cz));}
const X=new Float64Array(n),Y=new Float64Array(n),Z=new Float64Array(n);
for(let i=0;i<n;i++){X[i]=(D.x[i]-cx)/R;Y[i]=(D.y[i]-cy)/R;Z[i]=(D.z[i]-cz)/R;}
const groups=[...new Set(D.g)].sort((a,b)=>a-b), hidden=new Set();
let yaw=-0.9,pitch=0.45,zoom=1, spin=false, W=0,H=0, proj=new Float64Array(3*n), order=[...Array(n).keys()];
function size(){const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;W=r.width;H=r.height;
  cv.width=W*d;cv.height=H*d;ctx.setTransform(d,0,0,d,0,0);}
function P(x,y,z){ // rotate: yaw around vertical (PC3) axis, then pitch
  const c1=Math.cos(yaw),s1=Math.sin(yaw),c2=Math.cos(pitch),s2=Math.sin(pitch);
  const x1=c1*x-s1*y, y1=s1*x+c1*y;           // y1 = depth before pitch
  const z2=c2*z-s2*y1, d=s2*z+c2*y1;            // d = depth
  const f=Math.min(W,H)*0.40*zoom, persp=1/(1+0.25*d);
  return [W/2+x1*f*persp, H/2-z2*f*persp, d];
}
function draw(){
  ctx.clearRect(0,0,W,H);
  // axes
  const ends=[[1,0,0],[0,1,0],[0,0,1]];
  ctx.lineWidth=1.2; ctx.font="12px 'Source Sans Pro',Arial"; ctx.fillStyle="#52514e";
  const o=P(0,0,0);
  ends.forEach((e,k)=>{const a=P(-e[0]*0.9,-e[1]*0.9,-e[2]*0.9),b=P(e[0]*1.05,e[1]*1.05,e[2]*1.05);
    ctx.strokeStyle="#b9b7b1";ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
    ctx.fillText(AX[k],b[0]+4,b[1]-4);});
  for(let i=0;i<n;i++){const p=P(X[i],Y[i],Z[i]);proj[3*i]=p[0];proj[3*i+1]=p[1];proj[3*i+2]=p[2];}
  order.sort((a,b)=>proj[3*b+2]-proj[3*a+2]);   // far first
  for(const i of order){ if(hidden.has(D.g[i])) continue;
    const d=proj[3*i+2], r=Math.max(1.6,2.8*(1-0.25*d));
    ctx.globalAlpha=0.55+0.35*(1-(d+1)/2);
    ctx.fillStyle=D.colours[D.g[i]]; ctx.beginPath(); ctx.arc(proj[3*i],proj[3*i+1],r,0,6.2832); ctx.fill();}
  ctx.globalAlpha=1;
}
function legend(){const L=document.getElementById('legend');L.innerHTML='';
  groups.forEach(g=>{const cnt=D.g.filter(v=>v===g).length,row=document.createElement('div');
    row.style.cssText='cursor:pointer;display:flex;align-items:center;gap:6px;margin:2px 0;opacity:'+(hidden.has(g)?0.35:1);
    row.innerHTML='<span style="width:11px;height:11px;border-radius:50%;display:inline-block;background:'+D.colours[g]+'"></span>'+D.names[g]+' ('+cnt+')';
    row.onclick=()=>{hidden.has(g)?hidden.delete(g):hidden.add(g);legend();draw();};
    row.ondblclick=(e)=>{e.stopPropagation();hidden.clear();groups.forEach(h=>{if(h!==g)hidden.add(h)});legend();draw();};
    L.appendChild(row);});}
let drag=null;
cv.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,yaw,pitch];cv.setPointerCapture(e.pointerId);cv.style.cursor='grabbing';tip.style.display='none';});
cv.addEventListener('pointerup',e=>{drag=null;cv.style.cursor='grab';});
cv.addEventListener('pointermove',e=>{
  if(drag){yaw=drag[2]+(e.clientX-drag[0])*0.01; pitch=Math.max(-1.55,Math.min(1.55,drag[3]+(e.clientY-drag[1])*0.01)); draw(); return;}
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top; let best=-1,bd=49;
  for(let k=order.length-1;k>=0;k--){const i=order[k]; if(hidden.has(D.g[i]))continue;
    const dx=proj[3*i]-mx,dy=proj[3*i+1]-my,dd=dx*dx+dy*dy; if(dd<bd){bd=dd;best=i;}}
  if(best<0){tip.style.display='none';return;}
  tip.innerHTML='<b>Sample '+D.ids[best]+'</b><br>'+D.info[best]+'<br>'+AX[0]+' '+D.x[best].toFixed(2)+', '+AX[1]+' '+D.y[best].toFixed(2)+', '+AX[2]+' '+D.z[best].toFixed(2);
  tip.style.display='block'; tip.style.left=(mx+14)+'px'; tip.style.top=(my+cv.offsetTop-10)+'px';});
cv.addEventListener('pointerleave',()=>{tip.style.display='none';});
cv.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(0.3,Math.min(8,zoom*Math.exp(-e.deltaY*0.0015)));draw();},{passive:false});
cv.addEventListener('dblclick',()=>{yaw=-0.9;pitch=0.45;zoom=1;draw();});
document.getElementById('reset').onclick=()=>{yaw=-0.9;pitch=0.45;zoom=1;hidden.clear();legend();draw();};
document.getElementById('spin').onclick=()=>{spin=!spin;if(spin)loop();};
function loop(){if(!spin)return;yaw+=0.008;draw();requestAnimationFrame(loop);}
document.getElementById('save').onclick=()=>{
  const out=document.createElement('canvas'),s=3; out.width=W*s; out.height=H*s; const o2=out.getContext('2d');
  o2.fillStyle='#ffffff';o2.fillRect(0,0,out.width,out.height);o2.scale(s,s);
  const d=window.devicePixelRatio||1; o2.drawImage(cv,0,0,cv.width,cv.height,0,0,W,H);
  let yy=18; o2.font="13px Arial"; groups.forEach(g=>{if(hidden.has(g))return;o2.fillStyle=D.colours[g];
    o2.beginPath();o2.arc(W-120,yy-4,5,0,6.2832);o2.fill();o2.fillStyle='#0b0b0b';o2.fillText(D.names[g],W-110,yy);yy+=18;});
  const a=document.createElement('a'); a.download='__FILE__.png'; a.href=out.toDataURL('image/png'); a.click();};
window.addEventListener('resize',()=>{size();draw();});
// The frame may get its final size only after this script runs (browser, slow server): redraw whenever
// the canvas changes size, and keep trying until it has a width.
if (window.ResizeObserver) new ResizeObserver(()=>{size();draw();}).observe(cv);
legend();
(function first(n){ size(); draw(); if (W < 10 && n < 100) setTimeout(()=>first(n+1), 100); })(0);
</script>
"""


def show(P: np.ndarray, ev, labels, ids, info, title: str, colours: list[str], height: int = 560,
         file_name: str = "clusters_3d", key: str | None = None):
    """P: n × 3 coordinates; labels: integer group per sample; info: one hover line per sample."""
    groups = sorted(set(int(l) for l in labels))
    data = dict(x=np.round(P[:, 0], 4).tolist(), y=np.round(P[:, 1], 4).tolist(), z=np.round(P[:, 2], 4).tolist(),
                g=[int(l) for l in labels], ids=[str(i) for i in ids], info=[str(t) for t in info],
                colours={g: colours[(g - 1) % len(colours)] for g in groups}, names={g: f"C{g}" for g in groups},
                axes=[f"PC{j + 1} ({100 * ev[j]:.0f}%)" for j in range(3)])
    html = (_HTML.replace("__DATA__", json.dumps(data)).replace("__TITLE__", title)
                 .replace("__H__", str(height)).replace("__FILE__", file_name))
    components.html(html, height=height + 80, scrolling=False)
