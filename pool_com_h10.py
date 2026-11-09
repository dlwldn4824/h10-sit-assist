"""카메라 CoM + H10을 함께 잰 세 세트(60회)를 합쳐 상관과 H10 추정 CoM 일치도를 계산하고 그림을 그린다.

    python pool_com_h10.py

입력: results/video/1107b/all_sits_1107_all.csv, results/video/1107c/IMG_2334_pose_sits.csv, data/video/h10_*.csv
출력: results/video/pooled_sits.csv, presentation/assets/camcom/pooled_*.png (사람 데이터라 커밋하지 않음)
"""
import sys, numpy as np, pandas as pd
from scipy.stats import spearmanr, pearsonr
from pathlib import Path
R=str(Path(__file__).resolve().parent); sys.path.insert(0,R)
from sit_assist import h10_com_dx
from preprocess_h10 import to_100hz
V=R+'/results/video/'
a=pd.read_csv(V+'1107b/all_sits_1107_all.csv'); b=pd.read_csv(V+'1107c/IMG_2334_pose_sits.csv')
d=pd.concat([a,b],ignore_index=True)
logmap={'IMG_2330_pose':'h10_1107_set.csv','IMG_2331_pose':'h10_1107_set.csv','IMG_2332_pose':'h10_1107_log1full.csv','IMG_2333_pose':'h10_1107_log2.csv','IMG_2334_pose':'h10_1107_B30.csv'}
logs={f:to_100hz(pd.read_csv(R+'/data/video/'+f)) for f in set(logmap.values())}
est=[]
for _,r in d.iterrows():
    L=logs[logmap[r.source]]; i=int(round(r.h10_contact_t*100)); i=min(max(i,0),len(L)-1)
    th=(L.thigh_l_deg.iloc[i]+L.thigh_r_deg.iloc[i])/2; tk=L.trunk_deg.iloc[i]
    est.append(h10_com_dx(th,tk,17.0))
d['h10_com']=est
d['group']=d.chair.map(lambda c:'두 번째 피험자 30 cm' if c.startswith('B') else ('첫 번째 피험자 '+c[:5]))
d['type']=d.chair.map(lambda c:'털썩' if '털썩' in c else '그냥')
d=d.dropna(subset=['dx_contact'])
print(d.groupby(['group','type']).size())
for col in ['h10_peak_lean','h10_acc_peak','h10_w_peak','h10_contact_vel']:
    rho,p=spearmanr(d[col],d.dx_contact,nan_policy='omit'); s=f'{col}: pooled n={d[col].notna().sum()} rho={rho:.2f} p={p:.1e} |'
    for g,gg in d.groupby('group'):
        rr,pp=spearmanr(gg[col],gg.dx_contact,nan_policy='omit'); s+=f' {g[:8]}{g[-5:]} {rr:.2f}({pp:.3f})'
    print(s)
r,p=pearsonr(d.h10_com,d.dx_contact); print('H10 CoM est pooled r=%.2f p=%.1e'%(r,p))
for g,gg in d.groupby('group'): print('  ',g, 'r=%.2f'%pearsonr(gg.h10_com,gg.dx_contact)[0], 'n',len(gg))
print(d.groupby(['group','type'])[['dx_contact','h10_peak_lean','h10_acc_peak','h10_w_peak','h10_com']].mean().round(2))
OUT=R+'/results/video/pooled_sits.csv'; d.to_csv(OUT,index=False)

# ---- 그림 ----
import matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.lines import Line2D
fm.fontManager.addfont('/System/Library/Fonts/AppleSDGothicNeo.ttc')
plt.rcParams['font.family']='Apple SD Gothic Neo'; plt.rcParams['axes.unicode_minus']=False
d=pd.read_csv(OUT); A=R+'/presentation/assets/camcom/'
MK={'첫 번째 피험자 45 cm':'o','첫 번째 피험자 30 cm':'s','두 번째 피험자 30 cm':'^'}
CL={'그냥':'#8a8f8c','털썩':'#d64545'}
def sc(ax,x):
    for (g,t),gg in d.groupby(['group','type']):
        ax.scatter(gg[x],gg.dx_contact,marker=MK[g],s=55,c=CL[t],edgecolors='white',linewidths=0.8,alpha=0.9,zorder=3)
    ax.spines[['top','right']].set_visible(False); ax.grid(alpha=.25); ax.tick_params(labelsize=12)
def legend(ax,loc):
    h=[Line2D([],[],marker=m,ls='',color='#555',ms=9,label=g) for g,m in MK.items()]+[Line2D([],[],marker='o',ls='',color=c,ms=9,label=('털썩 주저앉기' if t=='털썩' else '그냥 앉기')) for t,c in CL.items()]
    ax.legend(handles=h,frameon=False,fontsize=11,loc=loc)
# fig A
fig,ax=plt.subplots(1,3,figsize=(15,4.6),dpi=170)
for a,(col,lab) in zip(ax,[('h10_peak_lean','H10 최대 상체 숙임 (°)'),('h10_acc_peak','H10 착석 충격 (m/s²)'),('h10_w_peak','H10 최대 허벅지 속도 (°/s)')]):
    sc(a,col); rho,p=spearmanr(d[col],d.dx_contact)
    a.set_xlabel(lab,fontsize=14); a.set_title('(%s)'%'abc'[list(ax).index(a)],fontsize=14,loc='left',fontweight='bold'); print(col,f'ρ = {rho:.2f}, p = {p:.1e}')
ax[0].set_ylabel('카메라 CoM–발목 거리\n(착석 순간, 다리 길이 배)',fontsize=13)
h=[Line2D([],[],marker=m,ls='',color='#555',ms=9,label=g) for g,m in MK.items()]+[Line2D([],[],marker='o',ls='',color=c,ms=9,label=('털썩 주저앉기' if t=='털썩' else '그냥 앉기')) for t,c in CL.items()]
fig.legend(handles=h,frameon=False,fontsize=13,loc='upper center',ncol=5)
fig.tight_layout(rect=[0,0,1,0.9]); fig.savefig(A+'pooled_h10_vs_com.png',facecolor='white')
# fig B
fig,ax=plt.subplots(1,2,figsize=(12,5),dpi=170,gridspec_kw={'width_ratios':[1.3,1]})
sc(ax[0],'h10_com'); lo,hi=-0.85,0.05; ax[0].plot([lo,hi],[lo,hi],'--',color='#999',lw=1); ax[0].set_xlim(lo,hi); ax[0].set_ylim(lo,hi)
r,_=pearsonr(d.h10_com,d.dx_contact); ax[0].set_title('(a)',fontsize=14,loc='left',fontweight='bold'); print(f'r = {r:.2f}')
ax[0].set_xlabel('H10만으로 추정한 CoM–발목 거리',fontsize=13); ax[0].set_ylabel('카메라 CoM–발목 거리',fontsize=13); legend(ax[0],'upper left')
gs=list(MK.keys()); rs=[pearsonr(d[d.group==g].h10_com,d[d.group==g].dx_contact)[0] for g in gs]
b=ax[1].bar(range(3),rs,color=['#3f9d63','#3f9d63','#9ec9ad'],width=0.6)
for i,v in enumerate(rs): ax[1].text(i,v+0.02,f'{v:.2f}',ha='center',fontsize=15,fontweight='bold')
ax[1].set_xticks(range(3)); ax[1].set_xticklabels([g.replace(' 피험자 ','\n') for g in gs],fontsize=12); ax[1].set_ylim(0,1.08)
ax[1].set_title('(b)',fontsize=14,loc='left',fontweight='bold'); ax[1].spines[['top','right']].set_visible(False); ax[1].grid(axis='y',alpha=.25)
fig.tight_layout(); fig.savefig(A+'pooled_h10_com_est.png',facecolor='white')
pl=d[d.type=='털썩']; print('plop cam %.2f est %.2f'%(pl.dx_contact.mean(),pl.h10_com.mean()))
