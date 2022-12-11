#include "caissa/accumulator_stack.hpp"
#include "caissa/search.hpp"
#include <algorithm>
#include <iostream>
#include <random>
#include <stdexcept>
#include <tuple>
using namespace caissa;
namespace {
void require(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
template<class F> void rejected(F action,const char* reason) {
    bool failed=false;try{action();}catch(const std::logic_error&){failed=true;}require(failed,reason);
}
void equal(AccumulatorStack& stack,const Position& p,const Network& network) {
    const auto& actual=stack.get(p);auto expected=network.refresh(p);
    require(actual==expected,"deferred accumulator differs from independent full refresh");
    for(int weight:{0,10,100})
        require(network.evaluate(p,actual,false,weight)==network.evaluate(p,expected,true,weight),
                "deferred scalar/SIMD or blended score differs");
}
void corners(const Network& network) {
    AccumulatorStack stack(network,true);auto p=Position::start();
    rejected([&]{(void)stack.get(p);},"uninitialized neural stack accepted");
    auto unrelated=p;auto unrelated_undo=unrelated.make(*unrelated.parse_uci("e2e4"));
    stack.reset(unrelated);
    rejected([&]{stack.push(unrelated,unrelated_undo);},"foreign parent neural stack accepted");
    rejected([&]{(void)stack.get(p);},"foreign current neural stack accepted");
    // Both kings cross bucket boundaries and return without an intervening
    // evaluation. A final-bucket ancestor remains a valid telescoping base.
    p=Position::from_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1");stack.reset(p);equal(stack,p,network);
    auto work=stack.work();std::vector<Undo> path;
    for(auto text:{"e1d1","e8d8","d1e1","d8e8"}) {
        auto move=p.parse_uci(text);require(move.has_value(),"king-return fixture move missing");
        path.push_back(p.make(*move));stack.push(p,path.back());
    }
    equal(stack,p,network);
    require(stack.work().perspective_refreshes==work.perspective_refreshes,
            "unobserved king return lost its matching-bucket ancestor");
    while(!path.empty()){p.unmake(path.back());path.pop_back();stack.pop();equal(stack,p,network);}
    for(auto [fen,text,chess960]:{
        std::tuple{"4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1","g5f6",false},
        std::tuple{"1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1","a7b8n",false},
        std::tuple{"4k3/P7/8/8/8/8/8/4K3 w - - 0 1","a7a8q",false},
        std::tuple{"4k3/8/8/8/8/8/8/5KR1 w G - 0 1","f1g1",true},
        std::tuple{"4k3/8/8/8/8/8/8/6KR w H - 0 1","g1h1",true},
        std::tuple{"4k3/8/8/8/8/8/8/1RK5 w B - 0 1","c1b1",true}}) {
        p=Position::from_fen(fen,chess960);stack.reset(p);auto original=network.refresh(p);
        equal(stack,p,network);auto move=p.parse_uci(text);require(move.has_value(),"special neural fixture move missing");
        auto undo=p.make(*move);stack.push(p,undo);equal(stack,p,network);p.unmake(undo);stack.pop();
        require(stack.get(p)==original,"special-move neural pop lost parent values");
        // Exercise a reset whose first materialization is below the root.
        stack.reset(p);undo=p.make(*move);stack.push(p,undo);equal(stack,p,network);p.unmake(undo);stack.pop();equal(stack,p,network);
    }
    p=Position::start();stack.reset(p);equal(stack,p,network);auto null_work=stack.work();
    auto null_undo=p.make_null();stack.push(p,null_undo);equal(stack,p,network);
    require(stack.work().delta_squares==null_work.delta_squares,"null move performed piece updates");
    p.unmake(null_undo);stack.pop();equal(stack,p,network);
    // The full capacity is bounded; a rejected push must leave the parent
    // frame usable and all preceding frames available for exact restoration.
    path.clear();
    for(int i=1;i<max_ply;++i){path.push_back(p.make_null());stack.push(p,path.back());}
    auto overflow=p.make_null();rejected([&]{stack.push(p,overflow);},"neural stack accepted an overflowing path");p.unmake(overflow);
    equal(stack,p,network);
    while(!path.empty()){p.unmake(path.back());path.pop_back();stack.pop();}
    equal(stack,p,network);
}
std::uint64_t tree(const Network& network,std::uint64_t count) {
    AccumulatorStack stack(network,true),eager(network,false);auto p=Position::start();
    stack.reset(p);eager.reset(p);std::mt19937 random(67867967);std::vector<Undo> path;
    std::uint64_t observations=0;
    for(std::uint64_t i=0;i<count;++i) {
        if(!path.empty()&&(random()%5==0||path.size()>=max_ply-2)) {
            p.unmake(path.back());path.pop_back();stack.pop();eager.pop();
        } else {
            auto moves=p.legal();
            if(moves.empty()||p.halfmove()>149||random()%257==0) {
                p=Position::start();path.clear();stack.reset(p);eager.reset(p);moves=p.legal();
            }
            auto undo=!p.in_check(p.side())&&random()%37==0?p.make_null():p.make(moves[random()%moves.size()]);
            path.push_back(undo);stack.push(p,undo);eager.push(p,undo);
        }
        if(random()%7==0||i+1==count) {
            equal(stack,p,network);require(stack.get(p)==eager.get(p),"deferred/eager tree accumulator mismatch");++observations;
        }
    }
    while(!path.empty()) {
        p.unmake(path.back());path.pop_back();stack.pop();eager.pop();
        equal(stack,p,network);require(stack.get(p)==eager.get(p),"deferred tree unwind differs");++observations;
    }
    require(stack.work().materializations<eager.work().materializations,"sparse observations did not defer neural work");
    return observations;
}
SearchResult search(const Position& p,SearchOptions options) {
    Limits limits;limits.nodes=3000;limits.depth=8;
    Search engine(std::make_shared<TranspositionTable>(4));
    return engine.run(p,limits,options,std::make_shared<SearchControl>());
}
void same_search(const SearchResult& a,const SearchResult& b) {
    require(a.best==b.best&&a.score==b.score&&a.pv==b.pv&&a.interrupted==b.interrupted&&a.info.depth==b.info.depth,
            "deferred neural work changed fixed-node search");
    require(a.info.nodes==b.info.nodes&&a.info.completed_depth_nodes==b.info.completed_depth_nodes,
            "deferred neural work changed visited/completed nodes");
    require(a.info.lines.size()==b.info.lines.size(),"deferred search line count changed");
    for(std::size_t i=0;i<a.info.lines.size();++i) {
        const auto& x=a.info.lines[i];const auto& y=b.info.lines[i];
        require(x.move==y.move&&x.score==y.score&&x.pv==y.pv&&x.bound==y.bound,"deferred root line changed");
    }
    const auto& x=a.info.stats;const auto& y=b.info.stats;
    require(x.qnodes==y.qnodes&&x.table_hits==y.table_hits&&x.table_cutoffs==y.table_cutoffs&&
            x.beta_cutoffs==y.beta_cutoffs&&x.null_cutoffs==y.null_cutoffs&&x.lmr_searches==y.lmr_searches&&
            x.researches==y.researches&&x.futility_skips==y.futility_skips&&x.evaluator_calls==y.evaluator_calls&&
            x.neural_evaluations==y.neural_evaluations&&x.neural_bound_cutoffs==y.neural_bound_cutoffs&&
            x.evaluation_cache_hits==y.evaluation_cache_hits&&x.ordering_hint_hits==y.ordering_hint_hits&&x.seldepth==y.seldepth,
            "deferred neural state changed search-tree counters");
}
std::uint64_t searches(std::shared_ptr<const Network> network) {
    std::vector<Position> positions;
    for(auto fen:{start_fen,std::string_view("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
                  std::string_view("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
                  std::string_view("1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1"),
                  std::string_view("4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1")})positions.push_back(Position::from_fen(fen));
    positions.push_back(Position::from_fen("4k3/8/8/8/8/8/8/5KR1 w G - 0 1",true));
    std::mt19937 random(86028121);auto p=Position::start();
    for(int i=0;i<96;++i){auto moves=p.legal();if(moves.empty()){p=Position::start();moves=p.legal();}p.make(moves[random()%moves.size()]);if(i%16==15)positions.push_back(p);}
    std::uint64_t cases=0,saved=0;
    for(int weight:{0,10,100})for(bool cached:{false,true})for(bool bounds:{false,true}) {
        SearchOptions options;options.network=network;options.neural_weight=weight;
        options.evaluation_cache=cached;options.neural_bounds=bounds;options.tactical_generation=cached;
        for(const auto& position:positions) {
            auto eager=search(position,options);options.lazy_neural=true;auto lazy=search(position,options);options.lazy_neural=false;
            same_search(eager,lazy);++cases;
            if(weight==0)require(eager.info.stats.accumulator_work.pushes==0&&lazy.info.stats.accumulator_work.materializations==0,
                                 "zero-weight search did neural accumulator work");
            else {
                require(eager.info.stats.accumulator_work.pushes==lazy.info.stats.accumulator_work.pushes,"lazy/eager path count differs");
                if(eager.info.stats.accumulator_work.materializations>lazy.info.stats.accumulator_work.materializations)++saved;
            }
        }
    }
    require(saved>0,"searches never avoided an unused accumulator update");
    for(int threads:{2,4,8}) {
        SearchOptions options;options.network=network;options.neural_weight=10;options.lazy_neural=true;options.threads=threads;
        auto result=search(Position::start(),options);auto board=Position::start();
        require(result.best.valid(),"parallel deferred search lost its fallback move");
        for(auto move:result.pv){auto legal=board.legal();require(std::find(legal.begin(),legal.end(),move)!=legal.end(),"parallel deferred search returned illegal PV");board.make(move);}
    }
    return cases;
}
}
int main(int argc,char** argv){try {
    if(argc<2||argc>3)throw InputError("accumulator_stack_test network [transitions]");
    auto count=argc==3?std::stoull(argv[2]):10000;
    if(count<1000||count>1000000)throw InputError("deferred transition count outside bounds");
    auto network=Network::load(argv[1]);corners(*network);auto observations=tree(*network,count);auto cases=searches(network);
    std::cout<<"{\"status\":\"passed\",\"transitions\":"<<count<<",\"full_refresh_observations\":"<<observations
             <<",\"exact_search_pairs\":"<<cases<<",\"parallel_workers\":[2,4,8],\"network_identity\":\""<<network->identity()<<"\"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
