#include "caissa/network.hpp"
#include "caissa/evaluation.hpp"
#include <iostream>
#include <random>
#include <stdexcept>
using namespace caissa;
int main(int argc,char** argv){try {
    if(argc!=3)throw InputError("network_test network transitions");auto net=Network::load(argv[1]);auto p=Position::start();auto acc=net->refresh(p);
    auto count=std::stoull(argv[2]);if(count>10000000)throw InputError("too many transitions");std::mt19937 rng(982451653);
    for(std::uint64_t i=0;i<count;++i) {
        auto moves=p.legal();if(moves.empty()||p.halfmove()>150){p=Position::start();acc=net->refresh(p);moves=p.legal();}
        auto before=acc;auto fen=p.fen();auto u=p.make(moves[rng()%moves.size()]);net->update(p,u,acc);
        if(acc!=net->refresh(p))throw std::runtime_error("incremental accumulator differs from full refresh");
        if(net->evaluate(p,acc,true)!=net->evaluate(p,acc,false))throw std::runtime_error("scalar/SIMD mismatch");
        if(i%127==0) {
            int neural=net->evaluate(p,acc),baseline=classical(p);
            for(int weight:{0,10,25,50,75,100}) {
                int expected=(neural*weight+baseline*(100-weight))/100;
                if(net->evaluate(p,acc,false,weight)!=expected||net->evaluate(p,acc,true,weight)!=expected)
                    throw std::runtime_error("combined evaluator changed the established blend");
            }
        }
        if(!p.coherent())throw std::runtime_error("incremental board hash mismatch");
        p.unmake(u);acc=before;if(p.fen()!=fen||acc!=net->refresh(p))throw std::runtime_error("network undo mismatch");
        u=p.make(moves[rng()%moves.size()]);net->update(p,u,acc);
    }
    std::cout<<"{\"transitions\":"<<count<<",\"status\":\"passed\",\"kernel\":\""<<native_kernel()<<"\"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
