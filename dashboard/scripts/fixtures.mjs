import { readFileSync, writeFileSync } from 'node:fs';
import YAML from 'yaml';
const site = YAML.parse(readFileSync(new URL('../../config/site.yaml', import.meta.url), 'utf8'));
const dir = new URL('../public/', import.meta.url);
writeFileSync(new URL('site.json', dir), JSON.stringify(site, null, 2));
const names = ['Oat milk, original','Almond milk','Barista oat','Whole milk','Soy drink','Organic granola','Cocoa oat bar','Wildflower honey','Almond butter','Breakfast oats','Sparkling water','Cold brew coffee','Green tea','Apple juice','Ginger shot','Sea salt crisps','Roasted almonds','Dark chocolate','Trail mix','Protein bar'];
const products = names.map((name, i) => ({product_id:`SKU-${String(i+1).padStart(3,'0')}`, name, brand:['Fieldwork','Common Good','Daily'][i%3], barcode:`5000000000${String(i+1).padStart(3,'0')}`, price_gbp:Math.round((1.8+i*.21)*100)/100, zone_id:`aisle-A-shelf-${Math.floor(i/5)+1}`}));
writeFileSync(new URL('products.json', dir), JSON.stringify(products, null, 2));
const rows = []; let id = 0;
const at = t => new Date(Date.parse('2026-11-01T16:30:00Z')+t*1000).toISOString();
const emit = (t,kind,data) => rows.push({t,msg:{kind,data}});
const event = (t,type,productIndex,extra={}) => { const p = products[productIndex]; emit(t,'event',{event_id:`demo-${++id}`,ts:at(t),site_id:site.site_id,zone_id:p.zone_id,type,product_id:p.product_id,x:1.1+(productIndex/5)*.68,y:1.2+(id%4)*.12,z:0,source:'camera-1',track_id:`anon-${id%4}`,confidence:.91,payload:type==='look'?{duration_s:2.4+id%4,gaze_hit_xyz:[1.1+Math.floor(productIndex/5)*.75+(id%5)*.12,2, .35+(id%4)*.33]}:{},...extra}); };
const drone = (t,state,x,y,bay=null,decision=null) => emit(t,'drone',{ts:at(t),mode:'sim',state,x,y,z:state==='IDLE'||state==='LAND'?0:1.5,yaw_deg:0,battery_pct:Math.round(94-t*.12),current_bay:bay,last_decision:decision,stop_requested:false,mission_id:'demo-patrol-1',feed_url:null});
drone(0,'IDLE',5,5);
for(let i=0;i<38;i++){ const t=i*.12; event(t,'pass_by',i%3===0?0:6); event(t+.03,'look',i%3===0?0:6); if(i%3===0)event(t+.05,'interest',6); }
for(let i=0;i<7;i++){ event(2+i*.3,'pick_up',6); event(2.1+i*.3,'put_back',6,{decision:{question:'reach_outcome',answer:{choice:'put_back'},policy:i===5?'review':'auto'},confidence:i===5?.67:.94}); }
for(let i=0;i<4;i++){event(3+i*.5,'pick_up',0);event(3.1+i*.5,'kept',0,{decision:{question:'reach_outcome',answer:{choice:'kept'},policy:'auto'}});}
drone(4,'TAKEOFF',5,5); drone(7,'GOTO_BAY',3,6);drone(10,'INSPECT',1.25,6.5,'bay-B-01',{bay_issue:'none',confidence:.96});
for(let i=0;i<40;i++){const t=5+i*1.2;event(t,'look',[0,6,10,15][i%4]);if(i%3===0)event(t+.2,'interest',6);}
drone(14,'GOTO_BAY',2.5,6.5);drone(17,'INSPECT',3.75,6.5,'bay-B-02',{bay_issue:'empty',severity:'act_now',confidence:.97});
emit(18,'event',{event_id:'bay-empty',ts:at(18),site_id:site.site_id,zone_id:'bay-B-02',type:'bay_issue',x:3.75,y:8.6,z:1.5,source:'drone-1',confidence:.97,decision:{question:'bay_issue',answer:{choice:'empty'},policy:'auto'},payload:{issue:'empty',severity:'act_now'}});
emit(19,'task',{task_id:'task-restock',created_at:at(19),zone_id:'bay-B-02',kind:'restock',severity:2.8,status:'open',source_event:'bay-empty',assignee:null,note:'Empty lower pick face. Replenish from reserve stock before next pick.'});
drone(24,'INSPECT',6.25,6.5,'bay-B-03',{bay_issue:'misplaced',severity:'act_today',confidence:.92});
emit(25,'event',{event_id:'bay-misplaced',ts:at(25),site_id:site.site_id,zone_id:'bay-B-03',type:'bay_issue',x:6.25,y:8.6,z:1.5,source:'drone-1',confidence:.92,decision:{question:'bay_issue',answer:{choice:'misplaced'},policy:'auto'},payload:{issue:'misplaced',severity:'act_today'}});
emit(26,'task',{task_id:'task-move',created_at:at(26),zone_id:'bay-B-03',kind:'move',severity:1.9,status:'open',source_event:'bay-misplaced',assignee:null,note:'Carton does not match its location label. Verify and move to assigned bay.'});
drone(32,'INSPECT',8.75,6.5,'bay-B-04',{bay_issue:'none',confidence:.95});
for(const [t,bay] of [[10,'bay-B-01'],[17,'bay-B-02'],[24,'bay-B-03'],[32,'bay-B-04']]) emit(t,'event',{event_id:`patrol-${bay}`,ts:at(t),site_id:site.site_id,zone_id:bay,type:'patrol',source:'drone-1',confidence:1,payload:{state:'INSPECT',bay}});
drone(42,'RETURN',7,6);drone(48,'LAND',5,5);drone(60,'IDLE',5,5);
rows.sort((a,b)=>a.t-b.t);writeFileSync(new URL('demo.jsonl',dir), rows.map(r=>JSON.stringify(r)).join('\n')+'\n');
console.log('Static site, mock catalogue, and 60-second replay generated.');
