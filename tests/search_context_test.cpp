#include "caissa/reference.hpp"
#include "caissa/search.hpp"
#include <algorithm>
#include <iostream>
#include <random>
#include <stdexcept>

using namespace caissa;
namespace {
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
Key avalanche(Key value) {
    value+=0x9e3779b97f4a7c15ULL;
    value=(value^(value>>30))*0xbf58476d1ce4e5b9ULL;
    value=(value^(value>>27))*0x94d049bb133111ebULL;
    return value^(value>>31);
}
// Expand the polynomial backwards from public history, without using the
// cached digest, its append operation, or the production Horner traversal.
Key reconstructed(const Position& position,unsigned synthetic_depth=0) {
    auto history=position.history();
    auto count=std::min(history.size(),std::size_t(position.halfmove())+1);
    Key polynomial=0,power=1;
    for(std::size_t offset=0;offset<count;++offset) {
        polynomial+=history[history.size()-1-offset]*power;
        power*=0x9e3779b185ebca87ULL;
    }
    auto key=position.key()^avalanche(polynomial^avalanche(Key(position.halfmove())+20000)^(Key(count)*0xd6e8feb86659fd93ULL));
    if(synthetic_depth)key^=avalanche(Key(synthetic_depth)+30000);
    return key;
}
void inspect(const Position& position,unsigned synthetic_depth=0) {
    require(position.coherent(),"incremental position or history digest is incoherent");
    require(position.search_key()==reconstructed(position,synthetic_depth),"incremental search identity differs from independent history expansion");
}
Undo play(Position& position,std::string_view text) {
    auto move=position.parse_uci(text);require(move.has_value(),"fixture move is illegal");
    auto undo=position.make(*move);inspect(position);return undo;
}
void restored(const Position& actual,const Position& saved,unsigned synthetic_depth=0) {
    inspect(actual,synthetic_depth);
    require(actual.fen()==saved.fen()&&actual.key()==saved.key()&&actual.search_key()==saved.search_key()
            &&actual.synthetic_search_path()==saved.synthetic_search_path()
            &&std::ranges::equal(actual.history(),saved.history()),"undo changed a position, clock, history, or synthetic context");
}
int minimax(Position& position,int depth,int ply) {
    auto legal=reference::legal(position);auto state=rules(position,legal);
    if(state.ended())return state.terminal==Termination::checkmate?-mate_score+ply:0;
    if(depth==0)return std::max(state.claimable()?0:-infinity,classical(position));
    int best=state.claimable()?0:-infinity;
    for(auto move:legal) {
        auto undo=position.make(move);best=std::max(best,-minimax(position,depth-1,ply+1));position.unmake(undo);
    }
    return best;
}
}
int main(){try {
    auto start=Position::start(),left=start,right=start;
    for(auto text:{"g1f3","g8f6","f3g1","f6g8"})play(left,text);
    for(auto text:{"b1c3","b8c6","c3b1","c6b8"})play(right,text);
    require(left.fen()==right.fen()&&left.repetition_key()==right.repetition_key(),"divergent history fixture does not transpose");
    require(left.search_key()!=right.search_key(),"equal-clock divergent histories shared a score identity");
    auto fen_only=Position::from_fen(left.fen());inspect(fen_only);
    require(fen_only.search_key()!=left.search_key(),"FEN invented the preceding game history");
    play(left,"e2e4");play(right,"e2e4");auto fresh=start;play(fresh,"e2e4");
    require(left.search_key()==right.search_key()&&left.search_key()==fresh.search_key(),"pawn reset retained unreachable history");
    auto high_clock=Position::from_fen("7k/8/8/8/8/8/8/R3K3 w - - 1000000 1");inspect(high_clock);
    for(auto text:{"a1a2","h8h7","a2a1","h7h8"})play(high_clock,text);
    inspect(high_clock);
    // Every special move must reset or retain the right reversible segment,
    // including castling where the internal destination contains our rook.
    for(auto [fen,move,chess960]:{
        std::tuple{"4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1","g5f6",false},
        std::tuple{"4k3/6P1/8/8/8/8/8/4K3 w - - 17 1","g7g8n",false},
        std::tuple{"3r3k/4P3/8/8/8/8/8/4K3 w - - 24 1","e7d8q",false},
        std::tuple{"r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 31 1","e1g1",false},
        std::tuple{"4k3/8/8/8/8/8/8/6KR w H - 9 1","g1h1",true},
        std::tuple{"4k3/8/8/8/8/8/8/5KR1 w G - 9 1","f1g1",true},
        std::tuple{"7k/8/8/8/8/8/r7/R3K3 w - - 89 1","a1a2",false}}) {
        auto position=Position::from_fen(fen,chess960),saved=position;inspect(position);
        auto undo=play(position,move);
        if(position.halfmove()==0)require(position.search_key()==Position::from_fen(position.fen(),chess960).search_key(),"capture or promotion failed to reset context");
        else require(position.halfmove()==saved.halfmove()+1,"castling incorrectly reset the rule clock");
        position.unmake(undo);restored(position,saved);
    }
    std::vector<Undo> long_undo;auto repeated=start;
    for(int cycle=0;cycle<256;++cycle)for(auto text:{"g1f3","g8f6","f3g1","f6g8"})long_undo.push_back(play(repeated,text));
    require(repeated.repetitions()==257,"long history lost repetition multiplicity");
    while(!long_undo.empty()){repeated.unmake(long_undo.back());long_undo.pop_back();inspect(repeated);}
    restored(repeated,start);
    auto synthetic=high_clock,saved=synthetic;auto null1=synthetic.make_null();inspect(synthetic,1);
    auto null_state=synthetic;auto null2=synthetic.make_null();inspect(synthetic,2);
    require(synthetic.key()==saved.key()&&synthetic.search_key()!=saved.search_key(),"double null reused a real-history score");
    auto actual=synthetic.make(*synthetic.parse_uci("a1a2"));inspect(synthetic,2);
    synthetic.unmake(actual);inspect(synthetic,2);synthetic.unmake(null2);restored(synthetic,null_state,1);
    synthetic.unmake(null1);restored(synthetic,saved);

    std::mt19937_64 random(104729);auto position=start;
    std::vector<std::pair<Undo,Position>> stack;std::uint64_t transitions=0,null_branches=0;
    while(transitions<1000000) {
        inspect(position);
        if(!stack.empty()&&(random()%5==0||stack.size()>=128)) {
            auto [undo,before]=std::move(stack.back());stack.pop_back();position.unmake(undo);restored(position,before);++transitions;continue;
        }
        auto legal=reference::legal(position);
        if(legal.empty()) {
            while(!stack.empty()){position.unmake(stack.back().first);stack.pop_back();inspect(position);}
            position=start;continue;
        }
        if(random()%97==0&&!position.in_check(position.side())) {
            auto before=position;auto undo=position.make_null();inspect(position,1);++null_branches;
            auto children=reference::legal(position);
            if(!children.empty()) {
                auto child_undo=position.make(children[random()%children.size()]);inspect(position,1);
                position.unmake(child_undo);inspect(position,1);
            }
            position.unmake(undo);restored(position,before);
        }
        auto before=position;auto undo=position.make(legal[random()%legal.size()]);inspect(position);
        stack.emplace_back(undo,std::move(before));++transitions;
    }
    while(!stack.empty()){auto [undo,before]=std::move(stack.back());stack.pop_back();position.unmake(undo);restored(position,before);}

    auto table=std::make_shared<TranspositionTable>(1);Search engine(table);
    SearchOptions exact;exact.null_move=false;exact.lmr=false;exact.extensions=false;exact.futility=false;exact.quiescence=false;
    Limits limits;limits.depth=3;unsigned exact_searches=0;
    for(int clock:{0,99,100,149,150})for(int cycles:{0,1,2}) {
        auto root=Position::from_fen("7k/8/8/8/8/8/8/R3K3 w - - "+std::to_string(clock)+" 1");
        for(int cycle=0;cycle<cycles;++cycle)for(auto text:{"a1a2","h8h7","a2a1","h7h8"})play(root,text);
        auto expected=minimax(root,3,0);
        for(bool enabled:{false,true})for(auto seed:{0ULL,11ULL}) {
            exact.table=enabled;exact.root_shuffle_seed=seed;
            auto result=engine.run(root,limits,exact,std::make_shared<SearchControl>());
            require(result.score==expected,"history-sensitive TT search differs from mailbox minimax");++exact_searches;
        }
    }
    table->clear();auto history=start;
    for(auto text:{"g1f3","g8f6","f3g1","f6g8"})play(history,text);
    table->store(history.search_key(),{},1234,567,12,Bound::exact,0);
    require(table->probe(history.search_key()).has_value()&&!table->probe(Position::from_fen(history.fen()).search_key()),"TT bound crossed a known-history boundary");
    std::cout<<"{\"status\":\"passed\",\"transitions\":"<<transitions<<",\"null_branches\":"<<null_branches
             <<",\"long_history_plies\":1024,\"history_clock_minimax_searches\":"<<exact_searches<<"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
