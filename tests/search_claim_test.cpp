#include "caissa/search.hpp"
#include <iostream>
#include <stdexcept>
using namespace caissa;
namespace {
void require(bool condition,const char* reason){if(!condition)throw std::runtime_error(reason);}
SearchResult run(Position position,int depth,bool table,bool quiescence) {
    SearchOptions options;options.table=table;options.quiescence=quiescence;
    options.null_move=false;options.lmr=false;options.extensions=false;options.futility=false;
    Limits limits;limits.depth=depth;limits.nodes=200000;
    Search search(std::make_shared<TranspositionTable>(1));
    auto result=search.run(position,limits,options,std::make_shared<SearchControl>());
    require(!result.interrupted&&result.info.depth==depth,"claim witness exceeded its depth/node ceiling");
    return result;
}
}
int main(){try {
    unsigned queries=0;
    auto clock=Position::from_fen("1r5k/8/8/8/8/8/8/K7 w - - 99 50");
    require(!rules(clock).claimable()&&!claim_by_move(clock).empty(),"clock witness is not an intended-only claim");
    auto repeated=Position::from_fen("3r3k/8/8/8/8/8/8/K7 b - - 0 1");
    for(auto text:{"h8h7","a1a2","h7h8","a2a1","h8h7","a1a2","h7h8"})repeated.make(*repeated.parse_uci(text));
    auto claims=claim_by_move(repeated);
    require(!rules(repeated).claimable()&&claims.size()==1&&repeated.uci(claims[0])=="a2a1","third-occurrence witness changed");
    for(bool table:{false,true})for(bool quiet:{false,true})for(int depth:{1,2,3,4}) {
        auto result=run(clock,depth,table,quiet);require(result.score==0&&clock.uci(result.best)=="a1a2","intended fifty-move claim lost to a winning reply");++queries;
        result=run(repeated,depth,table,quiet);require(result.score==0&&repeated.uci(result.best)=="a2a1","intended repetition claim lost or wrong move selected");++queries;
    }
    auto frontier=Position::from_fen("3r3k/8/8/8/8/8/8/K7 b - - 98 50");
    require(run(frontier,1,true,false).score==0,"frontier intended claim disappeared behind static evaluation");++queries;
    auto mate=Position::from_fen("7k/8/5KQ1/8/8/8/8/8 w - - 99 50");
    require(run(mate,2,true,true).score==mate_score-1,"intended draw hid an immediate checkmate");++queries;
    auto capture=Position::from_fen("1r5k/8/8/8/8/8/8/KQ6 w - - 99 50");
    auto reset=run(capture,2,true,true);
    require(reset.score>0&&capture.uci(reset.best)=="b1b8","optional root claim hid a winning reset");++queries;
    std::cout<<"{\"status\":\"passed\",\"claim_queries\":"<<queries<<",\"scope\":\"Intended draw, optional root continuation, mate and capture reset\"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
