"""Scalar interpretation of saved network bytes, independent of training and C++."""
import struct,zlib
from pathlib import Path
import chess
import numpy as np

def infer(path,fen):
    raw=Path(path).read_bytes()
    if len(raw)<120:raise ValueError('truncated independent network input')
    version,feature,nf,width,h1,h2,scale,clip=struct.unpack('<8I',raw[8:40])
    if raw[:8]!=f'CAISSAN{version}'.encode():raise ValueError('network magic/version mismatch')
    if raw[:8] not in [b'CAISSAN1',b'CAISSAN2'] or (feature,nf,h1,h2)!=(1,12288,32,16) or width not in [32,64,128]:raise ValueError('unsupported independent network layout')
    if (version,scale,clip) not in [(1,64,127),(2,1024,2047)]:raise ValueError('unsupported numerical contract')
    length,checksum,reserved=struct.unpack('<QII',raw[104:120])
    if length!=len(raw)-120 or reserved or checksum!=zlib.crc32(raw[120:]):raise ValueError('network payload integrity')
    offset=120
    def take(dtype,rows,columns=1):
        nonlocal offset
        dt=np.dtype(dtype);count=rows*columns;result=np.frombuffer(raw,dtype=dt,count=count,offset=offset).astype(np.int64).reshape(rows,columns);offset+=count*dt.itemsize;return result
    embedding=take('<i2',12288,width);bias=take('<i4',width).reshape(width);board=chess.Board(fen);vectors=[]
    for perspective in [board.turn,not board.turn]:
        king=board.king(perspective)
        if king is None:raise ValueError('king absent in inference probe')
        oriented_king=king if perspective else king^56;bucket=(oriented_king//16)*4+(oriented_king%8)//2;acc=bias.copy()
        for sq,piece in board.piece_map().items():
            relative=0 if piece.color==perspective else 6;oriented=sq if perspective else sq^56
            index=(bucket*12+relative+piece.piece_type-1)*64+oriented;acc+=embedding[index]
        vectors.extend(acc.clip(0,clip).tolist())
    x=np.array(vectors,dtype=np.int64)
    for rows,columns in [(32,width*2),(16,32),(1,16)]:
        weights=take('<i2',rows,columns);biases=take('<i4',rows).reshape(rows);value=weights@x+biases
        if rows==1:
            numerator=int(value[0])*400;denominator=scale*scale
            result=(abs(numerator)+denominator//2)//denominator
            return max(-29871,min(29871,result if numerator>=0 else -result))
        x=(np.sign(value)*((np.abs(value)+scale//2)//scale)).clip(0,clip)
    raise AssertionError('unreachable network output')
