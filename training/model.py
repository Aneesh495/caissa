"""Feature-v1 network and export contract, independently defined from native inference."""
import hashlib,json,math,struct,zlib
from pathlib import Path
import numpy as np
import torch
from torch import nn
FEATURES=16*12*64
WIDTH=64
HIDDEN1=32
HIDDEN2=16
SCALE=64
CLIP=127/64
PIECES='PNBRQKpnbrqk'

def features(fen):
    fields=fen.split()
    if len(fields)!=6:raise ValueError('FEN requires six fields')
    pieces=[];r=7;f=0;kings=[None,None]
    for ch in fields[0]:
        if ch=='/':
            if f!=8:raise ValueError('rank width')
            r-=1;f=0
        elif ch in '12345678':f+=int(ch)
        else:
            if ch not in PIECES or not 0<=r<8 or not 0<=f<8:raise ValueError('bad piece')
            sq=r*8+f;pc=PIECES.index(ch);pieces.append((pc,sq))
            if pc in (5,11):kings[pc//6]=sq
            f+=1
    if r!=0 or f!=8 or None in kings or len(pieces)>32:raise ValueError('invalid board')
    output=np.full((2,32),FEATURES,dtype=np.int64)
    for perspective in range(2):
        king=kings[perspective]^(56 if perspective else 0);bucket=((king//8)//2)*4+(king%8)//2
        for i,(pc,sq) in enumerate(pieces):
            relative=int(pc//6!=perspective);oriented=sq^(56 if perspective else 0)
            output[perspective,i]=((bucket*12+relative*6+pc%6)*64)+oriented
    if fields[1]=='b':output=output[[1,0]]
    elif fields[1]!='w':raise ValueError('bad side')
    return output

def ste_round(x):return x+(x.round()-x).detach()
class CaissaNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding=nn.Embedding(FEATURES+1,WIDTH,padding_idx=FEATURES)
        self.bias0=nn.Parameter(torch.full((WIDTH,),.25))
        self.dense1=nn.Linear(WIDTH*2,HIDDEN1)
        self.dense2=nn.Linear(HIDDEN1,HIDDEN2)
        self.output=nn.Linear(HIDDEN2,1)
        with torch.no_grad():
            self.embedding.weight.normal_(0,.03);self.embedding.weight[FEATURES].zero_()
            for layer in [self.dense1,self.dense2,self.output]:
                nn.init.xavier_uniform_(layer.weight);layer.bias.zero_()
    def forward(self,x,quantized=False):
        if quantized:
            emb=ste_round(self.embedding.weight*SCALE)/SCALE
            bias=ste_round(self.bias0*SCALE)/SCALE
            y=torch.nn.functional.embedding(x,emb,padding_idx=FEATURES).sum(dim=2)+bias
            y=ste_round(y.clamp(0,CLIP)*SCALE)/SCALE
        else:y=(self.embedding(x).sum(dim=2)+self.bias0).clamp(0,CLIP)
        y=y.flatten(start_dim=1)
        for layer in [self.dense1,self.dense2]:
            if quantized:
                w=ste_round(layer.weight*SCALE)/SCALE;b=ste_round(layer.bias*SCALE*SCALE)/(SCALE*SCALE)
                y=torch.nn.functional.linear(y,w,b)
                y=ste_round(y.clamp(0,CLIP)*SCALE)/SCALE
            else:y=layer(y).clamp(0,CLIP)
        if quantized:
            w=ste_round(self.output.weight*SCALE)/SCALE;b=ste_round(self.output.bias*SCALE*SCALE)/(SCALE*SCALE)
            return torch.nn.functional.linear(y,w,b).squeeze(-1)
        return self.output(y).squeeze(-1)

def state_hash(model):
    h=hashlib.sha256()
    for key,value in sorted(model.state_dict().items()):
        h.update(key.encode());h.update(value.detach().cpu().numpy().tobytes())
    return h.hexdigest()

def export_network(model,path,identity):
    if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('training identity must be SHA256 hex')
    chunks=[]
    def quantize(tensor,scale,dtype,bound):
        values=tensor.detach().cpu().numpy().astype(np.float64)
        if not np.isfinite(values).all():raise ValueError('nonfinite training state')
        q=np.rint(values*scale)
        if np.abs(q).max(initial=0)>bound:raise ValueError('quantized value exceeds arithmetic contract')
        return q.astype(dtype).tobytes()
    chunks.append(quantize(model.embedding.weight[:FEATURES],64,'<i2',32767))
    chunks.append(quantize(model.bias0,64,'<i4',1<<20))
    for layer in [model.dense1,model.dense2,model.output]:
        chunks.append(quantize(layer.weight,64,'<i2',32767));chunks.append(quantize(layer.bias,4096,'<i4',1<<20))
    payload=b''.join(chunks)
    header=b'CAISSAN1'+struct.pack('<8I',1,1,FEATURES,WIDTH,HIDDEN1,HIDDEN2,SCALE,127)+identity.encode()+struct.pack('<QII',len(payload),zlib.crc32(payload),0)
    assert len(header)==120
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(header+payload);temp.replace(path)
    return {'sha256':hashlib.sha256(header+payload).hexdigest(),'identity':identity,'crc32':zlib.crc32(payload),'bytes':len(header+payload)}

def integer_reference(path,x):
    """NumPy int64 reference; no calls to native feature or inference functions."""
    raw=Path(path).read_bytes()
    if len(raw)<120 or raw[:8]!=b'CAISSAN1':raise ValueError('invalid network')
    if tuple(struct.unpack('<8I',raw[8:40]))!=(1,1,FEATURES,WIDTH,HIDDEN1,HIDDEN2,64,127):raise ValueError('architecture mismatch')
    size,crc,reserved=struct.unpack('<QII',raw[104:120])
    if reserved or size!=len(raw)-120 or zlib.crc32(raw[120:])!=crc:raise ValueError('network integrity')
    offset=120
    def read(dtype,shape):
        nonlocal offset
        n=math.prod(shape);dt=np.dtype(dtype);v=np.frombuffer(raw,dtype=dt,count=n,offset=offset).reshape(shape).astype(np.int64);offset+=n*dt.itemsize;return v
    emb=read('<i2',(FEATURES,WIDTH));emb=np.concatenate([emb,np.zeros((1,WIDTH),np.int64)])
    bias=read('<i4',(WIDTH,));y=(emb[x].sum(axis=-2)+bias).clip(0,127).reshape(len(x),WIDTH*2)
    for nin,nout in [(WIDTH*2,HIDDEN1),(HIDDEN1,HIDDEN2),(HIDDEN2,1)]:
        w=read('<i2',(nout,nin));b=read('<i4',(nout,));z=y@w.T+b
        if nout==1:
            z=z*400;return (np.sign(z)*((np.abs(z)+2048)//4096)).clip(-29871,29871).reshape(-1)
        y=(np.sign(z)*((np.abs(z)+32)//64)).clip(0,127)
    raise AssertionError('unreachable')
