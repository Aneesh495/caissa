#include "caissa/position.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <iostream>
#include <stdexcept>

using namespace caissa;
namespace {
Key mix(Key v) {
    v+=0x9e3779b97f4a7c15ULL;v=(v^(v>>30))*0xbf58476d1ce4e5b9ULL;
    v=(v^(v>>27))*0x94d049bb133111ebULL;return v^(v>>31);
}
// The previous production lookup, retained for scaling measurements only.
Key previous(const Position& p) {
    Key context=mix(p.halfmove()+20000);
    auto history=p.history();auto count=std::min(history.size(),std::size_t(p.halfmove())+1);
    for(std::size_t i=history.size()-count;i<history.size();++i)context=mix(context^history[i]);
    return p.key()^context;
}
volatile Key consumed=0;
}
int main(){try {
    constexpr unsigned iterations=100000,repeats=7;
    for(unsigned plies:{0U,16U,64U,128U,512U,1024U}) {
        auto p=Position::start();
        for(unsigned i=0;i<plies;++i) {
            auto text=std::array{"g1f3","g8f6","f3g1","f6g8"}[i%4];
            auto move=p.parse_uci(text);if(!move)throw std::runtime_error("invalid benchmark history");p.make(*move);
        }
        std::array<Position,4> positions{p,p,p,p};
        for(unsigned i=1;i<positions.size();++i) {
            positions[i]=positions[i-1];auto move=positions[i].parse_uci(std::array{"g1f3","g8f6","f3g1"}[i-1]);
            if(!move)throw std::runtime_error("invalid benchmark variant");positions[i].make(*move);
        }
        for(unsigned repeat=0;repeat<repeats;++repeat)for(unsigned turn=0;turn<2;++turn) {
            bool incremental=(repeat+turn)%2==0;
            Key signature=0;auto started=std::chrono::steady_clock::now();
            for(unsigned i=0;i<iterations;++i) {
                // Prevent the compiler from replacing repeated board reads
                // with a precomputed result in either implementation.
                std::atomic_signal_fence(std::memory_order_seq_cst);
                signature+=incremental?positions[i%4].search_key():previous(positions[i%4]);
            }
            auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-started).count();
            consumed=signature;
            std::cout<<"{\"plies\":"<<plies<<",\"repeat\":"<<repeat<<",\"mode\":\""<<(incremental?"incremental":"previous-scan")
                     <<"\",\"lookups\":"<<iterations<<",\"nanoseconds\":"<<ns<<",\"signature\":"<<signature<<"}\n";
        }
    }
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
