#include "caissa/search.hpp"
#include "caissa/reference.hpp"
#include <iostream>
#include <stdexcept>
using namespace caissa;
int exact(Position& p,int depth,int ply,std::uint64_t& nodes) {
 if(++nodes>2000000)throw std::runtime_error("frozen oracle node ceiling exhausted");
 auto legal=reference::legal(p);auto state=rules(p,legal);
 if(state.ended())return state.terminal==Termination::checkmate?-mate_score+ply:0;
 if(!depth)return std::max(state.claimable()?0:-infinity,classical(p));
 int best=state.claimable()?0:-infinity;
 for(auto m:legal){auto undo=p.make(m);best=std::max(best,-exact(p,depth-1,ply+1,nodes));p.unmake(undo);}
 return best;
}
int main(){try {
 for(auto fen:{"8/8/8/4k3/8/4K3/4P3/8 w - - 0 1","8/8/8/4k3/8/4K3/4P3/8 b - - 0 1","7k/8/8/8/8/8/4P3/4K3 w - - 0 1","7k/8/8/8/8/8/4P3/4K3 b - - 0 1","8/8/2k5/8/2P5/2K5/8/8 w - - 0 1","8/8/2k5/8/2P5/2K5/8/8 b - - 0 1","8/8/8/8/3k4/8/3P4/3K4 w - - 0 1","8/8/8/8/3k4/8/3P4/3K4 b - - 0 1"}) {
  for(int depth:{4,5}) {
   auto position=Position::from_fen(fen);std::uint64_t oracle=0;int expected=exact(position,depth,0,oracle);
   for(bool lmr:{false,true}) {
    SearchOptions o;o.table=false;o.pvs=false;o.aspiration=false;o.quiescence=false;o.null_move=false;o.lmr=lmr;o.extensions=false;o.history=false;o.see=false;o.futility=false;
    Search engine(std::make_shared<TranspositionTable>(1));Limits limits;limits.depth=depth;
    auto r=engine.run(position,limits,o,std::make_shared<SearchControl>());
    if(!lmr&&r.score!=expected)throw std::runtime_error("nonselective reference disagrees with mailbox minimax");
    std::cout<<"{\"fen\":\""<<fen<<"\",\"depth\":"<<depth<<",\"lmr\":"<<(lmr?"true":"false")<<",\"expected\":"<<expected<<",\"actual\":"<<r.score<<",\"move\":\""<<position.uci(r.best)<<"\",\"oracle_nodes\":"<<oracle<<",\"lmr_searches\":"<<r.info.stats.lmr_searches<<",\"researches\":"<<r.info.stats.researches<<",\"native_nodes\":"<<r.info.nodes<<"}\n";
   }
  }
 }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
