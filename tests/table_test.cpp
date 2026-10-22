#include "caissa/table.hpp"
#include <iostream>
#include <thread>
#include <vector>
#include <stdexcept>
using namespace caissa;
int main(){try {
    TranspositionTable table(1);table.new_search();
    table.store(42,{1,18},29993,12,8,Bound::lower,4);
    auto e=table.probe(42);if(!e||mate_from_table(e->score,7)!=29990||e->bound!=Bound::lower)throw std::runtime_error("mate normalization or bound lost");
    if(table.probe(43))throw std::runtime_error("false key match");
    std::vector<std::jthread> threads;
    for(int t=0;t<8;++t) threads.emplace_back([&,t]{for(int i=0;i<10000;++i){auto key=static_cast<Key>(i*8+t);table.store(key,{1,18},i%100,0,i%16,Bound::exact,0);auto hit=table.probe(key);if(hit&&hit->key!=key)std::terminate();}});
    threads.clear();table.clear();if(table.probe(42))throw std::runtime_error("clear failed");
    std::cout<<"locked table replacement, concurrent access and mate scores passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
