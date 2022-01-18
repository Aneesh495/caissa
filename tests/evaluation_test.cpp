#include "caissa/evaluation.hpp"
#include <iostream>
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
    std::cout<<"tapered evaluation, symmetry and exchange tests passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
