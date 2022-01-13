#include "caissa/rules.hpp"
#include <iostream>
#include <stdexcept>
using namespace caissa;
void check(bool b,const char* message){if(!b)throw std::runtime_error(message);}
int main(){try {
    auto p=Position::start();auto bare=Position::start();
    for(int cycle=0;cycle<4;++cycle) {
        for(auto text:{"g1f3","g8f6","f3g1","f6g8"}) {auto m=p.parse_uci(text);check(m.has_value(),"repetition move absent");p.make(*m);}
        auto state=rules(p);
        check(p.repetition_key()==bare.repetition_key(),"same-board key differs");
        check(p.search_key()!=bare.search_key(),"history omitted from search identity");
        check(state.threefold_claim==(cycle>=1&&cycle<3),"claimable repetition boundary");
        check((state.terminal==Termination::fivefold)==(cycle==3),"automatic repetition boundary");
    }
    auto fresh=Position::from_fen(p.fen());check(!rules(fresh).claimable(),"FEN fabricated history");
    for(int clock:{99,100,149,150}) {
        auto q=Position::from_fen("7k/8/8/8/8/8/8/R3K3 w - - "+std::to_string(clock)+" 1");
        auto s=rules(q);check(s.fifty_move_claim==(clock>=100&&clock<150),"50-move boundary");
        check((s.terminal==Termination::seventy_five)==(clock>=150),"75-move boundary");
        if(clock==99) check(!claim_by_move(q).empty(),"intended-move claim absent");
    }
    auto mate=Position::from_fen("7k/6Q1/5K2/8/8/8/8/8 b - - 150 80");check(rules(mate).terminal==Termination::checkmate,"mate precedence");
    auto nn=Position::from_fen("7k/8/8/8/8/8/8/NN2K3 w - - 0 1");check(!proven_dead(nn),"two knights incorrectly dead");
    auto bishop=Position::from_fen("7k/8/8/8/8/8/8/2B1K3 w - - 0 1");check(proven_dead(bishop),"lone bishop not dead");
    auto ep=Position::from_fen("4k3/8/8/r4pPK/8/8/8/8 w - f6 0 1");
    auto noep=Position::from_fen("4k3/8/8/r4pPK/8/8/8/8 w - - 0 1");
    check(ep.key()!=noep.key()&&ep.repetition_key()==noep.repetition_key(),"illegal EP identity");
    std::cout<<"draw claims, history identity, clocks and mate precedence passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
