import importlib.util,json,os,platform,shutil,subprocess
from pathlib import Path
result={'os':platform.platform(),'machine':platform.machine(),'logical_cpus':os.cpu_count(),'free_bytes':shutil.disk_usage('.').free,'tools':{tool:shutil.which(tool) for tool in ['cmake','ninja','clang++','git','uv','node','npm']},'writable':os.access('.',os.W_OK),'python':platform.python_version(),'training':None,'data_manifests':[str(p) for p in Path('data').glob('*/CONFIG.json')]}
if importlib.util.find_spec('torch'):
    import torch
    result['training']={'torch':torch.__version__,'mps_built':torch.backends.mps.is_built(),'mps_available':torch.backends.mps.is_available(),'cuda_available':torch.cuda.is_available(),'default_dtype':str(torch.get_default_dtype()),'cpu_bfloat16':'requires workload-specific probe'}
print(json.dumps(result,indent=2))
