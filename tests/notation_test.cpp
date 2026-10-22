#include "caissa/notation.hpp"
#include <iostream>
#include <stdexcept>
using namespace caissa;
int main(){try {
    auto game=Game::parse("[Event \"Example\"]\n[Result \"*\"]\n1.e4 {center} (1.d4 d5 (1...Nf6)) e5 2.Nf3 Nc6 3.Bb5 a6 *");
    if(game.nodes.size()!=10)throw std::runtime_error("variation node count");
    auto exported=game.pgn();auto copy=Game::parse(exported);
    if(copy.nodes.size()!=game.nodes.size()||copy.pgn()!=exported)throw std::runtime_error("PGN round trip");
    auto p=Position::start();for(auto text:{"e4","e5","Nf3","Nc6","Bc4","Nf6","O-O"}){auto m=parse_san(p,text);if(!m)throw std::runtime_error("SAN move missing");p.make(*m);}
    bool rejected=false;try{Game::parse("1. e4 (1. d4 *");}catch(const InputError&){rejected=true;}if(!rejected)throw std::runtime_error("malformed variation accepted");
    rejected=false;try{Game::parse("1. e5 *");}catch(const InputError&){rejected=true;}if(!rejected)throw std::runtime_error("illegal SAN accepted");
    std::cout<<"SAN, nested variations, comments and deterministic PGN export passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
