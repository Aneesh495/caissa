#include "caissa/network.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <random>
#include <stdexcept>

using namespace caissa;
int main(){try {
    std::array<std::int16_t,256> input{};
    std::array<std::int16_t,256*32> weights{};
    std::array<std::int32_t,32> biases{};
    std::array<std::int16_t,32> native{},scalar{};
    std::mt19937 random(982451707);std::uint64_t comparisons=0;
    auto check=[&](std::size_t columns,std::size_t rows,int scale,int clip) {
        clipped_affine(input.data(),weights.data(),biases.data(),native.data(),columns,rows,scale,clip);
        clipped_affine(input.data(),weights.data(),biases.data(),scalar.data(),columns,rows,scale,clip,true);
        for(std::size_t row=0;row<rows;++row) {
            std::int64_t sum=biases[row];
            for(std::size_t column=0;column<columns;++column)
                sum+=static_cast<std::int64_t>(input[column])*weights[row*columns+column];
            auto magnitude=(std::abs(sum)+scale/2)/scale;
            auto expected=std::clamp<std::int64_t>(sum<0?-magnitude:magnitude,0,clip);
            if(native[row]!=expected||scalar[row]!=expected)throw std::runtime_error("dense kernel differs from wide scalar arithmetic");
            ++comparisons;
        }
    };
    for(int format:{1,2,4}) {
        int scale=format==1?64:(format==4?4096:1024),clip=format==1?127:(format==4?8188:2047);
        for(int iteration=0;iteration<100;++iteration) {
            for(auto& value:input)value=static_cast<std::int16_t>(random()%static_cast<unsigned>(clip+1));
            for(auto& value:weights)value=static_cast<std::int16_t>(static_cast<int>(random()%65536)-32768);
            for(auto& value:biases)value=static_cast<std::int32_t>(random()%536870913)-(1<<28);
            for(std::size_t columns:{std::size_t{1},std::size_t{7},std::size_t{16},std::size_t{31},std::size_t{32},std::size_t{33},std::size_t{64},std::size_t{127},std::size_t{128},std::size_t{129},std::size_t{255},std::size_t{256}})
                for(std::size_t rows:{std::size_t{1},std::size_t{3},std::size_t{4},std::size_t{15},std::size_t{16},std::size_t{31},std::size_t{32}})check(columns,rows,scale,clip);
        }
        input.fill(static_cast<std::int16_t>(clip));
        for(std::int16_t extreme:{std::int16_t{-32768},std::int16_t{32767}}) {
            weights.fill(extreme);
            for(int bias:{-(1<<28),0,1<<28}){biases.fill(bias);check(256,32,scale,clip);}
        }
        weights.fill(0);biases.fill(scale/2-1);check(256,32,scale,clip);
        biases.fill(scale/2);check(256,32,scale,clip);
        biases.fill(scale+scale/2);check(256,32,scale,clip);
    }
    for(auto [scale,clip]:{std::pair{4096,8191},std::pair{1024,8188},std::pair{2048,4094}}) {
        bool rejected=false;
        try{clipped_affine(input.data(),weights.data(),biases.data(),native.data(),128,32,scale,clip);}
        catch(const InputError&){rejected=true;}
        if(!rejected)throw std::runtime_error("dense kernel accepted an undeclared precision pair");
    }
    for(auto dimensions:{std::pair<std::size_t,std::size_t>{0,32},{257,32},{128,0},{128,33}}) {
        bool rejected=false;
        try{clipped_affine(input.data(),weights.data(),biases.data(),native.data(),dimensions.first,dimensions.second,1024,2047);}
        catch(const InputError&){rejected=true;}
        if(!rejected)throw std::runtime_error("dense kernel accepted out-of-contract dimensions");
    }
    std::cout<<"{\"status\":\"passed\",\"wide_scalar_output_comparisons\":"<<comparisons<<"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
