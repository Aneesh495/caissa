#include "caissa/network.hpp"
#include "caissa/evaluation.hpp"
#include <algorithm>
#include <bit>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <unistd.h>

using namespace caissa;
namespace {
void require(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
struct Fixture {
    std::filesystem::path path=std::filesystem::temp_directory_path()/
        ("caissa-precision-"+std::to_string(getpid())+".cai");
    std::vector<std::uint8_t> bytes;
    Fixture() {
        constexpr std::size_t payload=feature_count*transformer_width*2+transformer_width*4+
            dense1_width*transformer_width*4+dense1_width*4+dense2_width*dense1_width*2+
            dense2_width*4+dense2_width*2+4;
        bytes.assign(120+payload,0);std::string magic="CAISSAN4";
        std::copy(magic.begin(),magic.end(),bytes.begin());
        const std::array<std::uint32_t,8> fields{4,1,feature_count,transformer_width,dense1_width,dense2_width,4096,8188};
        for(std::size_t i=0;i<fields.size();++i)put(8+i*4,fields[i]);
        std::fill(bytes.begin()+40,bytes.begin()+104,'0');put(104,static_cast<std::uint32_t>(payload));put(116,1);
        std::mt19937 random(32452843);std::size_t at=120;
        auto weights=[&](std::size_t count){for(std::size_t i=0;i<count;++i){auto value=static_cast<std::uint16_t>(random()%65536);bytes[at++]=static_cast<std::uint8_t>(value);bytes[at++]=static_cast<std::uint8_t>(value>>8);}};
        auto biases=[&](std::size_t count){for(std::size_t i=0;i<count;++i){auto value=static_cast<std::int32_t>(random()%536870913)-(1<<28);put(at,std::bit_cast<std::uint32_t>(value));at+=4;}};
        weights(feature_count*transformer_width);biases(transformer_width);
        weights(dense1_width*transformer_width*2);biases(dense1_width);
        weights(dense2_width*dense1_width);biases(dense2_width);
        weights(dense2_width);biases(1);
        require(at==bytes.size(),"precision fixture payload accounting differs");
        put(112,crc32(std::span(bytes).subspan(120)));
    }
    void put(std::size_t offset,std::uint32_t value){for(int i=0;i<4;++i)bytes[offset+static_cast<std::size_t>(i)]=static_cast<std::uint8_t>(value>>(8*i));}
    void write(){std::ofstream stream(path,std::ios::binary);stream.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));require(static_cast<bool>(stream),"precision fixture could not be saved");}
    ~Fixture(){std::error_code error;std::filesystem::remove(path,error);}
};
}
int main(){try {
    static_assert(8188*1024==2047*4096);
    static_assert(std::int64_t{8}*8188*32768<INT32_MAX);
    Fixture fixture;fixture.write();auto network=Network::load(fixture.path);
    require(network->residual(),"format four dropped the original classical baseline");
    auto board=Position::start();auto accumulator=network->refresh(board);std::mt19937 random(49979687);
    std::uint64_t transitions=0,nonzero=0;
    for(;transitions<2048;++transitions) {
        auto legal=board.legal();if(legal.empty()||board.halfmove()>149){board=Position::start();accumulator=network->refresh(board);legal=board.legal();}
        auto saved=board;auto before=accumulator;auto move=legal[random()%legal.size()];auto undo=board.make(move);network->update(board,undo,accumulator);
        require(accumulator==network->refresh(board),"high-precision incremental accumulator differs from refresh");
        for(int weight:{0,10,100}) {
            int scalar=network->evaluate(board,accumulator,true,weight),native=network->evaluate(board,accumulator,false,weight);
            require(scalar==native,"high-precision scalar and SIMD scores differ");
            auto interval=network->score_interval(board,weight);require(interval.lower<=native&&native<=interval.upper,"high-precision interval excludes actual score");
            if(weight==0)require(native==classical(board),"precision conversion changed zero-weight classical evaluation");
            if(weight==100&&native!=classical(board))++nonzero;
        }
        board.unmake(undo);accumulator=before;
        require(board.fen()==saved.fen()&&accumulator==network->refresh(board),"precision undo did not restore state");
        undo=board.make(move);network->update(board,undo,accumulator);
    }
    require(nonzero>0,"high-precision fixture did not exercise a neural correction");
    const auto valid=fixture.bytes;unsigned rejections=0;
    for(auto [offset,value]:{std::pair<std::size_t,std::uint32_t>{32,1024},{36,8191},{116,0},{8,3}}) {
        fixture.bytes=valid;fixture.put(offset,value);fixture.write();bool rejected=false;
        try{(void)Network::load(fixture.path);}catch(const InputError&){rejected=true;}
        require(rejected,"high-precision loader accepted a mismatched contract");++rejections;
    }
    std::cout<<"{\"status\":\"passed\",\"transitions\":"<<transitions<<",\"nonzero_neural_scores\":"<<nonzero<<",\"contract_rejections\":"<<rejections<<"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
