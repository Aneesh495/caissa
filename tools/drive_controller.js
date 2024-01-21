// Run this source inside functions.exec with tools available.
// Binary payloads stay in the file adapter. Never print download references.
const root = "/Users/aneeshkrishna/Documents/Codex/2026-10-22/ex/outputs/caissa-chess";
const work = root + "/work/storage-cap-migration-2026-10-27";
const folder = "1VIh5amtHhs1_LXdCDNzAtdOVNtjLW-PC";
const started = Date.now();
const maximumMilliseconds = 500000;
const maximumRequests = 64;
const nonce = String(started);
const progress = { nonce, started_unix: started / 1000, completed_requests: 0 };

async function shell(code) {
  const r = await tools.exec_command({cmd:code,workdir:root,yield_time_ms:10000,max_output_tokens:2500});
  if (r.session_id) throw new Error("Unexpected long metadata helper");
  if (r.exit_code !== 0) throw new Error("Metadata helper failed: " + r.output.slice(-300));
  return r.output;
}
async function newJson(path, value) {
  await tools.apply_patch("*** Begin Patch\n*** Add File: " + path + "\n+" + JSON.stringify(value) + "\n*** End Patch");
}
function result(toolResult) {
  if (toolResult.isError) throw new Error("Drive connector rejected operation");
  if (!toolResult.structuredContent) throw new Error("Drive connector returned no metadata");
  return toolResult.structuredContent;
}
function privateMetadata(meta) {
  return meta.shared === false && Array.isArray(meta.permissions) && meta.permissions.length === 1 && meta.permissions[0].type === "user" && meta.permissions[0].role === "owner";
}
await shell("python3 - <<'PY'\nimport pathlib,json,time,os\nw=pathlib.Path("+JSON.stringify(work)+")\np=w/'drive-bridge/CONTROLLER.lock'\nif p.exists():\n s=json.loads(p.read_bytes())\n assert time.time()>s['expires_unix'],'another Drive controller is still leased'\n p.unlink()\nfd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\nos.write(fd,json.dumps({'nonce':"+JSON.stringify(nonce)+",'expires_unix':time.time()+900}).encode());os.close(fd)\nPY");
let completed = 0;
let last = "";
try {
  const destination = result(await tools.mcp__codex_apps__google_drive_get_file_metadata({fileId:folder,fields:"id,name,mimeType,permissions(type,role),shared"}));
  if (!privateMetadata(destination)) throw new Error("Archive folder privacy could not be verified");
  while (Date.now()-started < maximumMilliseconds && completed < maximumRequests) {
    const state = JSON.parse(await shell("python3 - <<'PY'\nimport pathlib,json\nw=pathlib.Path("+JSON.stringify(work)+")\np=w/'drive-bridge/REQUEST.json';u=w/'DRIVE_ARCHIVE_USAGE.json'\nprint(json.dumps({'request':json.loads(p.read_bytes()) if p.exists() else None,'closed':json.loads(u.read_bytes()).get('closed') if u.exists() else None}))\nPY"));
    if (state.closed === true) break;
    const request = state.request;
    if (!request || request.id === last) {await new Promise(resolve=>setTimeout(resolve,1000));continue;}
    if (!/^\d{7}$/.test(request.id) || request.schema !== "caissa-drive-bridge-v1") throw new Error("Invalid Drive bridge request");
    const exists = await shell("python3 - <<'PY'\nfrom pathlib import Path\nprint(int(Path("+JSON.stringify(work+"/drive-bridge/"+request.id+".response.json")+").exists()))\nPY");
    if (exists.trim() === "1") {last=request.id;continue;}
    let response;
    try {
      if (request.operation === "upload") {
        if (request.folder_id !== folder || request.source_path !== work+"/drive-spool/upload.bin" || !/^[A-Za-z0-9._-]+$/.test(request.file_name) || request.expected_bytes > 33554432 || request.expected_bytes < 1 || !/^[a-f0-9]{64}$/.test(request.expected_sha256)) throw new Error("Unsafe Drive upload request");
        const inspect = JSON.parse(await shell("python3 - <<'PY'\nimport hashlib,pathlib,json\np=pathlib.Path("+JSON.stringify(request.source_path)+");h=hashlib.sha256()\nwith p.open('rb') as f:\n while b:=f.read(1048576):h.update(b)\nprint(json.dumps({'bytes':p.stat().st_size,'sha256':h.hexdigest()}))\nPY"));
        if (inspect.bytes !== request.expected_bytes || inspect.sha256 !== request.expected_sha256) throw new Error("Staged upload bytes changed");
        const upload = result(await tools.mcp__codex_apps__google_drive_upload_file({file_uri:request.source_path,file_name:request.file_name,mime_type:"application/octet-stream",parent_folder_id:folder}));
        const meta = result(await tools.mcp__codex_apps__google_drive_get_file_metadata({fileId:upload.id,fields:"id,name,mimeType,size,parents,permissions(type,role),shared"}));
        if (Number(meta.size)!==request.expected_bytes || !meta.parent_ids?.includes(folder) || !privateMetadata(meta) || meta.mime_type?.startsWith("application/vnd.google-apps.")) throw new Error("Uploaded file metadata/privacy differs");
        response={id:request.id,status:"ok",file_id:meta.id,bytes:Number(meta.size),folder_id:folder,private_owner_only:true};
      } else if (request.operation === "fetch") {
        if (!/^[A-Za-z0-9_-]+$/.test(request.file_id) || request.expected_bytes>33554432 || request.expected_bytes<1) throw new Error("Unsafe Drive readback request");
        const meta = result(await tools.mcp__codex_apps__google_drive_get_file_metadata({fileId:request.file_id,fields:"id,name,mimeType,size,parents,permissions(type,role),shared"}));
        if (Number(meta.size)!==request.expected_bytes || !meta.parent_ids?.includes(folder) || !privateMetadata(meta)) throw new Error("Drive readback metadata/privacy differs");
        const raw = result(await tools.mcp__codex_apps__google_drive_fetch({url:"https://drive.google.com/file/d/"+meta.id+"/view",download_raw_file:true,include_base64:false}));
        if (!raw.file_uri?.download_url || Number(raw.file_size_bytes)!==request.expected_bytes) throw new Error("Authenticated raw readback reference differs");
        response={id:request.id,status:"ok",download_url:raw.file_uri.download_url};
      } else throw new Error("Unsupported Drive bridge operation");
    } catch (error) {
      response={id:request.id,status:"error",error:String(error.message).slice(0,160)};
    }
    await newJson(work+"/drive-bridge/"+request.id+".response.json",response);
    await newJson(work+"/drive-bridge/"+request.id+".controller.json",{id:request.id,operation:request.operation,status:response.status,controller_nonce:nonce,completed_unix:Date.now()/1000});
    completed++;last=request.id;
    if (response.status === "error") break;
  }
} finally {
  await shell("python3 - <<'PY'\nimport pathlib,json\np=pathlib.Path("+JSON.stringify(work+"/drive-bridge/CONTROLLER.lock")+")\nif p.exists() and json.loads(p.read_bytes()).get('nonce')=="+JSON.stringify(nonce)+":p.unlink()\nPY");
}
text({controller_nonce:nonce,completed_requests:completed,seconds:(Date.now()-started)/1000});
