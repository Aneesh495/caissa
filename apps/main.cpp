#include "caissa/version.hpp"
#include "caissa/uci.hpp"
#include "caissa/selfplay.hpp"
#include "caissa/network.hpp"
#include "caissa/serialization.hpp"
#include "caissa/state_probe.hpp"
#include "caissa/position.hpp"
#include "caissa/reference.hpp"
#include "caissa/search.hpp"
#include <algorithm>
#include <charconv>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <chrono>
#include <string_view>
using namespace caissa;
namespace {
std::uint64_t parse_u64(std::string_view text) {
    std::uint64_t value=0;auto [end,error]=std::from_chars(text.data(),text.data()+text.size(),value);
    if(error!=std::errc{}||end!=text.data()+text.size())throw InputError("invalid unsigned integer");return value;
}
std::string key_text(Key key){std::ostringstream text;text<<std::hex<<std::setw(16)<<std::setfill('0')<<key;return text.str();}
int parse_depth(std::string_view s) {
    int depth=-1;auto [p,e]=std::from_chars(s.data(),s.data()+s.size(),depth);
    if(e!=std::errc{}||p!=s.data()+s.size()||depth<0||depth>80) throw InputError("invalid depth");return depth;
}
void inspect(std::string_view text,bool tactical=false) {
    bool c960=text.starts_with("960|");if(c960) text.remove_prefix(4);
    auto p=Position::from_fen(text,c960);auto moves=p.legal();auto ref=reference::legal(p);
    auto sort=[](Moves& list){std::sort(list.begin(),list.end(),[](Move a,Move b){return a.packed()<b.packed();});};
    sort(moves);sort(ref);if(moves!=ref) throw std::logic_error("mailbox and bitboard move sets disagree");
    std::cout<<"{\"fen\":\""<<p.fen()<<"\",\"key\":"<<json_quote(key_text(p.key()))<<",\"repetition_key\":"<<json_quote(key_text(p.repetition_key()))<<",\"check\":"<<(p.in_check(p.side())?"true":"false")<<",\"moves\":[";
    bool first=true;for(auto m:moves){if(!first)std::cout<<',';first=false;std::cout<<'"'<<p.uci(m)<<'"';}
    std::cout<<']';
    if(tactical) {
        auto available=p.availability();auto captures=p.legal_tactical();
        std::cout<<",\"any\":"<<(available.any()?"true":"false")<<",\"availability_check\":"<<(available.checked()?"true":"false")<<",\"tactical\":[";
        first=true;for(auto m:captures){if(!first)std::cout<<',';first=false;std::cout<<json_quote(p.uci(m));}std::cout<<']';
    }
    std::cout<<"}\n"<<std::flush;
}
}
int main(int argc,char** argv) {
    try {
        if(argc==1)return uci_loop(std::cin,std::cout);
        if(argc==3&&std::string_view(argv[1])=="--state-probe") {
            auto network=Network::load(argv[2]);return state_probe(std::cin,std::cout,*network);
        }
        if((argc==4||argc==5)&&std::string_view(argv[1])=="--eval-bench") {
            auto net=Network::load(argv[2]);auto calls=parse_u64(argv[3]);if(calls<100||calls>10000000)throw InputError("evaluation calls outside bounds");
            auto requested_weight=argc==5?parse_u64(argv[4]):100;if(requested_weight>100)throw InputError("neural weight outside percentage bounds");int weight=static_cast<int>(requested_weight);
            auto p=Position::start();auto accumulator=net->refresh(p);std::int64_t signature=0;
            for(int i=0;i<128;++i)signature+=net->evaluate(p,accumulator);
            auto begin=monotonic_ns();for(std::uint64_t i=0;i<calls;++i)signature+=net->evaluate(p,accumulator,true,weight);auto scalar=monotonic_ns()-begin;
            begin=monotonic_ns();for(std::uint64_t i=0;i<calls;++i)signature+=net->evaluate(p,accumulator,false,weight);auto native=monotonic_ns()-begin;
            begin=monotonic_ns();for(std::uint64_t i=0;i<calls;++i)signature+=classical(p);auto baseline=monotonic_ns()-begin;
            std::int64_t legacy_signature=0;begin=monotonic_ns();
            for(std::uint64_t i=0;i<calls;++i) {
                if(weight==0)legacy_signature+=classical(p);
                else {int score=net->evaluate(p,accumulator);legacy_signature+=weight==100?score:(score*weight+classical(p)*(100-weight))/100;}
            }
            auto legacy=monotonic_ns()-begin;
            std::cout<<"{\"calls\":"<<calls<<",\"width\":"<<transformer_width<<",\"neural_weight\":"<<weight<<",\"scalar_ns_per_call\":"<<static_cast<double>(scalar)/static_cast<double>(calls)<<",\"native_ns_per_call\":"<<static_cast<double>(native)/static_cast<double>(calls)<<",\"legacy_blend_ns_per_call\":"<<static_cast<double>(legacy)/static_cast<double>(calls)<<",\"legacy_blend_signature\":"<<legacy_signature<<",\"classical_ns_per_call\":"<<static_cast<double>(baseline)/static_cast<double>(calls)<<",\"signature\":"<<signature<<"}\n";return 0;
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
        if(argc==2&&std::string_view(argv[1])=="--eval-probe") {
            std::string line;
            while(std::getline(std::cin,line)) {
                auto p=Position::from_fen(line);
                std::cout<<"{\"classical\":"<<classical(p)<<",\"contract\":"<<classical_contract_version<<"}\n"<<std::flush;
            }
            return 0;
        }
        if((argc==3||argc==4)&&std::string_view(argv[1])=="--net-probe") {
            auto net=Network::load(argv[2]);std::string line;
            auto requested_weight=argc==4?parse_u64(argv[3]):100;if(requested_weight>100)throw InputError("neural weight outside percentage bounds");int weight=static_cast<int>(requested_weight);
            while(std::getline(std::cin,line)) {
                auto p=Position::from_fen(line);auto acc=net->refresh(p);
                auto interval=net->score_interval(p,weight);
                std::cout<<"{\"scalar\":"<<net->evaluate(p,acc,true,weight)<<",\"native\":"<<net->evaluate(p,acc,false,weight)<<",\"lower\":"<<interval.lower<<",\"upper\":"<<interval.upper<<"}\n"<<std::flush;
            }
            return 0;
        }
        if((argc==6||(argc==7&&std::string_view(argv[6])=="searched-v2"))&&std::string_view(argv[1])=="--selfplay-pair") {
            std::uint64_t pair=parse_u64(argv[2]),seed=parse_u64(argv[3]),nodes=parse_u64(argv[4]);
            int opening=parse_depth(argv[5]);selfplay_pair(std::cout,pair,seed,nodes,opening,512,argc==7);return 0;
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
            std::cout<<"{\"bestmove\":\""<<p.uci(r.best)<<"\",\"score\":"<<r.score<<",\"depth\":"<<r.info.depth<<",\"nodes\":"<<r.info.nodes<<",\"milliseconds\":"<<r.info.elapsed_ms<<",\"completed_depth_nodes\":"<<r.info.completed_depth_nodes<<",\"evaluator_calls\":"<<r.info.stats.evaluator_calls<<",\"evaluator_ns\":"<<r.info.stats.evaluator_ns<<",\"table_hits\":"<<r.info.stats.table_hits<<",\"qnodes\":"<<r.info.stats.qnodes<<",\"pv\":[";
            bool first=true;for(auto m:r.pv){if(!first)std::cout<<',';first=false;std::cout<<'"'<<p.uci(m)<<'"';p.make(m);}
            std::cout<<"]}\n";return 0;
        }
        if(argc==2&&(std::string_view(argv[1])=="--inspect"||std::string_view(argv[1])=="--inspect-tactical")) {
            std::string line;
            while(std::getline(std::cin,line)) {
                try {inspect(line,std::string_view(argv[1])=="--inspect-tactical");}catch(const std::exception&){std::cout<<"{\"error\":\"invalid position or reference mismatch\"}\n"<<std::flush;}
            }
            return 0;
        }
        std::cerr<<"Usage: caissa --version | --perft depth [FEN] [960] | --divide depth [FEN] | --inspect\n";return 2;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
