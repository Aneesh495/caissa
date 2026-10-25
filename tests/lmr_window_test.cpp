#include "caissa/reference.hpp"
#include "caissa/search.hpp"
#include <iostream>
#include <stdexcept>

using namespace caissa;
namespace {
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
int minimax(Position& position,int depth,int ply,std::uint64_t& nodes) {
    require(++nodes<=2000000,"LMR regression oracle node ceiling exhausted");
    auto moves=reference::legal(position);auto state=rules(position,moves);
    if(state.ended())return state.terminal==Termination::checkmate?-mate_score+ply:0;
    if(!depth)return std::max(state.claimable()?0:-infinity,classical(position));
    int best=state.claimable()?0:-infinity;
    for(auto move:moves){auto undo=position.make(move);best=std::max(best,-minimax(position,depth-1,ply+1,nodes));position.unmake(undo);}
    return best;
}
}
int main(){try {
    // The old PVS-off/LMR-on path returned -139 at depth five. The independently
    // enumerated value is -196. A full-depth scout alone did not recover it.
    auto position=Position::from_fen("8/8/2k5/8/2P5/2K5/8/8 b - - 0 1");
    std::uint64_t oracle_nodes=0;int expected=minimax(position,5,0,oracle_nodes);
    require(expected==-196,"frozen LMR witness or classical contract changed");
    unsigned queries=0;std::uint64_t reductions=0,recoveries=0;
    for(bool pvs:{false,true})for(bool lmr:{false,true}) {
        SearchOptions options;options.table=false;options.pvs=pvs;options.lmr=lmr;
        options.aspiration=false;options.quiescence=false;options.null_move=false;
        options.extensions=false;options.history=false;options.see=false;options.futility=false;
        Search search(std::make_shared<TranspositionTable>(1));Limits limits;limits.depth=5;limits.nodes=100000;
        auto result=search.run(position,limits,options,std::make_shared<SearchControl>());
        require(!result.interrupted&&result.info.depth==5,"LMR witness did not complete its fixed depth");
        std::cout<<"{\"pvs\":"<<(pvs?"true":"false")<<",\"lmr\":"<<(lmr?"true":"false")<<",\"expected\":"<<expected<<",\"actual\":"<<result.score<<",\"lmr_searches\":"<<result.info.stats.lmr_searches<<",\"researches\":"<<result.info.stats.researches<<"}\n";
        require(result.score==expected,"PVS-off LMR recovery disagrees with independent minimax");
        auto replay=position;
        for(auto move:result.pv){auto legal=reference::legal(replay);require(std::find(legal.begin(),legal.end(),move)!=legal.end(),"LMR witness returned an illegal PV");replay.make(move);}
        if(lmr&&!pvs){reductions=result.info.stats.lmr_searches;recoveries=result.info.stats.researches;}
        ++queries;
    }
    require(reductions>0&&recoveries>0,"LMR witness never exercised reduction and recovery");
    std::cout<<"{\"status\":\"passed\",\"oracle_nodes\":"<<oracle_nodes<<",\"native_queries\":"<<queries<<"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
