#include "caissa/network.hpp"
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
    for(;i+16<=count;i+=16) {
        auto v=_mm256_madd_epi16(_mm256_loadu_si256(reinterpret_cast<const __m256i*>(a+i)),_mm256_loadu_si256(reinterpret_cast<const __m256i*>(b+i)));
        _mm256_store_si256(reinterpret_cast<__m256i*>(lanes.data()),v);for(auto lane:lanes)sum+=lane;
    }
    return sum+dot_scalar(a+i,b+i,count-i);
}
#endif
std::int64_t dot_native(const std::int16_t* a,const std::int16_t* b,std::size_t count) {
#if defined(__aarch64__)
    std::int64_t sum=0;std::size_t i=0;
    for(;i+8<=count;i+=8) {
        auto x=vld1q_s16(a+i),y=vld1q_s16(b+i);auto lo=vmull_s16(vget_low_s16(x),vget_low_s16(y));auto hi=vmull_s16(vget_high_s16(x),vget_high_s16(y));
        sum+=vaddlvq_s32(lo)+vaddlvq_s32(hi);
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
