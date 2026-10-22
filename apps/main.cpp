#include "caissa/version.hpp"
#include "caissa/position.hpp"
#include "caissa/reference.hpp"
#include <algorithm>
#include <charconv>
#include <iostream>
#include <string_view>
using namespace caissa;
namespace {
int parse_depth(std::string_view s) {
    int depth=-1;auto [p,e]=std::from_chars(s.data(),s.data()+s.size(),depth);
    if(e!=std::errc{}||p!=s.data()+s.size()||depth<0||depth>12) throw InputError("invalid depth");return depth;
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
        if(argc==2&&std::string_view(argv[1])=="--version") {std::cout<<version()<<'\n';return 0;}
        if(argc>=3&&(std::string_view(argv[1])=="--perft"||std::string_view(argv[1])=="--divide")) {
            int d=parse_depth(argv[2]);auto p=Position::from_fen(argc>3?argv[3]:start_fen,argc>4&&std::string_view(argv[4])=="960");
            if(std::string_view(argv[1])=="--perft") std::cout<<perft(p,d)<<'\n';
            else for(auto& [move,n]:divide(p,d)) std::cout<<move<<' '<<n<<'\n';
            return 0;
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
