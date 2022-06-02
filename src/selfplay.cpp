#include "caissa/selfplay.hpp"
#include "caissa/search.hpp"
#include <iostream>
#include <random>
#include <sstream>
namespace caissa {
namespace {
struct Sample {std::string fen;Key key;int score,depth,ply;std::uint64_t nodes;};
void game(std::ostream& out,Position p,const std::vector<std::string>& opening,std::uint64_t pair,int reverse,std::uint64_t seed,std::uint64_t nodes,int max_plies,bool searched_policy) {
    auto table=std::make_shared<TranspositionTable>(4);Search engine(table);SearchOptions options;options.multipv=searched_policy?1:3;
    options.root_shuffle_seed=searched_policy?(seed^(static_cast<std::uint64_t>(reverse)+1)*0x9e3779b97f4a7c15ULL):0;std::mt19937_64 rng(seed+static_cast<std::uint64_t>(reverse)*0x9e3779b97f4a7c15ULL);Limits limits;limits.nodes=nodes;
    std::vector<Sample> samples;std::vector<std::string> moves=opening;std::string reason="ply-limit",result="*";bool complete=false;
    auto start=monotonic_ns();int ply=static_cast<int>(opening.size());
    while(ply<max_plies) {
        auto state=rules(p);
        if(state.ended()) {
            reason=termination_name(state.terminal);result=state.terminal==Termination::checkmate?(p.side()==Color::white?"0-1":"1-0"):"1/2-1/2";complete=true;break;
        }
        if(state.claimable()) {reason=state.threefold_claim?"threefold-claim":"fifty-move-claim";result="1/2-1/2";complete=true;break;}
        auto r=engine.run(p,limits,options,std::make_shared<SearchControl>());
        if(!r.best.valid())throw std::logic_error("selfplay lost legal bestmove");
        if(ply>=12) samples.push_back({p.fen(),p.repetition_key(),r.score,r.info.depth,ply,r.info.nodes});
        auto chosen=r.best;
        if(ply<static_cast<int>(opening.size())+12&&rng()%4==0&&!r.info.lines.empty()) {
            std::vector<Move> near;
            for(auto& line:r.info.lines)if(line.score>=r.info.lines[0].score-30)near.push_back(line.move);
            if(!near.empty())chosen=near[rng()%near.size()];
        }
        moves.push_back(p.uci(chosen));p.make(chosen);++ply;
    }
    // Exhausting a safety budget is an unfinished game, never a fabricated draw.
    if(!complete) {auto state=rules(p);if(state.ended()){reason=termination_name(state.terminal);result=state.terminal==Termination::checkmate?(p.side()==Color::white?"0-1":"1-0"):"1/2-1/2";complete=true;}}
    out<<"{\"pair\":"<<pair<<",\"reverse\":"<<reverse<<",\"seed\":"<<seed<<",\"opening_plies\":"<<opening.size()<<",\"search_policy\":\""<<(searched_policy?"searched-v2":"legacy-v1")<<"\",\"root_shuffle_seed\":"<<options.root_shuffle_seed<<",\"budget_nodes\":"<<nodes<<",\"result\":\""<<result<<"\",\"termination\":\""<<reason<<"\",\"complete\":"<<(complete?"true":"false")<<",\"milliseconds\":"<<(monotonic_ns()-start)/1000000<<",\"moves\":[";
    bool first=true;for(auto& move:moves){if(!first)out<<',';first=false;out<<'"'<<move<<'"';}out<<"],\"positions\":[";
    first=true;for(auto& s:samples){if(!first)out<<',';first=false;out<<"{\"fen\":\""<<s.fen<<"\",\"key\":"<<s.key<<",\"score_stm\":"<<s.score<<",\"depth\":"<<s.depth<<",\"nodes\":"<<s.nodes<<",\"ply\":"<<s.ply<<"}";}
    out<<"]}\n"<<std::flush;
}
}
void selfplay_pair(std::ostream& output,std::uint64_t pair_id,std::uint64_t seed,std::uint64_t nodes,int opening_plies,int max_plies,bool searched_policy) {
    if(nodes<50||nodes>10000000||opening_plies<0||opening_plies>80||max_plies<100||max_plies>1024)throw InputError("selfplay resource limits invalid");
    std::mt19937_64 rng(seed);auto p=Position::start();std::vector<std::string> opening;
    for(int ply=0;ply<opening_plies;++ply){auto moves=p.legal();if(rules(p,moves).ended())break;auto move=moves[rng()%moves.size()];opening.push_back(p.uci(move));p.make(move);}
    game(output,p,opening,pair_id,0,seed,nodes,max_plies,searched_policy);
    game(output,p,opening,pair_id,1,seed,nodes,max_plies,searched_policy);
}
}
