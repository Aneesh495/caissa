#pragma once
#include "caissa/position.hpp"
#include <filesystem>
#include <memory>
#include <span>
namespace caissa {
inline constexpr int feature_version=1;
inline constexpr int king_buckets=16;
inline constexpr int feature_count=king_buckets*12*64;
#ifndef CAISSA_NETWORK_WIDTH
#define CAISSA_NETWORK_WIDTH 64
#endif
inline constexpr int transformer_width=CAISSA_NETWORK_WIDTH,dense1_width=32,dense2_width=16;
inline constexpr int network_scale=64,network_clip=127;
struct Accumulator {
    std::array<std::array<std::int32_t,transformer_width>,2> values{};
    std::array<int,2> buckets{};
    Key position_key=0;
    bool initialized=false;
    bool operator==(const Accumulator&)const=default;
};
int king_bucket(Color perspective,Square king);
int feature_index(Color perspective,int bucket,Piece piece,Square square);
std::uint32_t crc32(std::span<const std::uint8_t> bytes);
class Network {
public:
    static std::shared_ptr<const Network> load(const std::filesystem::path& path);
    Accumulator refresh(const Position& p) const;
    void update(const Position& after,const Undo& before,Accumulator& accumulator) const;
    int evaluate(const Position& p,const Accumulator& accumulator,bool scalar=false,int neural_weight=100) const;
    std::string identity()const{return identity_;}
    std::uint32_t checksum()const{return checksum_;}
private:
    std::vector<std::int16_t> embedding_;
    std::array<std::int32_t,transformer_width> bias0_{};
    std::array<std::int16_t,dense1_width*transformer_width*2> weights1_{};
    std::array<std::int32_t,dense1_width> bias1_{};
    std::array<std::int16_t,dense2_width*dense1_width> weights2_{};
    std::array<std::int32_t,dense2_width> bias2_{};
    std::array<std::int16_t,dense2_width> weights3_{};
    std::int32_t bias3_=0;
    std::string identity_;
    std::uint32_t checksum_=0;
    int scale_=64,clip_=127;
    bool residual_=false;
    void add(std::array<std::int32_t,transformer_width>& accumulator,int feature,int sign)const;
};
// Dot inputs are clipped activations in [0,2047] and arbitrary int16 weights.
std::int64_t dot_scalar(const std::int16_t* a,const std::int16_t* b,std::size_t count);
std::int64_t dot_native(const std::int16_t* a,const std::int16_t* b,std::size_t count);
std::string_view native_kernel();
}
