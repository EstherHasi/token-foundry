import json
def rgb(h,a=1):
    h=h.lstrip('#'); return {"r":int(h[0:2],16)/255,"g":int(h[2:4],16)/255,"b":int(h[4:6],16)/255,"a":a}
cols=[{"id":"VariableCollectionId:1:0","name":"Primitives","modes":[{"modeId":"1:0","name":"Value"}],"defaultModeId":"1:0"},
      {"id":"VariableCollectionId:2:0","name":"Alias","modes":[{"modeId":"2:0","name":"Mode 1"}],"defaultModeId":"2:0"},
      {"id":"VariableCollectionId:3:0","name":"Mapped","modes":[{"modeId":"3:0","name":"Light"},{"modeId":"3:1","name":"Dark"}],"defaultModeId":"3:0"},
      {"id":"VariableCollectionId:4:0","name":"Responsive","modes":[{"modeId":"4:0","name":"Desktop"},{"modeId":"4:1","name":"Mobile"}],"defaultModeId":"4:0"}]
V=[];n=[0]
def var(col,name,typ,vals,**kw):
    n[0]+=1; vid="VariableID:%d:%d"%(int(col.split(':')[1]),n[0]); V.append(dict(id=vid,name=name,resolvedType=typ,variableCollectionId=col,valuesByMode=vals,scopes=kw.get('scopes',["ALL_SCOPES"]),description=kw.get('d',''),codeSyntax={})); return vid
P="VariableCollectionId:1:0"
ramps={"red":["#FEF2F2","#FEE2E2","#FECACA","#FCA5A5","#F87171","#EF4444","#DC2626","#B91C1C","#991B1B","#7F1D1D"],
       "grey":["#FAFAFA","#F5F5F5","#EDEDED","#E0E0E0","#BDBDBD","#9E9E9E","#757575","#616161","#424242","#212121"],
       "blue":["#EFF6FF","#DBEAFE","#BFDBFE","#93C5FD","#60A5FA","#3B82F6","#2563EB","#1D4ED8","#1E40AF","#1E3A8A"]}
steps=[50,100,200,300,400,500,600,700,800,900]
ids={}
for r,hs in ramps.items():
    for s,h in zip(steps,hs):
        if r=="blue" and s==300: continue  # gap
        ids[f"{r}/{s}"]=var(P,f"color/{r}/{s}","COLOR",{"1:0":rgb(h)})
ids["white"]=var(P,"color/white","COLOR",{"1:0":rgb("#FFFFFF")})
ids["dup"]=var(P,"color/Brand Red","COLOR",{"1:0":rgb("#EF4444")})
for s in [4,8,12,16,24,32]: ids[f"sp{s}"]=var(P,f"spacing/{s}","FLOAT",{"1:0":s})
A="VariableCollectionId:2:0"
al=lambda k:{"type":"VARIABLE_ALIAS","id":ids[k]}
for s in steps:
    ids[f"primary/{s}"]=var(A,f"primary/{s}","COLOR",{"2:0":al(f"red/{s}")})
    ids[f"neutral/{s}"]=var(A,f"neutral/{s}","COLOR",{"2:0":al(f"grey/{s}")})
    if s!=300: ids[f"secondary/{s}"]=var(A,f"secondary/{s}","COLOR",{"2:0":al(f"blue/{s}")})
M="VariableCollectionId:3:0"
def m(name,l,dk,**kw):
    ids[name]=var(M,name,"COLOR",{"3:0":l if isinstance(l,dict) else rgb(l),"3:1":dk if isinstance(dk,dict) else rgb(dk)},**kw)
aa=lambda k:{"type":"VARIABLE_ALIAS","id":ids[k]}
m("surface/primary",aa("white"),aa("neutral/900"),d="Main page canvas")
m("surface/secondary",aa("primary/500"),aa("primary/700"))
m("surface/hover",aa("neutral/200"),aa("neutral/800"))
m("surface/disabled",aa("neutral/200"),aa("neutral/800"))
m("surface/subtle","#F5F5F5",aa("neutral/800"))
m("text/primary",aa("neutral/900"),aa("neutral/50"))
m("text/muted","#717171",aa("neutral/400"))
m("text/on-secondary",aa("white"),aa("white"))
m("border/default",aa("neutral/200"),aa("neutral/700"))
m("border/input",aa("neutral/300"),aa("neutral/600"))
m("red/accent",aa("primary/500"),aa("primary/300"))
ids["onlylight"]=var(M,"text/link","COLOR",{"3:0":aa("secondary/500")})
R="VariableCollectionId:4:0"
var(R,"spacing/md","FLOAT",{"4:0":16,"4:1":12})
var(R,"font/size/body","FLOAT",{"4:0":14,"4:1":14})
var(R,"font/family","STRING",{"4:0":"Open Sans","4:1":"Open Sans"})
import os
os.makedirs("fixtures", exist_ok=True)
json.dump({"format":"token-foundry/figma-export@1","fileName":"Demo design system","collections":[dict(c,variableIds=[]) for c in cols],"variables":V},open("fixtures/figma-variables-demo.json","w"),indent=1)
