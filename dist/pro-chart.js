/* Lightweight Charts 5.2.1; bundled locally. UI ranges survive reader refreshes. */
{
 let active=null;
 const fallbackChart=renderLinkedSvg;
 renderLinkedSvg=function(d,p){return window.LightweightCharts?'<div id="professional-chart-slot"></div>':fallbackChart(d,p)};
 function mount(){
  const slot=document.querySelector('#professional-chart-slot'),p=catalog.find(x=>x.id===state.project);
  if(!slot||!p){if(active){active.chart.remove();active=null}return}
  const d=chartCache.get(chartKey(p.id));if(!d)return;
  const key=chartKey(p.id);
  if(active&&active.key!==key){active.chart.remove();active=null}
  const L=window.LightweightCharts;
  if(!active){
   const node=document.createElement('div');node.className='professional-chart';
   node.innerHTML='<div class="chart-crosshair" aria-live="off">移动光标查看 OHLC · 滚轮缩放 / 拖动平移</div><div class="chart-canvas" role="img" aria-label="交互 K 线、成交量与持仓量图"></div><div class="chart-news-preview"></div><p class="module-note chart-oi-status"></p><small class="chart-attribution">TradingView Lightweight Charts™ · Copyright © 2025 TradingView, Inc. <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a></small>';
   slot.append(node);const chart=L.createChart(node.querySelector('.chart-canvas'),{autoSize:true,height:500,layout:{background:{color:'#fffefa'},textColor:'#60746b',attributionLogo:true,panes:{separatorColor:'#e5ede6',enableResize:true}},grid:{vertLines:{color:'#f0f3ee'},horzLines:{color:'#f0f3ee'}},timeScale:{timeVisible:true,secondsVisible:false},localization:{locale:'zh-CN',timeFormatter:t=>new Date(Number(t)*1000).toLocaleString('zh-CN')},rightPriceScale:{borderVisible:false}});
   const candle=chart.addSeries(L.CandlestickSeries,{upColor:'#35846b',downColor:'#bf6866',wickUpColor:'#35846b',wickDownColor:'#bf6866',borderVisible:false,priceFormat:{type:'price',precision:6,minMove:.000001}});
   const ema200=chart.addSeries(L.LineSeries,{color:'#b88b36',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
   const ema360=chart.addSeries(L.LineSeries,{color:'#7770ac',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
   const volume=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},priceLineVisible:false,title:'成交量（代币）'},1);
   const oi=chart.addSeries(L.LineSeries,{color:'#547cb3',lineWidth:2,priceFormat:{type:'volume'},priceLineVisible:false,title:'OI（代币）'},2);
   const markers=L.createSeriesMarkers(candle,[]);
   active={key,node,chart,candle,ema200,ema360,volume,oi,markers,signature:'',buckets:new Map()};
   chart.subscribeCrosshairMove(param=>{if(!active||active.chart!==chart)return;const row=param.seriesData.get(candle);node.querySelector('.chart-crosshair').textContent=row&&row.close!=null?`${new Date(Number(param.time)*1000).toLocaleString('zh-CN')}  开 ${number(row.open)} 高 ${number(row.high)} 低 ${number(row.low)} 收 ${number(row.close)}`:'移动光标查看 OHLC · 滚轮缩放 / 拖动平移';const items=active.buckets.get(Number(param.time))||[];node.querySelector('.chart-news-preview').textContent=items.map(e=>languageText(e,'title')).join(' · ')});
   chart.subscribeClick(param=>{if(!active||active.chart!==chart)return;const items=active.buckets.get(Number(param.time))||[];if(!items.length)return;const rows=chartCache.get(key)?.candles.slice(-80)||[];const index=rows.findIndex(r=>Math.floor(r.time/1000)===Number(param.time));if(index>=0)openChartNews(index)});
  }else slot.append(active.node);
  const rows=d.candles.slice(-80),buckets=new Map();
  if(chartSettings.news)for(const e of events.filter(e=>(e.projectIds||[e.p]).includes(p.id)&&readerEligible(e)&&e.type==='news'&&e.datePrecision!=='day')){const r=rows.find(r=>e.publishedAt>=r.time&&e.publishedAt<=r.closeTime);if(!r)continue;const t=Math.floor(r.time/1000);if(!buckets.has(t))buckets.set(t,[]);buckets.get(t).push(e)}
  active.buckets=buckets;
  const signature=JSON.stringify([d.fetchedAt,chartSettings,[...buckets].map(([t,v])=>[t,v.map(e=>e.id)])]);
  if(signature===active.signature)return;
  const range=active.chart.timeScale().getVisibleLogicalRange();
  active.candle.setData(rows.map(r=>({time:Math.floor(r.time/1000),open:r.open,high:r.high,low:r.low,close:r.close})));
  for(const field of ['ema200','ema360'])active[field].setData(chartSettings[field]?rows.filter(r=>Number.isFinite(r[field])).map(r=>({time:Math.floor(r.time/1000),value:r[field]})):[]);
  active.volume.setData(rows.map(r=>({time:Math.floor(r.time/1000),value:r.volume,color:r.close>=r.open?'#35846b88':'#bf686688'})));
  active.oi.setData((d.oi||[]).filter(r=>r.time>=rows[0]?.time&&r.time<=rows.at(-1)?.closeTime).map(r=>({time:Math.floor(r.time/1000),value:r.value})));
  active.markers.setMarkers([...buckets].sort((a,b)=>a[0]-b[0]).map(([time,items])=>({time,position:'aboveBar',shape:'circle',color:'#215b48',text:String(items.length),id:String(time)})));
  active.node.querySelector('.chart-oi-status').textContent=d.oiStatus==='ok'?'成交量 / OI 为币本位数量；OI 保留供应方实际采样时间，日线历史可能少于 K 线。':'OI 历史暂不可用，副图留空；价格 K 线继续显示。';
  active.chart.panes()[0]?.setHeight(300);active.chart.panes()[1]?.setHeight(90);active.chart.panes()[2]?.setHeight(90);
  if(range)active.chart.timeScale().setVisibleLogicalRange(range);else active.chart.timeScale().fitContent();active.signature=signature;
 }
 const previous=render;render=function(){previous();mount()};render();
}
