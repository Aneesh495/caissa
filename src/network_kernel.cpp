#include "caissa/network.hpp"
#include <algorithm>
#if defined(__aarch64__)
#include <arm_neon.h>
#elif defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
#include <immintrin.h>
#endif
namespace caissa {
std::int64_t dot_scalar(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
    std::int64_t sum=0;for(std::size_t i=0;i<count;++i)sum+=static_cast<std::int32_t>(a[i])*b[i];return sum;
}
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
template<std::size_t chunk>
__attribute__((target("avx2"))) static std::int64_t dot_avx2(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
    std::int64_t sum=0;std::size_t i=0;alignas(32) std::array<std::int32_t,8> lanes{};
    while(i+16<=count) {
        const auto end=std::min(count,i+chunk);auto accumulator=_mm256_setzero_si256();
        for(;i+16<=end;i+=16) {
            auto product=_mm256_madd_epi16(_mm256_loadu_si256(reinterpret_cast<const __m256i*>(a+i)),_mm256_loadu_si256(reinterpret_cast<const __m256i*>(b+i)));
            accumulator=_mm256_add_epi32(accumulator,product);
        }
        _mm256_store_si256(reinterpret_cast<__m256i*>(lanes.data()),accumulator);for(auto lane:lanes)sum+=lane;
    }
    return sum+dot_scalar(a+i,b+i,count-i);
}
#endif
#if defined(__aarch64__)
template<std::size_t chunk>
static std::int64_t dot_neon(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
    std::int64_t sum=0;std::size_t i=0;
    while(i+8<=count) {
        const auto end=std::min(count,i+chunk);int32x4_t accumulator=vdupq_n_s32(0);
        // Widen before the next chunk. The 128-input low-resolution and
        // 32-input high-resolution specializations both fit signed lanes.
        for(;i+8<=end;i+=8) {
            auto x=vld1q_s16(a+i),y=vld1q_s16(b+i);
            accumulator=vmlal_s16(accumulator,vget_low_s16(x),vget_low_s16(y));
            accumulator=vmlal_high_s16(accumulator,x,y);
        }
        sum+=vaddlvq_s32(accumulator);
    }
    return sum+dot_scalar(a+i,b+i,count-i);
}
#endif
std::int64_t dot_native(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
#if defined(__aarch64__)
    return dot_neon<128>(a,b,count);
#elif defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if(__builtin_cpu_supports("avx2"))return dot_avx2<128>(a,b,count);
#endif
    return dot_scalar(a,b,count);
}
std::int64_t dot_native_high_precision(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
#if defined(__aarch64__)
    return dot_neon<32>(a,b,count);
#elif defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if(__builtin_cpu_supports("avx2"))return dot_avx2<32>(a,b,count);
#endif
    return dot_scalar(a,b,count);
}
void clipped_affine(const std::int16_t* input,const std::int16_t* weights,
                    const std::int32_t* biases,std::int16_t* output,
                    std::size_t inputs,std::size_t outputs,int scale,int clip,bool scalar) {
    if(!input||!weights||!biases||!output||inputs==0||inputs>256||outputs==0||outputs>32||
       !(((scale==64||scale==1024)&&clip>=1&&clip<=2047)||(scale==4096&&clip==8188)))throw InputError("dense kernel dimensions or numerical contract");
    auto finish=[&](std::int64_t sum) {
        auto rounded=sum>=0?(sum+scale/2)/scale:-((-sum+scale/2)/scale);
        return static_cast<std::int16_t>(std::clamp<std::int64_t>(rounded,0,clip));
    };
    std::size_t row=0;
#if defined(__aarch64__)
    if(!scalar)for(;row+4<=outputs;row+=4) {
        std::array<std::int64_t,4> sums{biases[row],biases[row+1],biases[row+2],biases[row+3]};
        const std::size_t chunk=clip<=2047?128:32;
        for(std::size_t begin=0;begin<inputs;begin+=chunk) {
            auto end=std::min(inputs,begin+chunk);std::size_t i=begin;
            auto a0=vdupq_n_s32(0),a1=a0,a2=a0,a3=a0;
            for(;i+8<=end;i+=8) {
                auto x=vld1q_s16(input+i);auto lo=vget_low_s16(x);
                auto w0=vld1q_s16(weights+row*inputs+i),w1=vld1q_s16(weights+(row+1)*inputs+i);
                auto w2=vld1q_s16(weights+(row+2)*inputs+i),w3=vld1q_s16(weights+(row+3)*inputs+i);
                a0=vmlal_s16(a0,lo,vget_low_s16(w0));a0=vmlal_high_s16(a0,x,w0);
                a1=vmlal_s16(a1,lo,vget_low_s16(w1));a1=vmlal_high_s16(a1,x,w1);
                a2=vmlal_s16(a2,lo,vget_low_s16(w2));a2=vmlal_high_s16(a2,x,w2);
                a3=vmlal_s16(a3,lo,vget_low_s16(w3));a3=vmlal_high_s16(a3,x,w3);
            }
            // At q1024: 32*2047*32768 < INT32_MAX. At q4096:
            // 8*8188*32768 < INT32_MAX. Widen before combining chunks/biases.
            sums[0]+=vaddlvq_s32(a0);sums[1]+=vaddlvq_s32(a1);
            sums[2]+=vaddlvq_s32(a2);sums[3]+=vaddlvq_s32(a3);
            for(;i<end;++i)for(std::size_t k=0;k<4;++k)
                sums[k]+=static_cast<std::int32_t>(input[i])*weights[(row+k)*inputs+i];
        }
        for(std::size_t k=0;k<4;++k)output[row+k]=finish(sums[k]);
    }
#endif
    auto dot=scalar?dot_scalar:(clip<=2047?dot_native:dot_native_high_precision);
    for(;row<outputs;++row)output[row]=finish(dot(input,weights+row*inputs,inputs)+biases[row]);
}
std::string_view native_kernel() {
#if defined(__aarch64__)
    return "NEON (architectural AArch64 baseline)";
#elif defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    return __builtin_cpu_supports("avx2")?"AVX2 runtime dispatch":"scalar";
#else
    return "scalar";
#endif
}
}
