#include "caissa/version.hpp"
#include "caissa/uci.hpp"
#include "caissa/selfplay.hpp"
#include "caissa/network.hpp"
#include "caissa/serialization.hpp"
#include "caissa/position.hpp"
#include "caissa/reference.hpp"
#include "caissa/search.hpp"
#include <algorithm>
#include <charconv>
#include <iostream>
#include <chrono>
#include <string_view>
using namespace caissa;
namespace {
int parse_depth(std::string_view s) {
    int depth=-1;auto [p,e]=std::from_chars(s.data(),s.data()+s.size(),depth);
    if(e!=std::errc{}||p!=s.data()+s.size()||depth<0||depth>80) throw InputError("invalid depth");return depth;
}
void inspect(std::string_view text) {
    bool c960=text.starts_with("960|");if(c960) text.remove_prefix(4);
    auto p=Position::from_fen(text,c960);auto moves=p.legal();auto ref=reference::legal(p);
    auto sort=[](Moves& list){std::sort(list.begin(),list.end(),[](Move a,Move b){return a.packed()<b.packed();});};
    sort(moves);sort(ref);if(moves!=ref) throw std::logic_error("mailbox and bitboard move sets disagree");
    std::cout<<"{\"fen\":\""<<p.fen()<<"\",\"key\":"<<p.key()<<",\"repetition_key\":"<<p.repetition_key()<<",\"check\":"<<(p.in_check(p.side())?"true":"false")<<",\"moves\":[";
    bool first=true;for(auto m:moves){if(!first)std::cout<<',';first=false;std::cout<<'"'<<p.uci(m)<<'"';}
    std::cout<<"]}\n"<<std::flush;
}
}
int main(int argc,char** argv) {
    try {
        if(argc==1)return uci_loop(std::cin,std::cout);
        if(argc==4&&std::string_view(argv[1])=="--eval-bench") {
            auto net=Network::load(argv[2]);auto calls=std::stoull(argv[3]);if(calls<100||calls>10000000)throw InputError("evaluation calls outside bounds");
            auto p=Position::start();auto accumulator=net->refresh(p);std::int64_t signature=0;
            for(int i=0;i<128;++i)signature+=net->evaluate(p,accumulator);
            auto begin=monotonic_ns();for(std::uint64_t i=0;i<calls;++i)signature+=net->evaluate(p,accumulator,true);auto scalar=monotonic_ns()-begin;
            begin=monotonic_ns();for(std::uint64_t i=0;i<calls;++i)signature+=net->evaluate(p,accumulator,false);auto native=monotonic_ns()-begin;
            begin=monotonic_ns();for(std::uint64_t i=0;i<calls;++i)signature+=classical(p);auto baseline=monotonic_ns()-begin;
            std::cout<<"{\"calls\":"<<calls<<",\"width\":"<<transformer_width<<",\"scalar_ns_per_call\":"<<static_cast<double>(scalar)/static_cast<double>(calls)<<",\"native_ns_per_call\":"<<static_cast<double>(native)/static_cast<double>(calls)<<",\"classical_ns_per_call\":"<<static_cast<double>(baseline)/static_cast<double>(calls)<<",\"signature\":"<<signature<<"}\n";return 0;
        }
        if(argc==2&&std::string_view(argv[1])=="--pgn-json") {
            std::string input;char c;while(std::cin.get(c)){if(input.size()>=1048576)throw InputError("PGN exceeds 1 MiB");input+=c;}
            write_game_json(std::cout,Game::parse(input));return 0;
        }
        if(argc>=4&&std::string_view(argv[1])=="--move-json") {
            auto p=Position::from_fen(argv[2],argc>4&&std::string_view(argv[4])=="960");auto move=p.parse_uci(argv[3]);
            if(!move)throw InputError("illegal requested move");auto text=san(p,*move);p.make(*move);
            std::cout<<"{\"fen\":"<<json_quote(p.fen())<<",\"san\":"<<json_quote(text)<<"}\n";return 0;
        }
        if(argc==3&&std::string_view(argv[1])=="--net-probe") {
            auto net=Network::load(argv[2]);std::string line;
            while(std::getline(std::cin,line)) {
                auto p=Position::from_fen(line);auto acc=net->refresh(p);
                std::cout<<"{\"scalar\":"<<net->evaluate(p,acc,true)<<",\"native\":"<<net->evaluate(p,acc,false)<<"}\n"<<std::flush;
            }
            return 0;
        }
        if(argc==6&&std::string_view(argv[1])=="--selfplay-pair") {
            std::uint64_t pair=std::stoull(argv[2]),seed=std::stoull(argv[3]),nodes=std::stoull(argv[4]);
            int opening=parse_depth(argv[5]);selfplay_pair(std::cout,pair,seed,nodes,opening,512);return 0;
        }
        if(argc==2&&std::string_view(argv[1])=="--version") {std::cout<<version()<<'\n';return 0;}
        if(argc>=3&&(std::string_view(argv[1])=="--perft"||std::string_view(argv[1])=="--divide")) {
            int d=parse_depth(argv[2]);auto p=Position::from_fen(argc>3?argv[3]:start_fen,argc>4&&std::string_view(argv[4])=="960");
            if(std::string_view(argv[1])=="--perft") std::cout<<perft(p,d)<<'\n';
            else for(auto& [move,n]:divide(p,d)) std::cout<<move<<' '<<n<<'\n';
            return 0;
        }
        if(argc>=3&&std::string_view(argv[1])=="--search") {
            auto p=Position::from_fen(argc>3?argv[3]:start_fen);Limits limits;limits.depth=parse_depth(argv[2]);
            SearchOptions options;if(argc>4)options.threads=parse_depth(argv[4]);
            Search search(std::make_shared<TranspositionTable>(32));
            auto r=search.run(p,limits,options,std::make_shared<SearchControl>());
            std::cout<<"{\"bestmove\":\""<<p.uci(r.best)<<"\",\"score\":"<<r.score<<",\"depth\":"<<r.info.depth<<",\"nodes\":"<<r.info.nodes<<",\"milliseconds\":"<<r.info.elapsed_ms<<",\"pv\":[";
            bool first=true;for(auto m:r.pv){if(!first)std::cout<<',';first=false;std::cout<<'"'<<p.uci(m)<<'"';p.make(m);}
            std::cout<<"]}\n";return 0;
        }
        if(argc==2&&std::string_view(argv[1])=="--inspect") {
            std::string line;
            while(std::getline(std::cin,line)) {
                try {inspect(line);}catch(const std::exception&){std::cout<<"{\"error\":\"invalid position or reference mismatch\"}\n"<<std::flush;}
            }
            return 0;
        }
        std::cerr<<"Usage: caissa --version | --perft depth [FEN] [960] | --divide depth [FEN] | --inspect\n";return 2;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
