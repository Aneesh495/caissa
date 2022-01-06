#include "caissa/attacks.hpp"
#include <iostream>
#include <stdexcept>
using namespace caissa;
void require(bool ok, const char* message) { if(!ok) throw std::runtime_error(message); }
int main() {
    try {
        require(parse_square("a1")==Square{0},"a1 encoding");
        require(!parse_square("i9"),"invalid square");
        require(square_name(63)=="h8","h8 encoding");
        require(Move::unpack(Move{1,18}.packed())==Move{1,18},"move packing");
        for(int p=0;p<128;++p) for(int score : {0,123,-123,29990,-29990})
            require(mate_from_table(mate_to_table(score,p),p)==score,"mate score round trip");
        require(attacks::validate_tables(),"ray attacks disagree with independent stepping");
        require(std::popcount(attacks::knight(0))==2,"corner knight");
        require(attacks::between(0,56)==0x0001010101010100ULL,"file ray");
        std::cout<<"core types and attack tables passed\n";
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
