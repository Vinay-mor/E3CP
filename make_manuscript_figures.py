"""Create graphics used by the revised manuscript from actual experiment outputs."""
from pathlib import Path
import argparse
import csv, importlib.util, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="Generate manuscript supporting figures from experiment outputs.")
parser.add_argument("--output-dir", default="experiment_output",
                    help="Experiment output directory containing datasets/seed_42 and results_overall.csv")
args = parser.parse_args()
OUT = Path(args.output_dir).resolve()
SEED42 = OUT/'datasets'/'seed_42'
if not SEED42.exists():
    raise SystemExit(f"Missing {SEED42}; run run_experiments.py with this --output-dir first.")

# Time-series figures from seed 42, trace 0. These are illustrative trace dynamics,
# not aggregate results over the ten master seeds.
spec=importlib.util.spec_from_file_location('e3cp_simulation', HERE/'e3cp_simulation.py')
sim=importlib.util.module_from_spec(spec); sys.modules[spec.name]=sim; spec.loader.exec_module(sim)
sim.POLICY_FN.update({
    'E3CP-NoConsolidation': sim.place_e3cp,
    'First-Fit+Consolidation': sim.place_first_fit,
    'Latency-Aware+Consolidation': sim.place_latency_aware,
    'Min-Energy+Consolidation': sim.place_min_energy,
})
sim.NODES_CSV=str(SEED42/'edge_nodes.csv')
trace_path=SEED42/'container_requests_trace0.csv'
trace=sim.load_requests_by_interval(str(trace_path))
policies=['First-Fit','First-Fit+Consolidation','Latency-Aware','Latency-Aware+Consolidation',
          'Min-Energy','Min-Energy+Consolidation','E3CP-NoConsolidation','E3CP']
series={}
for policy in policies:
    sim.Container._next_id=0
    res=sim.run_one_trace(policy, trace, track_series=True)
    series[policy]=(res['series_energy'],res['series_active'])

labels={p:p.replace('+Consolidation',' + cons.').replace('E3CP-NoConsolidation','E3CP no cons.') for p in policies}
plt.figure(figsize=(7,4.2))
for p in policies:
    plt.plot(range(1,sim.NUM_INTERVALS+1),series[p][0],marker='o',linewidth=1.3,markersize=3,label=labels[p])
plt.xlabel('Simulated interval (10 min each)')
plt.ylabel('Modeled node energy per interval (kWh)')
plt.title('Modeled energy over time (master seed 42, trace 0)')
plt.legend(fontsize=6.3,ncol=2)
plt.tight_layout()
plt.savefig(OUT/'fig_energy_over_time_seed42.png',dpi=180)
plt.close()

plt.figure(figsize=(7,4.2))
for p in policies:
    plt.plot(range(1,sim.NUM_INTERVALS+1),series[p][1],marker='o',linewidth=1.3,markersize=3,label=labels[p])
plt.xlabel('Simulated interval (10 min each)')
plt.ylabel('Powered-on nodes')
plt.title('Active nodes over time (master seed 42, trace 0)')
plt.legend(fontsize=6.3,ncol=2)
plt.tight_layout()
plt.savefig(OUT/'fig_active_nodes_over_time_seed42.png',dpi=180)
plt.close()

# A compact configuration table with the same aspect ratio as the manuscript's existing figure.
W,H=1800,600
im=Image.new('RGB',(W,H),'white'); draw=ImageDraw.Draw(im)
try:
    fhead=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',26)
    fbody=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
except OSError:
    fhead=fbody=ImageFont.load_default()
rows=[
('Edge fleet','30 heterogeneous nodes; six logical regions; 12 image-layer types'),
('Workload generation','10 master seeds (42–51); five workload traces per seed; 12 intervals per trace'),
('Time horizon','Each interval is 10 minutes; two simulated hours per trace; 50 traces total'),
('Policies (8)','First-Fit; Latency-Aware; Min-Energy; E3CP; three baseline+consolidation variants; E3CP without consolidation'),
('Power model','Pᵢ(u)=P_idle,ᵢ+(P_max,ᵢ−P_idle,ᵢ)u²; u=max(CPU, memory, bandwidth utilization)'),
('Latency model','5 + 8|region difference| + 50u′² + 6 ms per missing image layer'),
('E3CP weights','Energy 0.35; latency 0.25; utilization 0.15; layer misses 0.10; density proxy 0.10; reliability 0.05'),
('Consolidation','Underload threshold 20%; migration proxy 0.0006 kWh/container; accepted migration proxy is added to modeled total'),
('Energy accounting','Modeled node power plus migration proxy; excludes network, image-transfer, and sleep/wake energy'),
]
col1=390; rh=H//(len(rows)+1)
draw.rectangle((0,0,W,rh),fill='#dbe7f4',outline='#627b94',width=2)
draw.text((18,13),'Parameter',font=fhead,fill='#102b43')
draw.text((col1+18,13),'Configuration used for the reproducibility evaluation',font=fhead,fill='#102b43')
for i,(a,b) in enumerate(rows,1):
 y=i*rh
 if i%2==0: draw.rectangle((0,y,W,y+rh),fill='#f4f7fb')
 draw.rectangle((0,y,W,y+rh),outline='#9baaba',width=1)
 draw.line((col1,y,col1,y+rh),fill='#9baaba',width=1)
 draw.text((18,y+12),a,font=fbody,fill='#1a2633')
 draw.text((col1+18,y+12),b,font=fbody,fill='#1a2633')
im.save(OUT/'fig_simulation_configuration_multiseed.png')

# A visually clear standalone result table image for convenience and reviewer browsing.
import pandas as pd
overall=pd.read_csv(OUT/'results_overall.csv').set_index('policy')
W,H=2200,880
im=Image.new('RGB',(W,H),'white'); draw=ImageDraw.Draw(im)
try:
    ftitle=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',30)
    fhead=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',22)
    fbody=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
except OSError:
    ftitle=fhead=fbody=ImageFont.load_default()
draw.text((20,10),'Multi-seed results: mean ± SD across ten master-seed means',font=ftitle,fill='#102b43')
cols=[('Policy',330),('Energy kWh',280),('Est. latency ms',300),('SLA failure %',260),('Active nodes',250),('Layer misses',250),('Migrations',220)]
xpos=[0]
for _,w in cols: xpos.append(xpos[-1]+w)
header_y=65; rh=88
for j,(label,w) in enumerate(cols):
 draw.rectangle((xpos[j],header_y,xpos[j+1],header_y+rh),fill='#dbe7f4',outline='#627b94',width=2)
 draw.text((xpos[j]+12,header_y+26),label,font=fhead,fill='#102b43')
for i,p in enumerate(policies,1):
 y=header_y+i*rh
 draw.rectangle((0,y,W,y+rh),fill=('#f4f7fb' if i%2==0 else 'white'),outline='#b1bac5',width=1)
 vals=[p,
       f"{overall.loc[p,'energy_kwh_mean_across_seeds']:.3f} ± {overall.loc[p,'energy_kwh_sd_across_seeds']:.3f}",
       f"{overall.loc[p,'avg_latency_ms_mean_across_seeds']:.2f} ± {overall.loc[p,'avg_latency_ms_sd_across_seeds']:.2f}",
       f"{overall.loc[p,'sla_violation_pct_mean_across_seeds']:.2f} ± {overall.loc[p,'sla_violation_pct_sd_across_seeds']:.2f}",
       f"{overall.loc[p,'avg_active_nodes_mean_across_seeds']:.2f} ± {overall.loc[p,'avg_active_nodes_sd_across_seeds']:.2f}",
       f"{overall.loc[p,'missing_image_layer_events_mean_across_seeds']:.1f} ± {overall.loc[p,'missing_image_layer_events_sd_across_seeds']:.1f}",
       f"{overall.loc[p,'migrations_mean_across_seeds']:.1f} ± {overall.loc[p,'migrations_sd_across_seeds']:.1f}"]
 for j,v in enumerate(vals):
  draw.text((xpos[j]+12,y+28),v,font=fbody,fill='#1a2633')
 for x in xpos: draw.line((x,y,x,y+rh),fill='#b1bac5',width=1)
im.save(OUT/'table_multiseed_results.png')

# Compact revised representative-work comparison; this is qualitative and should not imply superiority.
W,H=1800,510
im=Image.new('RGB',(W,H),'white'); draw=ImageDraw.Draw(im)
try:
    fh=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',21)
    fb=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',19)
except OSError: fh=fb=ImageFont.load_default()
cols=[('Study / method',360),('Main technique',450),('Energy / QoS scope',470),('Relation to E3CP',520)]
x=[0]
for _,w in cols:x.append(x[-1]+w)
rows2=[
('Zhang et al. [1]','Genetic algorithm for CaaS placement','Energy-aware container/VM/PM placement','Shows prior explicit energy-aware placement'),
('Chen et al. [2]','Actor–critic DRL + GCN','Container-cluster placement; energy and service efficiency','Represents learned graph-based placement'),
('Zeng et al. [3]','Graph-aware hybrid reinforcement learning','Joint placement/resource allocation; layer sharing','Addresses layer-aware service placement and latency'),
('Singh et al. [6]','Energy-aware edge container placement','Classifies placement algorithms and migration trade-offs','Motivates migration-aware evaluation'),
('Al-Moalmi et al. [7]','Whale optimization for CaaS','Joint container/VM/PM placement; energy and utilization','Prior metaheuristic energy optimization'),
('Proposed E3CP','Interpretable weighted heuristic + consolidation','Modeled node energy; estimated latency; synthetic trace evaluation','Evaluates placement and consolidation ablations; not claimed universally superior'),
]
rh=H//(len(rows2)+1)
for j,(label,w) in enumerate(cols):
 draw.rectangle((x[j],0,x[j+1],rh),fill='#dbe7f4',outline='#627b94',width=2)
 draw.text((x[j]+8,12),label,font=fh,fill='#102b43')
for i,row in enumerate(rows2,1):
 y=i*rh
 draw.rectangle((0,y,W,y+rh),fill=('#f5f7fa' if i%2==0 else 'white'),outline='#b1bac5',width=1)
 for j,val in enumerate(row):
  draw.text((x[j]+8,y+10),val,font=fb,fill='#1a2633')
  draw.line((x[j],y,x[j],y+rh),fill='#b1bac5',width=1)
im.save(OUT/'fig_related_work_comparison.png')
print('Created manuscript figures in', OUT)
