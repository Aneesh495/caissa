#include "caissa/evaluation.hpp"
#include <iostream>
#include <random>
#include <stdexcept>
using namespace caissa;
int main(){try {
    auto p=Position::start();if(evaluate_terms(p).white_score!=0)throw std::runtime_error("start symmetry");
    auto q=Position::from_fen("4k3/8/8/8/8/8/8/3QK3 w - - 0 1");
    if(classical(q)<800)throw std::runtime_error("queen advantage absent");
    auto free=Position::from_fen("4k3/8/8/8/8/8/4p3/3QK3 w - - 0 1");
    auto m=free.parse_uci("e1e2");if(!m||static_exchange(free,*m)!=100)throw std::runtime_error("free pawn SEE");
    auto poisoned=Position::from_fen("3rk3/8/8/8/8/8/3p4/3QK3 w - - 0 1");
    m=poisoned.parse_uci("d1d2");if(!m||static_exchange(poisoned,*m)>=0)throw std::runtime_error("poisoned pawn SEE");
    auto random_position=Position::start();std::mt19937 rng(433494437);int checked=0;
    for(int i=0;i<2000;++i){auto moves=random_position.legal();if(moves.empty()||random_position.halfmove()>100){random_position=Position::start();moves=random_position.legal();}
        for(auto move:moves)if(move.flag==MoveFlag::en_passant||(move.flag!=MoveFlag::castle&&random_position.at(move.to))){if(static_exchange(random_position,move)!=static_exchange_reference(random_position,move))throw std::runtime_error("fast SEE disagrees with legal reference");++checked;}
        random_position.make(moves[rng()%moves.size()]);}
    if(checked<1000)throw std::runtime_error("insufficient SEE comparisons");
    std::cout<<"tapered evaluation, symmetry and exchange tests passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
