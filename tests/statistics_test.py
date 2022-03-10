import math
from arena.statistics import summarize

def record(pair,result,opening='family'):
 return {'pair':pair,'opening_id':opening,'games':[{'candidate_color':'white','result':result,'termination':'checkmate'},{'candidate_color':'black','result':'0-1' if result=='1-0' else '1-0' if result=='0-1' else result,'termination':'checkmate'}]}
winning=summarize([record(i,'1-0',str(i)) for i in range(20)])
losing=summarize([record(i,'0-1',str(i)) for i in range(20)])
assert winning['score']==1 and winning['score_95'][0]<1
assert losing['score']==0 and losing['score_95'][1]>0
same=summarize([record(i,'1-0') for i in range(100)])
assert same['independent_opening_clusters']==1
assert same['score_95'][0]<.5
mixed=summarize([record(0,'1-0','a'),record(1,'0-1','b')])
assert mixed['score']==.5 and mixed['elo_difference']==0
print('Opening clusters and finite-sample endpoint uncertainty passed')
