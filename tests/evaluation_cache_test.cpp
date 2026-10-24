#include "caissa/evaluation_cache.hpp"
#include "caissa/search.hpp"
#include <iostream>
#include <random>
#include <stdexcept>
using namespace caissa;
namespace {
void require(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
SearchResult run(const Position& p,SearchOptions options,bool cached,int nodes=6000,int depth=8) {
    options.evaluation_cache=cached;Limits limits;limits.nodes=static_cast<std::uint64_t>(nodes);limits.depth=depth;
    Search search(std::make_shared<TranspositionTable>(4));
    return search.run(p,limits,options,std::make_shared<SearchControl>());
}
void identical(const SearchResult& a,const SearchResult& b) {
    require(a.best==b.best&&a.score==b.score&&a.pv==b.pv&&a.info.depth==b.info.depth,"cache changed a fixed-node result");
    require(a.info.nodes==b.info.nodes&&a.info.completed_depth_nodes==b.info.completed_depth_nodes,"cache changed visited or completed nodes");
    const auto& x=a.info.stats;const auto& y=b.info.stats;
    require(x.qnodes==y.qnodes&&x.table_hits==y.table_hits&&x.table_cutoffs==y.table_cutoffs&&x.beta_cutoffs==y.beta_cutoffs&&x.null_cutoffs==y.null_cutoffs&&x.lmr_searches==y.lmr_searches&&x.researches==y.researches&&x.futility_skips==y.futility_skips&&x.evaluator_calls==y.evaluator_calls,"cache changed search-tree counters");
}
}
int main(int argc,char** argv){try {
    EvaluationCache cache;require(!cache.find(0),"empty zero-key cache hit");
    cache.store(0,0);require(cache.find(0)&&*cache.find(0)==0,"zero key/value not retained");
    cache.store(EvaluationCache::capacity,123);require(!cache.find(0)&&cache.find(EvaluationCache::capacity)==123,"index collision reused an unrelated score");
    for(int value:{-infinity,-mate_threshold,mate_threshold,infinity}) {
        bool rejected=false;try{cache.store(3,value);}catch(const InputError&){rejected=true;}require(rejected,"mate/bound cache value accepted");
    }
    std::vector<Position> positions;
    for(auto fen:std::array<std::string_view,5>{start_fen,"r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1","8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1","1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1","4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1"})positions.push_back(Position::from_fen(fen));
    positions.push_back(Position::from_fen("4k3/8/8/8/8/8/8/5KR1 w G - 0 1",true));
    auto repeated=Position::start();for(auto text:{"g1f3","g8f6","f3g1","f6g8","g1f3","g8f6","f3g1","f6g8"})repeated.make(*repeated.parse_uci(text));positions.push_back(repeated);
    std::mt19937 rng(982451653);auto random=Position::start();
    for(int i=0;i<96;++i){auto moves=random.legal();if(moves.empty()){random=Position::start();moves=random.legal();}random.make(moves[rng()%moves.size()]);if(i%12==11)positions.push_back(random);}
    std::vector<SearchOptions> modes(2);modes[1].table=false;
    for(int i=1;i<argc;++i) {
        auto network=Network::load(argv[i]);
        for(int weight:{10,100}){SearchOptions option;option.network=network;option.neural_weight=weight;modes.push_back(option);}
        SearchOptions scalar;scalar.network=network;scalar.neural_weight=10;scalar.scalar_network=true;modes.push_back(scalar);
    }
    std::uint64_t hits=0,requests=0,pairs=0;
    for(const auto& options:modes)for(const auto& p:positions) {
        auto a=run(p,options,false),b=run(p,options,true);identical(a,b);++pairs;
        require(a.info.stats.evaluation_cache_bytes==0,"disabled cache allocated memory");
        require(b.info.stats.evaluation_cache_bytes==cache.bytes(),"cache memory accounting differs");
        hits+=b.info.stats.evaluation_cache_hits;requests+=b.info.stats.evaluator_calls;
        if(options.network&&options.neural_weight>0)
            require(a.info.stats.neural_evaluations==b.info.stats.neural_evaluations+b.info.stats.evaluation_cache_hits,"cache inference accounting differs");
    }
    require(hits>0&&requests>hits,"fixed-node cases did not exercise cache hits and misses");
    // Terminal/history decisions remain outside raw evaluation lookup.
    for(auto fen:{"7k/6Q1/5K2/8/8/8/8/8 b - - 150 80","4k3/8/8/8/8/8/8/4K3 w - - 150 80"}) {
        auto p=Position::from_fen(fen);identical(run(p,{},false),run(p,{},true));
    }
    for(int threads:{2,4,8}) {
        SearchOptions option;option.threads=threads;option.null_move=false;option.lmr=false;option.futility=false;option.extensions=false;
        auto p=Position::start();auto a=run(p,option,false,0,3),b=run(p,option,true,0,3);
        require(a.score==b.score&&a.info.depth==3&&b.info.depth==3,"parallel cache changed completed-tree score");
        require(b.info.stats.evaluation_cache_bytes==cache.bytes()*static_cast<std::size_t>(threads),"parallel private cache bytes differ");
    }
    // Certified lower bounds cannot be cached as exact static evaluations.
    if(argc>1)for(const auto& p:positions) {
        SearchOptions option;option.network=Network::load(argv[1]);option.neural_weight=10;option.neural_bounds=true;
        option.null_move=false;option.lmr=false;option.futility=false;option.extensions=false;
        auto a=run(p,option,false,0,3),b=run(p,option,true,0,3);
        require(a.score==b.score&&a.info.depth==b.info.depth,"bounds/cache interaction changed a completed exact tree");
    }
    std::cout<<"{\"status\":\"passed\",\"fixed_node_pairs\":"<<pairs<<",\"evaluation_requests\":"<<requests<<",\"cache_hits\":"<<hits<<",\"private_bytes_per_worker\":"<<cache.bytes()<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
