import sys
rows=["ABCDEFG","HIJKLMN","OPQRSTU","VWXYZ01","23456789"]
ys=[400,483,566,649,732]
pos={}
for r,y in zip(rows,ys):
    seg=520/len(r)
    for i,c in enumerate(r): pos[c]=(1248+77+seg*(i+.5),y)
pos[" "]=(1248+206,816); pos["."]=(1248+466,816)
text=sys.argv[1]
print(" ".join("mousemove %d %d click 1 sleep 0.12"%pos[c] for c in text))
