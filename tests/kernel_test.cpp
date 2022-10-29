#include "caissa/network.hpp"
#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
using namespace caissa;
int main(){try {
    std::array<std::int16_t,256> activations{},weights{};std::mt19937 rng(961748941);
    for(int iteration=0;iteration<10000;++iteration) {
        for(std::size_t i=0;i<256;++i){activations[i]=static_cast<std::int16_t>(rng()%2048);weights[i]=static_cast<std::int16_t>(static_cast<int>(rng()%65536)-32768);}
        for(std::size_t count:{std::size_t{1},std::size_t{7},std::size_t{16},std::size_t{32},std::size_t{64},std::size_t{127},std::size_t{128},std::size_t{256}})
            if(dot_scalar(activations.data(),weights.data(),count)!=dot_native(activations.data(),weights.data(),count))throw std::runtime_error("native/scalar dot mismatch");
    }
    activations.fill(2047);
    for(std::int16_t weight:{std::int16_t{-32768},std::int16_t{32767}}) {
        weights.fill(weight);auto expected=std::int64_t{2047}*weight*256;
        if(dot_native(activations.data(),weights.data(),256)!=expected)throw std::runtime_error("chunk accumulation overflow");
    }
    for(int iteration=0;iteration<10000;++iteration) {
        for(std::size_t i=0;i<256;++i){activations[i]=static_cast<std::int16_t>(rng()%8189);weights[i]=static_cast<std::int16_t>(static_cast<int>(rng()%65536)-32768);}
        for(std::size_t count:{std::size_t{1},std::size_t{7},std::size_t{16},std::size_t{31},std::size_t{32},std::size_t{33},std::size_t{63},std::size_t{64},std::size_t{65},std::size_t{127},std::size_t{128},std::size_t{255},std::size_t{256}})
            if(dot_scalar(activations.data(),weights.data(),count)!=dot_native_high_precision(activations.data(),weights.data(),count))throw std::runtime_error("high-precision native/scalar dot mismatch");
    }
    activations.fill(8188);
    for(std::int16_t weight:{std::int16_t{-32768},std::int16_t{32767}}) {
        weights.fill(weight);auto expected=std::int64_t{8188}*weight*256;
        if(dot_native_high_precision(activations.data(),weights.data(),256)!=expected)throw std::runtime_error("high-precision chunk accumulation overflow");
    }
    std::cout<<"bounded scalar/native integer products and extreme weights passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
