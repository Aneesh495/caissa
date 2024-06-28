"""Independent fresh served-build, browser flow and native-response acceptance."""

import copy
import hashlib
import json
from pathlib import Path
import zipfile

import chess
from verification.browser import cells, frames, tree, STEPS


def require(value, reason):
    if not value:
        raise ValueError(reason)


def inspect(data, expected):
    browser, network, assets, build = (data[k] for k in ['browser', 'network', 'assets', 'build'])
    require(browser['errors'] == data['errors'] == [] and browser.get('full_acceptance', False) is False, 'browser error or unsupported acceptance claim')
    require(0 < browser['elapsed_ms'] < 270000 and len(browser['records']) == 56, 'fresh final browser sample incomplete')
    require(build['status'] == 'compiled' and build['typescript'] == '7.0.2' and build['types_node'] == '25.9.5' and build['node'] == expected['node_version'], 'actual final compiler/type/runtime differs')
    for name, digest in expected['compiled_source_inputs'].items():require(build['source_inputs'].get(name) == digest, 'actual final build source graph differs')
    require(build['outputs'] == expected['build_outputs'] and len(build['outputs']) == 8, 'actual final compiled output differs')
    require([g['stage'] for g in data['groups']] == ['build', 'capture'] and all(g['group_absent_after_reap'] is True for g in data['groups']), 'final browser process groups survived')
    edited = chess.Board();edited.push_uci('e2e3');edited_fen = edited.fen(en_passant='fen')
    required_paths = {('g1f3',), ('g1f3', 'd7d5'), ('g1f3', 'd7d5', 'g2g3'), ('d2d4',), ('d2d4', 'g8f6'), ('e2e3',)}
    native_lines, completed, served = 0, 0, 0
    for mode in ['classical', 'neural']:
        for width in [1366, 375]:
            rows = [r for r in browser['records'] if r['mode'] == mode and r['width'] == width]
            require([r['name'] for r in rows] == STEPS, 'final browser action sequence differs')
            by_name = {r['name']: r for r in rows}
            for row in rows:
                name = row['name']
                if name in {'cancel-reaped', 'navigation-reaped'}:
                    require(row['health'] == {'positions': 0, 'analyses': 0}, 'final cancellation/navigation worker not reaped');continue
                if name == 'stale-session':
                    require(type(row['status']) is int and row['status'] == 403 and 'token' in json.loads(row['body'])['error'], 'final stale session accepted');continue
                require(row['scrollWidth'] <= row['innerWidth'] == width, 'final constrained browser overflow')
                fen = chess.STARTING_FEN if name in {'fresh', 'import', 'position-change', 'malformed-fen'} else edited_fen
                require(row['fen'] == fen if name != 'malformed-fen' else row['error'] is True and 'Invalid' in row['status'], 'final browser position/error differs')
                cells(row, fen)
                label = 'classical' if mode == 'classical' else 'experimental neural blend (10%)'
                require(row['engine'] == 'Caissa · '+label+' evaluation', 'final visible evaluator differs')
            require(by_name['keyboard-edit']['focus'] == 'e3', 'final keyboard destination focus lost')
            require(by_name['position-change']['nodes'] == '0' and by_name['position-change']['depth'] == '0 / 0' and by_name['position-change']['lines'] == [] and by_name['position-change']['nps'] == '0', 'final stale analysis leaked')
            require(type(by_name['cancel']['elapsed_ms']) is int and 0 <= by_name['cancel']['elapsed_ms'] < 1500, 'final UI cancellation exceeded original deadline')
            for name in ['export', 'final-export']:
                game, paths = tree(by_name[name]['pgn']);require(paths == required_paths and game.variations[0].move.uci() == 'e2e3', 'final variation/export changed')
            require(by_name['export']['pgn'] == by_name['final-export']['pgn'], 'final persistence changed exported PGN')
            saved = json.loads(by_name['restored']['storage']);require(saved['version'] == 2 and saved['path'] == ['e2e3'] and tree(saved['pgn'])[1] == required_paths, 'final persisted tree/selection differs')
            selected = [r for r in network if r['mode'] == mode and r['width'] == width]
            sessions = [json.loads(r['body']) for r in selected if r['url'] == '/api/session' and 'body' in r]
            require(len({s['token'] for s in sessions}) >= 2 and all(s['networkSha256'] == (expected['network_sha256'] if mode == 'neural' else None) for s in sessions), 'final service restart or selected model identity differs')
            responses = [r for r in selected if r['url'] == '/api/analyze' and r.get('transport_complete') is True and 'event: bestmove' in r.get('body', '') and json.loads(r['request'])['milliseconds'] == 3000]
            require(len(responses) == 1, 'final completed native response missing or duplicated')
            response = responses[0];request = json.loads(response['request'])
            require(request['threads'] == 1 and request['hash'] == 16 and request['multipv'] == 5 and request['inspect'] is True, 'actual final browser native resources differ')
            board = chess.Board(request['fen'], chess960=request['chess960'])
            for text in request['moves']:
                move = chess.Move.from_uci(text);require(move in board.legal_moves, 'final browser submitted illegal history');board.push(move)
            stream = frames(response['body']);require(stream[0][0] == 'started' and stream[0][1]['networkSha256'] == (expected['network_sha256'] if mode == 'neural' else None) and not any(k == 'error' for k, _ in stream), 'final native stream source/model/error differs')
            latest = {};statistics = []
            for event, value in stream:
                if event == 'info':
                    latest[value.get('multipv', 1)] = value;position = board.copy()
                    for text in value.get('pv', []):
                        move = chess.Move.from_uci(text);require(move in position.legal_moves, 'final native principal variation illegal');position.push(move)
                    native_lines += 1
                elif event == 'bestmove':require(chess.Move.from_uci(value['move']) in board.legal_moves, 'final native best move illegal')
                elif event == 'statistics':statistics.append(value)
            require(len(statistics) == 1 and (statistics[0]['neural_evaluations'] > 0 if mode == 'neural' else statistics[0]['neural_evaluations'] == 0), 'final requested evaluator not actually used')
            visible = [f'{rank}. '+ ' '.join(value.get('pv', []))+(' ('+value['bound']+')' if value.get('bound') else '') for rank, value in sorted(latest.items())]
            require(visible and by_name['analysis']['lines'] == visible and by_name['analysis']['state'] == 'READY', 'final displayed native variations differ')
            completed += 1
            for route, name in [('/', 'product/web/index.html'), ('/style.css', 'product/web/style.css'), ('/app.js', 'product/dist/web/app.js')]:
                captures = [a for a in assets if a['mode'] == mode and a['width'] == width and a['path'] == route]
                require(len(captures) == 2, 'final served asset response body missing')
                for asset in captures:
                    body = asset['body'].encode();require(asset['status'] == 200 and len(body) == asset['bytes'] and hashlib.sha256(body).hexdigest() == asset['sha256'] == expected['served_hashes'][name], 'served compiled/source asset bytes differ')
                    served += 1
    events = data['process_events'];started = [e for e in events if e['event'] == 'started'];closed = [e for e in events if e['event'] == 'closed']
    key = lambda e: (e['kind'], e['parent'], e['pid'], e['index'])
    require(len(started) == len(closed) and {key(e) for e in started} == {key(e) for e in closed}, 'final native/service/browser process not reaped')
    require(all(type(e['code']) is int and e['code'] == 0 and e['signal'] is None for e in closed), 'final owned process exited abnormally')
    service_ids = {e['pid'] for e in started if e['kind'] == 'service'};engines = [e for e in started if e['kind'] == 'engine']
    require(len(service_ids) == 6 and sum(e['kind'] == 'browser' for e in started) == 1 and 4 <= len(engines) <= 192, 'final process inventory differs')
    require(all(e['parent'] in service_ids and e['command'] == expected['engine_path'] for e in engines), 'final native actor or service ownership differs')
    return {'contexts': 4, 'board_states': 44, 'completed_native_responses': completed, 'native_pv_lines': native_lines, 'served_asset_bodies': served, 'served_compiled_js_bodies': 8, 'native_starts': len(engines), 'native_exits': len(engines), 'services': 6, 'browser_starts': 1, 'all_processes_closed': True}


def verify(output, scope):
    def doc(name):return json.loads((output/name).read_text())
    require(scope['engine_sha256'] == '1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897' and scope['network_sha256'] == '52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7', 'final browser replaced the frozen actor')
    for name, digest in scope['native_source_hashes'].items():
        target = Path(scope['root'])/name
        require(hashlib.sha256(target.read_bytes()).hexdigest() == digest and ('100755' if target.stat().st_mode & 0o111 else '100644') == scope['native_source_modes'][name], 'final browser native source or mode differs')
    profile = json.loads((Path(scope['root'])/'config/final-browser-runtime-v1.json').read_text())
    require(profile['widths'] == [1366, 375] and profile['modes'] == ['classical', 'neural'] and profile['required_contexts'] == 4 and profile['completed_analysis_ms'] == 3000 and profile['maximum_capture_bytes'] == 5242880, 'final browser profile weakened')
    for label in ['build', 'capture']:
        stage = doc(label+'.json');require(stage['exit'] == 0 and stage['reason'] == 'completed' and stage['cleanup_warnings'] == [] and stage['discarded_output_bytes'] == 0 and hashlib.sha256((output/(label+'.log')).read_bytes()).hexdigest() == stage['log_sha256'], 'actual final browser stage/log failed')
    build = doc('BUILD.json');outputs = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in build['outputs']}
    served = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ['product/web/index.html', 'product/web/style.css', 'product/dist/web/app.js']}
    require(served['product/web/index.html'] == scope['source_bindings'][str(Path(scope['root'])/'web/index.html')] and served['product/web/style.css'] == scope['source_bindings'][str(Path(scope['root'])/'web/style.css')], 'final copied source assets changed')
    expected = {'network_sha256': scope['network_sha256'], 'engine_path': scope['engine'], 'node_version': scope['node_version'], 'build_outputs': outputs, 'served_hashes': served, 'compiled_source_inputs': {str(Path(scope['root'])/name): scope['source_bindings'][str(Path(scope['root'])/name)] for name in ['web/app.ts', 'analysis-service/server.ts', 'analysis-service/native.ts', 'analysis-service/telemetry.ts']}}
    data = {'browser': doc('BROWSER.json'), 'network': doc('NETWORK.json'), 'assets': doc('ASSETS.json'), 'errors': doc('ERRORS.json'), 'build': build, 'groups': doc('GROUPS.json'), 'process_events': []}
    for text in [(output/'capture.log').read_text(), (output/'service.log').read_text()]:
        for line in text.splitlines():
            if line.startswith('{'):
                value = json.loads(line)
                if '_caissa_process_event' in value:data['process_events'].append(value['_caissa_process_event'])
    result = inspect(data, expected)
    for mode in ['classical', 'neural']:
        for width in [1366, 375]:
            trace = output/f'{mode}-{width}/trace.zip'
            with zipfile.ZipFile(trace) as z:
                entries = z.infolist();require(len(entries) <= 10000 and sum(e.file_size for e in entries) <= 128*1024**2 and z.testzip() is None, 'new browser trace damaged or excessive')
                calls = []
                for entry in entries:
                    require(not entry.filename.startswith('/') and '..' not in Path(entry.filename).parts, 'unsafe final trace member')
                    if entry.filename.endswith('.trace'):
                        require(entry.file_size <= 16*1024**2, 'final trace metadata too large')
                        calls += [json.loads(line) for line in z.read(entry).splitlines()]
                before = [r for r in calls if r.get('type') == 'before']
                require([r['params']['key'] for r in before if r.get('method') == 'keyboardPress'] == ['Enter', 'ArrowUp', 'Enter'] and not any(r.get('method') in {'route', 'routeFromHAR', 'fulfill'} for r in before), 'final trace keyboard or real-route provenance differs')
    def asset_change(x):
        a=next(a for a in x['assets'] if a['path']=='/app.js');a['body']+=' ';a['bytes']+=1;a['sha256']=hashlib.sha256(a['body'].encode()).hexdigest()
    def pv_change(x):
        row=next(r for r in x['network'] if r['url']=='/api/analyze' and 'event: bestmove' in r.get('body',''));parts=frames(row['body'])
        next(v for k,v in parts if k=='info')['pv']=['a1a8'];row['body']=''.join('event: '+k+'\ndata: '+json.dumps(v)+'\n\n' for k,v in parts)
    controls=[]
    cases=[('changed_compiled_asset_with_rehashed_body',asset_change),('missing_compiled_asset',lambda x:x['assets'].__setitem__(slice(None),[a for a in x['assets'] if a['path']!='/app.js'])),('illegal_native_pv',pv_change),('omitted_completed_native_bytes',lambda x:x['network'].__setitem__(slice(None),[r for r in x['network'] if r['url']!='/api/analyze'])),('changed_build_source',lambda x:x['build']['source_inputs'].__setitem__(str(Path(scope['root'])/'web/app.ts'),'0'*64)),('wrong_visible_evaluator',lambda x:x['browser']['records'][0].__setitem__('engine','other engine')),('lost_keyboard_focus',lambda x:next(r for r in x['browser']['records'] if r['name']=='keyboard-edit').__setitem__('focus',None)),('lost_exported_variation',lambda x:next(r for r in x['browser']['records'] if r['name']=='export').__setitem__('pgn','1. e3 *')),('unreaped_cancel',lambda x:next(r for r in x['browser']['records'] if r['name']=='cancel-reaped')['health'].__setitem__('analyses',1)),('viewport_overflow',lambda x:x['browser']['records'][0].__setitem__('scrollWidth',2000)),('missing_process_close',lambda x:x['process_events'].__setitem__(slice(None),[e for i,e in enumerate(x['process_events']) if i!=next(i for i,e in enumerate(x['process_events']) if e['event']=='closed')])),('forged_full_acceptance',lambda x:x['browser'].__setitem__('full_acceptance',True))]
    for name, mutate in cases:
        forged=copy.deepcopy(data);mutate(forged)
        try:inspect(forged, expected)
        except (ValueError,KeyError) as error:controls.append({'case':name,'rejected':True,'reason':str(error)})
        else:raise ValueError('forged final browser evidence accepted: '+name)
    result.update(status='passed_final_served_browser_domain',full_R10_complete=True,full_acceptance=False,product_source_commit=scope['product_commit'],scope_sha256=scope['scope_sha256'],profile_sha256=scope['profile_sha256'],engine_sha256=scope['engine_sha256'],network_sha256=scope['network_sha256'],native_source_files_and_modes=len(scope['native_source_hashes']),served_build_outputs=outputs,source_and_runtime_pins=len(scope['source_bindings']),semantic_controls=len(controls),whole_project_coordinator_executed=False,original_compiler_runtime_closure=False,historical_samples_reexecuted=False,new_match_games=0)
    return result, controls
