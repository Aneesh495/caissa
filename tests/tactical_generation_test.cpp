#include "caissa/search.hpp"
#include "caissa/reference.hpp"
#include <algorithm>
#include <iostream>
#include <random>
using namespace caissa;
namespace {
void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
bool tactical(const Position& p,Move m){return m.promotion!=Kind::none||m.flag==MoveFlag::en_passant||(m.flag!=MoveFlag::castle&&p.at(m.to));}
void same_rule(const RuleState& a,const RuleState& b){require(a.terminal==b.terminal&&a.threefold_claim==b.threefold_claim&&a.fifty_move_claim==b.fifty_move_claim,"availability changed draw or terminal rules");}
void inspect(Position& p) {
    auto before=p;auto moves=p.legal();auto filtered=moves;
    std::erase_if(filtered,[&](Move m){return !tactical(p,m);});
    require(filtered==p.legal_tactical(),"tactical moves differ in membership or stable order");
    auto available=p.availability();require(available.any()==!moves.empty()&&available.checked()==p.in_check(p.side()),"availability differs from complete legal list");
    same_rule(rules(p,moves),rules(p,available));
    auto slow=reference::legal(p);auto fast=moves;
    auto less=[](Move a,Move b){return a.packed()<b.packed();};std::sort(slow.begin(),slow.end(),less);std::sort(fast.begin(),fast.end(),less);
    require(slow==fast,"full move generation differs from independent mailbox");
    require(p.coherent()&&p.fen()==before.fen()&&p.key()==before.key()&&p.search_key()==before.search_key()&&p.repetition_key()==before.repetition_key()&&std::equal(p.history().begin(),p.history().end(),before.history().begin(),before.history().end()),"move query changed board or history");
    if(!moves.empty()) {
        auto undo=p.make(moves.front());bool rejected=false;try{rules(p,available);}catch(const InputError&){rejected=true;}
        require(rejected,"stale availability accepted after move");p.unmake(undo);same_rule(rules(p,moves),rules(p,available));
    }
    auto undo=p.make_null();bool rejected=false;try{rules(p,available);}catch(const InputError&){rejected=true;}
    require(rejected,"stale availability accepted after null move");p.unmake(undo);
}
SearchResult run(const Position& p,SearchOptions options,bool enabled) {
    options.tactical_generation=enabled;Limits limits;limits.nodes=6000;limits.depth=8;
    Search search(std::make_shared<TranspositionTable>(4));return search.run(p,limits,options,std::make_shared<SearchControl>());
}
void identical(const SearchResult& a,const SearchResult& b) {
    require(a.best==b.best&&a.score==b.score&&a.pv==b.pv&&a.info.depth==b.info.depth&&a.info.nodes==b.info.nodes&&a.info.completed_depth_nodes==b.info.completed_depth_nodes,"lazy tactical generation changed fixed-node result");
    auto x=a.info.stats,y=b.info.stats;
    require(x.qnodes==y.qnodes&&x.table_hits==y.table_hits&&x.table_cutoffs==y.table_cutoffs&&x.beta_cutoffs==y.beta_cutoffs&&x.null_cutoffs==y.null_cutoffs&&x.lmr_searches==y.lmr_searches&&x.researches==y.researches&&x.futility_skips==y.futility_skips&&x.evaluator_calls==y.evaluator_calls&&x.neural_evaluations==y.neural_evaluations&&x.neural_bound_cutoffs==y.neural_bound_cutoffs&&x.evaluation_cache_hits==y.evaluation_cache_hits,"lazy generation changed search tree or evaluator requests");
}
}
int main(int argc,char** argv){try {
    std::vector<Position> cases;
    for(auto fen:std::array<std::string_view,10>{start_fen,"r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1","8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1","1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1","4k3/8/8/r4pPK/8/8/8/8 w - f6 0 1","4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1","7k/6Q1/5K2/8/8/8/8/8 b - - 150 80","7k/5Q2/5K2/8/8/8/8/8 b - - 0 1","4k3/8/8/8/8/8/8/R3K3 w - - 100 51","4k3/8/8/8/8/8/8/4K3 w - - 150 80"})cases.push_back(Position::from_fen(fen));
    for(auto fen:{"4k3/8/8/8/8/8/8/5KR1 w G - 0 1","4k3/8/8/8/8/8/8/2RK4 w C - 0 1"})cases.push_back(Position::from_fen(fen,true));
    auto repeated=Position::start();auto available=repeated.availability();
    for(auto text:{"g1f3","g8f6","f3g1","f6g8","g1f3","g8f6","f3g1","f6g8"})repeated.make(*repeated.parse_uci(text));
    require(rules(repeated,available).threefold_claim,"board-only availability hid new repetition claim");cases.push_back(repeated);
    for(auto& p:cases)inspect(p);
    std::mt19937 rng(32452843);auto p=Position::start();
    for(int i=0;i<20000;++i) {
        inspect(p);auto moves=p.legal();if(moves.empty()||p.history().size()>240){p=cases[static_cast<std::size_t>(rng()%cases.size())];moves=p.legal();}
        if(!moves.empty())p.make(moves[rng()%moves.size()]);if(i%2500==2499)cases.push_back(p);
    }
    std::vector<SearchOptions> modes(2);modes[1].quiescence=false;
    for(int i=1;i<argc;++i) {
        auto net=Network::load(argv[i]);
        for(int weight:{10,100}){SearchOptions option;option.network=net;option.neural_weight=weight;modes.push_back(option);}
        SearchOptions option;option.network=net;option.neural_weight=10;option.scalar_network=true;option.evaluation_cache=true;modes.push_back(option);
    }
    std::uint64_t pairs=0;
    for(auto& options:modes)for(auto& position:cases){identical(run(position,options,false),run(position,options,true));++pairs;}
    std::cout<<"{\"status\":\"passed\",\"move_queries\":20000,\"search_pairs\":"<<pairs<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
