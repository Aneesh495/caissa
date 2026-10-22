"""Pure feature identities shared by data preparation, without training imports."""
import hashlib
import numpy as np
FEATURES=16*12*64
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

def input_identity(fen):
    """Normalize the mover to white; castling, EP and clocks are absent inputs."""
    parts=fen.split()
    if len(parts)!=6 or parts[1] not in ['w','b']:raise ValueError('invalid input identity FEN')
    placement=parts[0]
    if parts[1]=='b':placement='/'.join(rank.swapcase() for rank in placement.split('/')[::-1])
    return hashlib.sha256(placement.encode('ascii')).digest()
