#include "caissa/search.hpp"
#include "caissa/reference.hpp"
#include <future>
#include <thread>
#include <iostream>
#include <set>
#include <stdexcept>
using namespace caissa;
int exhaustive(Position& p,int depth,int ply) {
    auto moves=reference::legal(p);auto s=rules(p,moves);
    if(s.ended())return s.terminal==Termination::checkmate?-mate_score+ply:0;
    if(depth==0)return classical(p);
    int best=s.claimable()?0:-infinity;
    for(auto m:moves){auto u=p.make(m);int score=-exhaustive(p,depth-1,ply+1);p.unmake(u);best=std::max(best,score);}
    return best;
}
void check(bool b,const char* message){if(!b)throw std::runtime_error(message);}
void replay(Position p,const Moves& pv){for(auto m:pv){auto legal=p.legal();check(std::find(legal.begin(),legal.end(),m)!=legal.end(),"illegal PV");p.make(m);}}
int main(){try {
    SearchOptions exact;exact.null_move=false;exact.lmr=false;exact.extensions=false;exact.futility=false;exact.quiescence=false;
    for(auto fen:{"8/8/8/4k3/8/4K3/4P3/8 w - - 0 1","7k/8/8/8/8/8/4P3/4K3 w - - 0 1"}) {
        auto p=Position::from_fen(fen);int expected=exhaustive(p,4,0);
        for(bool use_table:{false,true}) {
            exact.table=use_table;Search engine(std::make_shared<TranspositionTable>(1));Limits limits;limits.depth=4;
            auto r=engine.run(p,limits,exact,std::make_shared<SearchControl>());check(r.score==expected,"PVS disagrees with independent minimax");replay(p,r.pv);
        }
    }
    auto p=Position::from_fen("7k/8/5KQ1/8/8/8/8/8 w - - 0 1");
    Search engine(std::make_shared<TranspositionTable>(1));Limits limits;limits.depth=3;SearchOptions options;options.threads=4;options.multipv=4;
    auto r=engine.run(p,limits,options,std::make_shared<SearchControl>());check(r.score==mate_score-1,"mate in one not found");replay(p,r.pv);
    std::set<std::uint32_t> roots;for(auto& line:r.info.lines){check(roots.insert(line.move.packed()).second,"duplicate MultiPV");replay(p,line.pv);}
    auto traced_options=options;traced_options.threads=1;traced_options.trace_limit=8;auto traced=engine.run(Position::start(),limits,traced_options,std::make_shared<SearchControl>());
    check(traced.info.trace.size()<=8,"trace budget exceeded");
    for(auto& sample:traced.info.trace)check(Position::from_fen(sample.fen).coherent(),"trace FEN invalid");
    auto control=std::make_shared<SearchControl>();limits.depth=64;limits.infinite=true;
    auto future=std::async(std::launch::async,[&]{return engine.run(Position::start(),limits,options,control);});
    std::this_thread::sleep_for(std::chrono::milliseconds(10));auto start=monotonic_ns();control->stop.store(true);
    check(future.wait_for(std::chrono::milliseconds(100))==std::future_status::ready,"stop did not finish");auto stopped=future.get();
    check(stopped.best.valid(),"stop lost legal fallback");check((monotonic_ns()-start)/1000000<100,"stop latency");
    limits.infinite=false;limits.nodes=250;options.threads=1;
    auto bounded=engine.run(Position::start(),limits,options,std::make_shared<SearchControl>());check(bounded.info.nodes<=250,"node budget exceeded");
    auto failure_options=options;failure_options.threads=4;failure_options.inject_worker_start_failure_after=2;Limits failure_limits;failure_limits.infinite=true;auto failure_start=monotonic_ns();bool launch_rejected=false;
    try{engine.run(Position::start(),failure_limits,failure_options,std::make_shared<SearchControl>());}catch(const std::runtime_error&){launch_rejected=true;}
    check(launch_rejected&&(monotonic_ns()-failure_start)<100000000,"partial worker startup did not cancel and join");
    auto early_hit=std::make_shared<SearchControl>();early_hit->ponderhit();Limits ponder_limits;ponder_limits.ponder=true;ponder_limits.milliseconds=100;early_hit->initialize(ponder_limits);
    check(!early_hit->pondering.load()&&early_hit->deadline_ns.load()!=INT64_MAX,"early ponder hit was lost");
    check(time_budget(1000,10,30,20)>0&&time_budget(1,0,30,20)==1,"time allocation bounds");
    std::cout<<"exhaustive minimax, mate, MultiPV, cancellation and node budget passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
