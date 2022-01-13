#include "caissa/position.hpp"
#include "caissa/reference.hpp"
#include <algorithm>
#include <iostream>
#include <random>
#include <stdexcept>
using namespace caissa;
void check(bool b,const char* text) { if(!b) throw std::runtime_error(text); }
int main() {
    try {
        auto p=Position::start();check(p.fen()==start_fen,"FEN round trip");
        check(perft(p,1)==20,"start depth 1");check(perft(p,2)==400,"start depth 2");
        check(perft(p,3)==8902,"start depth 3");check(perft(p,4)==197281,"start depth 4");
        auto kiwi=Position::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
        check(perft(kiwi,3)==97862,"kiwipete depth 3");
        auto ep=Position::from_fen("4k3/8/8/r4pPK/8/8/8/8 w - f6 0 1");
        check(!ep.parse_uci("g5f6"),"en passant exposes king");
        for(auto fen:{"8/8/8/8/8/8/8/8 w - - 0 1","4k3/8/8/8/8/8/8/4K3 w K - 0 1","4k3/8/8/8/8/8/8/4K3 w - - -1 0"}) {
            bool rejected=false;try {Position::from_fen(fen);}catch(const InputError&){rejected=true;}check(rejected,"bad FEN accepted");
        }
        std::mt19937 rng(1729);std::vector<Undo> stack;std::vector<std::string> fens;
        for(int i=0;i<5000;++i) {
            auto moves=p.legal();if(moves.empty()||stack.size()>200) {while(!stack.empty()){p.unmake(stack.back());stack.pop_back();fens.pop_back();}moves=p.legal();}
            auto slow=reference::legal(p);auto fast=moves;
            auto sorter=[](Move a,Move b){return a.packed()<b.packed();};
            std::sort(slow.begin(),slow.end(),sorter);std::sort(fast.begin(),fast.end(),sorter);check(slow==fast,"independent mailbox mismatch");
            auto before=p.fen();auto key=p.key();auto history=p.history().size();auto m=moves[rng()%moves.size()];
            auto u=p.make(m);check(p.coherent(),"state incoherent after make");p.unmake(u);
            check(p.fen()==before&&p.key()==key&&p.history().size()==history,"unmake restoration");
            fens.push_back(before);stack.push_back(p.make(m));
        }
        while(!stack.empty()){p.unmake(stack.back());check(p.fen()==fens.back(),"stack restoration");stack.pop_back();fens.pop_back();}
        auto overlap=Position::from_fen("4k3/8/8/8/8/8/8/5KR1 w G - 0 1",true);
        auto castle=overlap.parse_uci("f1g1");check(castle.has_value(),"overlap castle absent");
        auto before=overlap.fen();auto u=overlap.make(*castle);
        check(overlap.at(6)==piece(Color::white,Kind::king)&&overlap.at(5)==piece(Color::white,Kind::rook),"overlap castle result");
        overlap.unmake(u);check(overlap.fen()==before,"overlap unmake");
        std::cout<<"FEN, perft, castling, en passant and restoration passed\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
