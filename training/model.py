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
SCALE=1024
CLIP=2047/1024
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
    def __init__(self,version=2,width=64):
        super().__init__()
        if width not in [32,64,128]:raise ValueError("unsupported active width")
        self.width=width
        self.version=version;self.scale=64 if version==1 else 1024;self.clip=127/64 if version==1 else 2047/1024
        self.embedding=nn.Embedding(FEATURES+1,self.width,padding_idx=FEATURES)
        self.bias0=nn.Parameter(torch.full((self.width,),.25))
        self.dense1=nn.Linear(self.width*2,HIDDEN1)
        self.dense2=nn.Linear(HIDDEN1,HIDDEN2)
        self.output=nn.Linear(HIDDEN2,1)
        with torch.no_grad():
            self.embedding.weight.normal_(0,.03);self.embedding.weight[FEATURES].zero_()
            for layer in [self.dense1,self.dense2,self.output]:
                nn.init.xavier_uniform_(layer.weight);layer.bias.zero_()
    def forward(self,x,quantized=False):
        if quantized:
            emb=ste_round(self.embedding.weight*self.scale)/self.scale
            bias=ste_round(self.bias0*self.scale)/self.scale
            y=torch.nn.functional.embedding(x,emb,padding_idx=FEATURES).sum(dim=2)+bias
            y=ste_round(y.clamp(0,self.clip)*self.scale)/self.scale
        else:y=(self.embedding(x).sum(dim=2)+self.bias0).clamp(0,self.clip)
        y=y.flatten(start_dim=1)
        for layer in [self.dense1,self.dense2]:
            if quantized:
                w=ste_round(layer.weight*self.scale)/self.scale;b=ste_round(layer.bias*self.scale*self.scale)/(self.scale*self.scale)
                y=torch.nn.functional.linear(y,w,b)
                y=ste_round(y.clamp(0,self.clip)*self.scale)/self.scale
            else:y=layer(y).clamp(0,self.clip)
        if quantized:
            w=ste_round(self.output.weight*self.scale)/self.scale;b=ste_round(self.output.bias*self.scale*self.scale)/(self.scale*self.scale)
            return torch.nn.functional.linear(y,w,b).squeeze(-1)
        return self.output(y).squeeze(-1)

def state_hash(model):
    h=hashlib.sha256()
    for key,value in sorted(model.state_dict().items()):
        h.update(key.encode());h.update(value.detach().cpu().numpy().tobytes())
    return h.hexdigest()

def export_network(model,path,identity):
    scale=model.scale;clip=127 if model.version==1 else 2047;bias_limit=(1<<20) if model.version==1 else (1<<28)
    if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('training identity must be SHA256 hex')
    chunks=[]
    def quantize(tensor,scale,dtype,bound):
        values=tensor.detach().cpu().numpy().astype(np.float64)
        if not np.isfinite(values).all():raise ValueError('nonfinite training state')
        q=np.rint(values*scale)
        if np.abs(q).max(initial=0)>bound:raise ValueError('quantized value exceeds arithmetic contract')
        return q.astype(dtype).tobytes()
    chunks.append(quantize(model.embedding.weight[:FEATURES],scale,'<i2',32767))
    chunks.append(quantize(model.bias0,scale,'<i4',bias_limit))
    for layer in [model.dense1,model.dense2,model.output]:
        chunks.append(quantize(layer.weight,scale,'<i2',32767));chunks.append(quantize(layer.bias,scale*scale,'<i4',bias_limit))
    payload=b''.join(chunks)
    header=(b'CAISSAN1' if model.version==1 else b'CAISSAN2')+struct.pack('<8I',model.version,1,FEATURES,model.width,HIDDEN1,HIDDEN2,scale,clip)+identity.encode()+struct.pack('<QII',len(payload),zlib.crc32(payload),0)
    assert len(header)==120
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(header+payload);temp.replace(path)
    return {'sha256':hashlib.sha256(header+payload).hexdigest(),'identity':identity,'crc32':zlib.crc32(payload),'bytes':len(header+payload)}

def integer_reference(path,x):
    """NumPy int64 reference; no calls to native feature or inference functions."""
    raw=Path(path).read_bytes()
    if len(raw)<120 or raw[:8] not in [b'CAISSAN1',b'CAISSAN2']:raise ValueError('invalid network')
    version,fv,nf,width,h1,h2,scale,clip=struct.unpack('<8I',raw[8:40])
    if raw[:8]!=f'CAISSAN{version}'.encode():raise ValueError('magic/version mismatch')
    if (fv,nf,h1,h2)!=(1,FEATURES,HIDDEN1,HIDDEN2) or width not in [32,64,128] or (version,scale,clip) not in [(1,64,127),(2,1024,2047)]:raise ValueError('architecture mismatch')
    size,crc,reserved=struct.unpack('<QII',raw[104:120])
    if reserved or size!=len(raw)-120 or zlib.crc32(raw[120:])!=crc:raise ValueError('network integrity')
    offset=120
    def read(dtype,shape):
        nonlocal offset
        n=math.prod(shape);dt=np.dtype(dtype);v=np.frombuffer(raw,dtype=dt,count=n,offset=offset).reshape(shape).astype(np.int64);offset+=n*dt.itemsize;return v
    emb=read('<i2',(FEATURES,width));emb=np.concatenate([emb,np.zeros((1,width),np.int64)])
    bias=read('<i4',(width,));y=(emb[x].sum(axis=-2)+bias).clip(0,clip).reshape(len(x),width*2)
    for nin,nout in [(width*2,HIDDEN1),(HIDDEN1,HIDDEN2),(HIDDEN2,1)]:
        w=read('<i2',(nout,nin));b=read('<i4',(nout,));z=y@w.T+b
        if nout==1:
            z=z*400;return (np.sign(z)*((np.abs(z)+scale*scale//2)//(scale*scale))).clip(-29871,29871).reshape(-1)
        y=(np.sign(z)*((np.abs(z)+scale//2)//scale)).clip(0,clip)
    raise AssertionError('unreachable')
