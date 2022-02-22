"""Real loader rejection subprocesses for structurally distinct format faults."""
import argparse,hashlib,json,struct,subprocess,tempfile
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');ap.add_argument('--network',required=True,type=Path);a=ap.parse_args();raw=a.network.read_bytes();results=[]
    Path('runs').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='network-format-',dir='runs') as directory:
        cases={'truncated':raw[:-1],'trailing':raw+b'X','wrong-feature':raw[:12]+struct.pack('<I',99)+raw[16:],'wrong-width':raw[:20]+struct.pack('<I',32)+raw[24:],'wrong-scale':raw[:32]+struct.pack('<I',17)+raw[36:],'wrong-checksum':raw[:112]+struct.pack('<I',struct.unpack('<I',raw[112:116])[0]^1)+raw[116:]}
        damaged=bytearray(raw);damaged[120]^=1;cases['corrupt-weights']=bytes(damaged)
        for name,data in cases.items():
            path=Path(directory)/(name+'.cai');path.write_bytes(data);r=subprocess.run([a.engine,'--net-probe',str(path)],input='',capture_output=True,text=True,timeout=5)
            if r.returncode==0:raise ValueError('native loader accepted '+name)
            results.append({'case':name,'exit':r.returncode,'reason':r.stderr.strip()})
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
