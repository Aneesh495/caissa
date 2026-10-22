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
__attribute__((target("avx2"))) static std::int64_t dot_avx2(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
    std::int64_t sum=0;std::size_t i=0;alignas(32) std::array<std::int32_t,8> lanes{};
    while(i+16<=count) {
        const auto end=std::min(count,i+128);auto accumulator=_mm256_setzero_si256();
        for(;i+16<=end;i+=16) {
            auto product=_mm256_madd_epi16(_mm256_loadu_si256(reinterpret_cast<const __m256i*>(a+i)),_mm256_loadu_si256(reinterpret_cast<const __m256i*>(b+i)));
            accumulator=_mm256_add_epi32(accumulator,product);
        }
        _mm256_store_si256(reinterpret_cast<__m256i*>(lanes.data()),accumulator);for(auto lane:lanes)sum+=lane;
    }
    return sum+dot_scalar(a+i,b+i,count-i);
}
#endif
std::int64_t dot_native(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
#if defined(__aarch64__)
    std::int64_t sum=0;std::size_t i=0;
    while(i+8<=count) {
        const auto end=std::min(count,i+128);int32x4_t accumulator=vdupq_n_s32(0);
        // At most 32 products per lane: 32*2047*32768 < INT32_MAX.
        for(;i+8<=end;i+=8) {
            auto x=vld1q_s16(a+i),y=vld1q_s16(b+i);
            accumulator=vmlal_s16(accumulator,vget_low_s16(x),vget_low_s16(y));
            accumulator=vmlal_high_s16(accumulator,x,y);
        }
        sum+=vaddlvq_s32(accumulator);
    }
    return sum+dot_scalar(a+i,b+i,count-i);
#elif defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if(__builtin_cpu_supports("avx2"))return dot_avx2(a,b,count);
#endif
    return dot_scalar(a,b,count);
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
