"""A bounded UCI process owner. The arena, not this client, judges chess legality."""
import queue,subprocess,threading,time
class EngineFailure(RuntimeError):pass
class UciClient:
    def __init__(self,command,options,timeout=10,warmup_nodes=0):
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
        self.lines=queue.Queue(maxsize=10000);self.timeout=timeout
        def reader():
            try:
                for line in self.process.stdout:
                    if len(line)>16384:break
                    try:self.lines.put(line.strip(),timeout=1)
                    except queue.Full:break
            finally:
                try:self.lines.put(None,timeout=.1)
                except queue.Full:pass
        self.reader=threading.Thread(target=reader,daemon=True);self.reader.start()
        try:
            self.send('uci');self.until('uciok',timeout)
            for name,value in options.items():
                if any(c in str(name)+str(value) for c in '\r\n\0'):raise ValueError('invalid option delimiter')
                self.send(f'setoption name {name} value {str(value).lower() if isinstance(value,bool) else value}')
            self.send('isready');self.until('readyok',timeout)
            self.warmup_ms=0.
            if warmup_nodes:
                start=time.monotonic_ns();self.send('position startpos');self.send(f'go nodes {warmup_nodes}');self.until('bestmove ',timeout)
                self.warmup_ms=(time.monotonic_ns()-start)/1e6
                self.send('ucinewgame');self.send('isready');self.until('readyok',timeout)
        except BaseException:self.close();raise
    def send(self,line):
        if len(line)>8192:raise EngineFailure('command too long')
        try:self.process.stdin.write(line+'\n');self.process.stdin.flush()
        except (BrokenPipeError,OSError) as e:raise EngineFailure('engine pipe closed') from e
    def until(self,prefix,timeout):
        deadline=time.monotonic()+timeout;lines=[]
        while True:
            try:line=self.lines.get(timeout=max(.001,deadline-time.monotonic()))
            except queue.Empty as e:raise EngineFailure('engine response timeout') from e
            if line is None:raise EngineFailure('engine exited')
            lines.append(line)
            if len(lines)>5000:raise EngineFailure('engine output flood')
            if line.startswith(prefix):return lines
            if time.monotonic()>deadline:raise EngineFailure('engine response timeout')
    def play(self,initial,moves,nodes=None,milliseconds=None):
        self.send('position fen '+initial+(' moves '+' '.join(moves) if moves else ''))
        command=f'go nodes {nodes}' if nodes is not None else f'go movetime {milliseconds}'
        start=time.monotonic_ns();self.send(command)
        lines=self.until('bestmove ',max(2.,(milliseconds or 0)/1000+1))
        elapsed=(time.monotonic_ns()-start)/1e6
        return lines[-1].split()[1],elapsed,lines
    def close(self):
        p=self.process
        if p.poll() is None:
            try:self.send('stop');self.send('quit');p.wait(timeout=.5)
            except (EngineFailure,subprocess.TimeoutExpired):p.kill();p.wait(timeout=2)
        for stream in [p.stdin,p.stdout]:
            if stream:stream.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
