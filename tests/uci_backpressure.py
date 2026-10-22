"""An unread output pipe must not make stop/quit deadlock."""
import argparse,subprocess,tempfile,time
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--engine',default='build/caissa');a=ap.parse_args();Path('runs').mkdir(exist_ok=True)
    with tempfile.TemporaryFile('w+',dir='runs') as commands:
        commands.write('uci\nposition startpos\ngo infinite\n'+'isready\n'*100000+'stop\nquit\n');commands.seek(0)
        process=subprocess.Popen([a.engine],stdin=commands,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        start=time.monotonic()
        # Intentionally wait without draining stdout. A bounded overload exit is valid.
        process.wait(timeout=5)
        if process.returncode not in [0,2]:raise ValueError('unexpected backpressure exit '+str(process.returncode))
        stdout,stderr=process.communicate(timeout=1)
        if len(stdout)>256*1024:raise ValueError('unbounded protocol output was retained')
        print({'status':'passed','exit':process.returncode,'seconds':time.monotonic()-start,'retained_output_bytes':len(stdout),'stderr':stderr.decode()})
if __name__=='__main__':main()
