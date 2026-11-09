/* Homepage animations: scroll progress, rotating hero word, particles, tilt, magnetic buttons, bar fills, live-deploy toasts. Respects reduced-motion; light on phones. */
(()=>{if(matchMedia("(prefers-reduced-motion:reduce)").matches)return;const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const phone=innerWidth<700,fine=matchMedia("(pointer:fine)").matches;
function init(){if(!$(".fhero")||document.body.dataset.fx)return;document.body.dataset.fx=1;
 /* scroll progress + hero parallax */
 const pb=document.createElement("div");pb.className="sprog";document.body.appendChild(pb);const beams=$$(".fhero .lt,.fhero .aur");let tk=0;
 const onS=()=>{tk=0;const h=document.documentElement,p=h.scrollTop/Math.max(1,h.scrollHeight-innerHeight);pb.style.transform=`scaleX(${p})`;beams.forEach(b=>b.style.transform=`translateY(${Math.min(h.scrollTop,600)*.18}px)`)};
 addEventListener("scroll",()=>{if(!tk)tk=requestAnimationFrame(onS)},{passive:true});onS();
 /* rotating hero word */
 const g=$(".fhero h1 .grad");if(g){const W=["never slows","never lets","never drags"];let i=0;g.classList.add("rot");setInterval(()=>{g.classList.add("out");setTimeout(()=>{i=(i+1)%W.length;g.textContent=W[i];g.classList.remove("out")},350)},2600)}
 /* hero particles */
 const hero=$(".fhero");if(hero&&!phone||hero&&innerWidth>=420){const c=document.createElement("canvas");c.className="hpart";hero.prepend(c);const x=c.getContext("2d");let W,H,P=[],n=phone?26:60,run=true;
  const rs=()=>{W=c.width=hero.clientWidth;H=c.height=hero.clientHeight};rs();addEventListener("resize",rs);
  for(let k=0;k<n;k++)P.push({x:Math.random()*W,y:Math.random()*H,r:Math.random()*1.8+.4,vx:(Math.random()-.5)*.25,vy:-Math.random()*.4-.1,a:Math.random()*.6+.2});
  new IntersectionObserver(e=>run=e[0].isIntersecting).observe(hero);
  (function f(){if(run){x.clearRect(0,0,W,H);P.forEach(p=>{p.x+=p.vx;p.y+=p.vy;if(p.y<-5){p.y=H+5;p.x=Math.random()*W}x.beginPath();x.arc(p.x,p.y,p.r,0,7);x.fillStyle=`rgba(160,190,255,${p.a})`;x.fill()});
   if(!phone)for(let a=0;a<P.length;a++)for(let b=a+1;b<P.length;b++){const dx=P[a].x-P[b].x,dy=P[a].y-P[b].y,d=dx*dx+dy*dy;if(d<9000){x.strokeStyle=`rgba(120,150,255,${.14*(1-d/9000)})`;x.beginPath();x.moveTo(P[a].x,P[a].y);x.lineTo(P[b].x,P[b].y);x.stroke()}}}requestAnimationFrame(f)})()}
 /* stagger reveal */
 $$(".bento,.grid2,.grid3,.grid4").forEach(gr=>$$(":scope>.rv",gr).forEach((e,i)=>e.style.transitionDelay=(i*90)+"ms"));
 /* bars fill when visible */
 $$(".bar i").forEach(b=>{const w=b.style.width;b.dataset.w=w;b.style.width="0";new IntersectionObserver((e,o)=>{if(e[0].isIntersecting){b.style.transition="width 1.4s cubic-bezier(.2,.7,.2,1)";b.style.width=w;o.disconnect()}},{threshold:.4}).observe(b)});
 /* tilt + spotlight */
 $$(".cfg,.tile,.card").forEach(el=>{el.addEventListener("pointermove",e=>{const r=el.getBoundingClientRect(),px=(e.clientX-r.left)/r.width,py=(e.clientY-r.top)/r.height;el.style.setProperty("--mx",px*100+"%");el.style.setProperty("--my",py*100+"%");
   if(fine&&(el.classList.contains("cfg")||el.classList.contains("tile")))el.style.transform=`perspective(900px) rotateX(${(.5-py)*7}deg) rotateY(${(px-.5)*9}deg) translateY(-3px)`});
  el.addEventListener("pointerleave",()=>{el.style.transform=""})});
 /* magnetic primary buttons + shine */
 if(fine)$$(".btn.p").forEach(b=>{b.addEventListener("pointermove",e=>{const r=b.getBoundingClientRect();b.style.transform=`translate(${(e.clientX-r.left-r.width/2)*.18}px,${(e.clientY-r.top-r.height/2)*.28}px)`});b.addEventListener("pointerleave",()=>b.style.transform="")});
 /* live deploy toasts */
 const N=["Rahul","Aman","Priya","Karan","Sneha","Vikram","Ishaan","Neha","Arjun","Zoya"],T=["Minecraft 4 GB","Rust 10 slots","VPS 8 GB","Bot Starter","Minecraft 8 GB","VPS 16 GB"],C=["Mumbai","Delhi","Pune","Bengaluru","Hyderabad","Kolkata"];
 const tw=document.createElement("div");tw.className="ltoast";document.body.appendChild(tw);
 function show(){const r=a=>a[Math.random()*a.length|0];tw.innerHTML=`<i></i><div><b>${r(N)}</b> from ${r(C)} just deployed<br><span>${r(T)} · ${1+(Math.random()*9|0)} min ago</span></div>`;tw.classList.add("on");setTimeout(()=>tw.classList.remove("on"),4200);setTimeout(show,9000+Math.random()*8000)}
 setTimeout(show,6000);
}
setTimeout(init,120);addEventListener("load",()=>setTimeout(init,300));})();
