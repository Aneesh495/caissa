#include "caissa/position_line.hpp"
#include "caissa/reference.hpp"
#include "caissa/rules.hpp"
#include <algorithm>
#include <iostream>
#include <random>
#include <stdexcept>

using namespace caissa;
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
Position fresh(std::string_view fen,const std::vector<std::string>& history,bool chess960) {
    auto position=Position::from_fen(fen,chess960);
    for(auto& text:history) {
        auto legal=reference::legal(position);
        auto found=std::find_if(legal.begin(),legal.end(),[&](Move move){return position.uci(move)==text;});
        if(found==legal.end())throw InputError("independent history has an illegal move");
        position.make(*found);
    }
    return position;
}
void same(const Position& actual,const Position& expected) {
    check(actual.coherent()&&expected.coherent(),"cached position is incoherent");
    check(actual.fen()==expected.fen()&&actual.key()==expected.key()&&actual.search_key()==expected.search_key()&&
          actual.repetition_key()==expected.repetition_key()&&actual.chess960()==expected.chess960(),"cached position metadata differs from fresh mailbox replay");
    check(std::ranges::equal(actual.history(),expected.history()),"cached reversible history differs from full replay");
    auto a=actual,b=expected;auto ar=rules(a),br=rules(b);
    check(ar.terminal==br.terminal&&ar.threefold_claim==br.threefold_claim&&ar.fifty_move_claim==br.fifty_move_claim,
          "cached draw state differs from full history");
}
}
int main(){try {
    std::mt19937 random(86028181);PositionLine line;std::vector<std::string> history;
    const std::array<std::pair<std::string_view,bool>,6> roots{{
        {start_fen,false},
        {"4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1",false},
        {"r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",false},
        {"4k3/8/8/8/8/8/8/6KR w H - 0 1",true},
        {"4k3/8/8/8/8/8/8/5KR1 w G - 0 1",true},
        {"7k/8/4K3/8/8/8/1P6/8 w - - 149 1",false}}};
    std::string_view root=start_fen;bool chess960=false;std::uint64_t reused=0,parsed=0,unmade=0;
    for(unsigned iteration=0;iteration<1000;++iteration) {
        if(iteration%71==0){auto selected=roots[(iteration/71)%roots.size()];root=selected.first;chess960=selected.second;history.clear();}
        if(!history.empty()&&iteration%5==0)history.resize(random()%history.size());
        auto position=fresh(root,history,chess960);
        for(int extra=0;extra<2;++extra) {
            auto legal=reference::legal(position);
            if(legal.empty()||history.size()>90){history.clear();position=Position::from_fen(root,chess960);break;}
            auto move=legal[random()%legal.size()];history.push_back(position.uci(move));position.make(move);
        }
        line=line.updated(root,history,chess960);same(line.current(),fresh(root,history,chess960));
        reused+=line.work().reused_plies;parsed+=line.work().parsed_plies;unmade+=line.work().unmade_plies;
        auto identical=line.updated(root,history,chess960);
        same(identical.current(),line.current());
        check(identical.work().reused_plies==history.size()&&identical.work().parsed_plies==0&&identical.work().unmade_plies==0,
              "identical position command reparsed validated history");
        if(iteration%17==0) {
            auto invalid=history;invalid.push_back("z9z9");bool rejected=false;
            try{(void)line.updated(root,invalid,chess960);}catch(const InputError&){rejected=true;}
            check(rejected,"illegal suffix was accepted");same(line.current(),position);
            rejected=false;try{(void)line.updated("garbage",{},chess960);}catch(const InputError&){rejected=true;}
            check(rejected,"invalid root was accepted");same(line.current(),position);
        }
    }
    history.clear();line=PositionLine();
    for(int cycle=0;cycle<256;++cycle)for(auto text:{"g1f3","g8f6","f3g1","f6g8"})history.emplace_back(text);
    line=line.updated(start_fen,history,false);same(line.current(),fresh(start_fen,history,false));
    check(line.current().repetitions()==257,"long reversible history was truncated");
    auto too_long=history;too_long.push_back("g1f3");bool rejected=false;
    try{(void)line.updated(start_fen,too_long,false);}catch(const InputError&){rejected=true;}
    check(rejected,"oversized cached history was accepted");
    history.resize(8);line=line.updated(start_fen,history,false);same(line.current(),fresh(start_fen,history,false));
    check(line.current().repetitions()==3&&line.work().unmade_plies==1016,"history truncation changed a draw claim");
    check(reused>0&&unmade>0&&parsed>0,"history workload did not exercise all update paths");
    std::cout<<"{\"status\":\"passed\",\"divergent_updates\":1000,\"duplicate_updates\":1000,\"reused_plies\":"<<reused
             <<",\"unmade_plies\":"<<unmade<<",\"newly_validated_plies\":"<<parsed<<",\"long_history\":1024}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
